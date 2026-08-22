from __future__ import annotations

from statistics import median

from bardocompute.exchange import ExchangeResult, MembraneCommand
from bidirectional_homeostasis import BOOST_AMOUNT, BOOSTED_SAFE_CAP
from exchange_conservation import FlowPreservingMembrane
from real_work_queue_outcome_audit_r3 import (
    OutcomeStats,
    run_outcome_policy,
    safe_ratio,
)
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

# Fresh held-out family, preregistered in docs/computational-interoception-v0.19.md.
SEEDS = (7_100_171, 7_200_173, 7_300_179, 7_400_181, 7_500_187, 7_600_191)

# Frozen self-state thresholds. These are aligned to already-preregistered
# external miss bands and baseline capacity; they are not tuned on SEEDS.
MODERATE_PAIN = 0.25
SEVERE_PAIN = 0.50
LOW_RESERVE = 0.25
HEALTHY_PAIN = 0.10
RESTORED_RESERVE = 0.75
MIN_ACTIVE_LOAD = 0.50
WORSENING_TRAJECTORY = 0.05
RECOVERY_TRAJECTORY = 0.02
RECOVERY_DWELL = 2
TRAJECTORY_ALPHA = 0.40
MAX_RELEASE_REFERENCE = 128.0

# Preregistered v0.19 outcome/selectivity gates.
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


class InteroceptiveMembrane:
    """Multi-signal self-state using only the already-existing actuator family.

    The controller does not receive a scalar stress value. It keeps role-specific
    LOAD, PAIN, RESERVE, TRAJECTORY, and RECOVERY signals from completed past
    epochs. External outcome judgment remains separate in the R3 audit runner.
    """

    def __init__(self) -> None:
        self.base = FlowPreservingMembrane(route_enabled=True)
        self.current_boost = 0.0
        self.protective = False
        self.protective_transitions = 0
        self.protective_epochs = 0
        self.storage_epochs = 0

        self.load = 0.0
        self.pain = 0.0
        self.reserve = 1.0
        self.trajectory = 0.0
        self.recovery = 0
        self.buffered = 0
        self._previous_pain = 0.0
        self._previous_backlog_ratio = 0.0

    def _should_enter(self) -> bool:
        if self.pain >= SEVERE_PAIN:
            return True
        if self.load < MIN_ACTIVE_LOAD:
            return False
        if self.pain >= MODERATE_PAIN and self.trajectory >= WORSENING_TRAJECTORY:
            return True
        if self.reserve <= LOW_RESERVE and self.trajectory >= WORSENING_TRAJECTORY:
            return True
        return False

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.19 forbids voluntary admission shedding")

        if not self.protective and self._should_enter():
            self.protective = True
            self.protective_transitions += 1
        elif self.protective and self.recovery >= RECOVERY_DWELL:
            self.protective = False
            self.protective_transitions += 1

        if self.protective:
            self.current_boost = BOOST_AMOUNT
            release = min(base.release_limit, BOOSTED_SAFE_CAP)
            self.protective_epochs += 1
        else:
            self.current_boost = 0.0
            release = base.release_limit

        storage_active = self.protective or self.buffered > BASE_BUFFER
        buffer_limit = ELASTIC_BUFFER_LIMIT if storage_active else BASE_BUFFER
        self.storage_epochs += int(storage_active)

        return MembraneCommand(
            admission_limit=None,
            release_limit=release,
            buffer_limit=buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )

    def observe(self, result: ExchangeResult) -> None:
        self.base.observe(result)
        self.buffered = result.buffered

        self.load = min(1.5, result.released / MAX_RELEASE_REFERENCE)
        self.pain = max(0, result.released - result.delivered) / max(1, result.released)
        backlog_ratio = result.buffered / BASE_BUFFER
        self.reserve = max(0.0, 1.0 - backlog_ratio)

        raw_trajectory = (
            0.65 * (self.pain - self._previous_pain)
            + 0.35 * (backlog_ratio - self._previous_backlog_ratio)
        )
        self.trajectory = (
            (1.0 - TRAJECTORY_ALPHA) * self.trajectory
            + TRAJECTORY_ALPHA * raw_trajectory
        )

        healthy = (
            self.pain < HEALTHY_PAIN
            and self.reserve >= RESTORED_RESERVE
            and self.trajectory <= RECOVERY_TRAJECTORY
        )
        self.recovery = self.recovery + 1 if healthy else 0

        self._previous_pain = self.pain
        self._previous_backlog_ratio = backlog_ratio


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

    print("benchmark=computational_interoception_v0.19")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("self_state=LOAD+PAIN+RESERVE+TRAJECTORY+RECOVERY")
    print("scalar_internal_stress=false")
    print("external_outcome_judge=R3_independent_vector")
    print("new_actuators=false")
    print("future_phase_information=false")
    print("admission_shedding=false")

    rows: list[dict[str, float]] = []
    v19_stats_rows: list[OutcomeStats] = []
    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []
    r1_miss_ratios: list[float] = []
    r2_miss_ratios: list[float] = []

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
        controller = InteroceptiveMembrane()
        v19 = run_outcome_policy(
            epochs,
            controller=controller,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        row = ratios(v19, baseline)
        r1_row = ratios(r1, baseline)
        r2_row = ratios(r2, baseline)
        rows.append(row)
        v19_stats_rows.append(v19)
        r1_miss_ratios.append(r1_row["miss"])
        r2_miss_ratios.append(r2_row["miss"])

        relief_vs_r2.append(
            safe_ratio(v19.relief_occupancy(), r2.relief_occupancy())
        )
        storage_vs_r2.append(
            safe_ratio(v19.storage_occupancy(), r2.storage_occupancy())
        )
        completed_vs_r2.append(safe_ratio(v19.completed, r2.completed))
        miss_vs_r2.append(
            safe_ratio(v19.deadline_miss_epochs, r2.deadline_miss_epochs)
        )
        seconds_vs_r2.append(
            safe_ratio(v19.seconds_per_completion(), r2.seconds_per_completion())
        )

        print(
            f"seed={seed} "
            f"r1_miss_ratio={r1_row['miss']:.3f} r2_miss_ratio={r2_row['miss']:.3f} "
            f"v19_completed_ratio={row['completed']:.3f} v19_lost_ratio={row['lost']:.3f} "
            f"v19_seconds_ratio={row['seconds']:.3f} v19_miss_ratio={row['miss']:.3f} "
            f"v19_severe_ratio={row['severe']:.3f} "
            f"relief_occupancy={v19.relief_occupancy():.3f} "
            f"storage_occupancy={v19.storage_occupancy():.3f} "
            f"relief_vs_r2={relief_vs_r2[-1]:.3f} storage_vs_r2={storage_vs_r2[-1]:.3f} "
            f"completed_vs_r2={completed_vs_r2[-1]:.3f} miss_vs_r2={miss_vs_r2[-1]:.3f} "
            f"terminal_backlog={v19.terminal_backlog}"
        )

    total_mismatches = sum(row.digest_mismatches for row in v19_stats_rows)
    passes = (
        median(row["completed"] for row in rows) >= MIN_COMPLETED_BASELINE
        and median(row["lost"] for row in rows) <= MAX_LOST_BASELINE
        and median(row["seconds"] for row in rows) <= MAX_SECONDS_BASELINE
        and median(row["miss"] for row in rows) <= MAX_MISS_BASELINE
        and median(row["severe"] for row in rows) <= MAX_SEVERE_BASELINE
        and median(row.terminal_backlog for row in v19_stats_rows) == 0
        and total_mismatches == 0
        and median(row.relief_occupancy() for row in v19_stats_rows) <= MAX_OCCUPANCY
        and median(row.storage_occupancy() for row in v19_stats_rows) <= MAX_OCCUPANCY
        and median(relief_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(storage_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(completed_vs_r2) >= MIN_COMPLETED_VS_R2
        and median(miss_vs_r2) <= MAX_MISS_VS_R2
        and median(seconds_vs_r2) <= MAX_SECONDS_VS_R2
    )

    print("\n[overall]")
    print(
        f"r1_control_median_miss_ratio={median(r1_miss_ratios):.3f} "
        f"r2_control_median_miss_ratio={median(r2_miss_ratios):.3f}"
    )
    print(
        f"v19_median_completed_ratio={median(row['completed'] for row in rows):.3f} "
        f"v19_median_lost_ratio={median(row['lost'] for row in rows):.3f} "
        f"v19_median_seconds_ratio={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"v19_median_miss_ratio={median(row['miss'] for row in rows):.3f} "
        f"v19_median_severe_ratio={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"v19_median_relief_occupancy={median(row.relief_occupancy() for row in v19_stats_rows):.3f} "
        f"v19_median_storage_occupancy={median(row.storage_occupancy() for row in v19_stats_rows):.3f} "
        f"median_relief_vs_r2={median(relief_vs_r2):.3f} "
        f"median_storage_vs_r2={median(storage_vs_r2):.3f}"
    )
    print(
        f"median_completed_vs_r2={median(completed_vs_r2):.3f} "
        f"median_miss_vs_r2={median(miss_vs_r2):.3f} "
        f"median_seconds_vs_r2={median(seconds_vs_r2):.3f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in v19_stats_rows):.1f}")
    print(f"digest_mismatches={total_mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.19 tests whether role-separated internal self-state "
        "can preserve R2-quality real-work outcomes while making existing "
        "RELIEF and STORAGE protection materially more selective."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
