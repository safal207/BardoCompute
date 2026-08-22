from __future__ import annotations

from statistics import median

from computational_interoception_v019 import (
    HEALTHY_PAIN,
    RECOVERY_DWELL,
    InteroceptiveMembrane,
)
from exchange_conservation import FlowPreservingMembrane
from real_work_queue_outcome_audit_r3 import (
    OutcomeStats,
    SEVERE_MISS_THRESHOLD,
    run_outcome_policy,
    safe_ratio,
)
from real_work_queue_transfer import build_epochs, calibrate_rounds
from recovery_decoupling_v020 import RecoveryDecoupledMembrane
from recovery_predicate_ablation_v021 import PainOnlyRecoveryMembrane
from storage_reserve import ElasticStorageMembrane

# Fresh held-out family frozen in BardoCompute issue #3 before implementation.
SEEDS = (
    10_100_301,
    10_200_307,
    10_300_311,
    10_400_313,
    10_500_317,
    10_600_321,
)

# Frozen v0.19/v0.22 promotion bar. No retuning on this family.
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


class ResolutionStrengthMembrane(InteroceptiveMembrane):
    """v0.19 entry semantics with bounded accumulated recovery evidence.

    The actuator family and entry logic are unchanged.  Recovery no longer
    depends on restored RESERVE or TRAJECTORY.  Instead, while protection is
    active, completed-epoch evidence accumulates in [0, RECOVERY_DWELL]:

    * low PAIN and no severe miss -> +1
    * severe miss -> -1
    * intermediate non-severe evidence -> hold

    This is inspired by LS VisceralMemory.resolution_strength, but its value is
    judged only by BardoCompute's independent R3 outcome vector.
    """

    def __init__(self) -> None:
        super().__init__()
        self.resolution_strength = 0
        self.resolution_strength_transitions = 0
        self.reentry_count = 0
        self._has_recovered_once = False

    def command(self):
        was_protective = self.protective
        command = super().command()

        if not was_protective and self.protective:
            if self._has_recovered_once:
                self.reentry_count += 1
            if self.resolution_strength != 0:
                self.resolution_strength_transitions += 1
            self.resolution_strength = 0
            self.recovery = 0
        elif was_protective and not self.protective:
            self._has_recovered_once = True

        return command

    def observe(self, result) -> None:
        previous_strength = self.resolution_strength
        super().observe(result)

        # The R3 runner already supplies delivered=on_time in ExchangeResult,
        # so this uses only completed past-epoch evidence available to the
        # controller; it does not receive future phase labels or evaluator state.
        miss_fraction = max(0, result.released - result.delivered) / max(1, result.released)
        severe_miss = result.released > 0 and miss_fraction >= SEVERE_MISS_THRESHOLD

        if self.protective:
            healthy_evidence = self.pain < HEALTHY_PAIN and not severe_miss
            if healthy_evidence:
                self.resolution_strength = min(
                    RECOVERY_DWELL, self.resolution_strength + 1
                )
            elif severe_miss:
                self.resolution_strength = max(0, self.resolution_strength - 1)
            # Intermediate non-severe evidence deliberately holds accumulated
            # resolution rather than erasing it, per frozen issue #3 semantics.

        if self.resolution_strength != previous_strength:
            self.resolution_strength_transitions += 1

        # InteroceptiveMembrane.command() already uses self.recovery for the
        # exit predicate, so expose the frozen accumulator through that field.
        self.recovery = self.resolution_strength


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
        "severe": safe_ratio(
            candidate.severe_miss_epochs, baseline.severe_miss_epochs
        ),
    }


def summarize(name: str, rows: list[dict[str, float]], stats: list[OutcomeStats]) -> None:
    print(f"\n[{name}]")
    print(
        f"median_completed_ratio={median(row['completed'] for row in rows):.3f} "
        f"median_lost_ratio={median(row['lost'] for row in rows):.3f} "
        f"median_seconds_ratio={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"median_miss_ratio={median(row['miss'] for row in rows):.3f} "
        f"median_severe_ratio={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"median_relief_occupancy={median(row.relief_occupancy() for row in stats):.3f} "
        f"median_storage_occupancy={median(row.storage_occupancy() for row in stats):.3f} "
        f"median_terminal_backlog={median(row.terminal_backlog for row in stats):.1f}"
    )
    print(f"digest_mismatches={sum(row.digest_mismatches for row in stats)}")


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=resolution_strength_v0.22")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("source_inspiration=LS_VisceralMemory_resolution_strength")
    print("entry_semantics=unchanged_v0.19")
    print("recovery=bounded_resolution_strength")
    print(f"resolution_strength_bounds=0..{RECOVERY_DWELL}")
    print("RESERVE_entry_signal=true")
    print("RESERVE_recovery_veto=false")
    print("TRAJECTORY_required_for_exit=false")
    print("new_actuators=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    comparator_rows: dict[str, list[dict[str, float]]] = {
        "r2": [],
        "v19": [],
        "v20": [],
        "pain_only": [],
        "v22": [],
    }
    comparator_stats: dict[str, list[OutcomeStats]] = {
        key: [] for key in comparator_rows
    }

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []

    v22_miss_vs_v20: list[float] = []
    v22_relief_vs_v19: list[float] = []
    v22_storage_vs_v19: list[float] = []
    resolution_transitions: list[int] = []
    reentries: list[int] = []

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
        v19_controller = InteroceptiveMembrane()
        v19 = run_outcome_policy(
            epochs,
            controller=v19_controller,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v20_controller = RecoveryDecoupledMembrane()
        v20 = run_outcome_policy(
            epochs,
            controller=v20_controller,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        pain_controller = PainOnlyRecoveryMembrane()
        pain_only = run_outcome_policy(
            epochs,
            controller=pain_controller,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v22_controller = ResolutionStrengthMembrane()
        v22 = run_outcome_policy(
            epochs,
            controller=v22_controller,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        for name, stat in (
            ("r2", r2),
            ("v19", v19),
            ("v20", v20),
            ("pain_only", pain_only),
            ("v22", v22),
        ):
            comparator_rows[name].append(ratios(stat, baseline))
            comparator_stats[name].append(stat)

        relief_vs_r2.append(safe_ratio(v22.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v22.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v22.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v22.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(
            safe_ratio(v22.seconds_per_completion(), r2.seconds_per_completion())
        )

        v22_miss_vs_v20.append(
            safe_ratio(v22.deadline_miss_epochs, v20.deadline_miss_epochs)
        )
        v22_relief_vs_v19.append(
            safe_ratio(v22.relief_occupancy(), v19.relief_occupancy())
        )
        v22_storage_vs_v19.append(
            safe_ratio(v22.storage_occupancy(), v19.storage_occupancy())
        )
        resolution_transitions.append(v22_controller.resolution_strength_transitions)
        reentries.append(v22_controller.reentry_count)

        v22_row = comparator_rows["v22"][-1]
        print(
            f"seed={seed} "
            f"v22_completed_ratio={v22_row['completed']:.3f} "
            f"v22_lost_ratio={v22_row['lost']:.3f} "
            f"v22_seconds_ratio={v22_row['seconds']:.3f} "
            f"v22_miss_ratio={v22_row['miss']:.3f} "
            f"v22_severe_ratio={v22_row['severe']:.3f} "
            f"v22_relief={v22.relief_occupancy():.3f} "
            f"v22_storage={v22.storage_occupancy():.3f} "
            f"miss_vs_v20={v22_miss_vs_v20[-1]:.3f} "
            f"relief_vs_v19={v22_relief_vs_v19[-1]:.3f} "
            f"resolution_transitions={v22_controller.resolution_strength_transitions} "
            f"reentries={v22_controller.reentry_count} "
            f"terminal_backlog={v22.terminal_backlog}"
        )

    for name in ("r2", "v19", "v20", "pain_only", "v22"):
        summarize(name, comparator_rows[name], comparator_stats[name])

    rows = comparator_rows["v22"]
    stats_rows = comparator_stats["v22"]
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
        f"v22_median_completed_ratio={median(row['completed'] for row in rows):.3f} "
        f"v22_median_lost_ratio={median(row['lost'] for row in rows):.3f} "
        f"v22_median_seconds_ratio={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"v22_median_miss_ratio={median(row['miss'] for row in rows):.3f} "
        f"v22_median_severe_ratio={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"v22_median_relief={median(row.relief_occupancy() for row in stats_rows):.3f} "
        f"v22_median_storage={median(row.storage_occupancy() for row in stats_rows):.3f} "
        f"median_relief_vs_r2={median(relief_vs_r2):.3f} "
        f"median_storage_vs_r2={median(storage_vs_r2):.3f}"
    )
    print(
        f"median_completed_vs_r2={median(completed_vs_r2):.3f} "
        f"median_miss_vs_r2={median(miss_vs_r2):.3f} "
        f"median_seconds_vs_r2={median(seconds_vs_r2):.3f}"
    )
    print(
        f"median_v22_miss_vs_v20={median(v22_miss_vs_v20):.3f} "
        f"median_v22_relief_vs_v19={median(v22_relief_vs_v19):.3f} "
        f"median_v22_storage_vs_v19={median(v22_storage_vs_v19):.3f}"
    )
    print(
        f"median_resolution_strength_transitions={median(resolution_transitions):.1f} "
        f"median_reentry_count={median(reentries):.1f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.22 tests whether a separate bounded accumulator of "
        "successful recovery evidence can sit between chronic protection and "
        "premature exit while preserving independent real-work outcomes."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
