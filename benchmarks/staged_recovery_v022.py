from __future__ import annotations

from statistics import median

from bardocompute.exchange import MembraneCommand
from bidirectional_homeostasis import BOOST_AMOUNT, BOOSTED_SAFE_CAP
from computational_interoception_v019 import (
    HEALTHY_PAIN,
    RECOVERY_DWELL,
    InteroceptiveMembrane,
)
from exchange_conservation import FlowPreservingMembrane
from real_work_queue_outcome_audit_r3 import OutcomeStats, run_outcome_policy, safe_ratio
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from recovery_decoupling_v020 import RecoveryDecoupledMembrane
from storage_reserve import ELASTIC_BUFFER_LIMIT

# Fresh held-out family frozen in docs/staged-recovery-v0.22.md.
SEEDS = (10_100_281, 10_200_283, 10_300_293, 10_400_307, 10_500_311, 10_600_313)

# Original v0.19 absolute promotion bar.
MIN_COMPLETED_BASELINE = 1.25
MAX_LOST_BASELINE = 0.75
MAX_SECONDS_BASELINE = 1.15
MAX_MISS_BASELINE = 0.60
MAX_SEVERE_BASELINE = 0.25
MAX_OCCUPANCY = 0.65

# Frozen v0.19-relative preservation/selectivity gates from the preregistration.
MAX_RELIEF_VS_V19 = 0.75
MIN_COMPLETED_VS_V19 = 0.98
MAX_MISS_VS_V19 = 1.25
MAX_SECONDS_VS_V19 = 1.15


class StagedRecoveryMembrane(InteroceptiveMembrane):
    """Uncap RATE before withdrawing existing RELIEF; no new actuator magnitude."""

    def __init__(self) -> None:
        super().__init__()
        self.mode = "normal"
        self.mode_transitions = 0
        self.probe_epochs = 0

    def _set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            self.mode_transitions += 1
            # Recovery dwell is state-local evidence; do not carry it across modes.
            self.recovery = 0

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.22 forbids voluntary admission shedding")

        if self.mode == "normal":
            if self._should_enter():
                self._set_mode("protective")
        elif self.mode == "protective":
            if self.recovery >= RECOVERY_DWELL:
                self._set_mode("probe")
        elif self.mode == "probe":
            if self._should_enter():
                self._set_mode("protective")
            elif self.recovery >= RECOVERY_DWELL:
                self._set_mode("normal")
        else:
            raise AssertionError(f"unknown v0.22 mode: {self.mode}")

        if self.mode == "protective":
            self.current_boost = BOOST_AMOUNT
            release = min(base.release_limit, BOOSTED_SAFE_CAP)
            self.protective_epochs += 1
        elif self.mode == "probe":
            # Frozen v0.22 change: restore the existing base/full RATE first,
            # while retaining the already-existing RELIEF magnitude.
            self.current_boost = BOOST_AMOUNT
            release = base.release_limit
            self.probe_epochs += 1
        else:
            self.current_boost = 0.0
            release = base.release_limit

        # Preserve v0.19 retention semantics: protection expands storage, and
        # retained backlog keeps storage expanded until it is actually drained.
        storage_active = self.mode == "protective" or self.buffered > BASE_BUFFER
        buffer_limit = ELASTIC_BUFFER_LIMIT if storage_active else BASE_BUFFER
        self.storage_epochs += int(storage_active)
        self.protective = self.mode == "protective"

        return MembraneCommand(
            admission_limit=None,
            release_limit=release,
            buffer_limit=buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )

    def observe(self, result) -> None:
        previous_recovery = self.recovery
        super().observe(result)

        # v0.22 recovery evidence is deliberately PAIN-only; the tested change
        # is staged actuator withdrawal, not another predicate combination.
        healthy_for_recovery = self.pain < HEALTHY_PAIN
        self.recovery = previous_recovery + 1 if healthy_for_recovery else 0


def ratios(candidate: OutcomeStats, baseline: OutcomeStats) -> dict[str, float]:
    return {
        "completed": safe_ratio(candidate.completed, baseline.completed),
        "lost": safe_ratio(candidate.lost, baseline.lost),
        "seconds": safe_ratio(candidate.seconds_per_completion(), baseline.seconds_per_completion()),
        "miss": safe_ratio(candidate.deadline_miss_epochs, baseline.deadline_miss_epochs),
        "severe": safe_ratio(candidate.severe_miss_epochs, baseline.severe_miss_epochs),
    }


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=staged_recovery_v0.22")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("entry_semantics=unchanged_v0.19")
    print("recovery_sequence=PROTECTIVE->RECOVERY_PROBE->NORMAL")
    print("probe_rate=existing_base_release")
    print("probe_relief=existing_BOOST_AMOUNT")
    print(f"recovery_dwell={RECOVERY_DWELL}")
    print("new_actuators=false")
    print("new_actuator_magnitudes=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    rows_v22: list[dict[str, float]] = []
    stats_v22: list[OutcomeStats] = []
    relief_vs_v19: list[float] = []
    completed_vs_v19: list[float] = []
    miss_vs_v19: list[float] = []
    seconds_vs_v19: list[float] = []
    v19_relief: list[float] = []
    v19_storage: list[float] = []
    v20_relief: list[float] = []
    v20_storage: list[float] = []
    probe_occupancy: list[float] = []
    mode_transitions: list[int] = []

    for seed in SEEDS:
        epochs = build_epochs(seed)
        baseline = run_outcome_policy(
            epochs,
            controller=FlowPreservingMembrane(route_enabled=True),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        controller_v19 = InteroceptiveMembrane()
        v19 = run_outcome_policy(
            epochs,
            controller=controller_v19,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        controller_v20 = RecoveryDecoupledMembrane()
        v20 = run_outcome_policy(
            epochs,
            controller=controller_v20,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        controller_v22 = StagedRecoveryMembrane()
        v22 = run_outcome_policy(
            epochs,
            controller=controller_v22,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        row = ratios(v22, baseline)
        rows_v22.append(row)
        stats_v22.append(v22)
        relief_vs_v19.append(safe_ratio(v22.relief_occupancy(), v19.relief_occupancy()))
        completed_vs_v19.append(safe_ratio(v22.completed, v19.completed))
        miss_vs_v19.append(safe_ratio(v22.deadline_miss_epochs, v19.deadline_miss_epochs))
        seconds_vs_v19.append(safe_ratio(v22.seconds_per_completion(), v19.seconds_per_completion()))
        v19_relief.append(v19.relief_occupancy())
        v19_storage.append(v19.storage_occupancy())
        v20_relief.append(v20.relief_occupancy())
        v20_storage.append(v20.storage_occupancy())
        probe_occupancy.append(controller_v22.probe_epochs / max(1, v22.executed_epochs))
        mode_transitions.append(controller_v22.mode_transitions)

        print(
            f"seed={seed} "
            f"v22_completed={row['completed']:.3f} v22_lost={row['lost']:.3f} "
            f"v22_seconds={row['seconds']:.3f} v22_miss={row['miss']:.3f} "
            f"v22_severe={row['severe']:.3f} "
            f"v19_relief={v19.relief_occupancy():.3f} v20_relief={v20.relief_occupancy():.3f} "
            f"v22_relief={v22.relief_occupancy():.3f} v22_storage={v22.storage_occupancy():.3f} "
            f"v22_probe={probe_occupancy[-1]:.3f} transitions={controller_v22.mode_transitions} "
            f"completed_vs_v19={completed_vs_v19[-1]:.3f} miss_vs_v19={miss_vs_v19[-1]:.3f} "
            f"terminal_backlog={v22.terminal_backlog}"
        )

    mismatches = sum(row.digest_mismatches for row in stats_v22)
    passes = (
        median(row["completed"] for row in rows_v22) >= MIN_COMPLETED_BASELINE
        and median(row["lost"] for row in rows_v22) <= MAX_LOST_BASELINE
        and median(row["seconds"] for row in rows_v22) <= MAX_SECONDS_BASELINE
        and median(row["miss"] for row in rows_v22) <= MAX_MISS_BASELINE
        and median(row["severe"] for row in rows_v22) <= MAX_SEVERE_BASELINE
        and median(row.relief_occupancy() for row in stats_v22) <= MAX_OCCUPANCY
        and median(row.storage_occupancy() for row in stats_v22) <= MAX_OCCUPANCY
        and median(row.terminal_backlog for row in stats_v22) == 0
        and mismatches == 0
        and median(relief_vs_v19) <= MAX_RELIEF_VS_V19
        and median(completed_vs_v19) >= MIN_COMPLETED_VS_V19
        and median(miss_vs_v19) <= MAX_MISS_VS_V19
        and median(seconds_vs_v19) <= MAX_SECONDS_VS_V19
    )

    print("\n[overall]")
    print(
        f"v19_median_relief={median(v19_relief):.3f} v19_median_storage={median(v19_storage):.3f} "
        f"v20_median_relief={median(v20_relief):.3f} v20_median_storage={median(v20_storage):.3f}"
    )
    print(
        f"v22_median_completed_ratio={median(row['completed'] for row in rows_v22):.3f} "
        f"v22_median_lost_ratio={median(row['lost'] for row in rows_v22):.3f} "
        f"v22_median_seconds_ratio={median(row['seconds'] for row in rows_v22):.3f}"
    )
    print(
        f"v22_median_miss_ratio={median(row['miss'] for row in rows_v22):.3f} "
        f"v22_median_severe_ratio={median(row['severe'] for row in rows_v22):.3f}"
    )
    print(
        f"v22_median_relief={median(row.relief_occupancy() for row in stats_v22):.3f} "
        f"v22_median_storage={median(row.storage_occupancy() for row in stats_v22):.3f} "
        f"v22_median_probe={median(probe_occupancy):.3f} "
        f"v22_median_mode_transitions={median(mode_transitions):.1f}"
    )
    print(
        f"median_relief_vs_v19={median(relief_vs_v19):.3f} "
        f"median_completed_vs_v19={median(completed_vs_v19):.3f} "
        f"median_miss_vs_v19={median(miss_vs_v19):.3f} "
        f"median_seconds_vs_v19={median(seconds_vs_v19):.3f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_v22):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.22 tests staged de-escalation: restore the existing base RATE "
        "before withdrawing existing RELIEF, while keeping entry semantics, thresholds, "
        "actuator magnitudes, and the external R3 outcome judge frozen."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
