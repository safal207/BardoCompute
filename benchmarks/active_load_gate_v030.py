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
from real_work_queue_outcome_audit_r3 import OutcomeStats, run_outcome_policy, safe_ratio
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from staged_withdrawal_v024 import StagedWithdrawalMembrane
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

# Fresh held-out family frozen in issue #19 before implementation/results.
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


class ActiveLoadGatedRateFirstMembrane(RateFirstRecoveryMembrane):
    """Exact v0.28 state machine with one pre-existing LOAD gate.

    The only semantic change is that RATE_RELAXED cannot begin while
    load >= the already-frozen v0.19 MIN_ACTIVE_LOAD boundary.
    """

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
            and self.load < MIN_ACTIVE_LOAD
        ):
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

    print("benchmark=active_load_gate_rate_first_recovery_v0.30")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("entry_semantics=unchanged_v0.19")
    print("recovery_evidence=exact_v0.22_bounded_resolution_strength")
    print("withdrawal_order=RATE_first_then_RELIEF")
    print(f"rate_relax_load_gate=load<{MIN_ACTIVE_LOAD:.2f}")
    print("load_threshold_source=preexisting_v0.19_MIN_ACTIVE_LOAD")
    print("controllers_phase_blind=true")
    print("new_thresholds=false")
    print("new_actuator_magnitudes=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    names = ("r2", "v24", "v28", "v30")
    rows_by_name: dict[str, list[dict[str, float]]] = {name: [] for name in names}
    stats_by_name: dict[str, list[OutcomeStats]] = {name: [] for name in names}

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []

    v24_missed_work: list[float] = []
    v28_missed_work: list[float] = []
    v30_missed_work: list[float] = []
    v24_severe_excess: list[float] = []
    v28_severe_excess: list[float] = []
    v30_severe_excess: list[float] = []

    v28_rate_failures: list[int] = []
    v30_rate_failures: list[int] = []
    v28_full_exits: list[int] = []
    v30_full_exits: list[int] = []
    v28_reentries: list[int] = []
    v30_reentries: list[int] = []
    v30_rate_count: list[int] = []
    v30_rate_success: list[int] = []
    v30_relief_count: list[int] = []
    v30_relief_success: list[int] = []
    v30_protective_transitions: list[int] = []

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
            "v30": ActiveLoadGatedRateFirstMembrane(),
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
        c28 = controllers["v28"]
        c30 = controllers["v30"]
        assert isinstance(c28, RateFirstRecoveryMembrane)
        assert isinstance(c30, ActiveLoadGatedRateFirstMembrane)

        relief_vs_r2.append(safe_ratio(v30.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v30.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v30.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v30.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(
            safe_ratio(v30.seconds_per_completion(), r2.seconds_per_completion())
        )

        v28_rate_failures.append(c28.rate_relaxed_failure)
        v30_rate_failures.append(c30.rate_relaxed_failure)
        v28_full_exits.append(c28.relief_withdrawal_success)
        v30_full_exits.append(c30.relief_withdrawal_success)
        v28_reentries.append(c28.post_success_reentries)
        v30_reentries.append(c30.post_success_reentries)
        v30_rate_count.append(c30.rate_relaxed_count)
        v30_rate_success.append(c30.rate_relaxed_success)
        v30_relief_count.append(c30.relief_withdrawal_count)
        v30_relief_success.append(c30.relief_withdrawal_success)
        v30_protective_transitions.append(c30.protective_transitions)

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
        v30_cont = run_continuous_policy(
            epochs,
            controller=ActiveLoadGatedRateFirstMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v24_missed_work.append(v24_cont.missed_work_fraction())
        v28_missed_work.append(v28_cont.missed_work_fraction())
        v30_missed_work.append(v30_cont.missed_work_fraction())
        v24_severe_excess.append(v24_cont.severe_excess_fraction())
        v28_severe_excess.append(v28_cont.severe_excess_fraction())
        v30_severe_excess.append(v30_cont.severe_excess_fraction())

        row = rows_by_name["v30"][-1]
        print(
            f"seed={seed} "
            f"v30_completed_ratio={row['completed']:.3f} "
            f"v30_lost_ratio={row['lost']:.3f} "
            f"v30_seconds_ratio={row['seconds']:.3f} "
            f"v30_miss_ratio={row['miss']:.3f} "
            f"v30_severe_ratio={row['severe']:.3f} "
            f"v30_relief={v30.relief_occupancy():.3f} "
            f"v30_storage={v30.storage_occupancy():.3f} "
            f"v28_rate_fail={c28.rate_relaxed_failure} "
            f"v30_rate_fail={c30.rate_relaxed_failure} "
            f"v30_full_exits={c30.relief_withdrawal_success} "
            f"v30_reentries={c30.post_success_reentries}"
        )

    for name in names:
        summarize(name, rows_by_name[name], stats_by_name[name])

    rows = rows_by_name["v30"]
    stats_rows = stats_by_name["v30"]
    v24_stats = stats_by_name["v24"]
    mismatches = sum(row.digest_mismatches for row in stats_rows)

    v24_storage_median = median(row.storage_occupancy() for row in v24_stats)
    v30_storage_median = median(row.storage_occupancy() for row in stats_rows)
    v24_missed_median = median(v24_missed_work)
    v28_missed_median = median(v28_missed_work)
    v30_missed_median = median(v30_missed_work)

    mechanistic_ok = (
        median(v30_rate_failures) < median(v28_rate_failures)
        and median(v30_full_exits) >= median(v28_full_exits)
        and median(v30_reentries) <= median(v28_reentries)
    )

    passes = (
        median(row["completed"] for row in rows) >= MIN_COMPLETED_BASELINE
        and median(row["lost"] for row in rows) <= MAX_LOST_BASELINE
        and median(row["seconds"] for row in rows) <= MAX_SECONDS_BASELINE
        and median(row["miss"] for row in rows) <= MAX_MISS_BASELINE
        and median(row["severe"] for row in rows) <= MAX_SEVERE_BASELINE
        and median(row.terminal_backlog for row in stats_rows) == 0
        and mismatches == 0
        and median(row.relief_occupancy() for row in stats_rows) <= MAX_OCCUPANCY
        and v30_storage_median <= MAX_OCCUPANCY
        and median(relief_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(storage_vs_r2) <= MAX_OCCUPANCY_VS_R2
        and median(completed_vs_r2) >= MIN_COMPLETED_VS_R2
        and median(miss_vs_r2) <= 1.25
        and median(seconds_vs_r2) <= MAX_SECONDS_VS_R2
        and v30_missed_median <= v24_missed_median
        and v30_storage_median <= v24_storage_median
        and mechanistic_ok
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
        f"v30_median_relief={median(row.relief_occupancy() for row in stats_rows):.3f} "
        f"v30_median_storage={v30_storage_median:.3f} "
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
        f"v30_median_missed_work_fraction={v30_missed_median:.6f}"
    )
    print(
        f"v24_median_severe_excess_fraction={median(v24_severe_excess):.6f} "
        f"v28_median_severe_excess_fraction={median(v28_severe_excess):.6f} "
        f"v30_median_severe_excess_fraction={median(v30_severe_excess):.6f}"
    )
    print(
        f"v24_median_storage={v24_storage_median:.3f} "
        f"v30_not_worse_missed_work={str(v30_missed_median <= v24_missed_median).lower()} "
        f"v30_not_worse_storage={str(v30_storage_median <= v24_storage_median).lower()}"
    )
    print(
        f"median_v28_rate_failures={median(v28_rate_failures):.1f} "
        f"median_v30_rate_count={median(v30_rate_count):.1f} "
        f"median_v30_rate_success={median(v30_rate_success):.1f} "
        f"median_v30_rate_failures={median(v30_rate_failures):.1f}"
    )
    print(
        f"median_v28_full_exits={median(v28_full_exits):.1f} "
        f"median_v30_relief_count={median(v30_relief_count):.1f} "
        f"median_v30_full_exits={median(v30_full_exits):.1f}"
    )
    print(
        f"median_v28_reentries={median(v28_reentries):.1f} "
        f"median_v30_reentries={median(v30_reentries):.1f} "
        f"median_v30_protective_transitions={median(v30_protective_transitions):.1f}"
    )
    print(f"mechanistic_nonworsening={str(mechanistic_ok).lower()}")
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.30 tests whether the pre-existing v0.19 active-load "
        "boundary prevents premature v0.28 RATE relaxation without adding a "
        "new tuned threshold or phase label."
    )

    raise SystemExit(0 if passes else 2)


if __name__ == "__main__":
    main()
