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
from continuous_miss_burden_v026 import run_continuous_policy
from exchange_conservation import FlowPreservingMembrane
from real_work_queue_outcome_audit_r3 import (
    OutcomeStats,
    SEVERE_MISS_THRESHOLD,
    run_outcome_policy,
    safe_ratio,
)
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from staged_withdrawal_v024 import StagedWithdrawalMembrane
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

# Fresh held-out family frozen in issue #15 before implementation/results.
SEEDS = (
    16_100_533,
    16_200_539,
    16_300_547,
    16_400_553,
    16_500_559,
    16_600_563,
    16_700_571,
    16_800_577,
)


class RateFirstRecoveryMembrane(InteroceptiveMembrane):
    """Withdraw RATE protection before RELIEF using frozen v0.22 evidence.

    This changes only support-withdrawal order relative to v0.24. Entry logic,
    thresholds, actuator magnitudes, and the bounded v0.22 recovery accumulator
    remain frozen. Controllers never receive workload phase labels.
    """

    PROTECTED = 0
    RATE_RELAXED = 1
    RELIEF_WITHDRAWAL = 2

    def __init__(self) -> None:
        super().__init__()
        self.resolution_strength = 0
        self.withdrawal_stage = self.PROTECTED
        self.rate_relaxed_count = 0
        self.rate_relaxed_success = 0
        self.rate_relaxed_failure = 0
        self.relief_withdrawal_count = 0
        self.relief_withdrawal_success = 0
        self.relief_withdrawal_failure = 0
        self.post_success_reentries = 0
        self._successful_exit_pending_reentry = False

    def _normal_after_exit(self, base: MembraneCommand) -> MembraneCommand:
        storage_active = self.buffered > BASE_BUFFER
        return MembraneCommand(
            admission_limit=None,
            release_limit=base.release_limit,
            buffer_limit=ELASTIC_BUFFER_LIMIT if storage_active else BASE_BUFFER,
            secondary_fraction=base.secondary_fraction,
        )

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.28 forbids voluntary admission shedding")

        if not self.protective and self._should_enter():
            self.protective = True
            self.protective_transitions += 1
            self.resolution_strength = 0
            self.withdrawal_stage = self.PROTECTED
            if self._successful_exit_pending_reentry:
                self.post_success_reentries += 1
                self._successful_exit_pending_reentry = False

        if (
            self.protective
            and self.withdrawal_stage == self.PROTECTED
            and self.resolution_strength >= RECOVERY_DWELL
        ):
            self.withdrawal_stage = self.RATE_RELAXED
            self.rate_relaxed_count += 1

        if self.withdrawal_stage == self.RATE_RELAXED:
            # v0.27-supported recovery direction: release RATE cap first while
            # keeping the existing RELIEF support active for one challenge epoch.
            self.current_boost = BOOST_AMOUNT
            return MembraneCommand(
                admission_limit=None,
                release_limit=base.release_limit,
                buffer_limit=ELASTIC_BUFFER_LIMIT,
                secondary_fraction=base.secondary_fraction,
            )

        if self.withdrawal_stage == self.RELIEF_WITHDRAWAL:
            # Second challenge removes RELIEF only after RATE relaxation was
            # tolerated. Retained backlog keeps elastic storage until drained.
            self.current_boost = 0.0
            storage_active = self.buffered > BASE_BUFFER
            return MembraneCommand(
                admission_limit=None,
                release_limit=base.release_limit,
                buffer_limit=ELASTIC_BUFFER_LIMIT if storage_active else BASE_BUFFER,
                secondary_fraction=base.secondary_fraction,
            )

        if self.protective:
            self.current_boost = BOOST_AMOUNT
            self.protective_epochs += 1
            self.storage_epochs += 1
            return MembraneCommand(
                admission_limit=None,
                release_limit=min(base.release_limit, BOOSTED_SAFE_CAP),
                buffer_limit=ELASTIC_BUFFER_LIMIT,
                secondary_fraction=base.secondary_fraction,
            )

        self.current_boost = 0.0
        return self._normal_after_exit(base)

    def observe(self, result) -> None:
        super().observe(result)

        miss_fraction = max(0, result.released - result.delivered) / max(1, result.released)
        severe_miss = result.released > 0 and miss_fraction >= SEVERE_MISS_THRESHOLD
        healthy = self.pain < HEALTHY_PAIN and not severe_miss

        if self.withdrawal_stage == self.RATE_RELAXED:
            self.resolution_strength = 0
            if healthy:
                self.rate_relaxed_success += 1
                self.withdrawal_stage = self.RELIEF_WITHDRAWAL
                self.relief_withdrawal_count += 1
            else:
                self.rate_relaxed_failure += 1
                self.withdrawal_stage = self.PROTECTED
            self.recovery = 0
            return

        if self.withdrawal_stage == self.RELIEF_WITHDRAWAL:
            self.resolution_strength = 0
            if healthy:
                self.relief_withdrawal_success += 1
                self.withdrawal_stage = self.PROTECTED
                self.protective = False
                self.protective_transitions += 1
                self._successful_exit_pending_reentry = True
            else:
                self.relief_withdrawal_failure += 1
                self.withdrawal_stage = self.PROTECTED
            self.recovery = 0
            return

        if self.protective:
            # Exact v0.22 accumulator semantics (see issue #15 correction):
            # healthy -> +1; severe -> -1; intermediate non-severe -> hold.
            if healthy:
                self.resolution_strength = min(
                    RECOVERY_DWELL, self.resolution_strength + 1
                )
            elif severe_miss:
                self.resolution_strength = max(0, self.resolution_strength - 1)
        else:
            self.resolution_strength = 0

        # v0.28 owns the exit state machine explicitly; prevent v0.19's recovery
        # field from becoming a second hidden exit path.
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

    print("benchmark=rate_first_component_specific_recovery_v0.28")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("entry_semantics=unchanged_v0.19")
    print("recovery_evidence=exact_v0.22_bounded_resolution_strength")
    print("withdrawal_order=RATE_first_then_RELIEF")
    print("controllers_phase_blind=true")
    print("new_actuator_magnitudes=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    names = ("r2", "v24", "v28")
    rows_by_name: dict[str, list[dict[str, float]]] = {name: [] for name in names}
    stats_by_name: dict[str, list[OutcomeStats]] = {name: [] for name in names}

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []

    rate_relaxed_count: list[int] = []
    rate_relaxed_success: list[int] = []
    rate_relaxed_failure: list[int] = []
    relief_withdrawal_count: list[int] = []
    relief_withdrawal_success: list[int] = []
    relief_withdrawal_failure: list[int] = []
    post_success_reentries: list[int] = []
    protective_transitions: list[int] = []

    v24_missed_work: list[float] = []
    v28_missed_work: list[float] = []
    v24_severe_excess: list[float] = []
    v28_severe_excess: list[float] = []

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
            "v24": StagedWithdrawalMembrane(),
            "v28": RateFirstRecoveryMembrane(),
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
        v28 = current["v28"]
        controller = controllers["v28"]
        assert isinstance(controller, RateFirstRecoveryMembrane)

        relief_vs_r2.append(safe_ratio(v28.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v28.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v28.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v28.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(
            safe_ratio(v28.seconds_per_completion(), r2.seconds_per_completion())
        )

        rate_relaxed_count.append(controller.rate_relaxed_count)
        rate_relaxed_success.append(controller.rate_relaxed_success)
        rate_relaxed_failure.append(controller.rate_relaxed_failure)
        relief_withdrawal_count.append(controller.relief_withdrawal_count)
        relief_withdrawal_success.append(controller.relief_withdrawal_success)
        relief_withdrawal_failure.append(controller.relief_withdrawal_failure)
        post_success_reentries.append(controller.post_success_reentries)
        protective_transitions.append(controller.protective_transitions)

        # Continuous comparator is executed through the frozen v0.26 runner for
        # both policies on the same seed/calibration. This diagnostic does not
        # replace the R3 promotion judge above.
        v24_cont = run_continuous_policy(
            epochs,
            controller=StagedWithdrawalMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v28_cont = run_continuous_policy(
            epochs,
            controller=RateFirstRecoveryMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v24_missed_work.append(v24_cont.missed_work_fraction())
        v28_missed_work.append(v28_cont.missed_work_fraction())
        v24_severe_excess.append(v24_cont.severe_excess_fraction())
        v28_severe_excess.append(v28_cont.severe_excess_fraction())

        row = rows_by_name["v28"][-1]
        print(
            f"seed={seed} "
            f"v28_completed_ratio={row['completed']:.3f} "
            f"v28_lost_ratio={row['lost']:.3f} "
            f"v28_seconds_ratio={row['seconds']:.3f} "
            f"v28_miss_ratio={row['miss']:.3f} "
            f"v28_severe_ratio={row['severe']:.3f} "
            f"v28_relief={v28.relief_occupancy():.3f} "
            f"v28_storage={v28.storage_occupancy():.3f} "
            f"rate_relaxed={controller.rate_relaxed_success}/{controller.rate_relaxed_count} "
            f"relief_withdrawal={controller.relief_withdrawal_success}/{controller.relief_withdrawal_count} "
            f"post_success_reentries={controller.post_success_reentries} "
            f"v24_cont_missed={v24_cont.missed_work_fraction():.6f} "
            f"v28_cont_missed={v28_cont.missed_work_fraction():.6f}"
        )

    rows = rows_by_name["v28"]
    stats_rows = stats_by_name["v28"]
    v24_stats = stats_by_name["v24"]
    mismatches = sum(row.digest_mismatches for row in stats_rows)

    v24_storage_median = median(row.storage_occupancy() for row in v24_stats)
    v28_storage_median = median(row.storage_occupancy() for row in stats_rows)
    v24_missed_median = median(v24_missed_work)
    v28_missed_median = median(v28_missed_work)

    passes = (
        median(row["completed"] for row in rows) >= MIN_COMPLETED_BASELINE
        and median(row["lost"] for row in rows) <= MAX_LOST_BASELINE
        and median(row["seconds"] for row in rows) <= MAX_SECONDS_BASELINE
        and median(row["miss"] for row in rows) <= MAX_MISS_BASELINE
        and median(row["severe"] for row in rows) <= MAX_SEVERE_BASELINE
        and median(row.terminal_backlog for row in stats_rows) == 0
        and mismatches == 0
        and median(row.relief_occupancy() for row in stats_rows) <= MAX_OCCUPANCY
        and v28_storage_median <= MAX_OCCUPANCY
        and median(relief_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(storage_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(completed_vs_r2) >= MIN_COMPLETED_VS_R2
        and median(miss_vs_r2) <= MAX_MISS_VS_R2
        and median(seconds_vs_r2) <= MAX_SECONDS_VS_R2
        and v28_missed_median <= v24_missed_median
        and v28_storage_median <= v24_storage_median
    )

    print("\n[overall]")
    print(
        f"v28_median_completed_ratio={median(row['completed'] for row in rows):.3f} "
        f"v28_median_lost_ratio={median(row['lost'] for row in rows):.3f} "
        f"v28_median_seconds_ratio={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"v28_median_miss_ratio={median(row['miss'] for row in rows):.3f} "
        f"v28_median_severe_ratio={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"v28_median_relief={median(row.relief_occupancy() for row in stats_rows):.3f} "
        f"v28_median_storage={v28_storage_median:.3f} "
        f"median_relief_vs_r2={median(relief_vs_r2):.3f} "
        f"median_storage_vs_r2={median(storage_vs_r2):.3f}"
    )
    print(
        f"median_completed_vs_r2={median(completed_vs_r2):.3f} "
        f"median_miss_vs_r2={median(miss_vs_r2):.3f} "
        f"median_seconds_vs_r2={median(seconds_vs_r2):.3f}"
    )
    print(
        f"v24_median_missed_work_fraction={v24_missed_median:.6f} "
        f"v28_median_missed_work_fraction={v28_missed_median:.6f} "
        f"v24_median_severe_excess_fraction={median(v24_severe_excess):.6f} "
        f"v28_median_severe_excess_fraction={median(v28_severe_excess):.6f}"
    )
    print(
        f"v24_median_storage={v24_storage_median:.3f} "
        f"v28_not_worse_missed_work={str(v28_missed_median <= v24_missed_median).lower()} "
        f"v28_not_worse_storage={str(v28_storage_median <= v24_storage_median).lower()}"
    )
    print(
        f"median_rate_relaxed_count={median(rate_relaxed_count):.1f} "
        f"median_rate_relaxed_success={median(rate_relaxed_success):.1f} "
        f"median_rate_relaxed_failure={median(rate_relaxed_failure):.1f}"
    )
    print(
        f"median_relief_withdrawal_count={median(relief_withdrawal_count):.1f} "
        f"median_relief_withdrawal_success={median(relief_withdrawal_success):.1f} "
        f"median_relief_withdrawal_failure={median(relief_withdrawal_failure):.1f}"
    )
    print(
        f"median_post_success_reentries={median(post_success_reentries):.1f} "
        f"median_protective_transitions={median(protective_transitions):.1f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.28 tests whether withdrawing RATE limiting before "
        "RELIEF under phase-blind frozen recovery evidence converts the v0.27 "
        "phase-local causal finding into a selective adaptive policy."
    )

    raise SystemExit(0 if passes else 2)


if __name__ == "__main__":
    main()
