from __future__ import annotations

from statistics import median

from exchange_conservation import FlowPreservingMembrane
from real_work_queue_outcome_audit_r3 import OutcomeStats, run_outcome_policy, safe_ratio
from real_work_queue_transfer import build_epochs, calibrate_rounds
from real_work_queue_sensor_transfer_r2 import _sensor_independent_stress  # noqa: F401
from storage_reserve import ElasticStorageMembrane
from computational_interoception_v019 import (
    HEALTHY_PAIN,
    RECOVERY_TRAJECTORY,
    InteroceptiveMembrane,
)

SEEDS = (8_100_211, 8_200_223, 8_300_227, 8_400_229, 8_500_233, 8_600_239)

MIN_COMPLETED_BASELINE = 1.25
MAX_LOST_BASELINE = 0.75
MAX_SECONDS_BASELINE = 1.15
MAX_MISS_BASELINE = 0.60
MAX_SEVERE_BASELINE = 0.25
MAX_OCCUPANCY = 0.65
MAX_OCCUPANCY_VS_R2 = 0.75
MIN_COMPLETED_VS_R2 = 0.98
MAX_MISS_VS_R2 = 1.25
MAX_SECONDS_VS_R2 = 1.15


class RecoveryDecoupledMembrane(InteroceptiveMembrane):
    """v0.19 entry semantics with RESERVE removed only from recovery veto."""

    def observe(self, result) -> None:
        previous_recovery = self.recovery
        super().observe(result)

        # Freeze every v0.19 signal/threshold except the semantic role of
        # RESERVE during exit.  RESERVE still participates in _should_enter().
        healthy_for_recovery = (
            self.pain < HEALTHY_PAIN
            and self.trajectory <= RECOVERY_TRAJECTORY
        )
        self.recovery = previous_recovery + 1 if healthy_for_recovery else 0


def ratios(candidate: OutcomeStats, baseline: OutcomeStats) -> dict[str, float]:
    return {
        "completed": safe_ratio(candidate.completed, baseline.completed),
        "lost": safe_ratio(candidate.lost, baseline.lost),
        "seconds": safe_ratio(
            candidate.seconds_per_completion(), baseline.seconds_per_completion()
        ),
        "miss": safe_ratio(
            candidate.deadline_miss_epochs, baseline.deadline_miss_epochs
        ),
        "severe": safe_ratio(candidate.severe_miss_epochs, baseline.severe_miss_epochs),
    }


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=recovery_decoupling_v0.20")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("entry_semantics=unchanged_v0.19")
    print("recovery=low_PAIN+nonworsening_TRAJECTORY")
    print("RESERVE_entry_signal=true")
    print("RESERVE_recovery_veto=false")
    print("new_actuators=false")
    print("future_phase_information=false")
    print("admission_shedding=false")

    rows: list[dict[str, float]] = []
    stats_rows: list[OutcomeStats] = []
    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []
    v19_relief: list[float] = []
    v19_storage: list[float] = []

    for seed in SEEDS:
        epochs = build_epochs(seed)
        baseline = run_outcome_policy(
            epochs,
            controller=FlowPreservingMembrane(route_enabled=True),
            sensor_mode=None,
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
        v19 = run_outcome_policy(
            epochs,
            controller=InteroceptiveMembrane(),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v20 = run_outcome_policy(
            epochs,
            controller=RecoveryDecoupledMembrane(),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        row = ratios(v20, baseline)
        rows.append(row)
        stats_rows.append(v20)

        relief_vs_r2.append(safe_ratio(v20.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v20.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v20.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v20.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(
            safe_ratio(v20.seconds_per_completion(), r2.seconds_per_completion())
        )
        v19_relief.append(v19.relief_occupancy())
        v19_storage.append(v19.storage_occupancy())

        print(
            f"seed={seed} "
            f"v20_completed_ratio={row['completed']:.3f} "
            f"v20_lost_ratio={row['lost']:.3f} "
            f"v20_seconds_ratio={row['seconds']:.3f} "
            f"v20_miss_ratio={row['miss']:.3f} "
            f"v20_severe_ratio={row['severe']:.3f} "
            f"v19_relief={v19.relief_occupancy():.3f} "
            f"v20_relief={v20.relief_occupancy():.3f} "
            f"v19_storage={v19.storage_occupancy():.3f} "
            f"v20_storage={v20.storage_occupancy():.3f} "
            f"relief_vs_r2={relief_vs_r2[-1]:.3f} "
            f"storage_vs_r2={storage_vs_r2[-1]:.3f} "
            f"completed_vs_r2={completed_vs_r2[-1]:.3f} "
            f"miss_vs_r2={miss_vs_r2[-1]:.3f} "
            f"terminal_backlog={v20.terminal_backlog}"
        )

    mismatches = sum(row.digest_mismatches for row in stats_rows)
    passes = (
        median(row["completed"] for row in rows) >= MIN_COMPLETED_BASELINE
        and median(row["lost"] for row in rows) <= MAX_LOST_BASELINE
        and median(row["seconds"] for row in rows) <= MAX_SECONDS_BASELINE
        and median(row["miss"] for row in rows) <= MAX_MISS_BASELINE
        and median(row["severe"] for row in rows) <= MAX_SEVERE_BASELINE
        and median(row.terminal_backlog for row in stats_rows) == 0
        and mismatches == 0
        and median(row.relief_occupancy() for row in stats_rows) <= MAX_OCCUPANCY
        and median(row.storage_occupancy() for row in stats_rows) <= MAX_OCCUPANCY
        and median(relief_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(storage_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(completed_vs_r2) >= MIN_COMPLETED_VS_R2
        and median(miss_vs_r2) <= MAX_MISS_VS_R2
        and median(seconds_vs_r2) <= MAX_SECONDS_VS_R2
    )

    print("\n[overall]")
    print(
        f"v19_median_relief={median(v19_relief):.3f} "
        f"v19_median_storage={median(v19_storage):.3f}"
    )
    print(
        f"v20_median_completed_ratio={median(row['completed'] for row in rows):.3f} "
        f"v20_median_lost_ratio={median(row['lost'] for row in rows):.3f} "
        f"v20_median_seconds_ratio={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"v20_median_miss_ratio={median(row['miss'] for row in rows):.3f} "
        f"v20_median_severe_ratio={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"v20_median_relief={median(row.relief_occupancy() for row in stats_rows):.3f} "
        f"v20_median_storage={median(row.storage_occupancy() for row in stats_rows):.3f} "
        f"median_relief_vs_r2={median(relief_vs_r2):.3f} "
        f"median_storage_vs_r2={median(storage_vs_r2):.3f}"
    )
    print(
        f"median_completed_vs_r2={median(completed_vs_r2):.3f} "
        f"median_miss_vs_r2={median(miss_vs_r2):.3f} "
        f"median_seconds_vs_r2={median(seconds_vs_r2):.3f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.20 tests whether RESERVE was a self-locking recovery veto: "
        "entry remains unchanged, while recovery is allowed from low PAIN and a "
        "non-worsening TRAJECTORY using the same dwell and existing actuators."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
