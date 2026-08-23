from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from bardocompute.exchange import ExchangeResult
from rate_first_recovery_v028 import RateFirstRecoveryMembrane
from real_work_queue_outcome_audit_r3 import SEVERE_MISS_THRESHOLD
from real_work_queue_transfer import (
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)

# Spent v0.28 seeds. Diagnostic-only: never use for promotion/tuning.
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

ACTIVE_STRESS = {"burst", "primary_degraded", "global_congested"}
RECOVERY = {"recovery", "drain"}


@dataclass(slots=True)
class Attempt:
    kind: str
    seed: int
    epoch_index: int
    phase: str
    success: bool
    pain: float
    load: float
    reserve: float
    trajectory: float
    buffered: int
    resolution_strength: int
    previous_miss_fraction: float
    previous_backlog: int
    challenge_miss_fraction: float
    challenge_severe_miss: bool
    challenge_backlog_delta: int
    challenge_on_time: int
    challenge_released: int


@dataclass(slots=True)
class SeedRun:
    rate_attempts: list[Attempt]
    relief_attempts: list[Attempt]
    terminal_backlog: int
    digest_mismatches: int


def _pre_snapshot(controller: RateFirstRecoveryMembrane) -> dict[str, float | int]:
    return {
        "pain": controller.pain,
        "load": controller.load,
        "reserve": controller.reserve,
        "trajectory": controller.trajectory,
        "buffered": controller.buffered,
        "resolution_strength": controller.resolution_strength,
    }


def run_seed(seed: int, *, rounds: int, deadline_seconds: float) -> SeedRun:
    controller = RateFirstRecoveryMembrane()
    epochs = build_epochs(seed)
    rate_attempts: list[Attempt] = []
    relief_attempts: list[Attempt] = []
    backlog = 0
    previous_miss_fraction = 0.0
    previous_backlog = 0
    digest_mismatches = 0

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()

        queue = list(epochs)
        queue.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

        for epoch_index, spec in enumerate(queue):
            if spec.phase == "drain" and backlog == 0:
                break

            stage_before_command = controller.withdrawal_stage
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.29 diagnostic forbids voluntary admission shedding")

            rate_challenge = (
                controller.withdrawal_stage == controller.RATE_RELAXED
                and stage_before_command != controller.RATE_RELAXED
            )
            relief_challenge = controller.withdrawal_stage == controller.RELIEF_WITHDRAWAL

            rate_pre = _pre_snapshot(controller) if rate_challenge else None
            relief_pre = _pre_snapshot(controller) if relief_challenge else None
            backlog_before_epoch = backlog

            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            backlog += admitted

            released = min(backlog, command.release_limit)
            backlog -= released

            relief_active = bool(getattr(controller, "current_boost", 0.0) > 0.0)
            relief_count = 0
            if relief_active and released:
                relief_count = min(released, int(round(released * RELIEF_TASK_FRACTION)))
            ordinary = released - relief_count
            secondary_count = min(
                ordinary,
                max(0, int(round(ordinary * command.secondary_fraction))),
            )
            primary_count = ordinary - secondary_count

            _elapsed, p_on, s_on, r_on, mismatches = _execute_batch(
                primary=primary,
                secondary=secondary,
                relief=relief,
                primary_count=primary_count,
                secondary_count=secondary_count,
                relief_count=relief_count,
                rounds=rounds,
                primary_multiplier=spec.primary_multiplier,
                secondary_multiplier=spec.secondary_multiplier,
                deadline_seconds=deadline_seconds,
            )
            digest_mismatches += mismatches

            on_time = p_on + s_on + r_on
            missed = max(0, released - on_time)
            miss_fraction = missed / max(1, released)
            severe = released > 0 and miss_fraction >= SEVERE_MISS_THRESHOLD

            result = ExchangeResult(
                admitted=admitted,
                gate_rejected=0,
                released=released,
                primary_requested=primary_count,
                secondary_requested=secondary_count,
                primary_delivered=p_on,
                secondary_delivered=s_on,
                delivered=on_time,
                congestion=missed,
                buffered=backlog,
                overflow_dropped=overflow,
            )
            controller.observe(result)

            def make_attempt(kind: str, pre: dict[str, float | int], success: bool) -> Attempt:
                return Attempt(
                    kind=kind,
                    seed=seed,
                    epoch_index=epoch_index,
                    phase=spec.phase,
                    success=success,
                    pain=float(pre["pain"]),
                    load=float(pre["load"]),
                    reserve=float(pre["reserve"]),
                    trajectory=float(pre["trajectory"]),
                    buffered=int(pre["buffered"]),
                    resolution_strength=int(pre["resolution_strength"]),
                    previous_miss_fraction=previous_miss_fraction,
                    previous_backlog=previous_backlog,
                    challenge_miss_fraction=miss_fraction,
                    challenge_severe_miss=severe,
                    challenge_backlog_delta=backlog - backlog_before_epoch,
                    challenge_on_time=on_time,
                    challenge_released=released,
                )

            if rate_pre is not None:
                rate_attempts.append(
                    make_attempt(
                        "rate_relaxed",
                        rate_pre,
                        controller.withdrawal_stage == controller.RELIEF_WITHDRAWAL,
                    )
                )

            if relief_pre is not None:
                relief_attempts.append(
                    make_attempt(
                        "relief_withdrawal",
                        relief_pre,
                        not controller.protective,
                    )
                )

            previous_miss_fraction = miss_fraction
            previous_backlog = backlog

    return SeedRun(
        rate_attempts=rate_attempts,
        relief_attempts=relief_attempts,
        terminal_backlog=backlog,
        digest_mismatches=digest_mismatches,
    )


def med(rows: list[Attempt], attr: str) -> float:
    if not rows:
        return float("nan")
    return float(median(getattr(row, attr) for row in rows))


def summarize_group(name: str, rows: list[Attempt]) -> None:
    print(f"[{name}]")
    print(f"count={len(rows)}")
    for attr in (
        "pain",
        "load",
        "reserve",
        "trajectory",
        "buffered",
        "previous_miss_fraction",
        "challenge_miss_fraction",
        "challenge_backlog_delta",
    ):
        print(f"median_{attr}={med(rows, attr):.6f}")


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=recovery_readiness_false_positive_attribution_v0.29")
    print("diagnostic_only=true")
    print("controller=frozen_v0.28")
    print("spent_v028_seeds=true")
    print("policy_promotion_allowed=false")
    print("threshold_tuning_allowed=false")
    print("controllers_phase_blind=true")
    print("external_phase_used_for_attribution_only=true")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    rate_attempts: list[Attempt] = []
    relief_attempts: list[Attempt] = []
    terminal_backlogs: list[int] = []
    digest_mismatches = 0

    for seed in SEEDS:
        run = run_seed(seed, rounds=rounds, deadline_seconds=deadline_seconds)
        rate_attempts.extend(run.rate_attempts)
        relief_attempts.extend(run.relief_attempts)
        terminal_backlogs.append(run.terminal_backlog)
        digest_mismatches += run.digest_mismatches

        for row in run.rate_attempts + run.relief_attempts:
            print(
                f"attempt kind={row.kind} seed={row.seed} epoch={row.epoch_index} phase={row.phase} "
                f"success={str(row.success).lower()} pain={row.pain:.6f} "
                f"load={row.load:.6f} reserve={row.reserve:.6f} "
                f"trajectory={row.trajectory:.6f} buffered={row.buffered} "
                f"resolution={row.resolution_strength} prev_miss={row.previous_miss_fraction:.6f} "
                f"challenge_miss={row.challenge_miss_fraction:.6f} "
                f"challenge_severe={str(row.challenge_severe_miss).lower()} "
                f"backlog_delta={row.challenge_backlog_delta}"
            )

    success = [row for row in rate_attempts if row.success]
    failure = [row for row in rate_attempts if not row.success]
    phase_attempts = Counter(row.phase for row in rate_attempts)
    phase_failures = Counter(row.phase for row in failure)
    phase_successes = Counter(row.phase for row in success)

    active_failures = sum(count for phase, count in phase_failures.items() if phase in ACTIVE_STRESS)
    recovery_failures = sum(count for phase, count in phase_failures.items() if phase in RECOVERY)

    print("\n[readiness_attribution]")
    print(f"rate_relaxed_attempts_total={len(rate_attempts)}")
    print(f"rate_relaxed_successes={len(success)}")
    print(f"rate_relaxed_failures={len(failure)}")
    print("attempts_by_phase=" + ",".join(f"{p}:{phase_attempts[p]}" for p in sorted(phase_attempts)))
    print("failures_by_phase=" + ",".join(f"{p}:{phase_failures[p]}" for p in sorted(phase_failures)))
    print("successes_by_phase=" + ",".join(f"{p}:{phase_successes[p]}" for p in sorted(phase_successes)))
    print(f"failure_fraction_active_stress={active_failures / max(1, len(failure)):.6f}")
    print(f"failure_fraction_recovery_drain={recovery_failures / max(1, len(failure)):.6f}")
    print(f"relief_withdrawal_attempts_total={len(relief_attempts)}")
    print(f"relief_withdrawal_successes={sum(row.success for row in relief_attempts)}")
    print(f"relief_withdrawal_failures={sum(not row.success for row in relief_attempts)}")
    print(f"median_terminal_backlog={median(terminal_backlogs):.1f}")
    print(f"digest_mismatches={digest_mismatches}")
    print()
    summarize_group("successful_rate_attempts", success)
    print()
    summarize_group("failed_rate_attempts", failure)
    print()
    summarize_group("relief_withdrawal_context", relief_attempts)

    print("\n[diagnostic_interpretation]")
    if failure and active_failures > recovery_failures:
        dominant = "active_stress"
    elif failure and recovery_failures > active_failures:
        dominant = "recovery_drain"
    elif failure:
        dominant = "mixed_or_normal"
    else:
        dominant = "no_failures"
    print(f"dominant_failure_region={dominant}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=not_applicable")
    print(
        "interpretation=v0.29 attributes frozen-v0.28 false recovery-readiness "
        "decisions without changing policy or selecting a new threshold."
    )


if __name__ == "__main__":
    main()
