from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from active_load_gate_v030 import ActiveLoadGatedRateFirstMembrane
from bardocompute.exchange import ExchangeResult
from bidirectional_homeostasis import BOOSTED_SAFE_CAP
from computational_interoception_v019 import (
    MAX_RELEASE_REFERENCE,
    MIN_ACTIVE_LOAD,
    RECOVERY_DWELL,
)
from real_work_queue_outcome_audit_r3 import SEVERE_MISS_THRESHOLD
from real_work_queue_transfer import (
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)

# Spent canonical v0.30 seeds. Diagnostic-only.
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

ACTIVE_STRESS = {"burst", "primary_degraded", "global_congested"}
RECOVERY_DRAIN = {"recovery", "drain"}
PROTECTED_CAP_LOAD = BOOSTED_SAFE_CAP / MAX_RELEASE_REFERENCE
CAP_LOAD_TOLERANCE = 0.02


@dataclass(slots=True)
class ProtectedEpoch:
    seed: int
    epoch_index: int
    phase: str
    reason: str
    resolution_strength: int
    load: float
    pain: float
    reserve: float
    trajectory: float
    buffered: int
    previous_released: int
    previous_delivered: int
    previous_miss_fraction: float
    actual_released: int = 0
    on_time: int = 0
    miss_fraction: float = 0.0
    backlog_after: int = 0
    backlog_delta: int = 0


def classify(controller: ActiveLoadGatedRateFirstMembrane) -> str:
    if controller.resolution_strength < RECOVERY_DWELL:
        return "RESOLUTION_NOT_READY"
    if controller.load >= MIN_ACTIVE_LOAD:
        return "LOAD_GATE_BLOCKED"
    return "RATE_RELAXATION_ELIGIBLE"


def run_seed(seed: int, *, rounds: int, deadline_seconds: float) -> tuple[list[ProtectedEpoch], list[int], list[int], int, int]:
    controller = ActiveLoadGatedRateFirstMembrane()
    epochs = list(build_epochs(seed))
    epochs.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

    records: list[ProtectedEpoch] = []
    load_blocked_runs: list[int] = []
    ready_to_eligible_delays: list[int] = []
    current_blocked_run = 0
    first_ready_epoch: int | None = None
    first_eligible_epoch: int | None = None

    backlog = 0
    previous_released = 0
    previous_delivered = 0
    previous_miss_fraction = 0.0
    digest_mismatches = 0

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()

        for epoch_index, spec in enumerate(epochs):
            if spec.phase == "drain" and backlog == 0:
                break

            pre_record: ProtectedEpoch | None = None
            if controller.protective and controller.withdrawal_stage == controller.PROTECTED:
                reason = classify(controller)
                pre_record = ProtectedEpoch(
                    seed=seed,
                    epoch_index=epoch_index,
                    phase=spec.phase,
                    reason=reason,
                    resolution_strength=controller.resolution_strength,
                    load=controller.load,
                    pain=controller.pain,
                    reserve=controller.reserve,
                    trajectory=controller.trajectory,
                    buffered=controller.buffered,
                    previous_released=previous_released,
                    previous_delivered=previous_delivered,
                    previous_miss_fraction=previous_miss_fraction,
                )
                records.append(pre_record)

                if controller.resolution_strength >= RECOVERY_DWELL and first_ready_epoch is None:
                    first_ready_epoch = epoch_index
                if reason == "RATE_RELAXATION_ELIGIBLE" and first_eligible_epoch is None:
                    first_eligible_epoch = epoch_index

                if reason == "LOAD_GATE_BLOCKED":
                    current_blocked_run += 1
                elif current_blocked_run:
                    load_blocked_runs.append(current_blocked_run)
                    current_blocked_run = 0
            elif current_blocked_run:
                load_blocked_runs.append(current_blocked_run)
                current_blocked_run = 0

            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.32 diagnostic forbids voluntary admission shedding")

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

            if pre_record is not None:
                pre_record.actual_released = released
                pre_record.on_time = on_time
                pre_record.miss_fraction = miss_fraction
                pre_record.backlog_after = backlog
                pre_record.backlog_delta = backlog - backlog_before

            previous_released = released
            previous_delivered = on_time
            previous_miss_fraction = miss_fraction

    if current_blocked_run:
        load_blocked_runs.append(current_blocked_run)
    if first_ready_epoch is not None and first_eligible_epoch is not None:
        ready_to_eligible_delays.append(max(0, first_eligible_epoch - first_ready_epoch))

    return records, load_blocked_runs, ready_to_eligible_delays, backlog, digest_mismatches


def med(rows: list[ProtectedEpoch], attr: str) -> float:
    if not rows:
        return float("nan")
    return float(median(getattr(row, attr) for row in rows))


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=load_gate_self_lock_attribution_v0.32")
    print("controller=canonical_v0.30_unchanged")
    print("spent_v030_seeds=true")
    print("policy_promotion=false")
    print("threshold_tuning=false")
    print("controller_phase_blind=true")
    print("phase_labels_external_attribution_only=true")
    print(f"MIN_ACTIVE_LOAD={MIN_ACTIVE_LOAD:.6f}")
    print(f"MAX_RELEASE_REFERENCE={MAX_RELEASE_REFERENCE:.6f}")
    print(f"BOOSTED_SAFE_CAP={BOOSTED_SAFE_CAP}")
    print(f"protected_cap_load={PROTECTED_CAP_LOAD:.6f}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    records: list[ProtectedEpoch] = []
    blocked_runs: list[int] = []
    ready_delays: list[int] = []
    terminal_backlogs: list[int] = []
    digest_mismatches = 0

    for seed in SEEDS:
        seed_records, seed_runs, seed_delays, terminal_backlog, mismatches = run_seed(
            seed,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        records.extend(seed_records)
        blocked_runs.extend(seed_runs)
        ready_delays.extend(seed_delays)
        terminal_backlogs.append(terminal_backlog)
        digest_mismatches += mismatches

    reason_counts = Counter(row.reason for row in records)
    phase_reason_counts = Counter((row.phase, row.reason) for row in records)
    blocked = [row for row in records if row.reason == "LOAD_GATE_BLOCKED"]

    near_cap = [row for row in blocked if abs(row.load - PROTECTED_CAP_LOAD) <= CAP_LOAD_TOLERANCE]
    blocked_active = [row for row in blocked if row.phase in ACTIVE_STRESS]
    blocked_recovery = [row for row in blocked if row.phase in RECOVERY_DRAIN]

    print("\n[load_gate_attribution]")
    print(f"full_protection_epochs_total={len(records)}")
    for reason in ("RESOLUTION_NOT_READY", "LOAD_GATE_BLOCKED", "RATE_RELAXATION_ELIGIBLE"):
        count = reason_counts[reason]
        print(f"reason_{reason}=count:{count},fraction:{count / max(1, len(records)):.6f}")

    phase_keys = sorted(phase_reason_counts)
    print(
        "phase_reason_counts="
        + ",".join(
            f"{phase}/{reason}:{phase_reason_counts[(phase, reason)]}"
            for phase, reason in phase_keys
        )
    )

    for reason in ("RESOLUTION_NOT_READY", "LOAD_GATE_BLOCKED", "RATE_RELAXATION_ELIGIBLE"):
        rows = [row for row in records if row.reason == reason]
        print(
            f"reason={reason} count={len(rows)} "
            f"median_load={med(rows, 'load'):.6f} "
            f"median_buffered={med(rows, 'buffered'):.3f} "
            f"median_resolution_strength={med(rows, 'resolution_strength'):.3f} "
            f"median_miss_fraction={med(rows, 'miss_fraction'):.6f}"
        )

    print(f"load_blocked_near_cap_fraction={len(near_cap) / max(1, len(blocked)):.6f}")
    print(f"load_blocked_active_stress_fraction={len(blocked_active) / max(1, len(blocked)):.6f}")
    print(f"load_blocked_recovery_drain_fraction={len(blocked_recovery) / max(1, len(blocked)):.6f}")
    print(f"median_consecutive_load_blocked_run={median(blocked_runs) if blocked_runs else 0.0:.3f}")
    print(f"median_ready_to_eligible_delay={median(ready_delays) if ready_delays else 0.0:.3f}")
    print(f"median_terminal_backlog={median(terminal_backlogs):.1f}")
    print(f"digest_mismatches={digest_mismatches}")

    print("\n[diagnostic_interpretation]")
    resolution_ready_total = reason_counts["LOAD_GATE_BLOCKED"] + reason_counts["RATE_RELAXATION_ELIGIBLE"]
    blocked_after_ready_fraction = reason_counts["LOAD_GATE_BLOCKED"] / max(1, resolution_ready_total)
    print(f"blocked_after_resolution_ready_fraction={blocked_after_ready_fraction:.6f}")
    if (
        blocked_after_ready_fraction > 0.5
        and len(near_cap) / max(1, len(blocked)) >= 0.5
    ):
        classification = "actuator_shaped_load_gate_self_lock_supported"
    elif reason_counts["RESOLUTION_NOT_READY"] > reason_counts["LOAD_GATE_BLOCKED"]:
        classification = "resolution_accumulation_dominates"
    else:
        classification = "mixed_or_ambiguous"
    print(f"classification={classification}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=not_applicable")
    print(
        "interpretation=v0.32 attributes canonical-v0.30 FULL_PROTECTION duration "
        "to recovery-evidence readiness versus the pre-existing active-load gate, "
        "without changing controller semantics."
    )


if __name__ == "__main__":
    main()
