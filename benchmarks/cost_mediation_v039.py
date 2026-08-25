from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from bardocompute.exchange import ExchangeResult
from bidirectional_homeostasis import BOOSTED_SAFE_CAP
from continuous_miss_burden_v026 import MISS_THRESHOLD, SEVERE_MISS_THRESHOLD
from incremental_rate_weaning_v037 import IncrementalRateWeaningMembrane
from rate_first_recovery_v028 import RateFirstRecoveryMembrane
from real_work_queue_transfer import (
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)

# Fresh family frozen in issue #32 before implementation/results.
SEEDS = (
    22_100_823,
    22_200_829,
    22_300_837,
    22_400_843,
    22_500_851,
    22_600_857,
    22_700_863,
    22_800_869,
)
PAIRED_REPETITIONS = 4
MIN_SIGN_AGREEMENT = 6
MIN_BACKLOG_MEDIATED_SHARE = 0.95


@dataclass(slots=True)
class CostStats:
    incoming: int = 0
    completed: int = 0
    lost: int = 0
    terminal_backlog: int = 0
    wall_seconds: float = 0.0
    digest_mismatches: int = 0
    deadline_miss_epochs: int = 0
    severe_miss_epochs: int = 0
    missed_work_total: int = 0
    released_work_total: int = 0
    severe_excess_total: float = 0.0

    executed_epochs: int = 0
    drain_epochs: int = 0
    nonempty_batch_epochs: int = 0
    short_batch_epochs: int = 0
    pre_admission_backlog_area: int = 0
    post_release_backlog_area: int = 0
    peak_pre_admission_backlog: int = 0
    peak_post_release_backlog: int = 0
    buffer_saturated_epochs: int = 0
    overflow_epochs: int = 0
    intrinsic_overflow_total: int = 0
    backlog_mediated_overflow_total: int = 0
    rate_binding_epochs: int = 0
    rate_withheld_tasks_total: int = 0

    relief_active_epochs: int = 0
    relief_tasks_total: int = 0
    primary_tasks_total: int = 0
    secondary_tasks_total: int = 0
    critical_lane_units_total: float = 0.0
    calibrated_critical_floor_seconds: float = 0.0

    def seconds_per_completion(self) -> float:
        return self.wall_seconds / max(1, self.completed)

    def missed_work_fraction(self) -> float:
        return self.missed_work_total / max(1, self.released_work_total)

    def severe_excess_fraction(self) -> float:
        return self.severe_excess_total / max(1, self.released_work_total)

    def mean_nonempty_batch_size(self) -> float:
        return self.completed / max(1, self.nonempty_batch_epochs)

    def nonempty_epochs_per_completion(self) -> float:
        return self.nonempty_batch_epochs / max(1, self.completed)

    def critical_floor_seconds_per_completion(self) -> float:
        return self.calibrated_critical_floor_seconds / max(1, self.completed)

    def wall_to_floor_ratio(self) -> float:
        return self.wall_seconds / max(1e-15, self.calibrated_critical_floor_seconds)

    def backlog_mediated_overflow_share(self) -> float:
        return (
            1.0
            if self.lost == 0
            else self.backlog_mediated_overflow_total / self.lost
        )


def safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / max(1e-15, denominator)


def run_cost_policy(
    epochs: tuple[EpochSpec, ...],
    *,
    controller,
    rounds: int,
    calibrated_task_seconds: float,
    deadline_seconds: float,
) -> CostStats:
    stats = CostStats()
    backlog = 0

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()

        queue = list(epochs)
        queue.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

        for spec in queue:
            if spec.phase == "drain" and backlog == 0:
                break

            stats.executed_epochs += 1
            stats.drain_epochs += int(spec.phase == "drain")
            stats.pre_admission_backlog_area += backlog
            stats.peak_pre_admission_backlog = max(
                stats.peak_pre_admission_backlog, backlog
            )

            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.39 forbids voluntary admission shedding")

            # FlowPreservingMembrane.command() has already run exactly once inside
            # the unchanged controller. Read its resulting rate without calling it
            # a second time, which would mutate the base policy twice.
            base = getattr(controller, "base", None)
            base_release_limit = int(getattr(base, "rate", command.release_limit))

            stats.incoming += spec.incoming
            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            intrinsic_overflow = max(0, spec.incoming - command.buffer_limit)
            backlog_mediated_overflow = max(0, overflow - intrinsic_overflow)

            backlog += admitted
            backlog_after_admission = backlog
            stats.lost += overflow
            stats.overflow_epochs += int(overflow > 0)
            stats.intrinsic_overflow_total += intrinsic_overflow
            stats.backlog_mediated_overflow_total += backlog_mediated_overflow
            stats.buffer_saturated_epochs += int(
                backlog_after_admission >= command.buffer_limit
            )

            effective_released = min(backlog_after_admission, command.release_limit)
            base_released = min(backlog_after_admission, base_release_limit)
            withheld = max(0, base_released - effective_released)
            stats.rate_binding_epochs += int(withheld > 0)
            stats.rate_withheld_tasks_total += withheld

            released = effective_released
            backlog -= released
            stats.post_release_backlog_area += backlog
            stats.peak_post_release_backlog = max(
                stats.peak_post_release_backlog, backlog
            )
            if released > 0:
                stats.nonempty_batch_epochs += 1
                stats.short_batch_epochs += int(released < BOOSTED_SAFE_CAP)

            relief_active = bool(getattr(controller, "current_boost", 0.0) > 0.0)
            stats.relief_active_epochs += int(relief_active)
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

            stats.relief_tasks_total += relief_count
            stats.primary_tasks_total += primary_count
            stats.secondary_tasks_total += secondary_count

            primary_rounds = max(1, int(round(rounds * spec.primary_multiplier)))
            secondary_rounds = max(
                1, int(round(rounds * spec.secondary_multiplier))
            )
            primary_lane_units = primary_count * primary_rounds / max(1, rounds)
            secondary_lane_units = (
                secondary_count * secondary_rounds / max(1, rounds)
            )
            relief_lane_units = float(relief_count)
            stats.critical_lane_units_total += max(
                primary_lane_units,
                secondary_lane_units,
                relief_lane_units,
            )

            elapsed, p_on, s_on, r_on, mismatches = _execute_batch(
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
            stats.wall_seconds += elapsed
            stats.completed += released
            stats.digest_mismatches += mismatches

            on_time = p_on + s_on + r_on
            missed = max(0, released - on_time)
            miss_fraction = missed / max(1, released)
            stats.missed_work_total += missed
            stats.released_work_total += released
            stats.severe_excess_total += max(
                0.0, miss_fraction - SEVERE_MISS_THRESHOLD
            ) * released
            if released > 0:
                stats.deadline_miss_epochs += int(miss_fraction >= MISS_THRESHOLD)
                stats.severe_miss_epochs += int(
                    miss_fraction >= SEVERE_MISS_THRESHOLD
                )

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

    stats.terminal_backlog = backlog
    stats.calibrated_critical_floor_seconds = (
        stats.critical_lane_units_total * calibrated_task_seconds
    )
    return stats


def effect(
    *,
    seed: int,
    repetition: int,
    order: str,
    binary: CostStats,
    incremental: CostStats,
) -> dict[str, float | int | str]:
    return {
        "seed": seed,
        "repetition": repetition,
        "order": order,
        "completed_ratio": safe_ratio(incremental.completed, binary.completed),
        "lost_delta": incremental.lost - binary.lost,
        "seconds_ratio": safe_ratio(
            incremental.seconds_per_completion(),
            binary.seconds_per_completion(),
        ),
        "continuous_missed_delta": (
            incremental.missed_work_fraction() - binary.missed_work_fraction()
        ),
        "continuous_severe_delta": (
            incremental.severe_excess_fraction()
            - binary.severe_excess_fraction()
        ),
        "pre_backlog_area_delta": (
            incremental.pre_admission_backlog_area
            - binary.pre_admission_backlog_area
        ),
        "post_backlog_area_delta": (
            incremental.post_release_backlog_area
            - binary.post_release_backlog_area
        ),
        "rate_withheld_delta": (
            incremental.rate_withheld_tasks_total
            - binary.rate_withheld_tasks_total
        ),
        "nonempty_epochs_per_completion_ratio": safe_ratio(
            incremental.nonempty_epochs_per_completion(),
            binary.nonempty_epochs_per_completion(),
        ),
        "mean_batch_size_ratio": safe_ratio(
            incremental.mean_nonempty_batch_size(),
            binary.mean_nonempty_batch_size(),
        ),
        "critical_floor_per_completion_ratio": safe_ratio(
            incremental.critical_floor_seconds_per_completion(),
            binary.critical_floor_seconds_per_completion(),
        ),
        "wall_to_floor_ratio_delta": (
            incremental.wall_to_floor_ratio() - binary.wall_to_floor_ratio()
        ),
        "incremental_backlog_mediated_share": (
            incremental.backlog_mediated_overflow_share()
        ),
        "terminal_backlog_violations": int(binary.terminal_backlog != 0)
        + int(incremental.terminal_backlog != 0),
        "digest_mismatches": binary.digest_mismatches
        + incremental.digest_mismatches,
    }


def aggregate(rows: list[dict[str, float | int | str]]) -> dict[str, float]:
    numeric = (
        "completed_ratio",
        "lost_delta",
        "seconds_ratio",
        "continuous_missed_delta",
        "continuous_severe_delta",
        "pre_backlog_area_delta",
        "post_backlog_area_delta",
        "rate_withheld_delta",
        "nonempty_epochs_per_completion_ratio",
        "mean_batch_size_ratio",
        "critical_floor_per_completion_ratio",
        "wall_to_floor_ratio_delta",
        "incremental_backlog_mediated_share",
    )
    return {
        key: float(median(float(row[key]) for row in rows))
        for key in numeric
    }


def med(rows: list[dict[str, float | int | str]], key: str) -> float:
    return float(median(float(row[key]) for row in rows))


def sign(value: float, center: float = 0.0) -> int:
    if value > center:
        return 1
    if value < center:
        return -1
    return 0


def print_run(seed: int, repetition: int, policy: str, row: CostStats) -> None:
    print(
        f"run seed={seed} repetition={repetition} policy={policy} "
        f"incoming={row.incoming} completed={row.completed} lost={row.lost} "
        f"terminal_backlog={row.terminal_backlog} "
        f"pre_backlog_area={row.pre_admission_backlog_area} "
        f"post_backlog_area={row.post_release_backlog_area} "
        f"peak_pre_backlog={row.peak_pre_admission_backlog} "
        f"peak_post_backlog={row.peak_post_release_backlog} "
        f"saturated_epochs={row.buffer_saturated_epochs} "
        f"overflow_epochs={row.overflow_epochs} "
        f"intrinsic_overflow={row.intrinsic_overflow_total} "
        f"backlog_mediated_overflow={row.backlog_mediated_overflow_total} "
        f"rate_binding_epochs={row.rate_binding_epochs} "
        f"rate_withheld={row.rate_withheld_tasks_total} "
        f"drain_epochs={row.drain_epochs} wall_seconds={row.wall_seconds:.6f} "
        f"seconds_per_completion={row.seconds_per_completion():.9f} "
        f"executed_epochs={row.executed_epochs} "
        f"nonempty_epochs={row.nonempty_batch_epochs} "
        f"mean_batch={row.mean_nonempty_batch_size():.6f} "
        f"short_batch_epochs={row.short_batch_epochs} "
        f"relief_epochs={row.relief_active_epochs} "
        f"relief_tasks={row.relief_tasks_total} "
        f"primary_tasks={row.primary_tasks_total} "
        f"secondary_tasks={row.secondary_tasks_total} "
        f"critical_lane_units={row.critical_lane_units_total:.6f} "
        f"critical_floor_seconds={row.calibrated_critical_floor_seconds:.6f} "
        f"critical_floor_per_completion="
        f"{row.critical_floor_seconds_per_completion():.9f} "
        f"wall_to_floor={row.wall_to_floor_ratio():.6f} "
        f"missed_fraction={row.missed_work_fraction():.6f} "
        f"severe_excess={row.severe_excess_fraction():.6f} "
        f"deadline_miss_epochs={row.deadline_miss_epochs} "
        f"severe_miss_epochs={row.severe_miss_epochs} "
        f"digest_mismatches={row.digest_mismatches}"
    )


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=queue_and_batch_cost_mediation_v0.39")
    print("controllers=binary_v028_vs_incremental_v037_unchanged")
    print("fresh_seed_family=true")
    print("policy_promotion=false")
    print("controller_changes=false")
    print("controllers_phase_blind=true")
    print("instrumentation_only=true")
    print(f"paired_repetitions={PAIRED_REPETITIONS}")
    print(f"MIN_SIGN_AGREEMENT={MIN_SIGN_AGREEMENT}")
    print(f"MIN_BACKLOG_MEDIATED_SHARE={MIN_BACKLOG_MEDIATED_SHARE:.2f}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    all_pairs: list[dict[str, float | int | str]] = []
    pairs_by_seed: dict[int, list[dict[str, float | int | str]]] = defaultdict(list)
    stats_by_policy: dict[str, list[CostStats]] = {
        "binary": [],
        "incremental": [],
    }

    for seed in SEEDS:
        epochs = build_epochs(seed)
        for repetition in range(PAIRED_REPETITIONS):
            binary_first = (seed + repetition) % 2 == 0
            policies = (
                ("binary", "incremental")
                if binary_first
                else ("incremental", "binary")
            )
            current: dict[str, CostStats] = {}
            for policy in policies:
                controller = (
                    RateFirstRecoveryMembrane()
                    if policy == "binary"
                    else IncrementalRateWeaningMembrane()
                )
                current[policy] = run_cost_policy(
                    epochs,
                    controller=controller,
                    rounds=rounds,
                    calibrated_task_seconds=calibrated_task_seconds,
                    deadline_seconds=deadline_seconds,
                )
                stats_by_policy[policy].append(current[policy])
                print_run(seed, repetition, policy, current[policy])

            row = effect(
                seed=seed,
                repetition=repetition,
                order="BINARY_FIRST" if binary_first else "INCREMENTAL_FIRST",
                binary=current["binary"],
                incremental=current["incremental"],
            )
            all_pairs.append(row)
            pairs_by_seed[seed].append(row)
            print(
                f"pair seed={seed} repetition={repetition} order={row['order']} "
                f"completed_ratio={float(row['completed_ratio']):.6f} "
                f"lost_delta={int(row['lost_delta'])} "
                f"seconds_ratio={float(row['seconds_ratio']):.6f} "
                f"missed_delta={float(row['continuous_missed_delta']):.6f} "
                f"pre_backlog_delta={int(row['pre_backlog_area_delta'])} "
                f"rate_withheld_delta={int(row['rate_withheld_delta'])} "
                f"batch_ratio={float(row['mean_batch_size_ratio']):.6f} "
                f"epoch_density_ratio="
                f"{float(row['nonempty_epochs_per_completion_ratio']):.6f} "
                f"floor_ratio="
                f"{float(row['critical_floor_per_completion_ratio']):.6f}"
            )

    seed_rows = [aggregate(pairs_by_seed[seed]) for seed in SEEDS]
    terminal_backlog_violations = sum(
        int(row["terminal_backlog_violations"]) for row in all_pairs
    )
    digest_mismatches = sum(int(row["digest_mismatches"]) for row in all_pairs)
    integrity_ok = terminal_backlog_violations == 0 and digest_mismatches == 0

    lost_positive_seeds = sum(row["lost_delta"] > 0.0 for row in seed_rows)
    pre_backlog_positive_seeds = sum(
        row["pre_backlog_area_delta"] > 0.0 for row in seed_rows
    )
    seconds_cost_seeds = sum(row["seconds_ratio"] > 1.0 for row in seed_rows)

    queue_mediation_supported = (
        med(seed_rows, "lost_delta") > 0.0
        and lost_positive_seeds >= MIN_SIGN_AGREEMENT
        and med(seed_rows, "pre_backlog_area_delta") > 0.0
        and pre_backlog_positive_seeds >= MIN_SIGN_AGREEMENT
        and med(seed_rows, "incremental_backlog_mediated_share")
        >= MIN_BACKLOG_MEDIATED_SHARE
        and integrity_ok
    )
    runtime_cost_sign = (
        med(seed_rows, "seconds_ratio") > 1.0
        and seconds_cost_seeds >= MIN_SIGN_AGREEMENT
    )
    runtime_fragmentation_supported = (
        runtime_cost_sign
        and med(seed_rows, "mean_batch_size_ratio") < 1.0
        and med(seed_rows, "nonempty_epochs_per_completion_ratio") > 1.0
    )
    runtime_geometry_supported = (
        runtime_cost_sign
        and med(seed_rows, "critical_floor_per_completion_ratio") > 1.0
    )
    runtime_residual = (
        runtime_cost_sign
        and not runtime_fragmentation_supported
        and not runtime_geometry_supported
    )

    order_rows = {
        order: [row for row in all_pairs if row["order"] == order]
        for order in ("BINARY_FIRST", "INCREMENTAL_FIRST")
    }
    order_sign_disagreement = any(
        sign(med(order_rows["BINARY_FIRST"], key), center)
        * sign(med(order_rows["INCREMENTAL_FIRST"], key), center)
        < 0
        for key, center in (
            ("lost_delta", 0.0),
            ("pre_backlog_area_delta", 0.0),
            ("seconds_ratio", 1.0),
        )
    )

    if order_sign_disagreement:
        local_classification = "order_sensitive"
    elif queue_mediation_supported and runtime_fragmentation_supported and runtime_geometry_supported:
        local_classification = "queue_plus_fragmentation_and_geometry"
    elif queue_mediation_supported and runtime_fragmentation_supported:
        local_classification = "queue_plus_fragmentation"
    elif queue_mediation_supported and runtime_geometry_supported:
        local_classification = "queue_plus_geometry"
    elif queue_mediation_supported and runtime_residual:
        local_classification = "queue_supported_runtime_residual"
    elif queue_mediation_supported:
        local_classification = "queue_supported_no_stable_runtime_cost"
    elif runtime_fragmentation_supported and runtime_geometry_supported:
        local_classification = "runtime_fragmentation_and_geometry_without_queue"
    elif runtime_fragmentation_supported:
        local_classification = "runtime_fragmentation_without_queue"
    elif runtime_geometry_supported:
        local_classification = "runtime_geometry_without_queue"
    elif runtime_residual:
        local_classification = "runtime_residual_without_queue"
    else:
        local_classification = "no_stable_mediation"

    binary_rows = stats_by_policy["binary"]
    incremental_rows = stats_by_policy["incremental"]

    print("\n[cost_mediation]")
    print(f"paired_runs={len(all_pairs)}")
    print(f"seed_summaries={len(seed_rows)}")
    for key in (
        "completed_ratio",
        "lost_delta",
        "seconds_ratio",
        "continuous_missed_delta",
        "continuous_severe_delta",
        "pre_backlog_area_delta",
        "post_backlog_area_delta",
        "rate_withheld_delta",
        "incremental_backlog_mediated_share",
        "mean_batch_size_ratio",
        "nonempty_epochs_per_completion_ratio",
        "critical_floor_per_completion_ratio",
        "wall_to_floor_ratio_delta",
    ):
        print(f"median_seed_{key}={med(seed_rows, key):.6f}")
    print(f"lost_positive_seeds={lost_positive_seeds}/{len(SEEDS)}")
    print(
        f"pre_backlog_positive_seeds="
        f"{pre_backlog_positive_seeds}/{len(SEEDS)}"
    )
    print(f"seconds_cost_seeds={seconds_cost_seeds}/{len(SEEDS)}")
    print(
        f"binary_median_mean_batch_size="
        f"{median(row.mean_nonempty_batch_size() for row in binary_rows):.6f} "
        f"incremental_median_mean_batch_size="
        f"{median(row.mean_nonempty_batch_size() for row in incremental_rows):.6f}"
    )
    print(
        f"binary_median_nonempty_epochs="
        f"{median(row.nonempty_batch_epochs for row in binary_rows):.3f} "
        f"incremental_median_nonempty_epochs="
        f"{median(row.nonempty_batch_epochs for row in incremental_rows):.3f}"
    )
    print(
        f"binary_median_rate_withheld="
        f"{median(row.rate_withheld_tasks_total for row in binary_rows):.3f} "
        f"incremental_median_rate_withheld="
        f"{median(row.rate_withheld_tasks_total for row in incremental_rows):.3f}"
    )
    print(
        f"binary_median_pre_backlog_area="
        f"{median(row.pre_admission_backlog_area for row in binary_rows):.3f} "
        f"incremental_median_pre_backlog_area="
        f"{median(row.pre_admission_backlog_area for row in incremental_rows):.3f}"
    )

    for order, rows in order_rows.items():
        print(
            f"order={order} n={len(rows)} "
            f"median_lost_delta={med(rows, 'lost_delta'):.3f} "
            f"median_pre_backlog_delta={med(rows, 'pre_backlog_area_delta'):.3f} "
            f"median_seconds_ratio={med(rows, 'seconds_ratio'):.6f} "
            f"median_batch_ratio={med(rows, 'mean_batch_size_ratio'):.6f} "
            f"median_floor_ratio="
            f"{med(rows, 'critical_floor_per_completion_ratio'):.6f}"
        )

    print(f"terminal_backlog_violations={terminal_backlog_violations}")
    print(f"digest_mismatches={digest_mismatches}")
    print(f"integrity_ok={str(integrity_ok).lower()}")
    print(f"queue_mediation_supported={str(queue_mediation_supported).lower()}")
    print(f"runtime_cost_sign={str(runtime_cost_sign).lower()}")
    print(
        f"runtime_fragmentation_supported="
        f"{str(runtime_fragmentation_supported).lower()}"
    )
    print(
        f"runtime_geometry_supported="
        f"{str(runtime_geometry_supported).lower()}"
    )
    print(f"runtime_residual={str(runtime_residual).lower()}")
    print(f"order_sign_disagreement={str(order_sign_disagreement).lower()}")
    print(f"local_classification={local_classification}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=requires_cross_runtime_interpretation")
    print(
        "interpretation=v0.39 instruments unchanged v0.28 and v0.37 policies "
        "to attribute overflow and runtime cost to retained backlog, batch "
        "fragmentation, and calibrated critical-lane execution geometry."
    )


if __name__ == "__main__":
    main()
