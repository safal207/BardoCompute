from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from statistics import median

from active_load_gate_v030 import ActiveLoadGatedRateFirstMembrane
from bardocompute.exchange import ExchangeResult
from bidirectional_homeostasis import BOOSTED_SAFE_CAP
from computational_interoception_v019 import (
    HEALTHY_PAIN,
    MAX_RELEASE_REFERENCE,
    MIN_ACTIVE_LOAD,
    RECOVERY_DWELL,
    RECOVERY_TRAJECTORY,
    RESTORED_RESERVE,
)
from real_work_queue_transfer import (
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)
from storage_reserve import ELASTIC_BUFFER_LIMIT

# Fresh family frozen in issue #27 before implementation/results.
SEEDS = (
    18_100_631,
    18_200_633,
    18_300_637,
    18_400_643,
    18_500_651,
    18_600_657,
    18_700_661,
    18_800_669,
)
MAX_CANDIDATES_PER_SEED = 3
PAIRED_REPETITIONS = 4


@dataclass(frozen=True, slots=True)
class Candidate:
    seed: int
    ordinal: int
    epoch_index: int
    phase: str
    pain: float
    load: float
    reserve: float
    trajectory: float
    resolution_strength: int
    backlog: int
    incoming: int
    admitted: int
    available: int
    base_release_limit: int
    protected_release: int
    uncapped_release: int
    withdrawal_delta: int
    secondary_fraction: float
    relief_active: bool
    primary_multiplier: float
    secondary_multiplier: float


@dataclass(frozen=True, slots=True)
class ArmResult:
    arm: str
    released: int
    on_time_primary: int
    on_time_secondary: int
    on_time_relief: int
    total_on_time: int
    total_missed: int
    miss_fraction: float
    wall_seconds: float
    digest_mismatches: int


@dataclass(frozen=True, slots=True)
class PairResult:
    seed: int
    candidate_ordinal: int
    repetition: int
    order: str
    cap: ArmResult
    relax: ArmResult

    @property
    def additional_release(self) -> int:
        return self.relax.released - self.cap.released

    @property
    def net_on_time_gain(self) -> int:
        return self.relax.total_on_time - self.cap.total_on_time

    @property
    def additional_missed(self) -> int:
        return self.relax.total_missed - self.cap.total_missed

    @property
    def miss_fraction_delta(self) -> float:
        return self.relax.miss_fraction - self.cap.miss_fraction

    @property
    def wall_seconds_delta(self) -> float:
        return self.relax.wall_seconds - self.cap.wall_seconds


@dataclass(frozen=True, slots=True)
class CandidateEffect:
    candidate: Candidate
    repetitions: int
    additional_release: float
    net_on_time_gain: float
    additional_missed: float
    miss_fraction_delta: float
    wall_seconds_delta: float
    on_time_yield: float
    miss_yield: float


def execute_arm(
    candidate: Candidate,
    arm: str,
    *,
    rounds: int,
    deadline_seconds: float,
) -> ArmResult:
    if arm not in {"CAP", "RELAX"}:
        raise ValueError(f"unknown arm: {arm}")

    released = (
        candidate.protected_release if arm == "CAP" else candidate.uncapped_release
    )
    relief_count = 0
    if candidate.relief_active and released:
        relief_count = min(
            released,
            int(round(released * RELIEF_TASK_FRACTION)),
        )
    ordinary = released - relief_count
    secondary_count = min(
        ordinary,
        max(0, int(round(ordinary * candidate.secondary_fraction))),
    )
    primary_count = ordinary - secondary_count

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()
        elapsed, p_on, s_on, r_on, mismatches = _execute_batch(
            primary=primary,
            secondary=secondary,
            relief=relief,
            primary_count=primary_count,
            secondary_count=secondary_count,
            relief_count=relief_count,
            rounds=rounds,
            primary_multiplier=candidate.primary_multiplier,
            secondary_multiplier=candidate.secondary_multiplier,
            deadline_seconds=deadline_seconds,
        )

    total_on_time = p_on + s_on + r_on
    total_missed = max(0, released - total_on_time)
    return ArmResult(
        arm=arm,
        released=released,
        on_time_primary=p_on,
        on_time_secondary=s_on,
        on_time_relief=r_on,
        total_on_time=total_on_time,
        total_missed=total_missed,
        miss_fraction=total_missed / max(1, released),
        wall_seconds=elapsed,
        digest_mismatches=mismatches,
    )


def collect_candidates(
    seed: int,
    *,
    rounds: int,
    deadline_seconds: float,
) -> tuple[list[Candidate], int, int]:
    controller = ActiveLoadGatedRateFirstMembrane()
    queue = list(build_epochs(seed))
    queue.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

    candidates: list[Candidate] = []
    backlog = 0
    digest_mismatches = 0

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()

        for epoch_index, spec in enumerate(queue):
            if spec.phase == "drain" and backlog == 0:
                break

            pre_full_protection = (
                controller.protective
                and controller.withdrawal_stage == controller.PROTECTED
            )
            base_copy = deepcopy(controller.base)
            base_command = base_copy.command()

            protected_capacity = max(0, ELASTIC_BUFFER_LIMIT - backlog)
            predicted_admitted = min(spec.incoming, protected_capacity)
            predicted_available = backlog + predicted_admitted
            predicted_uncapped = min(
                predicted_available,
                base_command.release_limit,
            )
            predicted_protected = min(predicted_uncapped, BOOSTED_SAFE_CAP)
            binding = predicted_uncapped > predicted_protected

            if (
                len(candidates) < MAX_CANDIDATES_PER_SEED
                and pre_full_protection
                and controller.resolution_strength >= RECOVERY_DWELL
                and binding
            ):
                candidates.append(
                    Candidate(
                        seed=seed,
                        ordinal=len(candidates) + 1,
                        epoch_index=epoch_index,
                        phase=spec.phase,
                        pain=controller.pain,
                        load=controller.load,
                        reserve=controller.reserve,
                        trajectory=controller.trajectory,
                        resolution_strength=controller.resolution_strength,
                        backlog=backlog,
                        incoming=spec.incoming,
                        admitted=predicted_admitted,
                        available=predicted_available,
                        base_release_limit=base_command.release_limit,
                        protected_release=predicted_protected,
                        uncapped_release=predicted_uncapped,
                        withdrawal_delta=predicted_uncapped - predicted_protected,
                        secondary_fraction=base_command.secondary_fraction,
                        relief_active=True,
                        primary_multiplier=spec.primary_multiplier,
                        secondary_multiplier=spec.secondary_multiplier,
                    )
                )

            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.35 canonical path forbids admission shedding")

            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            backlog += admitted
            released = min(backlog, command.release_limit)
            backlog -= released

            relief_active = bool(getattr(controller, "current_boost", 0.0) > 0.0)
            relief_count = 0
            if relief_active and released:
                relief_count = min(
                    released,
                    int(round(released * RELIEF_TASK_FRACTION)),
                )
            ordinary = released - relief_count
            secondary_count = min(
                ordinary,
                max(0, int(round(ordinary * command.secondary_fraction))),
            )
            primary_count = ordinary - secondary_count

            _elapsed, p_on, s_on, r_on, mismatches = _execute_batch(
                primary=primary,
                secondary=secondary,
                relief=relief,
                primary_count=primary_count,
                secondary_count=secondary_count,
                relief_count=relief_count,
                rounds=rounds,
                primary_multiplier=spec.primary_multiplier,
                secondary_multiplier=spec.secondary_multiplier,
                deadline_seconds=deadline_seconds,
            )
            digest_mismatches += mismatches

            on_time = p_on + s_on + r_on
            missed = max(0, released - on_time)
            controller.observe(
                ExchangeResult(
                    admitted=admitted,
                    gate_rejected=0,
                    released=released,
                    primary_requested=primary_count,
                    secondary_requested=secondary_count,
                    primary_delivered=p_on,
                    secondary_delivered=s_on,
                    delivered=on_time,
                    congestion=missed,
                    buffered=backlog,
                    overflow_dropped=overflow,
                )
            )

    return candidates, backlog, digest_mismatches


def paired_effect(candidate: Candidate, pairs: list[PairResult]) -> CandidateEffect:
    if not pairs:
        raise ValueError("candidate has no paired repetitions")
    additional_release = float(median(pair.additional_release for pair in pairs))
    net_on_time_gain = float(median(pair.net_on_time_gain for pair in pairs))
    additional_missed = float(median(pair.additional_missed for pair in pairs))
    miss_fraction_delta = float(median(pair.miss_fraction_delta for pair in pairs))
    wall_seconds_delta = float(median(pair.wall_seconds_delta for pair in pairs))
    return CandidateEffect(
        candidate=candidate,
        repetitions=len(pairs),
        additional_release=additional_release,
        net_on_time_gain=net_on_time_gain,
        additional_missed=additional_missed,
        miss_fraction_delta=miss_fraction_delta,
        wall_seconds_delta=wall_seconds_delta,
        on_time_yield=net_on_time_gain / max(1.0, additional_release),
        miss_yield=additional_missed / max(1.0, additional_release),
    )


def med_effect(rows: list[CandidateEffect], attr: str) -> float:
    if not rows:
        return float("nan")
    return float(median(getattr(row, attr) for row in rows))


def print_group(dimension: str, value: str, rows: list[CandidateEffect]) -> None:
    print(
        f"group={dimension}:{value} n={len(rows)} "
        f"median_withdrawal_delta={med_effect(rows, 'additional_release'):.3f} "
        f"median_net_on_time_gain={med_effect(rows, 'net_on_time_gain'):.3f} "
        f"median_additional_missed={med_effect(rows, 'additional_missed'):.3f} "
        f"median_on_time_yield={med_effect(rows, 'on_time_yield'):.6f} "
        f"median_miss_yield={med_effect(rows, 'miss_yield'):.6f}"
    )


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=matched_binding_rate_withdrawal_v0.35")
    print("controller=canonical_v0.30_unchanged")
    print("fresh_seed_family=true")
    print("policy_promotion=false")
    print("threshold_tuning=false")
    print("controller_phase_blind=true")
    print("phase_labels_external_attribution_only=true")
    print("probe_results_update_canonical_state=false")
    print("matched_arms=CAP_vs_RELAX")
    print(f"paired_repetitions={PAIRED_REPETITIONS}")
    print(f"max_candidates_per_seed={MAX_CANDIDATES_PER_SEED}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    candidates: list[Candidate] = []
    terminal_backlogs: list[int] = []
    canonical_digest_mismatches = 0
    for seed in SEEDS:
        rows, terminal_backlog, mismatches = collect_candidates(
            seed,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        candidates.extend(rows)
        terminal_backlogs.append(terminal_backlog)
        canonical_digest_mismatches += mismatches

    pair_rows: list[PairResult] = []
    probe_digest_mismatches = 0
    by_candidate_pairs: dict[tuple[int, int], list[PairResult]] = defaultdict(list)

    for candidate in candidates:
        for repetition in range(PAIRED_REPETITIONS):
            cap_first = (candidate.seed + candidate.ordinal + repetition) % 2 == 0
            order = ("CAP", "RELAX") if cap_first else ("RELAX", "CAP")
            arm_results: dict[str, ArmResult] = {}
            for arm in order:
                result = execute_arm(
                    candidate,
                    arm,
                    rounds=rounds,
                    deadline_seconds=deadline_seconds,
                )
                arm_results[arm] = result
                probe_digest_mismatches += result.digest_mismatches
            pair = PairResult(
                seed=candidate.seed,
                candidate_ordinal=candidate.ordinal,
                repetition=repetition,
                order="CAP_FIRST" if cap_first else "RELAX_FIRST",
                cap=arm_results["CAP"],
                relax=arm_results["RELAX"],
            )
            pair_rows.append(pair)
            by_candidate_pairs[(candidate.seed, candidate.ordinal)].append(pair)

    effects = [
        paired_effect(
            candidate,
            by_candidate_pairs[(candidate.seed, candidate.ordinal)],
        )
        for candidate in candidates
    ]

    seeds_with_candidates = {candidate.seed for candidate in candidates}
    phase_counts = Counter(effect.candidate.phase for effect in effects)

    print("\n[matched_binding_effects]")
    print(f"seeds_with_binding_candidate={len(seeds_with_candidates)}/{len(SEEDS)}")
    print(f"binding_candidates={len(candidates)}")
    print(f"paired_repetitions_total={len(pair_rows)}")
    print(f"candidate_phase_counts={','.join(f'{k}:{phase_counts[k]}' for k in sorted(phase_counts))}")
    print(f"median_withdrawal_delta={med_effect(effects, 'additional_release'):.3f}")
    print(f"median_net_on_time_gain={med_effect(effects, 'net_on_time_gain'):.3f}")
    print(f"median_additional_missed={med_effect(effects, 'additional_missed'):.3f}")
    print(f"median_on_time_yield={med_effect(effects, 'on_time_yield'):.6f}")
    print(f"median_miss_yield={med_effect(effects, 'miss_yield'):.6f}")
    print(f"median_miss_fraction_delta={med_effect(effects, 'miss_fraction_delta'):.6f}")
    print(f"median_wall_seconds_delta={med_effect(effects, 'wall_seconds_delta'):.6f}")
    print(
        "fraction_candidates_net_on_time_gain_positive="
        f"{sum(effect.net_on_time_gain > 0 for effect in effects) / max(1, len(effects)):.6f}"
    )
    print(
        "fraction_candidates_additional_missed_nonpositive="
        f"{sum(effect.additional_missed <= 0 for effect in effects) / max(1, len(effects)):.6f}"
    )
    print(
        "fraction_candidates_positive_gain_and_nonpositive_missed="
        f"{sum(effect.net_on_time_gain > 0 and effect.additional_missed <= 0 for effect in effects) / max(1, len(effects)):.6f}"
    )

    order_rows: dict[str, list[PairResult]] = defaultdict(list)
    for pair in pair_rows:
        order_rows[pair.order].append(pair)
    for order in ("CAP_FIRST", "RELAX_FIRST"):
        rows = order_rows[order]
        print(
            f"order={order} n={len(rows)} "
            f"median_net_on_time_gain={median([row.net_on_time_gain for row in rows]) if rows else float('nan'):.3f} "
            f"median_additional_missed={median([row.additional_missed for row in rows]) if rows else float('nan'):.3f} "
            f"median_wall_seconds_delta={median([row.wall_seconds_delta for row in rows]) if rows else float('nan'):.6f}"
        )

    grouped: dict[tuple[str, str], list[CandidateEffect]] = defaultdict(list)
    for effect in effects:
        candidate = effect.candidate
        grouped[("phase", candidate.phase)].append(effect)
        grouped[("pain", "low" if candidate.pain <= HEALTHY_PAIN else "high")].append(effect)
        grouped[("load", "low" if candidate.load < MIN_ACTIVE_LOAD else "high")].append(effect)
        grouped[("reserve", "restored" if candidate.reserve >= RESTORED_RESERVE else "low")].append(effect)
        grouped[("trajectory", "nonworsening" if candidate.trajectory <= RECOVERY_TRAJECTORY else "worsening")].append(effect)
        grouped[("resolution_strength", str(candidate.resolution_strength))].append(effect)

    print("\n[preexisting_signal_groups]")
    for (dimension, value), rows in sorted(grouped.items()):
        print_group(dimension, value, rows)

    print(f"median_terminal_canonical_backlog={median(terminal_backlogs):.1f}")
    print(f"canonical_digest_mismatches={canonical_digest_mismatches}")
    print(f"probe_digest_mismatches={probe_digest_mismatches}")

    enough_candidates = len(seeds_with_candidates) >= 6
    median_gain = med_effect(effects, "net_on_time_gain")
    median_extra_missed = med_effect(effects, "additional_missed")
    if not enough_candidates:
        classification = "underpowered_binding_opportunities"
    elif median_gain > 0 and median_extra_missed <= 0:
        classification = "productive_without_median_miss_cost"
    elif median_gain > 0 and median_extra_missed > 0:
        classification = "service_risk_tradeoff"
    elif median_gain <= 0 and median_extra_missed > 0:
        classification = "locally_harmful_withdrawal"
    else:
        classification = "mixed_or_no_immediate_gain"

    print("\n[diagnostic_interpretation]")
    print(f"classification={classification}")
    print(f"candidate_power_sufficient={str(enough_candidates).lower()}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=not_applicable")
    print(
        "interpretation=v0.35 directly measures the immediate paired effect "
        "of genuinely binding RATE-cap withdrawal from the same observed state, "
        "without changing the canonical controller."
    )


if __name__ == "__main__":
    main()
