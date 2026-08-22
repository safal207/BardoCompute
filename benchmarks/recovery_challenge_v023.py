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
from recovery_decoupling_v020 import RecoveryDecoupledMembrane
from resolution_strength_v022 import ResolutionStrengthMembrane
from storage_reserve import ELASTIC_BUFFER_LIMIT, ElasticStorageMembrane

# Fresh held-out family frozen in BardoCompute issue #4 before implementation.
SEEDS = (
    11_100_331,
    11_200_337,
    11_300_341,
    11_400_347,
    11_500_349,
    11_600_353,
)

# Frozen promotion bar inherited unchanged from v0.22.
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


class RecoveryChallengeMembrane(InteroceptiveMembrane):
    """Three-state recovery controller with a one-epoch unsupported challenge.

    NORMAL -> PROTECTED uses the exact v0.19 entry predicate.
    PROTECTED accumulates the exact frozen v0.22 resolution evidence.
    Once evidence reaches RECOVERY_DWELL, one CHALLENGE epoch runs with RELIEF
    off and ordinary unprotected release.  Only a healthy challenge commits to
    NORMAL; a failed challenge returns directly to PROTECTED.
    """

    NORMAL = "normal"
    PROTECTED = "protected"
    CHALLENGE = "challenge"

    def __init__(self) -> None:
        super().__init__()
        self.mode = self.NORMAL
        self.resolution_strength = 0
        self.challenge_attempts = 0
        self.challenge_passes = 0
        self.challenge_failures = 0
        self.challenge_severe_misses = 0

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.23 forbids voluntary admission shedding")

        if self.mode == self.NORMAL and self._should_enter():
            self.mode = self.PROTECTED
            self.protective = True
            self.protective_transitions += 1
            self.resolution_strength = 0
            self.recovery = 0
        elif self.mode == self.PROTECTED and self.resolution_strength >= RECOVERY_DWELL:
            self.mode = self.CHALLENGE
            self.protective = False
            self.protective_transitions += 1
            self.challenge_attempts += 1

        if self.mode == self.PROTECTED:
            self.current_boost = BOOST_AMOUNT
            release = min(base.release_limit, BOOSTED_SAFE_CAP)
            self.protective_epochs += 1
        else:
            # CHALLENGE deliberately uses the existing unprotected actuator state.
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

        if self.mode == self.CHALLENGE:
            if severe_miss:
                self.challenge_severe_misses += 1
            if healthy_evidence:
                self.challenge_passes += 1
                self.mode = self.NORMAL
                self.protective = False
            else:
                self.challenge_failures += 1
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
            # Intermediate non-severe evidence preserves accumulated credit,
            # exactly as frozen in v0.22.
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

    print("benchmark=recovery_challenge_v0.23")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("state_machine=NORMAL->PROTECTED->CHALLENGE->NORMAL/PROTECTED")
    print("entry_semantics=unchanged_v0.19")
    print("resolution_evidence=unchanged_v0.22")
    print("challenge_epochs=1")
    print("challenge_RELIEF=off")
    print("new_actuators=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    names = ("r2", "v20", "v22", "v23")
    all_rows: dict[str, list[dict[str, float]]] = {name: [] for name in names}
    all_stats: dict[str, list[OutcomeStats]] = {name: [] for name in names}

    relief_vs_r2: list[float] = []
    storage_vs_r2: list[float] = []
    completed_vs_r2: list[float] = []
    miss_vs_r2: list[float] = []
    seconds_vs_r2: list[float] = []
    miss_vs_v22: list[float] = []
    relief_vs_v22: list[float] = []
    challenge_attempts: list[int] = []
    challenge_passes: list[int] = []
    challenge_failures: list[int] = []
    challenge_severe: list[int] = []
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
        v20 = run_outcome_policy(
            epochs,
            controller=RecoveryDecoupledMembrane(),
            sensor_mode=None,
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
        controller = RecoveryChallengeMembrane()
        v23 = run_outcome_policy(
            epochs,
            controller=controller,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        for name, stat in (("r2", r2), ("v20", v20), ("v22", v22), ("v23", v23)):
            all_rows[name].append(ratios(stat, baseline))
            all_stats[name].append(stat)

        relief_vs_r2.append(safe_ratio(v23.relief_occupancy(), r2.relief_occupancy()))
        storage_vs_r2.append(safe_ratio(v23.storage_occupancy(), r2.storage_occupancy()))
        completed_vs_r2.append(safe_ratio(v23.completed, r2.completed))
        miss_vs_r2.append(safe_ratio(v23.deadline_miss_epochs, r2.deadline_miss_epochs))
        seconds_vs_r2.append(
            safe_ratio(v23.seconds_per_completion(), r2.seconds_per_completion())
        )
        miss_vs_v22.append(safe_ratio(v23.deadline_miss_epochs, v22.deadline_miss_epochs))
        relief_vs_v22.append(safe_ratio(v23.relief_occupancy(), v22.relief_occupancy()))
        challenge_attempts.append(controller.challenge_attempts)
        challenge_passes.append(controller.challenge_passes)
        challenge_failures.append(controller.challenge_failures)
        challenge_severe.append(controller.challenge_severe_misses)
        protective_transitions.append(controller.protective_transitions)

        row = all_rows["v23"][-1]
        print(
            f"seed={seed} "
            f"v23_completed_ratio={row['completed']:.3f} "
            f"v23_lost_ratio={row['lost']:.3f} "
            f"v23_seconds_ratio={row['seconds']:.3f} "
            f"v23_miss_ratio={row['miss']:.3f} "
            f"v23_severe_ratio={row['severe']:.3f} "
            f"v23_relief={v23.relief_occupancy():.3f} "
            f"v23_storage={v23.storage_occupancy():.3f} "
            f"miss_vs_v22={miss_vs_v22[-1]:.3f} "
            f"challenge_attempts={controller.challenge_attempts} "
            f"passes={controller.challenge_passes} "
            f"failures={controller.challenge_failures} "
            f"terminal_backlog={v23.terminal_backlog}"
        )

    for name in names:
        summarize(name, all_rows[name], all_stats[name])

    rows = all_rows["v23"]
    stats_rows = all_stats["v23"]
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
        f"median_challenge_attempts={median(challenge_attempts):.1f} "
        f"median_challenge_passes={median(challenge_passes):.1f} "
        f"median_challenge_failures={median(challenge_failures):.1f} "
        f"median_challenge_severe_misses={median(challenge_severe):.1f} "
        f"median_protective_transitions={median(protective_transitions):.1f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats_rows):.1f}")
    print(f"digest_mismatches={mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=v0.23 tests whether an explicit one-epoch unsupported "
        "challenge distinguishes support-dependent apparent recovery from "
        "support-independent recovery without weakening the external gate."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
