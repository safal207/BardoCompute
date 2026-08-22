from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from statistics import median

from bardocompute.exchange import ExchangeResult
from continuous_miss_burden_v026 import (
    FixedSupportMembrane,
    MISS_THRESHOLD,
    SEVERE_MISS_THRESHOLD,
)
from real_work_queue_transfer import (
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)

# Fresh held-out family frozen in issue #13 before implementation/results.
SEEDS = (
    15_100_487,
    15_200_491,
    15_300_499,
    15_400_503,
    15_500_509,
    15_600_521,
    15_700_523,
    15_800_531,
)

PHASES = (
    "normal",
    "burst",
    "primary_degraded",
    "global_congested",
    "recovery",
    "drain",
)
ACTIVE_STRESS_PHASES = ("burst", "primary_degraded", "global_congested")
RECOVERY_PHASES = ("recovery", "drain")
MIN_SIGN_AGREEMENT = 6
MIN_COMPLETED_PRESERVATION = 0.98


@dataclass(slots=True)
class PhaseStats:
    released_work: int = 0
    completed_work: int = 0
    missed_work_total: int = 0
    severe_excess_total: float = 0.0
    wall_seconds: float = 0.0
    backlog_area: int = 0
    phase_end_backlog: int = 0
    lost: int = 0
    digest_mismatches: int = 0
    deadline_miss_epochs: int = 0
    severe_miss_epochs: int = 0

    def missed_work_fraction(self) -> float:
        return self.missed_work_total / max(1, self.released_work)

    def severe_excess_fraction(self) -> float:
        return self.severe_excess_total / max(1, self.released_work)

    def backlog_per_released(self) -> float:
        return self.backlog_area / max(1, self.released_work)

    def seconds_per_completed(self) -> float:
        return self.wall_seconds / max(1, self.completed_work)


@dataclass(slots=True)
class RunStats:
    phases: dict[str, PhaseStats] = field(default_factory=dict)
    completed: int = 0
    terminal_backlog: int = 0
    digest_mismatches: int = 0

    def phase(self, name: str) -> PhaseStats:
        return self.phases.get(name, PhaseStats())


def run_phase_local_policy(
    epochs: tuple[EpochSpec, ...],
    *,
    controller: FixedSupportMembrane,
    rounds: int,
    deadline_seconds: float,
) -> RunStats:
    run = RunStats()
    backlog = 0

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

        for spec in queue:
            if spec.phase == "drain" and backlog == 0:
                break

            phase = run.phases.setdefault(spec.phase, PhaseStats())
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.27 forbids voluntary admission shedding")

            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            backlog += admitted
            phase.lost += overflow

            released = min(backlog, command.release_limit)
            backlog -= released

            relief_active = bool(getattr(controller, "current_boost", 0.0) > 0.0)
            relief_count = 0
            if relief_active and released:
                relief_count = min(
                    released,
                    int(round(released * RELIEF_TASK_FRACTION)),
                )
            ordinary = released - relief_count
            secondary_count = min(
                ordinary,
                max(0, int(round(ordinary * command.secondary_fraction))),
            )
            primary_count = ordinary - secondary_count

            elapsed, p_on, s_on, r_on, mismatches = _execute_batch(
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

            on_time = p_on + s_on + r_on
            missed = max(0, released - on_time)
            miss_fraction = missed / max(1, released)

            phase.released_work += released
            phase.completed_work += released
            phase.missed_work_total += missed
            phase.severe_excess_total += max(
                0.0, miss_fraction - SEVERE_MISS_THRESHOLD
            ) * released
            phase.wall_seconds += elapsed
            phase.backlog_area += backlog
            phase.phase_end_backlog = backlog
            phase.digest_mismatches += mismatches
            if released > 0:
                phase.deadline_miss_epochs += int(miss_fraction >= MISS_THRESHOLD)
                phase.severe_miss_epochs += int(
                    miss_fraction >= SEVERE_MISS_THRESHOLD
                )

            run.completed += released
            run.digest_mismatches += mismatches

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

    run.terminal_backlog = backlog
    return run


def phase_diff(candidate: RunStats, reference: RunStats, phase: str) -> dict[str, float]:
    c = candidate.phase(phase)
    r = reference.phase(phase)
    return {
        "missed": c.missed_work_fraction() - r.missed_work_fraction(),
        "severe": c.severe_excess_fraction() - r.severe_excess_fraction(),
        "backlog": c.backlog_per_released() - r.backlog_per_released(),
        "end_backlog": float(c.phase_end_backlog - r.phase_end_backlog),
        "seconds": c.seconds_per_completed() - r.seconds_per_completed(),
    }


def positive(values: list[float]) -> int:
    return sum(value > 0.0 for value in values)


def negative(values: list[float]) -> int:
    return sum(value < 0.0 for value in values)


def stable_harmful_miss(rows: list[dict[str, float]]) -> bool:
    values = [row["missed"] for row in rows]
    return median(values) > 0.0 and positive(values) >= MIN_SIGN_AGREEMENT


def stable_beneficial_backlog(rows: list[dict[str, float]]) -> bool:
    values = [row["backlog"] for row in rows]
    return median(values) < 0.0 and negative(values) >= MIN_SIGN_AGREEMENT


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=phase_local_support_value_v0.27")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("controllers_phase_blind=true")
    print("phase_labels_external_audit_only=true")
    print("support_matrix=frozen_v0.26")
    print("new_actuator_magnitudes=false")
    print("admission_shedding=false")

    names = ("full_support", "rate_cap_only", "relief_only", "storage_only")
    all_runs: dict[str, list[RunStats]] = {name: [] for name in names}
    relief_diffs: dict[str, list[dict[str, float]]] = {phase: [] for phase in PHASES}
    rate_diffs: dict[str, list[dict[str, float]]] = {phase: [] for phase in PHASES}

    for seed in SEEDS:
        epochs = build_epochs(seed)
        controllers = {
            "full_support": FixedSupportMembrane(relief=True, rate_cap=True),
            "rate_cap_only": FixedSupportMembrane(relief=False, rate_cap=True),
            "relief_only": FixedSupportMembrane(relief=True, rate_cap=False),
            "storage_only": FixedSupportMembrane(relief=False, rate_cap=False),
        }
        current: dict[str, RunStats] = {}
        for name, controller in controllers.items():
            current[name] = run_phase_local_policy(
                epochs,
                controller=controller,
                rounds=rounds,
                deadline_seconds=deadline_seconds,
            )
            all_runs[name].append(current[name])

        a = current["full_support"]
        b = current["rate_cap_only"]
        c = current["relief_only"]
        for phase in PHASES:
            relief_diffs[phase].append(phase_diff(b, a, phase))
            rate_diffs[phase].append(phase_diff(c, a, phase))

        print(f"\nseed={seed}")
        for phase in PHASES:
            a_phase = a.phase(phase)
            relief_delta = relief_diffs[phase][-1]
            rate_delta = rate_diffs[phase][-1]
            print(
                f"phase={phase} "
                f"A_missed={a_phase.missed_work_fraction():.6f} "
                f"relief_remove_missed_delta={relief_delta['missed']:.6f} "
                f"rate_remove_missed_delta={rate_delta['missed']:.6f} "
                f"rate_remove_backlog_delta={rate_delta['backlog']:.6f} "
                f"rate_remove_end_backlog_delta={rate_delta['end_backlog']:.1f}"
            )

    for phase in PHASES:
        relief_rows = relief_diffs[phase]
        rate_rows = rate_diffs[phase]
        relief_missed = [row["missed"] for row in relief_rows]
        rate_missed = [row["missed"] for row in rate_rows]
        rate_backlog = [row["backlog"] for row in rate_rows]
        print(f"\n[phase={phase}]")
        print(
            f"relief_removal_median_missed_delta={median(relief_missed):.6f} "
            f"relief_harmful_seeds={positive(relief_missed)}/{len(SEEDS)}"
        )
        print(
            f"rate_removal_median_missed_delta={median(rate_missed):.6f} "
            f"rate_harmful_seeds={positive(rate_missed)}/{len(SEEDS)}"
        )
        print(
            f"rate_removal_median_backlog_delta={median(rate_backlog):.6f} "
            f"rate_backlog_beneficial_seeds={negative(rate_backlog)}/{len(SEEDS)}"
        )

    rate_active_harmful = [
        phase for phase in ACTIVE_STRESS_PHASES if stable_harmful_miss(rate_diffs[phase])
    ]
    rate_recovery_beneficial = [
        phase for phase in RECOVERY_PHASES if stable_beneficial_backlog(rate_diffs[phase])
    ]
    relief_active_harmful = [
        phase for phase in ACTIVE_STRESS_PHASES if stable_harmful_miss(relief_diffs[phase])
    ]

    completed_preservation = median(
        candidate.completed / max(1, reference.completed)
        for candidate, reference in zip(
            all_runs["relief_only"], all_runs["full_support"], strict=True
        )
    )
    integrity_ok = (
        completed_preservation >= MIN_COMPLETED_PRESERVATION
        and all(run.terminal_backlog == 0 for run in all_runs["relief_only"])
        and sum(run.digest_mismatches for run in all_runs["relief_only"]) == 0
    )
    rate_phase_tradeoff_supported = bool(
        rate_active_harmful and rate_recovery_beneficial and integrity_ok
    )

    print("\n[phase_local_causal]" )
    print(
        "rate_active_harmful_phases="
        + (",".join(rate_active_harmful) if rate_active_harmful else "none")
    )
    print(
        "rate_recovery_backlog_beneficial_phases="
        + (",".join(rate_recovery_beneficial) if rate_recovery_beneficial else "none")
    )
    print(
        "relief_active_harmful_phases="
        + (",".join(relief_active_harmful) if relief_active_harmful else "none")
    )
    print(f"rate_completed_preservation={completed_preservation:.3f}")
    print(f"integrity_ok={str(integrity_ok).lower()}")
    print(f"rate_phase_tradeoff_supported={str(rate_phase_tradeoff_supported).lower()}")
    print("phase_local_audit_complete=true")
    print(
        "interpretation=v0.27 keeps controllers phase-blind and uses phase labels "
        "only in the external evaluator to test whether support value changes "
        "between active pressure and recovery/drain."
    )


if __name__ == "__main__":
    main()
