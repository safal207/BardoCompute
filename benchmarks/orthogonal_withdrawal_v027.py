from __future__ import annotations

from statistics import median

from bardocompute.exchange import MembraneCommand
from bidirectional_homeostasis import BOOST_AMOUNT, BOOSTED_SAFE_CAP
from computational_interoception_v019 import (
    HEALTHY_PAIN,
    InteroceptiveMembrane,
    MAX_LOST_BASELINE,
    MAX_MISS_BASELINE,
    MAX_OCCUPANCY,
    MAX_OCCUPANCY_VS_R2,
    MAX_SECONDS_BASELINE,
    MAX_SECONDS_VS_R2,
    MAX_SEVERE_BASELINE,
    MIN_COMPLETED_BASELINE,
    MIN_COMPLETED_VS_R2,
    RECOVERY_DWELL,
)
from continuous_missed_work_factorial_v026 import run_continuous_policy
from exchange_conservation import FlowPreservingMembrane
from real_work_queue_outcome_audit_r3 import (
    OutcomeStats,
    SEVERE_MISS_THRESHOLD,
    run_outcome_policy,
    safe_ratio,
)
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from resolution_strength_v022 import ResolutionStrengthMembrane
from staged_withdrawal_v024 import StagedWithdrawalMembrane
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

# Fresh held-out family frozen in issue #14 before implementation/results.
SEEDS = (
    15_100_479,
    15_200_487,
    15_300_491,
    15_400_499,
    15_500_503,
    15_600_509,
)


class OrthogonalWithdrawalMembrane(InteroceptiveMembrane):
    """Probe RELIEF and RATE readiness independently before full withdrawal.

    State path for one recovery attempt:

        PROTECTED
          -> RELIEF_PROBE      (RELIEF off, RATE cap on)
          -> FULL_SUPPORT_BRIDGE
          -> RATE_PROBE        (RELIEF on, base RATE)
          -> FINAL_PROBE       (RELIEF off, base RATE)
          -> normal exchange

    Any failed probe returns to PROTECTED and resets the bounded recovery
    evidence.  The bridge lasts exactly one completed epoch and has no gate.
    """

    PROTECTED = 0
    RELIEF_PROBE = 1
    FULL_SUPPORT_BRIDGE = 2
    RATE_PROBE = 3
    FINAL_PROBE = 4

    def __init__(self) -> None:
        super().__init__()
        self.resolution_strength = 0
        self.withdrawal_stage = self.PROTECTED
        self.relief_ready = False
        self.rate_ready = False

        self.relief_probe_count = 0
        self.relief_probe_success = 0
        self.relief_probe_failure = 0
        self.rate_probe_count = 0
        self.rate_probe_success = 0
        self.rate_probe_failure = 0
        self.final_probe_count = 0
        self.final_probe_success = 0
        self.final_probe_failure = 0
        self.bridge_count = 0
        self.post_success_reentries = 0
        self._successful_exit_pending_reentry = False

    def _reset_attempt(self) -> None:
        self.resolution_strength = 0
        self.relief_ready = False
        self.rate_ready = False
        self.withdrawal_stage = self.PROTECTED
        self.recovery = 0

    def _normal_after_exit(self, base: MembraneCommand) -> MembraneCommand:
        storage_active = self.buffered > BASE_BUFFER
        return MembraneCommand(
            admission_limit=None,
            release_limit=base.release_limit,
            buffer_limit=ELASTIC_BUFFER_LIMIT if storage_active else BASE_BUFFER,
            secondary_fraction=base.secondary_fraction,
        )

    def _full_support(self, base: MembraneCommand) -> MembraneCommand:
        self.current_boost = BOOST_AMOUNT
        return MembraneCommand(
            admission_limit=None,
            release_limit=min(base.release_limit, BOOSTED_SAFE_CAP),
            buffer_limit=ELASTIC_BUFFER_LIMIT,
            secondary_fraction=base.secondary_fraction,
        )

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.27 forbids voluntary admission shedding")

        if not self.protective and self._should_enter():
            self.protective = True
            self.protective_transitions += 1
            self._reset_attempt()
            if self._successful_exit_pending_reentry:
                self.post_success_reentries += 1
                self._successful_exit_pending_reentry = False

        if (
            self.protective
            and self.withdrawal_stage == self.PROTECTED
            and self.resolution_strength >= RECOVERY_DWELL
        ):
            self.withdrawal_stage = self.RELIEF_PROBE
            self.relief_probe_count += 1

        if self.withdrawal_stage == self.RELIEF_PROBE:
            self.current_boost = 0.0
            return MembraneCommand(
                admission_limit=None,
                release_limit=min(base.release_limit, BOOSTED_SAFE_CAP),
                buffer_limit=ELASTIC_BUFFER_LIMIT,
                secondary_fraction=base.secondary_fraction,
            )

        if self.withdrawal_stage == self.FULL_SUPPORT_BRIDGE:
            return self._full_support(base)

        if self.withdrawal_stage == self.RATE_PROBE:
            self.current_boost = BOOST_AMOUNT
            return MembraneCommand(
                admission_limit=None,
                release_limit=base.release_limit,
                buffer_limit=ELASTIC_BUFFER_LIMIT,
                secondary_fraction=base.secondary_fraction,
            )

        if self.withdrawal_stage == self.FINAL_PROBE:
            self.current_boost = 0.0
            return MembraneCommand(
                admission_limit=None,
                release_limit=base.release_limit,
                buffer_limit=ELASTIC_BUFFER_LIMIT,
                secondary_fraction=base.secondary_fraction,
            )

        if self.protective:
            self.protective_epochs += 1
            self.storage_epochs += 1
            return self._full_support(base)

        self.current_boost = 0.0
        return self._normal_after_exit(base)

    def observe(self, result) -> None:
        super().observe(result)

        miss_fraction = max(0, result.released - result.delivered) / max(1, result.released)
        severe_miss = result.released > 0 and miss_fraction >= SEVERE_MISS_THRESHOLD
        healthy = self.pain < HEALTHY_PAIN and not severe_miss

        if self.withdrawal_stage == self.RELIEF_PROBE:
            if healthy:
                self.relief_probe_success += 1
                self.relief_ready = True
                self.withdrawal_stage = self.FULL_SUPPORT_BRIDGE
                self.bridge_count += 1
            else:
                self.relief_probe_failure += 1
                self._reset_attempt()
            self.recovery = 0
            return

        if self.withdrawal_stage == self.FULL_SUPPORT_BRIDGE:
            # Frozen prereg clarification: exactly one completed full-support
            # bridge epoch, no extra success/failure criterion.
            self.withdrawal_stage = self.RATE_PROBE
            self.rate_probe_count += 1
            self.recovery = 0
            return

        if self.withdrawal_stage == self.RATE_PROBE:
            if healthy:
                self.rate_probe_success += 1
                self.rate_ready = True
                self.withdrawal_stage = self.FINAL_PROBE
                self.final_probe_count += 1
            else:
                self.rate_probe_failure += 1
                self._reset_attempt()
            self.recovery = 0
            return

        if self.withdrawal_stage == self.FINAL_PROBE:
            if healthy and self.relief_ready and self.rate_ready:
                self.final_probe_success += 1
                self.withdrawal_stage = self.PROTECTED
                self.protective = False
                self.protective_transitions += 1
                self._successful_exit_pending_reentry = True
                self.resolution_strength = 0
                self.relief_ready = False
                self.rate_ready = False
            else:
                self.final_probe_failure += 1
                self._reset_attempt()
            self.recovery = 0
            return

        if self.protective:
            if healthy:
                self.resolution_strength = min(
                    RECOVERY_DWELL, self.resolution_strength + 1
                )
            elif severe_miss:
                self.resolution_strength = max(0, self.resolution_strength - 1)
        else:
            self.resolution_strength = 0

        # Exit is controlled only by the explicit orthogonal state machine.
        self.recovery = 0


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


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=orthogonal_support_withdrawal_v0.27")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("entry_semantics=unchanged_v0.19")
    print("recovery_prerequisite=resolution_strength>=2")
    print("probe1=RELIEF_off+RATE_cap")
    print("bridge=one_full_support_epoch_no_gate")
    print("probe2=RELIEF_on+base_RATE")
    print("final_probe=RELIEF_off+base_RATE")
    print("new_actuator_magnitudes=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")
    print("continuous_burden=separate_same_seed_diagnostic_replay")

    names = ("r2", "v19", "v22", "v24", "v27")
    rows_by_name: dict[str, list[dict[str, float]]] = {name: [] for name in names}
    stats_by_name: dict[str, list[OutcomeStats]] = {name: [] for name in names}

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []
    burden_diagnostic: list[float] = []

    relief_probe_count: list[int] = []
    relief_probe_success: list[int] = []
    relief_probe_failure: list[int] = []
    rate_probe_count: list[int] = []
    rate_probe_success: list[int] = []
    rate_probe_failure: list[int] = []
    final_probe_count: list[int] = []
    final_probe_success: list[int] = []
    final_probe_failure: list[int] = []
    bridge_count: list[int] = []
    post_success_reentries: list[int] = []
    protective_transitions: list[int] = []

    for seed in SEEDS:
        epochs = build_epochs(seed)
        baseline = run_outcome_policy(
            epochs,
            controller=FlowPreservingMembrane(route_enabled=True),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        controllers = {
            "r2": ElasticStorageMembrane(),
            "v19": InteroceptiveMembrane(),
            "v22": ResolutionStrengthMembrane(),
            "v24": StagedWithdrawalMembrane(),
            "v27": OrthogonalWithdrawalMembrane(),
        }
        current: dict[str, OutcomeStats] = {}
        for name, controller in controllers.items():
            current[name] = run_outcome_policy(
                epochs,
                controller=controller,
                sensor_mode="r2" if name == "r2" else None,
                rounds=rounds,
                deadline_seconds=deadline_seconds,
            )
            rows_by_name[name].append(ratios(current[name], baseline))
            stats_by_name[name].append(current[name])

        r2 = current["r2"]
        v27 = current["v27"]
        controller = controllers["v27"]
        assert isinstance(controller, OrthogonalWithdrawalMembrane)

        relief_vs_r2.append(safe_ratio(v27.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v27.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v27.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v27.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(
            safe_ratio(v27.seconds_per_completion(), r2.seconds_per_completion())
        )

        diagnostic = run_continuous_policy(
            epochs,
            controller=OrthogonalWithdrawalMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        burden_diagnostic.append(diagnostic.missed_work_burden())

        relief_probe_count.append(controller.relief_probe_count)
        relief_probe_success.append(controller.relief_probe_success)
        relief_probe_failure.append(controller.relief_probe_failure)
        rate_probe_count.append(controller.rate_probe_count)
        rate_probe_success.append(controller.rate_probe_success)
        rate_probe_failure.append(controller.rate_probe_failure)
        final_probe_count.append(controller.final_probe_count)
        final_probe_success.append(controller.final_probe_success)
        final_probe_failure.append(controller.final_probe_failure)
        bridge_count.append(controller.bridge_count)
        post_success_reentries.append(controller.post_success_reentries)
        protective_transitions.append(controller.protective_transitions)

        row = rows_by_name["v27"][-1]
        print(
            f"seed={seed} "
            f"completed={row['completed']:.3f} lost={row['lost']:.3f} "
            f"seconds={row['seconds']:.3f} miss={row['miss']:.3f} "
            f"severe={row['severe']:.3f} relief={v27.relief_occupancy():.3f} "
            f"storage={v27.storage_occupancy():.3f} burden={burden_diagnostic[-1]:.6f} "
            f"relief_probe={controller.relief_probe_success}/{controller.relief_probe_count} "
            f"rate_probe={controller.rate_probe_success}/{controller.rate_probe_count} "
            f"final_probe={controller.final_probe_success}/{controller.final_probe_count} "
            f"reentries={controller.post_success_reentries}"
        )

    rows = rows_by_name["v27"]
    stats_rows = stats_by_name["v27"]
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
        and median(miss_vs_r2) <= 1.25
        and median(seconds_vs_r2) <= MAX_SECONDS_VS_R2
    )

    print("\n[overall]")
    print(
        f"v27_median_completed_ratio={median(row['completed'] for row in rows):.3f} "
        f"v27_median_lost_ratio={median(row['lost'] for row in rows):.3f} "
        f"v27_median_seconds_ratio={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"v27_median_miss_ratio={median(row['miss'] for row in rows):.3f} "
        f"v27_median_severe_ratio={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"v27_median_relief={median(row.relief_occupancy() for row in stats_rows):.3f} "
        f"v27_median_storage={median(row.storage_occupancy() for row in stats_rows):.3f} "
        f"median_relief_vs_r2={median(relief_vs_r2):.3f} "
        f"median_storage_vs_r2={median(storage_vs_r2):.3f}"
    )
    print(
        f"median_completed_vs_r2={median(completed_vs_r2):.3f} "
        f"median_miss_vs_r2={median(miss_vs_r2):.3f} "
        f"median_seconds_vs_r2={median(seconds_vs_r2):.3f}"
    )
    print(f"median_continuous_missed_work_burden={median(burden_diagnostic):.6f}")
    print(
        f"median_relief_probe_count={median(relief_probe_count):.1f} "
        f"median_relief_probe_success={median(relief_probe_success):.1f} "
        f"median_relief_probe_failure={median(relief_probe_failure):.1f}"
    )
    print(
        f"median_rate_probe_count={median(rate_probe_count):.1f} "
        f"median_rate_probe_success={median(rate_probe_success):.1f} "
        f"median_rate_probe_failure={median(rate_probe_failure):.1f}"
    )
    print(
        f"median_final_probe_count={median(final_probe_count):.1f} "
        f"median_final_probe_success={median(final_probe_success):.1f} "
        f"median_final_probe_failure={median(final_probe_failure):.1f} "
        f"median_bridge_count={median(bridge_count):.1f}"
    )
    print(
        f"median_post_success_reentries={median(post_success_reentries):.1f} "
        f"median_protective_transitions={median(protective_transitions):.1f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.27 tests component-specific readiness by probing RELIEF "
        "and RATE withdrawal independently with the complementary support restored, "
        "then requiring a final combined unsupported challenge."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
