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
from real_work_queue_outcome_audit_r3 import (
    OutcomeStats,
    SEVERE_MISS_THRESHOLD,
    run_outcome_policy,
    safe_ratio,
)
from real_work_queue_transfer import BASE_BUFFER, build_epochs, calibrate_rounds
from recovery_challenge_v023 import RecoveryChallengeMembrane
from resolution_strength_v022 import ResolutionStrengthMembrane
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

# Fresh held-out family frozen in BardoCompute issue #5 before implementation.
SEEDS = (
    12_100_359,
    12_200_367,
    12_300_373,
    12_400_379,
    12_500_383,
    12_600_389,
)

# Promotion bar inherited unchanged from v0.22/v0.23.
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


class MatchedLoadRecoveryMembrane(InteroceptiveMembrane):
    """Two-stage recovery challenge isolating support from rate restoration.

    NORMAL -> PROTECTED uses frozen v0.19 entry semantics.
    PROTECTED accumulates frozen v0.22 resolution evidence.
    SUPPORT_CHALLENGE removes RELIEF while retaining the exact protective rate
    cap.  Only after that succeeds does RATE_CHALLENGE restore ordinary release.
    """

    NORMAL = "normal"
    PROTECTED = "protected"
    SUPPORT_CHALLENGE = "support_challenge"
    RATE_CHALLENGE = "rate_challenge"

    def __init__(self) -> None:
        super().__init__()
        self.mode = self.NORMAL
        self.resolution_strength = 0

        self.support_attempts = 0
        self.support_passes = 0
        self.support_failures = 0
        self.support_severe_misses = 0

        self.rate_attempts = 0
        self.rate_passes = 0
        self.rate_failures = 0
        self.rate_severe_misses = 0

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.24 forbids voluntary admission shedding")

        if self.mode == self.NORMAL and self._should_enter():
            self.mode = self.PROTECTED
            self.protective = True
            self.protective_transitions += 1
            self.resolution_strength = 0
            self.recovery = 0
        elif self.mode == self.PROTECTED and self.resolution_strength >= RECOVERY_DWELL:
            self.mode = self.SUPPORT_CHALLENGE
            self.protective = False
            self.protective_transitions += 1
            self.support_attempts += 1

        if self.mode == self.PROTECTED:
            self.current_boost = BOOST_AMOUNT
            release = min(base.release_limit, BOOSTED_SAFE_CAP)
            self.protective_epochs += 1
        elif self.mode == self.SUPPORT_CHALLENGE:
            # Matched-load withdrawal: remove only RELIEF; retain the same rate
            # cap used in PROTECTED so support dependence is isolated.
            self.current_boost = 0.0
            release = min(base.release_limit, BOOSTED_SAFE_CAP)
        elif self.mode == self.RATE_CHALLENGE:
            # Support has already been removed successfully; now change only RATE.
            self.current_boost = 0.0
            release = base.release_limit
        else:
            self.current_boost = 0.0
            release = base.release_limit

        storage_active = self.mode == self.PROTECTED or self.buffered > BASE_BUFFER
        buffer_limit = ELASTIC_BUFFER_LIMIT if storage_active else BASE_BUFFER
        self.storage_epochs += int(storage_active)

        return MembraneCommand(
            admission_limit=None,
            release_limit=release,
            buffer_limit=buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )

    def observe(self, result) -> None:
        super().observe(result)

        miss_fraction = max(0, result.released - result.delivered) / max(1, result.released)
        severe_miss = result.released > 0 and miss_fraction >= SEVERE_MISS_THRESHOLD
        healthy_evidence = self.pain < HEALTHY_PAIN and not severe_miss

        if self.mode == self.SUPPORT_CHALLENGE:
            if severe_miss:
                self.support_severe_misses += 1
            if healthy_evidence:
                self.support_passes += 1
                self.mode = self.RATE_CHALLENGE
                self.rate_attempts += 1
            else:
                self.support_failures += 1
                self.mode = self.PROTECTED
                self.protective = True
                self.protective_transitions += 1
                self.resolution_strength = 0
            self.recovery = 0
            return

        if self.mode == self.RATE_CHALLENGE:
            if severe_miss:
                self.rate_severe_misses += 1
            if healthy_evidence:
                self.rate_passes += 1
                self.mode = self.NORMAL
                self.protective = False
            else:
                self.rate_failures += 1
                self.mode = self.PROTECTED
                self.protective = True
                self.protective_transitions += 1
            self.resolution_strength = 0
            self.recovery = 0
            return

        if self.mode == self.PROTECTED:
            if healthy_evidence:
                self.resolution_strength = min(
                    RECOVERY_DWELL, self.resolution_strength + 1
                )
            elif severe_miss:
                self.resolution_strength = max(0, self.resolution_strength - 1)
            # Intermediate non-severe evidence holds accumulated credit exactly
            # as frozen in the v0.22 Resolution Strength semantics.
            self.recovery = self.resolution_strength
        else:
            self.resolution_strength = 0
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

    print("benchmark=matched_load_recovery_v0.24")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("state_machine=NORMAL->PROTECTED->SUPPORT_CHALLENGE->RATE_CHALLENGE->NORMAL")
    print("entry_semantics=unchanged_v0.19")
    print("resolution_evidence=unchanged_v0.22")
    print("support_challenge=RELIEF_off+protective_rate_cap")
    print("rate_challenge=RELIEF_off+ordinary_full_release")
    print("new_actuators=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    names = ("r2", "v22", "v23", "v24")
    all_rows: dict[str, list[dict[str, float]]] = {name: [] for name in names}
    all_stats: dict[str, list[OutcomeStats]] = {name: [] for name in names}

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []
    miss_vs_v23: list[float] = []
    relief_vs_v23: list[float] = []

    support_attempts: list[int] = []
    support_passes: list[int] = []
    support_failures: list[int] = []
    support_severe: list[int] = []
    rate_attempts: list[int] = []
    rate_passes: list[int] = []
    rate_failures: list[int] = []
    rate_severe: list[int] = []
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
        r2 = run_outcome_policy(
            epochs,
            controller=ElasticStorageMembrane(),
            sensor_mode="r2",
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v22 = run_outcome_policy(
            epochs,
            controller=ResolutionStrengthMembrane(),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        v23 = run_outcome_policy(
            epochs,
            controller=RecoveryChallengeMembrane(),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        controller = MatchedLoadRecoveryMembrane()
        v24 = run_outcome_policy(
            epochs,
            controller=controller,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        for name, stat in (("r2", r2), ("v22", v22), ("v23", v23), ("v24", v24)):
            all_rows[name].append(ratios(stat, baseline))
            all_stats[name].append(stat)

        relief_vs_r2.append(safe_ratio(v24.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v24.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v24.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v24.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(
            safe_ratio(v24.seconds_per_completion(), r2.seconds_per_completion())
        )
        miss_vs_v23.append(safe_ratio(v24.deadline_miss_epochs, v23.deadline_miss_epochs))
        relief_vs_v23.append(safe_ratio(v24.relief_occupancy(), v23.relief_occupancy()))

        support_attempts.append(controller.support_attempts)
        support_passes.append(controller.support_passes)
        support_failures.append(controller.support_failures)
        support_severe.append(controller.support_severe_misses)
        rate_attempts.append(controller.rate_attempts)
        rate_passes.append(controller.rate_passes)
        rate_failures.append(controller.rate_failures)
        rate_severe.append(controller.rate_severe_misses)
        protective_transitions.append(controller.protective_transitions)

        row = all_rows["v24"][-1]
        print(
            f"seed={seed} "
            f"v24_completed_ratio={row['completed']:.3f} "
            f"v24_lost_ratio={row['lost']:.3f} "
            f"v24_seconds_ratio={row['seconds']:.3f} "
            f"v24_miss_ratio={row['miss']:.3f} "
            f"v24_severe_ratio={row['severe']:.3f} "
            f"v24_relief={v24.relief_occupancy():.3f} "
            f"v24_storage={v24.storage_occupancy():.3f} "
            f"support={controller.support_passes}/{controller.support_attempts} "
            f"rate={controller.rate_passes}/{controller.rate_attempts} "
            f"terminal_backlog={v24.terminal_backlog}"
        )

    for name in names:
        summarize(name, all_rows[name], all_stats[name])

    rows = all_rows["v24"]
    stats_rows = all_stats["v24"]
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

    support_attempt_total = sum(support_attempts)
    rate_attempt_total = sum(rate_attempts)
    support_pass_rate = sum(support_passes) / max(1, support_attempt_total)
    rate_pass_rate = sum(rate_passes) / max(1, rate_attempt_total)

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
        f"support_attempts_total={support_attempt_total} "
        f"support_passes_total={sum(support_passes)} "
        f"support_failures_total={sum(support_failures)} "
        f"support_severe_misses_total={sum(support_severe)} "
        f"support_pass_rate={support_pass_rate:.3f}"
    )
    print(
        f"rate_attempts_total={rate_attempt_total} "
        f"rate_passes_total={sum(rate_passes)} "
        f"rate_failures_total={sum(rate_failures)} "
        f"rate_severe_misses_total={sum(rate_severe)} "
        f"rate_pass_rate={rate_pass_rate:.3f}"
    )
    print(
        f"median_protective_transitions={median(protective_transitions):.1f} "
        f"support_withdrawal_tolerated={str(support_pass_rate > 0.0).lower()} "
        f"rate_restoration_tolerated={str(rate_attempt_total > 0 and rate_pass_rate > 0.0).lower()}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.24 decomposes support withdrawal from rate restoration "
        "under matched load using only pre-existing actuator states and the "
        "independent R3 outcome vector."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
