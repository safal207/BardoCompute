from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field
from statistics import median

from bardocompute.hazard_cadence import (
    HazardCadenceEvidence,
    evaluate_hazard_cadence,
)

SEEDS = tuple(0xB4D000 + index * 7919 for index in range(32))
HAZARDS = (0.0005, 0.001, 0.0025, 0.005, 0.010, 0.020)
PROBE_COSTS = (2.0, 8.0, 32.0)
STALE_REGRETS = (2.0, 10.0, 50.0)
FIXED_INTERVALS = (8, 16, 32, 64, 128, 256)


@dataclass(frozen=True, slots=True)
class Environment:
    changes: tuple[bool, ...]
    hazards: tuple[float, ...]


@dataclass(slots=True)
class HazardEstimator:
    mode: str
    cumulative_events: float = 1.0
    cumulative_exposure: float = 128.0
    ewma: float = 1.0 / 128.0
    rolling: deque[tuple[int, int]] = field(default_factory=lambda: deque(maxlen=8))

    def update(self, events: int, exposure: int) -> None:
        if exposure <= 0:
            return
        self.cumulative_events += events
        self.cumulative_exposure += exposure
        observed = events / exposure
        weight = 1.0 - math.exp(-math.log(2.0) * exposure / 512.0)
        self.ewma = (1.0 - weight) * self.ewma + weight * observed
        self.rolling.append((events, exposure))

    def value(self) -> float:
        if self.mode == "cumulative":
            return min(1.0, self.cumulative_events / self.cumulative_exposure)
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
    stale_steps: int = 0
    interval_sum: int = 0
    interval_count: int = 0


def build_environment(seed: int) -> Environment:
    rng = random.Random(seed)
    hazards = list(HAZARDS)
    rng.shuffle(hazards)
    changes: list[bool] = []
    truth_hazard: list[float] = []

    # Every seed contains all six hazard levels, but in a different order and
    # with independently randomized duration. No policy receives those labels.
    for hazard in hazards:
        length = rng.randint(4_000, 8_000)
        for _ in range(length):
            truth_hazard.append(hazard)
            changes.append(rng.random() < hazard)

    return Environment(tuple(changes), tuple(truth_hazard))


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


def run(
    environment: Environment,
    *,
    probe_cost: float,
    stale_regret: float,
    mode: str,
    fixed_interval: int | None = None,
) -> Stats:
    stats = Stats()
    estimator = HazardEstimator(
        mode=mode if mode in {"cumulative", "ewma", "rolling"} else "ewma"
    )
    current_epoch = 0
    calibrated_epoch = 0
    last_probe_epoch = 0
    last_probe_step = 0

    if fixed_interval is not None:
        interval = fixed_interval
    elif mode == "oracle":
        interval = cadence(environment.hazards[0], probe_cost, stale_regret)
    else:
        interval = cadence(estimator.value(), probe_cost, stale_regret)
    next_probe = interval

    for step, changed in enumerate(environment.changes):
        if changed:
            current_epoch += 1
        if current_epoch != calibrated_epoch:
            stats.loss += stale_regret
            stats.stale_steps += 1
        if step < next_probe:
            continue

        stats.loss += probe_cost
        stats.probes += 1
        exposure = max(1, step - last_probe_step)
        events = current_epoch - last_probe_epoch
        if mode in {"cumulative", "ewma", "rolling"}:
            estimator.update(events, exposure)
        calibrated_epoch = current_epoch
        last_probe_epoch = current_epoch
        last_probe_step = step

        if fixed_interval is not None:
            interval = fixed_interval
        elif mode == "oracle":
            interval = cadence(environment.hazards[step], probe_cost, stale_regret)
        else:
            interval = cadence(estimator.value(), probe_cost, stale_regret)
        stats.interval_sum += interval
        stats.interval_count += 1
        next_probe = step + interval

    return stats


def mean_loss(stats: Stats, steps: int) -> float:
    return stats.loss / steps


def percentile_nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def summarize(name: str, ratios: list[float], oracle_closure: list[float]) -> None:
    wins = sum(ratio < 1.0 for ratio in ratios)
    ties = sum(abs(ratio - 1.0) < 1e-12 for ratio in ratios)
    print(
        f"{name}: win_rate={wins / len(ratios):.3f} "
        f"ties={ties} median_ratio={median(ratios):.3f} "
        f"p90_ratio={percentile_nearest_rank(ratios, 0.90):.3f} "
        f"worst_ratio={max(ratios):.3f} "
        f"median_oracle_gap_closed={median(oracle_closure):.3f}"
    )


def main() -> None:
    environments = [(seed, build_environment(seed)) for seed in SEEDS]
    print(f"seeds={len(SEEDS)}")
    print("hazard_levels=" + ",".join(f"{value:.4f}" for value in HAZARDS))
    print("regime_order=randomized_per_seed")
    print("regime_length=uniform_integer_4000_to_8000")
    print("policy_input=hidden regime order, lengths, labels, boundaries, future hazards")
    print("best_fixed_control=chosen after the fact per seed/profile")

    overall: dict[str, list[float]] = {
        "cumulative": [],
        "ewma": [],
        "rolling": [],
    }
    overall_gap: dict[str, list[float]] = {
        "cumulative": [],
        "ewma": [],
        "rolling": [],
    }

    for probe_cost in PROBE_COSTS:
        for stale_regret in STALE_REGRETS:
            profile_ratios = {name: [] for name in overall}
            profile_gap = {name: [] for name in overall}
            losing_seeds = {name: [] for name in overall}

            for seed, environment in environments:
                steps = len(environment.changes)
                fixed_rows = [
                    run(
                        environment,
                        probe_cost=probe_cost,
                        stale_regret=stale_regret,
                        mode="fixed",
                        fixed_interval=interval,
                    )
                    for interval in FIXED_INTERVALS
                ]
                best_fixed_loss = min(mean_loss(row, steps) for row in fixed_rows)
                oracle = run(
                    environment,
                    probe_cost=probe_cost,
                    stale_regret=stale_regret,
                    mode="oracle",
                )
                oracle_loss = mean_loss(oracle, steps)

                for name in ("cumulative", "ewma", "rolling"):
                    adaptive = run(
                        environment,
                        probe_cost=probe_cost,
                        stale_regret=stale_regret,
                        mode=name,
                    )
                    adaptive_loss = mean_loss(adaptive, steps)
                    ratio = adaptive_loss / best_fixed_loss
                    profile_ratios[name].append(ratio)
                    overall[name].append(ratio)
                    if ratio >= 1.0:
                        losing_seeds[name].append(seed)

                    available_gap = max(1e-12, best_fixed_loss - oracle_loss)
                    closure = (best_fixed_loss - adaptive_loss) / available_gap
                    profile_gap[name].append(closure)
                    overall_gap[name].append(closure)

            print(
                f"\n[probe_cost={probe_cost:.0f},stale_regret={stale_regret:.0f}]"
            )
            for name in ("cumulative", "ewma", "rolling"):
                summarize(name, profile_ratios[name], profile_gap[name])
                if losing_seeds[name]:
                    print(
                        f"  {name}_nonwins="
                        + ",".join(hex(seed) for seed in losing_seeds[name])
                    )

    print("\n[overall_288_seed_profiles]")
    for name in ("cumulative", "ewma", "rolling"):
        summarize(name, overall[name], overall_gap[name])

    print(
        "\ninterpretation=This robustness sweep predeclares 32 seeds and nine "
        "cost profiles. The strongest fixed control is selected after the fact "
        "for each seed/profile, while online hazard estimators see only paid "
        "past/present transition counts. Any losing seed/profile is printed and "
        "retained rather than averaged away."
    )


if __name__ == "__main__":
    main()
