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
from recovery_decoupling_v020 import RecoveryDecoupledMembrane
from resolution_strength_v022 import ResolutionStrengthMembrane
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

# Fresh held-out family frozen before implementation in BardoCompute issue #7.
SEEDS = (
    11_100_331,
    11_200_337,
    11_300_347,
    11_400_349,
    11_500_353,
    11_600_359,
)


class WithdrawalReadinessMembrane(InteroceptiveMembrane):
    """Two-stage recovery: supported evidence, then one unsupported challenge.

    Entry semantics and actuator magnitudes remain those of v0.19.  Once two
    units of supported recovery evidence are accumulated, the controller runs
    exactly one epoch in the already-existing normal-exchange configuration.
    The challenge result determines whether protection is actually removed.
    """

    def __init__(self) -> None:
        super().__init__()
        self.resolution_strength = 0
        self.in_withdrawal_challenge = False
        self.withdrawal_challenges = 0
        self.withdrawal_successes = 0
        self.withdrawal_failures = 0
        self.post_success_reentries = 0
        self._successful_exit_pending_reentry = False

    def _normal_command(self, base: MembraneCommand) -> MembraneCommand:
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
            raise AssertionError("v0.23 forbids voluntary admission shedding")

        if not self.protective and self._should_enter():
            self.protective = True
            self.protective_transitions += 1
            self.resolution_strength = 0
            if self._successful_exit_pending_reentry:
                self.post_success_reentries += 1
                self._successful_exit_pending_reentry = False

        if self.protective and not self.in_withdrawal_challenge:
            if self.resolution_strength >= RECOVERY_DWELL:
                self.in_withdrawal_challenge = True
                self.withdrawal_challenges += 1

        if self.in_withdrawal_challenge:
            # Exact unsupported configuration the controller intends to enter:
            # no RELIEF, base release rate/route, elastic storage only if retained
            # backlog still exceeds baseline capacity.
            self.current_boost = 0.0
            return self._normal_command(base)

        if self.protective:
            self.current_boost = BOOST_AMOUNT
            release = min(base.release_limit, BOOSTED_SAFE_CAP)
            self.protective_epochs += 1
            buffer_limit = ELASTIC_BUFFER_LIMIT
            self.storage_epochs += 1
            return MembraneCommand(
                admission_limit=None,
                release_limit=release,
                buffer_limit=buffer_limit,
                secondary_fraction=base.secondary_fraction,
            )

        self.current_boost = 0.0
        return self._normal_command(base)

    def observe(self, result) -> None:
        # Parent updates LOAD/PAIN/RESERVE/TRAJECTORY using completed epoch data.
        # Its recovery scalar is ignored below; v0.23 owns the exit state machine.
        super().observe(result)

        miss_fraction = max(0, result.released - result.delivered) / max(1, result.released)
        severe_miss = result.released > 0 and miss_fraction >= SEVERE_MISS_THRESHOLD
        healthy = self.pain < HEALTHY_PAIN and not severe_miss

        if self.in_withdrawal_challenge:
            self.in_withdrawal_challenge = False
            self.resolution_strength = 0
            if healthy:
                self.withdrawal_successes += 1
                self.protective = False
                self.protective_transitions += 1
                self._successful_exit_pending_reentry = True
            else:
                self.withdrawal_failures += 1
                # Protection stays active; support resumes next epoch.
            self.recovery = 0
            return

        if self.protective:
            if healthy:
                self.resolution_strength = min(
                    RECOVERY_DWELL, self.resolution_strength + 1
                )
            elif severe_miss:
                self.resolution_strength = max(0, self.resolution_strength - 1)
            # Intermediate non-severe noise preserves earned evidence.
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

    print("benchmark=withdrawal_readiness_v0.23")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("prior_lesson=supported_health_not_equal_support_independent_recovery")
    print("entry_semantics=unchanged_v0.19")
    print("supported_evidence_budget=2")
    print("withdrawal_challenge_epochs=1")
    print("challenge_RELIEF=0")
    print("challenge_RATE=base_release_limit")
    print("challenge_ROUTE=base_secondary_fraction")
    print("new_actuators=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    names = ("r2", "v19", "v20", "v22", "v23")
    rows_by_name: dict[str, list[dict[str, float]]] = {name: [] for name in names}
    stats_by_name: dict[str, list[OutcomeStats]] = {name: [] for name in names}

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []
    miss_vs_v22: list[float] = []
    relief_vs_v22: list[float] = []

    challenge_counts: list[int] = []
    challenge_successes: list[int] = []
    challenge_failures: list[int] = []
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
            "v20": RecoveryDecoupledMembrane(),
            "v22": ResolutionStrengthMembrane(),
            "v23": WithdrawalReadinessMembrane(),
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
        v22 = current["v22"]
        v23 = current["v23"]
        controller = controllers["v23"]
        assert isinstance(controller, WithdrawalReadinessMembrane)

        relief_vs_r2.append(safe_ratio(v23.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v23.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v23.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v23.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(
            safe_ratio(v23.seconds_per_completion(), r2.seconds_per_completion())
        )
        miss_vs_v22.append(
            safe_ratio(v23.deadline_miss_epochs, v22.deadline_miss_epochs)
        )
        relief_vs_v22.append(
            safe_ratio(v23.relief_occupancy(), v22.relief_occupancy())
        )

        challenge_counts.append(controller.withdrawal_challenges)
        challenge_successes.append(controller.withdrawal_successes)
        challenge_failures.append(controller.withdrawal_failures)
        post_success_reentries.append(controller.post_success_reentries)
        protective_transitions.append(controller.protective_transitions)

        row = rows_by_name["v23"][-1]
        print(
            f"seed={seed} "
            f"v23_completed_ratio={row['completed']:.3f} "
            f"v23_lost_ratio={row['lost']:.3f} "
            f"v23_seconds_ratio={row['seconds']:.3f} "
            f"v23_miss_ratio={row['miss']:.3f} "
            f"v23_severe_ratio={row['severe']:.3f} "
            f"v23_relief={v23.relief_occupancy():.3f} "
            f"v23_storage={v23.storage_occupancy():.3f} "
            f"challenges={controller.withdrawal_challenges} "
            f"challenge_successes={controller.withdrawal_successes} "
            f"challenge_failures={controller.withdrawal_failures} "
            f"post_success_reentries={controller.post_success_reentries}"
        )

    for name in names:
        summarize(name, rows_by_name[name], stats_by_name[name])

    rows = rows_by_name["v23"]
    stats_rows = stats_by_name["v23"]
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
        f"v23_median_completed_ratio={median(row['completed'] for row in rows):.3f} "
        f"v23_median_lost_ratio={median(row['lost'] for row in rows):.3f} "
        f"v23_median_seconds_ratio={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"v23_median_miss_ratio={median(row['miss'] for row in rows):.3f} "
        f"v23_median_severe_ratio={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"v23_median_relief={median(row.relief_occupancy() for row in stats_rows):.3f} "
        f"v23_median_storage={median(row.storage_occupancy() for row in stats_rows):.3f} "
        f"median_relief_vs_r2={median(relief_vs_r2):.3f} "
        f"median_storage_vs_r2={median(storage_vs_r2):.3f}"
    )
    print(
        f"median_completed_vs_r2={median(completed_vs_r2):.3f} "
        f"median_miss_vs_r2={median(miss_vs_r2):.3f} "
        f"median_seconds_vs_r2={median(seconds_vs_r2):.3f}"
    )
    print(
        f"median_v23_miss_vs_v22={median(miss_vs_v22):.3f} "
        f"median_v23_relief_vs_v22={median(relief_vs_v22):.3f}"
    )
    print(
        f"median_withdrawal_challenges={median(challenge_counts):.1f} "
        f"median_challenge_successes={median(challenge_successes):.1f} "
        f"median_challenge_failures={median(challenge_failures):.1f} "
        f"median_post_success_reentries={median(post_success_reentries):.1f} "
        f"median_protective_transitions={median(protective_transitions):.1f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.23 tests whether an explicit one-epoch unsupported "
        "challenge can separate support-dependent apparent recovery from readiness "
        "to remain viable after support withdrawal."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
