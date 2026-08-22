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
from exchange_conservation import FlowPreservingMembrane
from real_work_queue_outcome_audit_r3 import (
    OutcomeStats,
    SEVERE_MISS_THRESHOLD,
    run_outcome_policy,
    safe_ratio,
)
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from resolution_strength_v022 import ResolutionStrengthMembrane
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane
from withdrawal_readiness_v023 import WithdrawalReadinessMembrane

SEEDS = (
    12_100_367,
    12_200_373,
    12_300_379,
    12_400_383,
    12_500_389,
    12_600_397,
)


class StagedWithdrawalMembrane(InteroceptiveMembrane):
    """Withdraw existing support components one at a time.

    Stage 1 removes RELIEF while retaining the existing safe RATE cap.
    Stage 2 restores the base RATE while RELIEF stays off.  Only a healthy
    Stage-2 epoch exits protection.  No new actuator magnitude is introduced.
    """

    PROTECTED = 0
    RELIEF_CHALLENGE = 1
    RATE_CHALLENGE = 2

    def __init__(self) -> None:
        super().__init__()
        self.resolution_strength = 0
        self.withdrawal_stage = self.PROTECTED
        self.stage1_count = 0
        self.stage1_success = 0
        self.stage1_failure = 0
        self.stage2_count = 0
        self.stage2_success = 0
        self.stage2_failure = 0
        self.post_success_reentries = 0
        self._successful_exit_pending_reentry = False

    def _normal_after_exit(self, base: MembraneCommand) -> MembraneCommand:
        storage_active = self.buffered > BASE_BUFFER
        buffer_limit = ELASTIC_BUFFER_LIMIT if storage_active else BASE_BUFFER
        return MembraneCommand(
            admission_limit=None,
            release_limit=base.release_limit,
            buffer_limit=buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.24 forbids voluntary admission shedding")

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
            self.withdrawal_stage = self.RELIEF_CHALLENGE
            self.stage1_count += 1

        if self.withdrawal_stage == self.RELIEF_CHALLENGE:
            self.current_boost = 0.0
            return MembraneCommand(
                admission_limit=None,
                release_limit=min(base.release_limit, BOOSTED_SAFE_CAP),
                buffer_limit=ELASTIC_BUFFER_LIMIT,
                secondary_fraction=base.secondary_fraction,
            )

        if self.withdrawal_stage == self.RATE_CHALLENGE:
            self.current_boost = 0.0
            return MembraneCommand(
                admission_limit=None,
                release_limit=base.release_limit,
                buffer_limit=ELASTIC_BUFFER_LIMIT,
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

        if self.withdrawal_stage == self.RELIEF_CHALLENGE:
            self.resolution_strength = 0
            if healthy:
                self.stage1_success += 1
                self.withdrawal_stage = self.RATE_CHALLENGE
                self.stage2_count += 1
            else:
                self.stage1_failure += 1
                self.withdrawal_stage = self.PROTECTED
            self.recovery = 0
            return

        if self.withdrawal_stage == self.RATE_CHALLENGE:
            self.resolution_strength = 0
            if healthy:
                self.stage2_success += 1
                self.withdrawal_stage = self.PROTECTED
                self.protective = False
                self.protective_transitions += 1
                self._successful_exit_pending_reentry = True
            else:
                self.stage2_failure += 1
                self.withdrawal_stage = self.PROTECTED
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

        self.recovery = 0


def ratios(candidate: OutcomeStats, baseline: OutcomeStats) -> dict[str, float]:
    return {
        "completed": safe_ratio(candidate.completed, baseline.completed),
        "lost": safe_ratio(candidate.lost, baseline.lost),
        "seconds": safe_ratio(candidate.seconds_per_completion(), baseline.seconds_per_completion()),
        "miss": safe_ratio(candidate.deadline_miss_epochs, baseline.deadline_miss_epochs),
        "severe": safe_ratio(candidate.severe_miss_epochs, baseline.severe_miss_epochs),
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
        f"median_storage_occupancy={median(row.storage_occupancy() for row in stats):.3f}"
    )


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=staged_withdrawal_v0.24")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("entry_semantics=unchanged_v0.19")
    print("stage1=RELIEF_off+RATE_cap_retained")
    print("stage2=RELIEF_off+base_RATE")
    print("new_actuator_magnitudes=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    names = ("r2", "v19", "v22", "v23", "v24")
    rows_by_name: dict[str, list[dict[str, float]]] = {name: [] for name in names}
    stats_by_name: dict[str, list[OutcomeStats]] = {name: [] for name in names}

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []
    miss_vs_v23: list[float] = []
    relief_vs_v23: list[float] = []

    stage1_count: list[int] = []
    stage1_success: list[int] = []
    stage1_failure: list[int] = []
    stage2_count: list[int] = []
    stage2_success: list[int] = []
    stage2_failure: list[int] = []
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
            "v23": WithdrawalReadinessMembrane(),
            "v24": StagedWithdrawalMembrane(),
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
        v23 = current["v23"]
        v24 = current["v24"]
        controller = controllers["v24"]
        assert isinstance(controller, StagedWithdrawalMembrane)

        relief_vs_r2.append(safe_ratio(v24.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v24.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v24.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v24.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(
            safe_ratio(v24.seconds_per_completion(), r2.seconds_per_completion())
        )
        miss_vs_v23.append(
            safe_ratio(v24.deadline_miss_epochs, v23.deadline_miss_epochs)
        )
        relief_vs_v23.append(
            safe_ratio(v24.relief_occupancy(), v23.relief_occupancy())
        )

        stage1_count.append(controller.stage1_count)
        stage1_success.append(controller.stage1_success)
        stage1_failure.append(controller.stage1_failure)
        stage2_count.append(controller.stage2_count)
        stage2_success.append(controller.stage2_success)
        stage2_failure.append(controller.stage2_failure)
        post_success_reentries.append(controller.post_success_reentries)
        protective_transitions.append(controller.protective_transitions)

        row = rows_by_name["v24"][-1]
        print(
            f"seed={seed} "
            f"v24_completed_ratio={row['completed']:.3f} "
            f"v24_lost_ratio={row['lost']:.3f} "
            f"v24_seconds_ratio={row['seconds']:.3f} "
            f"v24_miss_ratio={row['miss']:.3f} "
            f"v24_severe_ratio={row['severe']:.3f} "
            f"v24_relief={v24.relief_occupancy():.3f} "
            f"v24_storage={v24.storage_occupancy():.3f} "
            f"stage1={controller.stage1_success}/{controller.stage1_count} "
            f"stage2={controller.stage2_success}/{controller.stage2_count} "
            f"post_success_reentries={controller.post_success_reentries}"
        )

    for name in names:
        summarize(name, rows_by_name[name], stats_by_name[name])

    rows = rows_by_name["v24"]
    stats_rows = stats_by_name["v24"]
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
        f"v24_median_completed_ratio={median(row['completed'] for row in rows):.3f} "
        f"v24_median_lost_ratio={median(row['lost'] for row in rows):.3f} "
        f"v24_median_seconds_ratio={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"v24_median_miss_ratio={median(row['miss'] for row in rows):.3f} "
        f"v24_median_severe_ratio={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"v24_median_relief={median(row.relief_occupancy() for row in stats_rows):.3f} "
        f"v24_median_storage={median(row.storage_occupancy() for row in stats_rows):.3f} "
        f"median_relief_vs_r2={median(relief_vs_r2):.3f} "
        f"median_storage_vs_r2={median(storage_vs_r2):.3f}"
    )
    print(
        f"median_completed_vs_r2={median(completed_vs_r2):.3f} "
        f"median_miss_vs_r2={median(miss_vs_r2):.3f} "
        f"median_seconds_vs_r2={median(seconds_vs_r2):.3f}"
    )
    print(
        f"median_v24_miss_vs_v23={median(miss_vs_v23):.3f} "
        f"median_v24_relief_vs_v23={median(relief_vs_v23):.3f}"
    )
    print(
        f"median_stage1_count={median(stage1_count):.1f} "
        f"median_stage1_success={median(stage1_success):.1f} "
        f"median_stage1_failure={median(stage1_failure):.1f} "
        f"median_stage2_count={median(stage2_count):.1f} "
        f"median_stage2_success={median(stage2_success):.1f} "
        f"median_stage2_failure={median(stage2_failure):.1f}"
    )
    print(
        f"median_post_success_reentries={median(post_success_reentries):.1f} "
        f"median_protective_transitions={median(protective_transitions):.1f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.24 tests whether staged removal of existing RELIEF and "
        "RATE support can isolate support dependence without introducing a new "
        "actuator magnitude."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
