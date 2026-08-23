from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from bardocompute.exchange import ExchangeResult
from bidirectional_homeostasis import BOOSTED_SAFE_CAP
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

# Spent v0.28 seeds. Diagnostic-only; never use for promotion/tuning.
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
class BindingAttempt:
    seed: int
    epoch_index: int
    phase: str
    success: bool
    binding: bool
    base_release_limit: int
    protected_release_limit: int
    withdrawal_delta: int
    pain: float
    load: float
    reserve: float
    trajectory: float
    buffered: int
    resolution_strength: int
    challenge_miss_fraction: float
    challenge_backlog_delta: int


@dataclass(slots=True)
class SeedRun:
    attempts: list[BindingAttempt]
    terminal_backlog: int
    digest_mismatches: int


def run_seed(seed: int, *, rounds: int, deadline_seconds: float) -> SeedRun:
    controller = RateFirstRecoveryMembrane()
    epochs = build_epochs(seed)
    attempts: list[BindingAttempt] = []
    backlog = 0
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

            stage_before = controller.withdrawal_stage
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.29b diagnostic forbids admission shedding")

            is_rate_challenge = (
                controller.withdrawal_stage == controller.RATE_RELAXED
                and stage_before != controller.RATE_RELAXED
            )

            if is_rate_challenge:
                # In RATE_RELAXED the returned command uses the base/normal rate.
                # Compare it to the exact existing protected cap to determine
                # whether withdrawing RATE protection materially changes the command.
                base_release_limit = command.release_limit
                protected_release_limit = min(base_release_limit, BOOSTED_SAFE_CAP)
                binding = base_release_limit > BOOSTED_SAFE_CAP
                pre = {
                    "pain": controller.pain,
                    "load": controller.load,
                    "reserve": controller.reserve,
                    "trajectory": controller.trajectory,
                    "buffered": controller.buffered,
                    "resolution_strength": controller.resolution_strength,
                }
            else:
                base_release_limit = 0
                protected_release_limit = 0
                binding = False
                pre = None

            backlog_before = backlog
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

            if is_rate_challenge and pre is not None:
                success = controller.withdrawal_stage == controller.RELIEF_WITHDRAWAL
                attempts.append(
                    BindingAttempt(
                        seed=seed,
                        epoch_index=epoch_index,
                        phase=spec.phase,
                        success=success,
                        binding=binding,
                        base_release_limit=base_release_limit,
                        protected_release_limit=protected_release_limit,
                        withdrawal_delta=base_release_limit - protected_release_limit,
                        pain=float(pre["pain"]),
                        load=float(pre["load"]),
                        reserve=float(pre["reserve"]),
                        trajectory=float(pre["trajectory"]),
                        buffered=int(pre["buffered"]),
                        resolution_strength=int(pre["resolution_strength"]),
                        challenge_miss_fraction=miss_fraction,
                        challenge_backlog_delta=backlog - backlog_before,
                    )
                )

    return SeedRun(
        attempts=attempts,
        terminal_backlog=backlog,
        digest_mismatches=digest_mismatches,
    )


def _median(rows: list[BindingAttempt], attr: str) -> float:
    if not rows:
        return float("nan")
    return float(median(getattr(row, attr) for row in rows))


def summarize(name: str, rows: list[BindingAttempt]) -> None:
    successes = [row for row in rows if row.success]
    failures = [row for row in rows if not row.success]
    phases = Counter(row.phase for row in rows)
    print(f"[{name}]")
    print(f"attempts={len(rows)}")
    print(f"successes={len(successes)}")
    print(f"failures={len(failures)}")
    print(f"success_fraction={len(successes) / max(1, len(rows)):.6f}")
    print("attempts_by_phase=" + ",".join(f"{p}:{phases[p]}" for p in sorted(phases)))
    print(f"median_withdrawal_delta={_median(rows, 'withdrawal_delta'):.6f}")
    print(f"median_challenge_miss_fraction={_median(rows, 'challenge_miss_fraction'):.6f}")
    print(f"median_challenge_backlog_delta={_median(rows, 'challenge_backlog_delta'):.6f}")


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=rate_cap_binding_attribution_v0.29b")
    print("diagnostic_only=true")
    print("controller=frozen_v0.28")
    print("spent_v028_seeds=true")
    print("policy_promotion_allowed=false")
    print("threshold_selection_allowed=false")
    print("controllers_phase_blind=true")
    print("external_phase_used_for_attribution_only=true")
    print(f"protected_rate_cap={BOOSTED_SAFE_CAP}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    attempts: list[BindingAttempt] = []
    terminal_backlogs: list[int] = []
    digest_mismatches = 0

    for seed in SEEDS:
        run = run_seed(seed, rounds=rounds, deadline_seconds=deadline_seconds)
        attempts.extend(run.attempts)
        terminal_backlogs.append(run.terminal_backlog)
        digest_mismatches += run.digest_mismatches
        for row in run.attempts:
            print(
                f"attempt seed={row.seed} epoch={row.epoch_index} phase={row.phase} "
                f"success={str(row.success).lower()} binding={str(row.binding).lower()} "
                f"base_release={row.base_release_limit} protected_release={row.protected_release_limit} "
                f"withdrawal_delta={row.withdrawal_delta} load={row.load:.6f} "
                f"pain={row.pain:.6f} reserve={row.reserve:.6f} trajectory={row.trajectory:.6f} "
                f"buffered={row.buffered} resolution={row.resolution_strength} "
                f"challenge_miss={row.challenge_miss_fraction:.6f} "
                f"backlog_delta={row.challenge_backlog_delta}"
            )

    binding = [row for row in attempts if row.binding]
    nonbinding = [row for row in attempts if not row.binding]
    successes = [row for row in attempts if row.success]
    nonbinding_successes = [row for row in successes if not row.binding]
    binding_failures = [row for row in binding if not row.success]
    binding_successes = [row for row in binding if row.success]

    binding_fail_active = sum(row.phase in ACTIVE_STRESS for row in binding_failures)
    binding_success_recovery = sum(row.phase in RECOVERY for row in binding_successes)

    print("\n[binding_attribution]")
    summarize("binding_challenges", binding)
    print()
    summarize("nonbinding_challenges", nonbinding)
    print()
    print(f"all_successes={len(successes)}")
    print(f"nonbinding_successes={len(nonbinding_successes)}")
    print(
        "fraction_successes_nonbinding="
        f"{len(nonbinding_successes) / max(1, len(successes)):.6f}"
    )
    print(
        "fraction_binding_failures_active_stress="
        f"{binding_fail_active / max(1, len(binding_failures)):.6f}"
    )
    print(
        "fraction_binding_successes_recovery_drain="
        f"{binding_success_recovery / max(1, len(binding_successes)):.6f}"
    )
    print(f"median_terminal_backlog={median(terminal_backlogs):.1f}")
    print(f"digest_mismatches={digest_mismatches}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=not_applicable")
    print(
        "interpretation=v0.29b distinguishes meaningful RATE-cap withdrawal "
        "from non-binding/no-op challenges without changing the frozen v0.28 controller."
    )


if __name__ == "__main__":
    main()
