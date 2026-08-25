from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from continuous_miss_burden_v026 import ContinuousStats, run_continuous_policy
from incremental_rate_weaning_v037 import IncrementalRateWeaningMembrane
from rate_first_recovery_v028 import RateFirstRecoveryMembrane
from real_work_queue_transfer import build_epochs, calibrate_rounds

# Fresh family frozen in issue #30 before implementation/results.
SEEDS = (
    21_100_777,
    21_200_781,
    21_300_787,
    21_400_793,
    21_500_799,
    21_600_807,
    21_700_811,
    21_800_819,
)
PAIRED_REPETITIONS = 4
MIN_COMPLETED_PRESERVATION = 0.98
MAX_SECONDS_RATIO = 1.05
MIN_SIGN_AGREEMENT = 6


@dataclass(frozen=True, slots=True)
class PairEffect:
    seed: int
    repetition: int
    order: str
    completed_ratio: float
    lost_delta: int
    seconds_ratio: float
    continuous_missed_delta: float
    continuous_severe_delta: float
    deadline_miss_epoch_delta: int
    severe_miss_epoch_delta: int
    binary_terminal_backlog: int
    incremental_terminal_backlog: int
    digest_mismatches: int


@dataclass(frozen=True, slots=True)
class SeedEffect:
    seed: int
    completed_ratio: float
    lost_delta: float
    seconds_ratio: float
    continuous_missed_delta: float
    continuous_severe_delta: float
    deadline_miss_epoch_delta: float
    severe_miss_epoch_delta: float


def safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / max(denominator, 1e-15)


def make_effect(
    *,
    seed: int,
    repetition: int,
    order: str,
    binary: ContinuousStats,
    incremental: ContinuousStats,
) -> PairEffect:
    return PairEffect(
        seed=seed,
        repetition=repetition,
        order=order,
        completed_ratio=safe_ratio(incremental.completed, binary.completed),
        lost_delta=incremental.lost - binary.lost,
        seconds_ratio=safe_ratio(
            incremental.seconds_per_completion(),
            binary.seconds_per_completion(),
        ),
        continuous_missed_delta=(
            incremental.missed_work_fraction() - binary.missed_work_fraction()
        ),
        continuous_severe_delta=(
            incremental.severe_excess_fraction()
            - binary.severe_excess_fraction()
        ),
        deadline_miss_epoch_delta=(
            incremental.deadline_miss_epochs - binary.deadline_miss_epochs
        ),
        severe_miss_epoch_delta=(
            incremental.severe_miss_epochs - binary.severe_miss_epochs
        ),
        binary_terminal_backlog=binary.terminal_backlog,
        incremental_terminal_backlog=incremental.terminal_backlog,
        digest_mismatches=(
            binary.digest_mismatches + incremental.digest_mismatches
        ),
    )


def aggregate_seed(seed: int, rows: list[PairEffect]) -> SeedEffect:
    if len(rows) != PAIRED_REPETITIONS:
        raise AssertionError(
            f"seed {seed} has {len(rows)} pairs, expected {PAIRED_REPETITIONS}"
        )
    return SeedEffect(
        seed=seed,
        completed_ratio=float(median(row.completed_ratio for row in rows)),
        lost_delta=float(median(row.lost_delta for row in rows)),
        seconds_ratio=float(median(row.seconds_ratio for row in rows)),
        continuous_missed_delta=float(
            median(row.continuous_missed_delta for row in rows)
        ),
        continuous_severe_delta=float(
            median(row.continuous_severe_delta for row in rows)
        ),
        deadline_miss_epoch_delta=float(
            median(row.deadline_miss_epoch_delta for row in rows)
        ),
        severe_miss_epoch_delta=float(
            median(row.severe_miss_epoch_delta for row in rows)
        ),
    )


def med(rows: list[object], attr: str) -> float:
    if not rows:
        return float("nan")
    return float(median(getattr(row, attr) for row in rows))


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=repeated_matched_runtime_attribution_v0.38")
    print("controllers=binary_v028_vs_incremental_v037_unchanged")
    print("fresh_seed_family=true")
    print("policy_promotion=false")
    print("step_tuning=false")
    print("controllers_phase_blind=true")
    print("primary_risk=continuous_missed_work_burden")
    print("secondary_risk=thresholded_epoch_counts_absolute_deltas")
    print(f"paired_repetitions={PAIRED_REPETITIONS}")
    print(f"MIN_COMPLETED_PRESERVATION={MIN_COMPLETED_PRESERVATION:.3f}")
    print(f"MAX_SECONDS_RATIO={MAX_SECONDS_RATIO:.3f}")
    print(f"MIN_SIGN_AGREEMENT={MIN_SIGN_AGREEMENT}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    all_pairs: list[PairEffect] = []
    pairs_by_seed: dict[int, list[PairEffect]] = defaultdict(list)

    for seed in SEEDS:
        epochs = build_epochs(seed)
        for repetition in range(PAIRED_REPETITIONS):
            binary_first = (seed + repetition) % 2 == 0
            order = (
                ("binary", "incremental")
                if binary_first
                else ("incremental", "binary")
            )
            results: dict[str, ContinuousStats] = {}
            for policy in order:
                controller = (
                    RateFirstRecoveryMembrane()
                    if policy == "binary"
                    else IncrementalRateWeaningMembrane()
                )
                results[policy] = run_continuous_policy(
                    epochs,
                    controller=controller,
                    rounds=rounds,
                    deadline_seconds=deadline_seconds,
                )

            effect = make_effect(
                seed=seed,
                repetition=repetition,
                order="BINARY_FIRST" if binary_first else "INCREMENTAL_FIRST",
                binary=results["binary"],
                incremental=results["incremental"],
            )
            all_pairs.append(effect)
            pairs_by_seed[seed].append(effect)
            print(
                f"seed={seed} repetition={repetition} order={effect.order} "
                f"completed_ratio={effect.completed_ratio:.6f} "
                f"seconds_ratio={effect.seconds_ratio:.6f} "
                f"missed_delta={effect.continuous_missed_delta:.6f} "
                f"severe_delta={effect.continuous_severe_delta:.6f} "
                f"deadline_epoch_delta={effect.deadline_miss_epoch_delta} "
                f"severe_epoch_delta={effect.severe_miss_epoch_delta} "
                f"digest_mismatches={effect.digest_mismatches}"
            )

    seed_effects = [
        aggregate_seed(seed, pairs_by_seed[seed]) for seed in SEEDS
    ]

    missed_negative_seeds = sum(
        row.continuous_missed_delta < 0.0 for row in seed_effects
    )
    severe_nonpositive_seeds = sum(
        row.continuous_severe_delta <= 0.0 for row in seed_effects
    )
    completed_preserved_seeds = sum(
        row.completed_ratio >= MIN_COMPLETED_PRESERVATION for row in seed_effects
    )
    seconds_preserved_seeds = sum(
        row.seconds_ratio <= MAX_SECONDS_RATIO for row in seed_effects
    )

    terminal_backlog_violations = sum(
        row.binary_terminal_backlog != 0
        or row.incremental_terminal_backlog != 0
        for row in all_pairs
    )
    digest_mismatches = sum(row.digest_mismatches for row in all_pairs)

    missed_reduction = (
        med(seed_effects, "continuous_missed_delta") < 0.0
        and missed_negative_seeds >= MIN_SIGN_AGREEMENT
    )
    severe_preserved = (
        med(seed_effects, "continuous_severe_delta") <= 0.0
        and severe_nonpositive_seeds >= MIN_SIGN_AGREEMENT
    )
    completed_preserved = (
        med(seed_effects, "completed_ratio") >= MIN_COMPLETED_PRESERVATION
    )
    seconds_preserved = med(seed_effects, "seconds_ratio") <= MAX_SECONDS_RATIO
    integrity_ok = terminal_backlog_violations == 0 and digest_mismatches == 0

    if (
        missed_reduction
        and severe_preserved
        and completed_preserved
        and seconds_preserved
        and integrity_ok
    ):
        local_classification = "robust_risk_reduction_with_service_preservation"
    elif (
        missed_reduction
        and severe_preserved
        and completed_preserved
        and not seconds_preserved
        and integrity_ok
    ):
        local_classification = "robust_risk_reduction_with_runtime_cost"
    elif missed_reduction and not severe_preserved and integrity_ok:
        local_classification = "risk_reduction_with_tail_cost"
    else:
        local_classification = "no_robust_effect"

    print("\n[repeated_matched]")
    print(f"paired_runs={len(all_pairs)}")
    print(f"seed_summaries={len(seed_effects)}")
    print(f"median_pair_completed_ratio={med(all_pairs, 'completed_ratio'):.6f}")
    print(f"median_pair_seconds_ratio={med(all_pairs, 'seconds_ratio'):.6f}")
    print(
        f"median_pair_continuous_missed_delta="
        f"{med(all_pairs, 'continuous_missed_delta'):.6f}"
    )
    print(
        f"median_pair_continuous_severe_delta="
        f"{med(all_pairs, 'continuous_severe_delta'):.6f}"
    )
    print(
        f"median_pair_deadline_miss_epoch_delta="
        f"{med(all_pairs, 'deadline_miss_epoch_delta'):.3f}"
    )
    print(
        f"median_pair_severe_miss_epoch_delta="
        f"{med(all_pairs, 'severe_miss_epoch_delta'):.3f}"
    )
    print(f"median_seed_completed_ratio={med(seed_effects, 'completed_ratio'):.6f}")
    print(f"median_seed_lost_delta={med(seed_effects, 'lost_delta'):.3f}")
    print(f"median_seed_seconds_ratio={med(seed_effects, 'seconds_ratio'):.6f}")
    print(
        f"median_seed_continuous_missed_delta="
        f"{med(seed_effects, 'continuous_missed_delta'):.6f}"
    )
    print(
        f"median_seed_continuous_severe_delta="
        f"{med(seed_effects, 'continuous_severe_delta'):.6f}"
    )
    print(
        f"median_seed_deadline_miss_epoch_delta="
        f"{med(seed_effects, 'deadline_miss_epoch_delta'):.3f}"
    )
    print(
        f"median_seed_severe_miss_epoch_delta="
        f"{med(seed_effects, 'severe_miss_epoch_delta'):.3f}"
    )
    print(
        f"seeds_continuous_missed_delta_negative="
        f"{missed_negative_seeds}/{len(SEEDS)}"
    )
    print(
        f"seeds_continuous_severe_delta_nonpositive="
        f"{severe_nonpositive_seeds}/{len(SEEDS)}"
    )
    print(
        f"seeds_completed_preserved="
        f"{completed_preserved_seeds}/{len(SEEDS)}"
    )
    print(
        f"seeds_seconds_preserved="
        f"{seconds_preserved_seeds}/{len(SEEDS)}"
    )

    for order in ("BINARY_FIRST", "INCREMENTAL_FIRST"):
        rows = [row for row in all_pairs if row.order == order]
        print(
            f"order={order} n={len(rows)} "
            f"median_completed_ratio={med(rows, 'completed_ratio'):.6f} "
            f"median_seconds_ratio={med(rows, 'seconds_ratio'):.6f} "
            f"median_missed_delta={med(rows, 'continuous_missed_delta'):.6f} "
            f"median_severe_delta={med(rows, 'continuous_severe_delta'):.6f}"
        )

    print(f"terminal_backlog_violations={terminal_backlog_violations}")
    print(f"digest_mismatches={digest_mismatches}")
    print(f"missed_reduction_sign_rule={str(missed_reduction).lower()}")
    print(f"severe_preservation_sign_rule={str(severe_preserved).lower()}")
    print(f"completed_preservation={str(completed_preserved).lower()}")
    print(f"seconds_preservation={str(seconds_preserved).lower()}")
    print(f"integrity_ok={str(integrity_ok).lower()}")
    print(f"local_classification={local_classification}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=requires_cross_runtime_interpretation")
    print(
        "interpretation=v0.38 uses repeated matched full-policy trials to "
        "separate continuous deadline burden from thresholded executor/deadline "
        "variance without changing v0.28 or v0.37."
    )


if __name__ == "__main__":
    main()
