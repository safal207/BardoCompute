from __future__ import annotations

from statistics import median

from bardocompute.exchange import MembraneCommand
from bidirectional_homeostasis import BOOST_AMOUNT, BOOSTED_SAFE_CAP
from computational_interoception_v019 import (
    MAX_LOST_BASELINE,
    MAX_MISS_BASELINE,
    MAX_OCCUPANCY,
    MAX_OCCUPANCY_VS_R2,
    MAX_SECONDS_BASELINE,
    MAX_SECONDS_VS_R2,
    MAX_SEVERE_BASELINE,
    MIN_ACTIVE_LOAD,
    MIN_COMPLETED_BASELINE,
    MIN_COMPLETED_VS_R2,
    RECOVERY_DWELL,
)
from continuous_miss_burden_v026 import run_continuous_policy
from exchange_conservation import FlowPreservingMembrane
from rate_first_recovery_v028 import RateFirstRecoveryMembrane
from real_work_queue_outcome_audit_r3 import OutcomeStats, run_outcome_policy, safe_ratio
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

# Fresh held-out family frozen in issue #20 before implementation/results.
SEEDS = (
    17_100_581,
    17_200_587,
    17_300_593,
    17_400_601,
    17_500_607,
    17_600_613,
    17_700_617,
    17_800_623,
)


class LoadGatedRateRelaxationMembrane(RateFirstRecoveryMembrane):
    """v0.28 rate-first recovery plus the frozen v0.19 LOAD readiness gate."""

    def __init__(self) -> None:
        super().__init__()
        self.blocked_readiness_epochs = 0

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.30 forbids voluntary admission shedding")

        if not self.protective and self._should_enter():
            self.protective = True
            self.protective_transitions += 1
            self.resolution_strength = 0
            self.withdrawal_stage = self.PROTECTED
            if self._successful_exit_pending_reentry:
                self.post_success_reentries += 1
                self._successful_exit_pending_reentry = False

        readiness_accumulated = (
            self.protective
            and self.withdrawal_stage == self.PROTECTED
            and self.resolution_strength >= RECOVERY_DWELL
        )
        if readiness_accumulated and self.load >= MIN_ACTIVE_LOAD:
            self.blocked_readiness_epochs += 1
        if readiness_accumulated and self.load < MIN_ACTIVE_LOAD:
            self.withdrawal_stage = self.RATE_RELAXED
            self.rate_relaxed_count += 1

        if self.withdrawal_stage == self.RATE_RELAXED:
            self.current_boost = BOOST_AMOUNT
            return MembraneCommand(
                admission_limit=None,
                release_limit=base.release_limit,
                buffer_limit=ELASTIC_BUFFER_LIMIT,
                secondary_fraction=base.secondary_fraction,
            )

        if self.withdrawal_stage == self.RELIEF_WITHDRAWAL:
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

    print("benchmark=load_gated_rate_relaxation_v0.30")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print(f"load_gate=LOAD<{MIN_ACTIVE_LOAD:.2f}")
    print("load_threshold_source=frozen_v0.19_MIN_ACTIVE_LOAD")
    print("recovery_memory=exact_v0.22")
    print("withdrawal_order=RATE_first_then_RELIEF")
    print("controllers_phase_blind=true")
    print("new_thresholds=false")
    print("new_actuators=false")

    rows_by_name: dict[str, list[dict[str, float]]] = {name: [] for name in ("r2", "v28", "v30")}
    stats_by_name: dict[str, list[OutcomeStats]] = {name: [] for name in rows_by_name}

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []
    blocked_readiness: list[int] = []
    rate_count: list[int] = []
    rate_success: list[int] = []
    rate_failure: list[int] = []
    relief_count: list[int] = []
    relief_success: list[int] = []
    relief_failure: list[int] = []
    reentries: list[int] = []

    v28_missed: list[float] = []
    v30_missed: list[float] = []
    v28_severe: list[float] = []
    v30_severe: list[float] = []

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
            "v28": RateFirstRecoveryMembrane(),
            "v30": LoadGatedRateRelaxationMembrane(),
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
        v30 = current["v30"]
        ctrl = controllers["v30"]
        assert isinstance(ctrl, LoadGatedRateRelaxationMembrane)

        relief_vs_r2.append(safe_ratio(v30.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v30.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v30.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v30.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(safe_ratio(v30.seconds_per_completion(), r2.seconds_per_completion()))
        blocked_readiness.append(ctrl.blocked_readiness_epochs)
        rate_count.append(ctrl.rate_relaxed_count)
        rate_success.append(ctrl.rate_relaxed_success)
        rate_failure.append(ctrl.rate_relaxed_failure)
        relief_count.append(ctrl.relief_withdrawal_count)
        relief_success.append(ctrl.relief_withdrawal_success)
        relief_failure.append(ctrl.relief_withdrawal_failure)
        reentries.append(ctrl.post_success_reentries)

        v28_cont = run_continuous_policy(
            epochs,
            controller=RateFirstRecoveryMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v30_cont = run_continuous_policy(
            epochs,
            controller=LoadGatedRateRelaxationMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v28_missed.append(v28_cont.missed_work_fraction())
        v30_missed.append(v30_cont.missed_work_fraction())
        v28_severe.append(v28_cont.severe_excess_fraction())
        v30_severe.append(v30_cont.severe_excess_fraction())

        row = rows_by_name["v30"][-1]
        print(
            f"seed={seed} completed={row['completed']:.3f} lost={row['lost']:.3f} "
            f"seconds={row['seconds']:.3f} miss={row['miss']:.3f} severe={row['severe']:.3f} "
            f"relief={v30.relief_occupancy():.3f} storage={v30.storage_occupancy():.3f} "
            f"blocked_readiness={ctrl.blocked_readiness_epochs} "
            f"rate={ctrl.rate_relaxed_success}/{ctrl.rate_relaxed_count} "
            f"relief_withdrawal={ctrl.relief_withdrawal_success}/{ctrl.relief_withdrawal_count}"
        )

    rows = rows_by_name["v30"]
    stats = stats_by_name["v30"]
    v28_stats = stats_by_name["v28"]
    mismatches = sum(row.digest_mismatches for row in stats)

    v30_storage = median(row.storage_occupancy() for row in stats)
    v28_storage = median(row.storage_occupancy() for row in v28_stats)
    v30_missed_med = median(v30_missed)
    v28_missed_med = median(v28_missed)
    v30_rate_fail = median(rate_failure)
    v28_rate_fail = median(
        getattr(controller, "rate_relaxed_failure", 0)
        for controller in []
    ) if False else None

    # Re-run only the comparator state-machine counters; outcome data above remain frozen.
    v28_failure_counts: list[int] = []
    for seed in SEEDS:
        epochs = build_epochs(seed)
        ctrl28 = RateFirstRecoveryMembrane()
        run_outcome_policy(
            epochs,
            controller=ctrl28,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v28_failure_counts.append(ctrl28.rate_relaxed_failure)
    v28_rate_fail_med = median(v28_failure_counts)

    passes = (
        median(row["completed"] for row in rows) >= MIN_COMPLETED_BASELINE
        and median(row["lost"] for row in rows) <= MAX_LOST_BASELINE
        and median(row["seconds"] for row in rows) <= MAX_SECONDS_BASELINE
        and median(row["miss"] for row in rows) <= MAX_MISS_BASELINE
        and median(row["severe"] for row in rows) <= MAX_SEVERE_BASELINE
        and median(row.terminal_backlog for row in stats) == 0
        and mismatches == 0
        and median(row.relief_occupancy() for row in stats) <= MAX_OCCUPANCY
        and v30_storage <= MAX_OCCUPANCY
        and median(relief_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(storage_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(completed_vs_r2) >= MIN_COMPLETED_VS_R2
        and median(miss_vs_r2) <= 1.25
        and median(seconds_vs_r2) <= MAX_SECONDS_VS_R2
        and v30_missed_med <= v28_missed_med
        and v30_storage <= v28_storage
        and v30_rate_fail < v28_rate_fail_med
    )

    print("\n[overall]")
    print(
        f"v30_median_completed_ratio={median(row['completed'] for row in rows):.3f} "
        f"v30_median_lost_ratio={median(row['lost'] for row in rows):.3f} "
        f"v30_median_seconds_ratio={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"v30_median_miss_ratio={median(row['miss'] for row in rows):.3f} "
        f"v30_median_severe_ratio={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"v30_median_relief={median(row.relief_occupancy() for row in stats):.3f} "
        f"v30_median_storage={v30_storage:.3f} "
        f"median_relief_vs_r2={median(relief_vs_r2):.3f} "
        f"median_storage_vs_r2={median(storage_vs_r2):.3f}"
    )
    print(
        f"median_completed_vs_r2={median(completed_vs_r2):.3f} "
        f"median_miss_vs_r2={median(miss_vs_r2):.3f} "
        f"median_seconds_vs_r2={median(seconds_vs_r2):.3f}"
    )
    print(
        f"v28_median_missed_work_fraction={v28_missed_med:.6f} "
        f"v30_median_missed_work_fraction={v30_missed_med:.6f} "
        f"v28_median_severe_excess_fraction={median(v28_severe):.6f} "
        f"v30_median_severe_excess_fraction={median(v30_severe):.6f}"
    )
    print(
        f"v28_median_storage={v28_storage:.3f} "
        f"v30_not_worse_missed_work={str(v30_missed_med <= v28_missed_med).lower()} "
        f"v30_not_worse_storage={str(v30_storage <= v28_storage).lower()}"
    )
    print(
        f"median_blocked_readiness_epochs={median(blocked_readiness):.1f} "
        f"median_rate_relaxed_count={median(rate_count):.1f} "
        f"median_rate_relaxed_success={median(rate_success):.1f} "
        f"median_rate_relaxed_failure={v30_rate_fail:.1f} "
        f"v28_median_rate_relaxed_failure={v28_rate_fail_med:.1f}"
    )
    print(
        f"median_relief_withdrawal_count={median(relief_count):.1f} "
        f"median_relief_withdrawal_success={median(relief_success):.1f} "
        f"median_relief_withdrawal_failure={median(relief_failure):.1f} "
        f"median_post_success_reentries={median(reentries):.1f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.30 tests whether the already-existing fixed LOAD threshold "
        "filters premature v0.28 RATE-relaxation attempts without phase labels or retuning."
    )

    raise SystemExit(0 if passes else 1)


if __name__ == "__main__":
    main()
