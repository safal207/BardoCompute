from __future__ import annotations

from statistics import median

from bardocompute.exchange import ExchangeResult, MembraneCommand
from bidirectional_homeostasis import BOOST_AMOUNT, BOOSTED_SAFE_CAP
from computational_interoception_v019 import (
    HEALTHY_PAIN,
    InteroceptiveMembrane,
    RECOVERY_DWELL,
)
from continuous_miss_burden_v026 import run_continuous_policy
from exchange_conservation import FlowPreservingMembrane
from rate_first_recovery_v028 import RateFirstRecoveryMembrane, ratios
from real_work_queue_outcome_audit_r3 import (
    OutcomeStats,
    SEVERE_MISS_THRESHOLD,
    run_outcome_policy,
    safe_ratio,
)
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

# Fresh held-out family frozen in issue #29 before implementation/results.
SEEDS = (
    20_100_727,
    20_200_733,
    20_300_739,
    20_400_743,
    20_500_751,
    20_600_759,
    20_700_763,
    20_800_771,
)

# Historical pre-v0.36 increment from FeedbackMembrane.
RATE_STEP = 8

# Frozen v0.37 preservation bounds versus binary v0.28.
MIN_COMPLETED_VS_V28 = 0.98
MAX_SECONDS_VS_V28 = 1.05


class IncrementalRateWeaningMembrane(InteroceptiveMembrane):
    """Withdraw RATE protection in historical +8 increments before RELIEF.

    Entry, support magnitudes, recovery dwell, and v0.22 resolution evidence
    remain frozen. Controllers receive no workload phase labels.
    """

    PROTECTED = 0
    RATE_WEANING = 1
    RELIEF_WITHDRAWAL = 2

    def __init__(self) -> None:
        super().__init__()
        self.resolution_strength = 0
        self.withdrawal_stage = self.PROTECTED
        self.weaning_limit = BOOSTED_SAFE_CAP
        self.step_resolution = 0

        self.weaning_entries = 0
        self.step_attempts = 0
        self.step_advances = 0
        self.step_holds = 0
        self.step_rollbacks = 0
        self.full_rate_reaches = 0

        self.relief_withdrawal_count = 0
        self.relief_withdrawal_success = 0
        self.relief_withdrawal_failure = 0
        self.successful_exits = 0
        self.post_success_reentries = 0
        self._successful_exit_pending_reentry = False

        self.weaning_limits: list[int] = []
        self.weaning_episode_lengths: list[int] = []
        self._current_weaning_epochs = 0
        self._last_base_release_limit = BOOSTED_SAFE_CAP
        self._last_effective_release_limit = BOOSTED_SAFE_CAP

    def _normal_after_exit(self, base: MembraneCommand) -> MembraneCommand:
        storage_active = self.buffered > BASE_BUFFER
        return MembraneCommand(
            admission_limit=None,
            release_limit=base.release_limit,
            buffer_limit=ELASTIC_BUFFER_LIMIT if storage_active else BASE_BUFFER,
            secondary_fraction=base.secondary_fraction,
        )

    def _start_weaning(self, base_release_limit: int) -> None:
        self.withdrawal_stage = self.RATE_WEANING
        self.weaning_entries += 1
        self.step_attempts += 1
        self.weaning_limit = min(
            base_release_limit,
            BOOSTED_SAFE_CAP + RATE_STEP,
        )
        self.step_resolution = 0
        self.resolution_strength = 0
        self._current_weaning_epochs = 0
        self.weaning_limits.append(self.weaning_limit)

    def _rollback_weaning(self) -> None:
        self.step_rollbacks += 1
        if self._current_weaning_epochs:
            self.weaning_episode_lengths.append(self._current_weaning_epochs)
        self.withdrawal_stage = self.PROTECTED
        self.weaning_limit = BOOSTED_SAFE_CAP
        self.step_resolution = 0
        self.resolution_strength = 0
        self._current_weaning_epochs = 0
        self.recovery = 0

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.37 forbids voluntary admission shedding")

        if not self.protective and self._should_enter():
            self.protective = True
            self.protective_transitions += 1
            self.resolution_strength = 0
            self.withdrawal_stage = self.PROTECTED
            self.weaning_limit = BOOSTED_SAFE_CAP
            self.step_resolution = 0
            if self._successful_exit_pending_reentry:
                self.post_success_reentries += 1
                self._successful_exit_pending_reentry = False

        if (
            self.protective
            and self.withdrawal_stage == self.PROTECTED
            and self.resolution_strength >= RECOVERY_DWELL
        ):
            self._start_weaning(base.release_limit)

        if self.withdrawal_stage == self.RATE_WEANING:
            self.current_boost = BOOST_AMOUNT
            self.protective_epochs += 1
            self.storage_epochs += 1
            self._current_weaning_epochs += 1
            release_limit = min(base.release_limit, self.weaning_limit)
            self._last_base_release_limit = base.release_limit
            self._last_effective_release_limit = release_limit
            return MembraneCommand(
                admission_limit=None,
                release_limit=release_limit,
                buffer_limit=ELASTIC_BUFFER_LIMIT,
                secondary_fraction=base.secondary_fraction,
            )

        if self.withdrawal_stage == self.RELIEF_WITHDRAWAL:
            self.current_boost = 0.0
            storage_active = self.buffered > BASE_BUFFER
            self.storage_epochs += int(storage_active)
            self._last_base_release_limit = base.release_limit
            self._last_effective_release_limit = base.release_limit
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
            release_limit = min(base.release_limit, BOOSTED_SAFE_CAP)
            self._last_base_release_limit = base.release_limit
            self._last_effective_release_limit = release_limit
            return MembraneCommand(
                admission_limit=None,
                release_limit=release_limit,
                buffer_limit=ELASTIC_BUFFER_LIMIT,
                secondary_fraction=base.secondary_fraction,
            )

        self.current_boost = 0.0
        self._last_base_release_limit = base.release_limit
        self._last_effective_release_limit = base.release_limit
        return self._normal_after_exit(base)

    def observe(self, result: ExchangeResult) -> None:
        super().observe(result)

        miss_fraction = max(0, result.released - result.delivered) / max(
            1, result.released
        )
        severe_miss = (
            result.released > 0 and miss_fraction >= SEVERE_MISS_THRESHOLD
        )
        healthy = self.pain < HEALTHY_PAIN and not severe_miss

        if self.withdrawal_stage == self.RATE_WEANING:
            if severe_miss:
                self._rollback_weaning()
                return

            if healthy:
                self.step_resolution = min(
                    RECOVERY_DWELL,
                    self.step_resolution + 1,
                )
            else:
                self.step_holds += 1

            if self.step_resolution < RECOVERY_DWELL:
                if healthy:
                    self.step_holds += 1
            else:
                if (
                    self._last_base_release_limit
                    <= self._last_effective_release_limit
                ):
                    self.full_rate_reaches += 1
                    self.weaning_episode_lengths.append(
                        self._current_weaning_epochs
                    )
                    self.withdrawal_stage = self.RELIEF_WITHDRAWAL
                    self.relief_withdrawal_count += 1
                    self.step_resolution = 0
                    self._current_weaning_epochs = 0
                else:
                    next_limit = min(
                        self._last_base_release_limit,
                        self.weaning_limit + RATE_STEP,
                    )
                    if next_limit <= self.weaning_limit:
                        self.full_rate_reaches += 1
                        self.weaning_episode_lengths.append(
                            self._current_weaning_epochs
                        )
                        self.withdrawal_stage = self.RELIEF_WITHDRAWAL
                        self.relief_withdrawal_count += 1
                        self._current_weaning_epochs = 0
                    else:
                        self.weaning_limit = next_limit
                        self.weaning_limits.append(self.weaning_limit)
                        self.step_advances += 1
                        self.step_attempts += 1
                    self.step_resolution = 0

            self.resolution_strength = 0
            self.recovery = 0
            return

        if self.withdrawal_stage == self.RELIEF_WITHDRAWAL:
            self.resolution_strength = 0
            if healthy:
                self.relief_withdrawal_success += 1
                self.successful_exits += 1
                self.withdrawal_stage = self.PROTECTED
                self.protective = False
                self.protective_transitions += 1
                self._successful_exit_pending_reentry = True
            else:
                self.relief_withdrawal_failure += 1
                self.withdrawal_stage = self.PROTECTED
            self.weaning_limit = BOOSTED_SAFE_CAP
            self.step_resolution = 0
            self.recovery = 0
            return

        if self.protective:
            # Exact v0.22 accumulator semantics:
            # healthy -> +1; severe -> -1; intermediate non-severe -> hold.
            if healthy:
                self.resolution_strength = min(
                    RECOVERY_DWELL,
                    self.resolution_strength + 1,
                )
            elif severe_miss:
                self.resolution_strength = max(
                    0,
                    self.resolution_strength - 1,
                )
        else:
            self.resolution_strength = 0

        # v0.37 owns the recovery state machine; disable the inherited exit path.
        self.recovery = 0


def median_ratio(
    candidates: list[OutcomeStats],
    references: list[OutcomeStats],
    value,
) -> float:
    return float(
        median(
            safe_ratio(value(candidate), value(reference))
            for candidate, reference in zip(candidates, references, strict=True)
        )
    )


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=incremental_rate_weaning_v0.37")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print(f"RATE_STEP={RATE_STEP}")
    print("step_source=historical_FeedbackMembrane_plus_8")
    print("dose_selected_from_v036=false")
    print("recovery_evidence=exact_v022_resolution_strength")
    print("step_dwell=RECOVERY_DWELL")
    print("withdrawal_order=incremental_RATE_then_RELIEF")
    print("controllers_phase_blind=true")
    print("new_actuator_magnitudes=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    stats_by_name: dict[str, list[OutcomeStats]] = {
        "baseline": [],
        "r2": [],
        "v28": [],
        "v37": [],
    }
    rows_v28: list[dict[str, float]] = []
    rows_v37: list[dict[str, float]] = []
    v28_continuous = []
    v37_continuous = []
    controllers_v37: list[IncrementalRateWeaningMembrane] = []

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
        v28 = run_outcome_policy(
            epochs,
            controller=RateFirstRecoveryMembrane(),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        controller = IncrementalRateWeaningMembrane()
        v37 = run_outcome_policy(
            epochs,
            controller=controller,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        stats_by_name["baseline"].append(baseline)
        stats_by_name["r2"].append(r2)
        stats_by_name["v28"].append(v28)
        stats_by_name["v37"].append(v37)
        rows_v28.append(ratios(v28, baseline))
        rows_v37.append(ratios(v37, baseline))
        controllers_v37.append(controller)

        v28_cont = run_continuous_policy(
            epochs,
            controller=RateFirstRecoveryMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v37_cont = run_continuous_policy(
            epochs,
            controller=IncrementalRateWeaningMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v28_continuous.append(v28_cont)
        v37_continuous.append(v37_cont)

        print(
            f"seed={seed} "
            f"v28_completed={v28.completed} v37_completed={v37.completed} "
            f"v28_miss={v28.deadline_miss_epochs} "
            f"v37_miss={v37.deadline_miss_epochs} "
            f"v28_severe={v28.severe_miss_epochs} "
            f"v37_severe={v37.severe_miss_epochs} "
            f"v28_cont_missed={v28_cont.missed_work_fraction():.6f} "
            f"v37_cont_missed={v37_cont.missed_work_fraction():.6f} "
            f"v37_relief={v37.relief_occupancy():.3f} "
            f"v37_storage={v37.storage_occupancy():.3f} "
            f"weaning_entries={controller.weaning_entries} "
            f"step_advances={controller.step_advances} "
            f"step_rollbacks={controller.step_rollbacks} "
            f"successful_exits={controller.successful_exits}"
        )

    r2_stats = stats_by_name["r2"]
    v28_stats = stats_by_name["v28"]
    v37_stats = stats_by_name["v37"]

    completed_vs_v28 = median_ratio(
        v37_stats, v28_stats, lambda row: row.completed
    )
    lost_vs_v28 = median_ratio(v37_stats, v28_stats, lambda row: row.lost)
    seconds_vs_v28 = median_ratio(
        v37_stats, v28_stats, lambda row: row.seconds_per_completion()
    )
    miss_vs_v28 = median_ratio(
        v37_stats, v28_stats, lambda row: row.deadline_miss_epochs
    )
    severe_vs_v28 = median_ratio(
        v37_stats, v28_stats, lambda row: row.severe_miss_epochs
    )
    relief_vs_v28 = median_ratio(
        v37_stats, v28_stats, lambda row: row.relief_occupancy()
    )
    storage_vs_v28 = median_ratio(
        v37_stats, v28_stats, lambda row: row.storage_occupancy()
    )
    continuous_missed_vs_v28 = float(
        median(
            safe_ratio(
                candidate.missed_work_fraction(),
                reference.missed_work_fraction(),
            )
            for candidate, reference in zip(
                v37_continuous,
                v28_continuous,
                strict=True,
            )
        )
    )
    continuous_severe_vs_v28 = float(
        median(
            safe_ratio(
                candidate.severe_excess_fraction(),
                reference.severe_excess_fraction(),
            )
            for candidate, reference in zip(
                v37_continuous,
                v28_continuous,
                strict=True,
            )
        )
    )

    digest_mismatches = sum(row.digest_mismatches for row in v37_stats)
    terminal_backlog = float(median(row.terminal_backlog for row in v37_stats))

    local_dominates = (
        completed_vs_v28 >= MIN_COMPLETED_VS_V28
        and seconds_vs_v28 <= MAX_SECONDS_VS_V28
        and miss_vs_v28 < 1.0
        and severe_vs_v28 <= 1.0
        and continuous_missed_vs_v28 < 1.0
        and terminal_backlog == 0
        and digest_mismatches == 0
    )
    risk_improves = (
        miss_vs_v28 < 1.0
        and severe_vs_v28 <= 1.0
        and continuous_missed_vs_v28 < 1.0
    )
    service_preserved = (
        completed_vs_v28 >= MIN_COMPLETED_VS_V28
        and seconds_vs_v28 <= MAX_SECONDS_VS_V28
    )
    if local_dominates:
        local_classification = "incremental_dominates_binary"
    elif risk_improves and not service_preserved:
        local_classification = "risk_reduction_with_service_cost"
    elif (
        miss_vs_v28 > 1.0
        and severe_vs_v28 >= 1.0
        and continuous_missed_vs_v28 > 1.0
        and completed_vs_v28 <= 1.0
    ):
        local_classification = "incremental_worse"
    else:
        local_classification = "no_material_advantage"

    limits = [
        value
        for controller in controllers_v37
        for value in controller.weaning_limits
    ]
    episode_lengths = [
        value
        for controller in controllers_v37
        for value in controller.weaning_episode_lengths
    ]

    print("\n[overall]")
    print(
        f"v28_median_completed_ratio="
        f"{median(row['completed'] for row in rows_v28):.3f} "
        f"v37_median_completed_ratio="
        f"{median(row['completed'] for row in rows_v37):.3f}"
    )
    print(
        f"v28_median_miss_ratio="
        f"{median(row['miss'] for row in rows_v28):.3f} "
        f"v37_median_miss_ratio="
        f"{median(row['miss'] for row in rows_v37):.3f} "
        f"v28_median_severe_ratio="
        f"{median(row['severe'] for row in rows_v28):.3f} "
        f"v37_median_severe_ratio="
        f"{median(row['severe'] for row in rows_v37):.3f}"
    )
    print(
        f"v28_median_relief="
        f"{median(row.relief_occupancy() for row in v28_stats):.3f} "
        f"v37_median_relief="
        f"{median(row.relief_occupancy() for row in v37_stats):.3f} "
        f"v28_median_storage="
        f"{median(row.storage_occupancy() for row in v28_stats):.3f} "
        f"v37_median_storage="
        f"{median(row.storage_occupancy() for row in v37_stats):.3f}"
    )
    print(
        f"v28_median_continuous_missed="
        f"{median(row.missed_work_fraction() for row in v28_continuous):.6f} "
        f"v37_median_continuous_missed="
        f"{median(row.missed_work_fraction() for row in v37_continuous):.6f} "
        f"v28_median_continuous_severe_excess="
        f"{median(row.severe_excess_fraction() for row in v28_continuous):.6f} "
        f"v37_median_continuous_severe_excess="
        f"{median(row.severe_excess_fraction() for row in v37_continuous):.6f}"
    )
    print(
        f"completed_vs_v28={completed_vs_v28:.6f} "
        f"lost_vs_v28={lost_vs_v28:.6f} "
        f"seconds_vs_v28={seconds_vs_v28:.6f} "
        f"miss_vs_v28={miss_vs_v28:.6f} "
        f"severe_vs_v28={severe_vs_v28:.6f}"
    )
    print(
        f"continuous_missed_vs_v28={continuous_missed_vs_v28:.6f} "
        f"continuous_severe_vs_v28={continuous_severe_vs_v28:.6f} "
        f"relief_vs_v28={relief_vs_v28:.6f} "
        f"storage_vs_v28={storage_vs_v28:.6f}"
    )
    print(
        f"v37_completed_vs_r2="
        f"{median_ratio(v37_stats, r2_stats, lambda row: row.completed):.6f} "
        f"v37_miss_vs_r2="
        f"{median_ratio(v37_stats, r2_stats, lambda row: row.deadline_miss_epochs):.6f} "
        f"v37_seconds_vs_r2="
        f"{median_ratio(v37_stats, r2_stats, lambda row: row.seconds_per_completion()):.6f}"
    )
    print(
        f"median_weaning_entries="
        f"{median(controller.weaning_entries for controller in controllers_v37):.1f} "
        f"median_step_attempts="
        f"{median(controller.step_attempts for controller in controllers_v37):.1f} "
        f"median_step_advances="
        f"{median(controller.step_advances for controller in controllers_v37):.1f} "
        f"median_step_holds="
        f"{median(controller.step_holds for controller in controllers_v37):.1f} "
        f"median_step_rollbacks="
        f"{median(controller.step_rollbacks for controller in controllers_v37):.1f}"
    )
    print(
        f"median_full_rate_reaches="
        f"{median(controller.full_rate_reaches for controller in controllers_v37):.1f} "
        f"median_relief_withdrawal_count="
        f"{median(controller.relief_withdrawal_count for controller in controllers_v37):.1f} "
        f"median_relief_withdrawal_success="
        f"{median(controller.relief_withdrawal_success for controller in controllers_v37):.1f} "
        f"median_relief_withdrawal_failure="
        f"{median(controller.relief_withdrawal_failure for controller in controllers_v37):.1f}"
    )
    print(
        f"median_successful_exits="
        f"{median(controller.successful_exits for controller in controllers_v37):.1f} "
        f"median_post_success_reentries="
        f"{median(controller.post_success_reentries for controller in controllers_v37):.1f} "
        f"median_protective_transitions="
        f"{median(controller.protective_transitions for controller in controllers_v37):.1f}"
    )
    print(
        f"median_weaning_limit={median(limits) if limits else float('nan'):.1f} "
        f"max_weaning_limit={max(limits) if limits else 0} "
        f"median_weaning_episode_epochs="
        f"{median(episode_lengths) if episode_lengths else float('nan'):.1f}"
    )
    print(f"median_terminal_backlog={terminal_backlog:.1f}")
    print(f"digest_mismatches={digest_mismatches}")
    print(f"local_classification={local_classification}")
    print(f"local_incremental_dominates_binary={str(local_dominates).lower()}")
    print("passes_preregistered_acceptance=requires_cross_runtime_interpretation")
    print(
        "interpretation=v0.37 tests whether phase-blind incremental RATE "
        "weaning with the historical +8 step reduces deadline risk relative "
        "to binary full withdrawal while preserving service."
    )


if __name__ == "__main__":
    main()
