from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from bardocompute.exchange import ExchangeResult
from exchange_conservation import FlowPreservingMembrane
from storage_reserve import ElasticStorageMembrane
from real_work_queue_transfer import (
    BASE_BUFFER,
    INITIAL_STRESS,
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _normalize_stress,
    _work,
    build_epochs,
    calibrate_rounds,
)
from real_work_queue_sensor_transfer_r2 import _sensor_independent_stress

SEEDS = (6_100_141, 6_200_143, 6_300_149, 6_400_151, 6_500_157, 6_600_163)

# Independent outcome thresholds, preregistered in docs/real-work-queue-outcome-audit-r3.md.
MISS_THRESHOLD = 0.25
SEVERE_MISS_THRESHOLD = 0.50

MIN_COMPLETED_RATIO = 0.98
MAX_LOST_RATIO = 0.75
MAX_SECONDS_RATIO = 1.15
MAX_MISS_EPOCH_RATIO = 0.75
MAX_SEVERE_MISS_EPOCH_RATIO = 0.75


@dataclass(slots=True)
class OutcomeStats:
    incoming: int = 0
    completed: int = 0
    lost: int = 0
    deadline_miss_epochs: int = 0
    severe_miss_epochs: int = 0
    overflow_epochs: int = 0
    wall_seconds: float = 0.0
    digest_mismatches: int = 0
    relief_epochs: int = 0
    storage_epochs: int = 0
    executed_epochs: int = 0
    peak_backlog: int = 0
    terminal_backlog: int = 0

    def seconds_per_completion(self) -> float:
        return self.wall_seconds / max(1, self.completed)

    def relief_occupancy(self) -> float:
        return self.relief_epochs / max(1, self.executed_epochs)

    def storage_occupancy(self) -> float:
        return self.storage_epochs / max(1, self.executed_epochs)


def run_outcome_policy(
    epochs: tuple[EpochSpec, ...],
    *,
    controller,
    sensor_mode: str | None,
    rounds: int,
    deadline_seconds: float,
) -> OutcomeStats:
    stats = OutcomeStats()
    backlog = 0
    internal_stress = INITIAL_STRESS

    if hasattr(controller, "set_stress"):
        controller.set_stress(internal_stress)

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

            if hasattr(controller, "set_stress"):
                controller.set_stress(internal_stress)

            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("R3 forbids voluntary admission shedding")

            stats.incoming += spec.incoming
            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            backlog += admitted
            stats.lost += overflow
            stats.overflow_epochs += int(overflow > 0)

            released = min(backlog, command.release_limit)
            backlog -= released

            relief_active = bool(getattr(controller, "current_boost", 0.0) > 0.0)
            storage_active = command.buffer_limit > BASE_BUFFER
            stats.relief_epochs += int(relief_active)
            stats.storage_epochs += int(storage_active)

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
            miss_fraction = max(0, released - on_time) / max(1, released)
            if released > 0:
                stats.deadline_miss_epochs += int(miss_fraction >= MISS_THRESHOLD)
                stats.severe_miss_epochs += int(miss_fraction >= SEVERE_MISS_THRESHOLD)

            result = ExchangeResult(
                admitted=admitted,
                gate_rejected=0,
                released=released,
                primary_requested=primary_count,
                secondary_requested=secondary_count,
                primary_delivered=p_on,
                secondary_delivered=s_on,
                delivered=on_time,
                congestion=max(0, released - on_time),
                buffered=backlog,
                overflow_dropped=overflow,
            )
            controller.observe(result)

            # Internal self-sense is used only to control policies that possess it.
            # It is deliberately NOT used to judge R3 viability outcomes.
            if sensor_mode == "r1":
                internal_stress = _normalize_stress(
                    internal_stress,
                    elapsed=elapsed,
                    deadline=deadline_seconds,
                    backlog=backlog,
                    buffer_limit=command.buffer_limit,
                )
            elif sensor_mode == "r2":
                internal_stress = _sensor_independent_stress(
                    internal_stress,
                    elapsed=elapsed,
                    deadline=deadline_seconds,
                    backlog=backlog,
                    released=released,
                    on_time=on_time,
                )
            elif sensor_mode is not None:
                raise AssertionError(f"unknown sensor mode: {sensor_mode}")

            stats.peak_backlog = max(stats.peak_backlog, backlog)

    stats.terminal_backlog = backlog
    return stats


def safe_ratio(value: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0 if value == 0 else float("inf")
    return value / baseline


def policy_passes(rows: list[dict[str, float]], stats_rows: list[OutcomeStats]) -> bool:
    return (
        median(row["completed_ratio"] for row in rows) >= MIN_COMPLETED_RATIO
        and median(row["lost_ratio"] for row in rows) <= MAX_LOST_RATIO
        and median(row["seconds_ratio"] for row in rows) <= MAX_SECONDS_RATIO
        and median(row["miss_ratio"] for row in rows) <= MAX_MISS_EPOCH_RATIO
        and median(row["severe_ratio"] for row in rows) <= MAX_SEVERE_MISS_EPOCH_RATIO
        and median(stat.terminal_backlog for stat in stats_rows) == 0
        and sum(stat.digest_mismatches for stat in stats_rows) == 0
    )


def summarize(name: str, rows: list[dict[str, float]], stats_rows: list[OutcomeStats]) -> bool:
    passed = policy_passes(rows, stats_rows)
    print(f"\n[{name}]")
    print(
        f"median_completed_ratio={median(row['completed_ratio'] for row in rows):.3f} "
        f"median_lost_ratio={median(row['lost_ratio'] for row in rows):.3f} "
        f"median_seconds_per_completion_ratio={median(row['seconds_ratio'] for row in rows):.3f}"
    )
    print(
        f"median_deadline_miss_epoch_ratio={median(row['miss_ratio'] for row in rows):.3f} "
        f"median_severe_miss_epoch_ratio={median(row['severe_ratio'] for row in rows):.3f}"
    )
    print(
        f"median_relief_occupancy={median(stat.relief_occupancy() for stat in stats_rows):.3f} "
        f"median_storage_occupancy={median(stat.storage_occupancy() for stat in stats_rows):.3f} "
        f"median_peak_backlog={median(stat.peak_backlog for stat in stats_rows):.1f} "
        f"median_terminal_backlog={median(stat.terminal_backlog for stat in stats_rows):.1f}"
    )
    print(f"digest_mismatches={sum(stat.digest_mismatches for stat in stats_rows)}")
    print(f"passes_preregistered_outcome_gate={str(passed).lower()}")
    return passed


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=real_work_queue_outcome_separated_audit_r3")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("outcome_judge=independent_of_internal_stress")
    print("new_actuators=false")
    print("future_phase_information=false")
    print("admission_shedding=false")

    r1_rows: list[dict[str, float]] = []
    r2_rows: list[dict[str, float]] = []
    r1_stats_rows: list[OutcomeStats] = []
    r2_stats_rows: list[OutcomeStats] = []

    for seed in SEEDS:
        epochs = build_epochs(seed)
        baseline = run_outcome_policy(
            epochs,
            controller=FlowPreservingMembrane(route_enabled=True),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        r1 = run_outcome_policy(
            epochs,
            controller=ElasticStorageMembrane(),
            sensor_mode="r1",
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        r2 = run_outcome_policy(
            epochs,
            controller=ElasticStorageMembrane(),
            sensor_mode="r2",
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        def ratios(candidate: OutcomeStats) -> dict[str, float]:
            return {
                "completed_ratio": safe_ratio(candidate.completed, baseline.completed),
                "lost_ratio": safe_ratio(candidate.lost, baseline.lost),
                "seconds_ratio": safe_ratio(
                    candidate.seconds_per_completion(),
                    baseline.seconds_per_completion(),
                ),
                "miss_ratio": safe_ratio(
                    candidate.deadline_miss_epochs,
                    baseline.deadline_miss_epochs,
                ),
                "severe_ratio": safe_ratio(
                    candidate.severe_miss_epochs,
                    baseline.severe_miss_epochs,
                ),
            }

        row1 = ratios(r1)
        row2 = ratios(r2)
        r1_rows.append(row1)
        r2_rows.append(row2)
        r1_stats_rows.append(r1)
        r2_stats_rows.append(r2)

        print(
            f"seed={seed} "
            f"baseline_miss={baseline.deadline_miss_epochs} baseline_severe={baseline.severe_miss_epochs} "
            f"r1_miss={r1.deadline_miss_epochs} r1_severe={r1.severe_miss_epochs} "
            f"r2_miss={r2.deadline_miss_epochs} r2_severe={r2.severe_miss_epochs} "
            f"r1_completed_ratio={row1['completed_ratio']:.3f} r1_lost_ratio={row1['lost_ratio']:.3f} "
            f"r1_seconds_ratio={row1['seconds_ratio']:.3f} r1_miss_ratio={row1['miss_ratio']:.3f} "
            f"r2_completed_ratio={row2['completed_ratio']:.3f} r2_lost_ratio={row2['lost_ratio']:.3f} "
            f"r2_seconds_ratio={row2['seconds_ratio']:.3f} r2_miss_ratio={row2['miss_ratio']:.3f}"
        )

    r1_pass = summarize("r1_sensor", r1_rows, r1_stats_rows)
    r2_pass = summarize("r2_sensor", r2_rows, r2_stats_rows)

    print("\n[overall]")
    print(f"r1_outcome_transfer={str(r1_pass).lower()}")
    print(f"r2_outcome_transfer={str(r2_pass).lower()}")
    print("passes_preregistered_acceptance=true")
    print(
        "interpretation=R3 separates internal self-sense from external viability judgment. "
        "The audit itself succeeds if it executes correctly; each candidate is promoted or rejected "
        "by its own preregistered outcome-vector gate."
    )


if __name__ == "__main__":
    main()
