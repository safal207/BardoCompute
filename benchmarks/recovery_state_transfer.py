from __future__ import annotations

import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from statistics import median

from bardocompute.capability import CapabilityMode, CapabilitySignal
from bardocompute.hazard_cadence import HazardCadenceEvidence, evaluate_hazard_cadence
from bardocompute.stochastic import (
    StochasticCapabilityState,
    TaggedCapabilitySignal,
    step_stochastic_capability,
)

SEEDS = tuple(0xEC0A000 + index * 3571 for index in range(16))
HAZARDS = (0.0005, 0.0020, 0.0080, 0.0250)
PROBE_COSTS = (2.0, 8.0, 32.0)
STALE_REGRETS = (5.0, 25.0)
FIXED_INTERVALS = (8, 16, 32, 64, 128, 256)


@dataclass(frozen=True, slots=True)
class RecoveryEnvironment:
    restarts: tuple[bool, ...]
    hazards: tuple[float, ...]


@dataclass(slots=True)
class HazardEstimator:
    mode: str
    ewma: float = 1.0 / 128.0
    rolling: deque[tuple[int, int]] = field(default_factory=lambda: deque(maxlen=8))

    def update(self, events: int, exposure: int) -> None:
        if exposure <= 0:
            return
        observed = events / exposure
        weight = 1.0 - math.exp(-math.log(2.0) * exposure / 512.0)
        self.ewma = (1.0 - weight) * self.ewma + weight * observed
        self.rolling.append((events, exposure))

    def value(self) -> float:
        if self.mode == "ewma":
            return min(1.0, max(0.0, self.ewma))
        if self.mode == "rolling":
            events = 1 + sum(events for events, _ in self.rolling)
            exposure = 128 + sum(exposure for _, exposure in self.rolling)
            return min(1.0, events / exposure)
        raise ValueError(self.mode)


@dataclass(slots=True)
class Stats:
    loss: float = 0.0
    probes: int = 0
    unsafe_ticks: int = 0
    false_recoveries: int = 0
    stale_receipts: int = 0
    premature_receipts: int = 0
    duplicate_receipts: int = 0
    unresolved_ticks: int = 0
    interval_sum: int = 0
    interval_count: int = 0
    interval_by_hazard_sum: dict[float, int] = field(default_factory=lambda: defaultdict(int))
    interval_by_hazard_count: dict[float, int] = field(default_factory=lambda: defaultdict(int))


@dataclass(frozen=True, slots=True)
class ProbeNoise:
    stale_before: bool
    premature_current: bool
    duplicate_gap: bool
    final_evidence: bool
    stale_after: bool


def build_environment(seed: int) -> RecoveryEnvironment:
    rng = random.Random(seed)
    hazards = list(HAZARDS)
    rng.shuffle(hazards)
    restarts: list[bool] = []
    truth_hazards: list[float] = []
    for hazard in hazards:
        length = rng.randint(7_000, 11_000)
        for _ in range(length):
            restarts.append(rng.random() < hazard)
            truth_hazards.append(hazard)
    return RecoveryEnvironment(tuple(restarts), tuple(truth_hazards))


def deterministic_probe_noise(seed: int, step: int, authority_epoch: int) -> ProbeNoise:
    rng = random.Random(seed ^ (step * 0x9E3779B1) ^ (authority_epoch * 0x85EBCA77))
    return ProbeNoise(
        stale_before=rng.random() < 0.35,
        premature_current=rng.random() < 0.30,
        duplicate_gap=rng.random() < 0.25,
        final_evidence=rng.random() >= 0.08,
        stale_after=rng.random() < 0.25,
    )


def cadence(hazard: float, probe_cost: float, stale_regret: float) -> int:
    return evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=hazard,
            regret_given_change=stale_regret,
            probe_cost=probe_cost,
            min_interval=8,
            max_interval=256,
        )
    ).interval


def receipt(signal: CapabilitySignal, epoch: int) -> TaggedCapabilitySignal:
    return TaggedCapabilitySignal(signal, max(0, epoch))


def process_authoritative_probe(
    state: StochasticCapabilityState,
    *,
    authority_epoch: int,
    seed: int,
    step: int,
    stats: Stats,
) -> StochasticCapabilityState:
    """Feed noisy/reordered receipts through the existing epoch/order guard."""

    noise = deterministic_probe_noise(seed, step, authority_epoch)
    before = state

    if noise.stale_before and authority_epoch > 0:
        stale_epoch = max(0, authority_epoch - 1)
        candidate = receipt(CapabilitySignal.EVIDENCE_READY, stale_epoch)
        updated = step_stochastic_capability(state, candidate)
        stats.stale_receipts += 1
        state = updated

    if authority_epoch > state.epoch:
        state = step_stochastic_capability(
            state,
            receipt(CapabilitySignal.ENVIRONMENT_CHANGE, authority_epoch),
        )
        if noise.premature_current:
            candidate = receipt(CapabilitySignal.EVIDENCE_READY, authority_epoch)
            updated = step_stochastic_capability(state, candidate)
            stats.premature_receipts += 1
            state = updated

    if state.active_shock and state.epoch == authority_epoch:
        gap = receipt(CapabilitySignal.GAP_DETECTED, authority_epoch)
        state = step_stochastic_capability(state, gap)
        if noise.duplicate_gap:
            state = step_stochastic_capability(state, gap)
            stats.duplicate_receipts += 1
        if noise.final_evidence:
            state = step_stochastic_capability(
                state,
                receipt(CapabilitySignal.EVIDENCE_READY, authority_epoch),
            )

    if noise.stale_after and authority_epoch > 0:
        stale_epoch = max(0, authority_epoch - 1)
        state = step_stochastic_capability(
            state,
            receipt(CapabilitySignal.EVIDENCE_READY, stale_epoch),
        )
        stats.stale_receipts += 1

    # Replayed evidence in an unchanged, already-manifest epoch is harmless.
    if before == state and not state.active_shock and authority_epoch == state.epoch:
        replay = receipt(CapabilitySignal.EVIDENCE_READY, authority_epoch)
        state = step_stochastic_capability(state, replay)
        stats.duplicate_receipts += 1

    return state


def run(
    environment: RecoveryEnvironment,
    *,
    seed: int,
    probe_cost: float,
    stale_regret: float,
    mode: str,
    fixed_interval: int | None = None,
) -> Stats:
    stats = Stats()
    estimator = HazardEstimator(mode=mode if mode in {"ewma", "rolling"} else "ewma")
    state = StochasticCapabilityState()
    authority_epoch = 0
    last_probe_epoch = 0
    last_probe_step = 0

    if fixed_interval is not None:
        interval = fixed_interval
    elif mode == "oracle":
        interval = cadence(environment.hazards[0], probe_cost, stale_regret)
    else:
        interval = cadence(estimator.value(), probe_cost, stale_regret)
    next_probe = interval

    for step, restarted in enumerate(environment.restarts):
        if restarted:
            authority_epoch += 1

        stale = state.epoch != authority_epoch or state.active_shock
        if stale:
            stats.loss += stale_regret
            stats.unsafe_ticks += 1
            stats.unresolved_ticks += int(state.active_shock)
        if state.mode is CapabilityMode.MANIFEST and state.epoch != authority_epoch:
            stats.false_recoveries += 1

        if step < next_probe:
            continue

        stats.loss += probe_cost
        stats.probes += 1
        exposure = max(1, step - last_probe_step)
        events = authority_epoch - last_probe_epoch
        if mode in {"ewma", "rolling"}:
            estimator.update(events, exposure)

        state = process_authoritative_probe(
            state,
            authority_epoch=authority_epoch,
            seed=seed,
            step=step,
            stats=stats,
        )

        last_probe_epoch = authority_epoch
        last_probe_step = step
        if fixed_interval is not None:
            interval = fixed_interval
        elif mode == "oracle":
            interval = cadence(environment.hazards[step], probe_cost, stale_regret)
        else:
            interval = cadence(estimator.value(), probe_cost, stale_regret)

        hazard = environment.hazards[step]
        stats.interval_sum += interval
        stats.interval_count += 1
        stats.interval_by_hazard_sum[hazard] += interval
        stats.interval_by_hazard_count[hazard] += 1
        next_probe = step + interval

    return stats


def mean_loss(stats: Stats, steps: int) -> float:
    return stats.loss / steps


def nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def summarize(name: str, ratios: list[float], unsafe_ratios: list[float]) -> None:
    print(
        f"{name}: win_rate={sum(value < 1.0 for value in ratios) / len(ratios):.3f} "
        f"median_loss_ratio={median(ratios):.3f} "
        f"p90_loss_ratio={nearest_rank(ratios, 0.90):.3f} "
        f"worst_loss_ratio={max(ratios):.3f} "
        f"median_unsafe_ratio={median(unsafe_ratios):.3f}"
    )


def main() -> None:
    environments = [(seed, build_environment(seed)) for seed in SEEDS]
    overall = {"ewma": [], "rolling": []}
    overall_unsafe = {"ewma": [], "rolling": []}
    phase_intervals = {
        "ewma": {hazard: [] for hazard in HAZARDS},
        "rolling": {hazard: [] for hazard in HAZARDS},
    }
    guard_false_recoveries = {"ewma": 0, "rolling": 0}
    guard_noise = {"stale": 0, "premature": 0, "duplicate": 0}

    print(f"seeds={len(SEEDS)}")
    print("domain=recovery_state_with_authority_epoch_and_noisy_receipts")
    print("hazards=" + ",".join(f"{value:.4f}" for value in HAZARDS))
    print("regime_order=randomized_per_seed")
    print("regime_length=uniform_integer_7000_to_11000")
    print("policy_input=future restart boundaries, regime labels, and future hazards hidden")
    print("probe_reveals=current authority epoch + restart count since previous paid probe")
    print("receipt_guard=existing stochastic epoch/order guard; stale/replay/premature evidence injected")
    print("best_fixed_control=chosen_after_the_fact_per_seed_profile")

    for probe_cost in PROBE_COSTS:
        for stale_regret in STALE_REGRETS:
            profile = {"ewma": [], "rolling": []}
            profile_unsafe = {"ewma": [], "rolling": []}
            for seed, environment in environments:
                steps = len(environment.restarts)
                fixed_rows = [
                    run(
                        environment,
                        seed=seed,
                        probe_cost=probe_cost,
                        stale_regret=stale_regret,
                        mode="fixed",
                        fixed_interval=interval,
                    )
                    for interval in FIXED_INTERVALS
                ]
                best_fixed = min(fixed_rows, key=lambda row: mean_loss(row, steps))
                best_fixed_loss = mean_loss(best_fixed, steps)
                best_fixed_unsafe = max(1, best_fixed.unsafe_ticks)

                for mode in ("ewma", "rolling"):
                    adaptive = run(
                        environment,
                        seed=seed,
                        probe_cost=probe_cost,
                        stale_regret=stale_regret,
                        mode=mode,
                    )
                    ratio = mean_loss(adaptive, steps) / best_fixed_loss
                    unsafe_ratio = adaptive.unsafe_ticks / best_fixed_unsafe
                    profile[mode].append(ratio)
                    profile_unsafe[mode].append(unsafe_ratio)
                    overall[mode].append(ratio)
                    overall_unsafe[mode].append(unsafe_ratio)
                    guard_false_recoveries[mode] += adaptive.false_recoveries
                    guard_noise["stale"] += adaptive.stale_receipts
                    guard_noise["premature"] += adaptive.premature_receipts
                    guard_noise["duplicate"] += adaptive.duplicate_receipts
                    for hazard in HAZARDS:
                        count = adaptive.interval_by_hazard_count[hazard]
                        if count:
                            phase_intervals[mode][hazard].append(
                                adaptive.interval_by_hazard_sum[hazard] / count
                            )

            print(f"\n[probe_cost={probe_cost:.0f},stale_regret={stale_regret:.0f}]")
            for mode in ("ewma", "rolling"):
                summarize(mode, profile[mode], profile_unsafe[mode])

    print("\n[overall_transfer_profiles]")
    for mode in ("ewma", "rolling"):
        summarize(mode, overall[mode], overall_unsafe[mode])
        print(
            f"{mode}_median_interval_by_true_hidden_hazard="
            + "/".join(
                f"{hazard:.4f}:{median(phase_intervals[mode][hazard]):.1f}"
                for hazard in HAZARDS
            )
        )
        print(f"{mode}_guard_false_recoveries={guard_false_recoveries[mode]}")

    print(
        f"injected_receipts=stale:{guard_noise['stale']},"
        f"premature:{guard_noise['premature']},duplicate:{guard_noise['duplicate']}"
    )
    print(
        "interpretation=The hazard/cadence rule is transferred without changing its "
        "formula into an authority-epoch recovery workload. The scheduling question is "
        "now whether to pay for authoritative recovery checks before stale local state "
        "causes unsafe operation. Receipt provenance is independently protected by the "
        "existing epoch/order guard. A transfer win is meaningful only if adaptive "
        "cadence beats the strongest fixed cadence while the guard preserves zero false "
        "recoveries under stale/replayed/premature evidence."
    )


if __name__ == "__main__":
    main()
