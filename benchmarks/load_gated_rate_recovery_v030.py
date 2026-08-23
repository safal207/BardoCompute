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
from rate_first_recovery_v028 import RateFirstRecoveryMembrane, ratios
from real_work_queue_outcome_audit_r3 import run_outcome_policy, safe_ratio
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

SEEDS = (
    17_100_587,
    17_200_593,
    17_300_599,
    17_400_601,
    17_500_607,
    17_600_613,
    17_700_617,
    17_800_619,
)


class LoadGatedRateRecoveryMembrane(RateFirstRecoveryMembrane):
    """v0.28 with one already-frozen readiness veto: LOAD < 0.50."""

    def __init__(self) -> None:
        super().__init__()
        self.readiness_veto_epochs = 0

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

        if (
            self.protective
            and self.withdrawal_stage == self.PROTECTED
            and self.resolution_strength >= RECOVERY_DWELL
        ):
            if self.load < MIN_ACTIVE_LOAD:
                self.withdrawal_stage = self.RATE_RELAXED
                self.rate_relaxed_count += 1
            else:
                self.readiness_veto_epochs += 1

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


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=load_gated_rate_recovery_v0.30")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print(f"load_readiness_threshold={MIN_ACTIVE_LOAD:.2f}")
    print("threshold_source=frozen_v0.19_MIN_ACTIVE_LOAD")
    print("entry_semantics=unchanged_v0.19")
    print("resolution_evidence=unchanged_v0.22")
    print("withdrawal_order=unchanged_v0.28_RATE_first_then_RELIEF")
    print("controllers_phase_blind=true")
    print("new_actuator_magnitudes=false")
    print("admission_shedding=false")

    names = ("r2", "v28", "v30")
    rows_by_name = {name: [] for name in names}
    stats_by_name = {name: [] for name in names}

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []

    veto_epochs: list[int] = []
    v28_rate_failures: list[int] = []
    v30_rate_failures: list[int] = []
    v30_rate_attempts: list[int] = []
    v30_rate_successes: list[int] = []
    v30_relief_attempts: list[int] = []
    v30_relief_successes: list[int] = []
    post_success_reentries: list[int] = []

    v28_missed_work: list[float] = []
    v30_missed_work: list[float] = []

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
            "v30": LoadGatedRateRecoveryMembrane(),
        }
        current = {}
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
        v28_controller = controllers["v28"]
        v30_controller = controllers["v30"]
        assert isinstance(v28_controller, RateFirstRecoveryMembrane)
        assert isinstance(v30_controller, LoadGatedRateRecoveryMembrane)

        relief_vs_r2.append(safe_ratio(v30.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v30.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v30.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v30.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(safe_ratio(v30.seconds_per_completion(), r2.seconds_per_completion()))

        veto_epochs.append(v30_controller.readiness_veto_epochs)
        v28_rate_failures.append(v28_controller.rate_relaxed_failure)
        v30_rate_failures.append(v30_controller.rate_relaxed_failure)
        v30_rate_attempts.append(v30_controller.rate_relaxed_count)
        v30_rate_successes.append(v30_controller.rate_relaxed_success)
        v30_relief_attempts.append(v30_controller.relief_withdrawal_count)
        v30_relief_successes.append(v30_controller.relief_withdrawal_success)
        post_success_reentries.append(v30_controller.post_success_reentries)

        v28_cont = run_continuous_policy(
            epochs,
            controller=RateFirstRecoveryMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v30_cont = run_continuous_policy(
            epochs,
            controller=LoadGatedRateRecoveryMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v28_missed_work.append(v28_cont.missed_work_fraction())
        v30_missed_work.append(v30_cont.missed_work_fraction())

        row = rows_by_name["v30"][-1]
        print(
            f"seed={seed} completed={row['completed']:.3f} lost={row['lost']:.3f} "
            f"seconds={row['seconds']:.3f} miss={row['miss']:.3f} severe={row['severe']:.3f} "
            f"relief={v30.relief_occupancy():.3f} storage={v30.storage_occupancy():.3f} "
            f"veto={v30_controller.readiness_veto_epochs} "
            f"rate={v30_controller.rate_relaxed_success}/{v30_controller.rate_relaxed_count} "
            f"rate_fail={v30_controller.rate_relaxed_failure} "
            f"v28_rate_fail={v28_controller.rate_relaxed_failure}"
        )

    rows = rows_by_name["v30"]
    stats_rows = stats_by_name["v30"]
    v28_stats = stats_by_name["v28"]
    mismatches = sum(stat.digest_mismatches for stat in stats_rows)

    v30_storage = median(stat.storage_occupancy() for stat in stats_rows)
    v28_storage = median(stat.storage_occupancy() for stat in v28_stats)
    v30_missed = median(v30_missed_work)
    v28_missed = median(v28_missed_work)

    passes = (
        median(row["completed"] for row in rows) >= MIN_COMPLETED_BASELINE
        and median(row["lost"] for row in rows) <= MAX_LOST_BASELINE
        and median(row["seconds"] for row in rows) <= MAX_SECONDS_BASELINE
        and median(row["miss"] for row in rows) <= MAX_MISS_BASELINE
        and median(row["severe"] for row in rows) <= MAX_SEVERE_BASELINE
        and median(stat.terminal_backlog for stat in stats_rows) == 0
        and mismatches == 0
        and median(stat.relief_occupancy() for stat in stats_rows) <= MAX_OCCUPANCY
        and v30_storage <= MAX_OCCUPANCY
        and median(relief_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(storage_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(completed_vs_r2) >= MIN_COMPLETED_VS_R2
        and median(miss_vs_r2) <= 1.25
        and median(seconds_vs_r2) <= MAX_SECONDS_VS_R2
        and v30_missed <= v28_missed
        and median(v30_rate_failures) < median(v28_rate_failures)
        and v30_storage <= v28_storage
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
        f"v30_median_relief={median(stat.relief_occupancy() for stat in stats_rows):.3f} "
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
        f"v28_median_missed_work_fraction={v28_missed:.6f} "
        f"v30_median_missed_work_fraction={v30_missed:.6f} "
        f"v30_not_worse_missed_work={str(v30_missed <= v28_missed).lower()}"
    )
    print(
        f"v28_median_storage={v28_storage:.3f} "
        f"v30_not_worse_storage={str(v30_storage <= v28_storage).lower()}"
    )
    print(
        f"median_readiness_veto_epochs={median(veto_epochs):.1f} "
        f"median_v28_rate_failures={median(v28_rate_failures):.1f} "
        f"median_v30_rate_failures={median(v30_rate_failures):.1f}"
    )
    print(
        f"median_rate_attempts={median(v30_rate_attempts):.1f} "
        f"median_rate_successes={median(v30_rate_successes):.1f} "
        f"median_relief_attempts={median(v30_relief_attempts):.1f} "
        f"median_relief_successes={median(v30_relief_successes):.1f} "
        f"median_post_success_reentries={median(post_success_reentries):.1f}"
    )
    print(f"median_terminal_backlog={median(stat.terminal_backlog for stat in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.30 tests whether the already-frozen v0.19 active-load "
        "threshold can veto premature v0.28 RATE withdrawal without phase labels."
    )

    if not passes:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
