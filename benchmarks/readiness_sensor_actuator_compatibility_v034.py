from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
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


@dataclass(slots=True)
class EpochEvidence:
    epoch_index: int
    phase: str
    incoming: int
    admitted: int
    backlog_before: int
    backlog_after: int
    available: int
    base_release_limit: int
    uncapped_release: int
    protected_release: int
    actual_release: int
    execution_binding: bool
    load_after: float


@dataclass(slots=True)
class ChallengeRecord:
    seed: int
    challenge_ordinal: int
    eligibility_epoch: int
    challenge_epoch: int
    eligibility_phase: str
    challenge_phase: str
    observed_load: float
    observed_released: int
    observed_backlog_before: int
    observed_backlog_after: int
    observed_available: int
    observed_base_release_limit: int
    observed_uncapped_release: int
    observed_protected_release: int
    observed_execution_binding: bool
    challenge_incoming: int
    challenge_admitted: int
    challenge_backlog_before: int
    challenge_backlog_after: int
    challenge_available: int
    challenge_base_release_limit: int
    challenge_uncapped_release: int
    challenge_protected_release: int
    challenge_withdrawal_delta: int
    challenge_execution_binding: bool
    incoming_delta: int
    challenge_backlog_delta: int
    transition_class: str
    success: bool
    miss_fraction: float


def transition_class(observed_binding: bool, challenge_binding: bool) -> str:
    if not observed_binding and not challenge_binding:
        return "NONBINDING_STAYS_NONBINDING"
    if not observed_binding and challenge_binding:
        return "NONBINDING_BECOMES_BINDING"
    if observed_binding and challenge_binding:
        return "BINDING_STAYS_BINDING"
    return "BINDING_BECOMES_NONBINDING"


def run_seed(
    seed: int,
    *,
    rounds: int,
    deadline_seconds: float,
) -> tuple[list[ChallengeRecord], int, int, int]:
    controller = ActiveLoadGatedRateFirstMembrane()
    epochs = list(build_epochs(seed))
    epochs.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

    records: list[ChallengeRecord] = []
    previous_epoch: EpochEvidence | None = None
    backlog = 0
    digest_mismatches = 0
    eligibility_observations = 0
    challenge_ordinal = 0

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

            pre_protective = controller.protective
            pre_stage = controller.withdrawal_stage
            pre_rate_count = controller.rate_relaxed_count
            observed_load = controller.load

            gate_eligible = (
                pre_protective
                and pre_stage == controller.PROTECTED
                and controller.resolution_strength >= RECOVERY_DWELL
                and observed_load < MIN_ACTIVE_LOAD
            )
            if gate_eligible:
                eligibility_observations += 1

            base_copy = deepcopy(controller.base)
            base_command = base_copy.command()
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.34 diagnostic forbids voluntary admission shedding")

            challenge_started = (
                gate_eligible
                and controller.withdrawal_stage == controller.RATE_RELAXED
                and controller.rate_relaxed_count == pre_rate_count + 1
            )
            if challenge_started and previous_epoch is None:
                raise AssertionError("RATE challenge has no previous eligibility evidence epoch")
            if (
                challenge_started
                and previous_epoch is not None
                and abs(previous_epoch.load_after - observed_load) > 1e-12
            ):
                raise AssertionError(
                    "persisted eligibility evidence does not match controller LOAD"
                )

            backlog_before = backlog
            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            available = backlog + admitted

            uncapped_release = min(available, base_command.release_limit)
            protected_release = min(uncapped_release, BOOSTED_SAFE_CAP)
            released = min(available, command.release_limit)
            backlog = available - released

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

            success_before = controller.rate_relaxed_success
            failure_before = controller.rate_relaxed_failure
            controller.observe(result)

            if challenge_started:
                assert previous_epoch is not None
                success_delta = controller.rate_relaxed_success - success_before
                failure_delta = controller.rate_relaxed_failure - failure_before
                if success_delta + failure_delta != 1:
                    raise AssertionError("RATE challenge did not resolve exactly once")

                challenge_ordinal += 1
                challenge_binding = uncapped_release > protected_release
                observed_binding = previous_epoch.execution_binding
                records.append(
                    ChallengeRecord(
                        seed=seed,
                        challenge_ordinal=challenge_ordinal,
                        eligibility_epoch=previous_epoch.epoch_index,
                        challenge_epoch=epoch_index,
                        eligibility_phase=previous_epoch.phase,
                        challenge_phase=spec.phase,
                        observed_load=observed_load,
                        observed_released=previous_epoch.actual_release,
                        observed_backlog_before=previous_epoch.backlog_before,
                        observed_backlog_after=previous_epoch.backlog_after,
                        observed_available=previous_epoch.available,
                        observed_base_release_limit=previous_epoch.base_release_limit,
                        observed_uncapped_release=previous_epoch.uncapped_release,
                        observed_protected_release=previous_epoch.protected_release,
                        observed_execution_binding=observed_binding,
                        challenge_incoming=spec.incoming,
                        challenge_admitted=admitted,
                        challenge_backlog_before=backlog_before,
                        challenge_backlog_after=backlog,
                        challenge_available=available,
                        challenge_base_release_limit=base_command.release_limit,
                        challenge_uncapped_release=uncapped_release,
                        challenge_protected_release=protected_release,
                        challenge_withdrawal_delta=uncapped_release - protected_release,
                        challenge_execution_binding=challenge_binding,
                        incoming_delta=spec.incoming - previous_epoch.incoming,
                        challenge_backlog_delta=backlog - backlog_before,
                        transition_class=transition_class(
                            observed_binding, challenge_binding
                        ),
                        success=success_delta == 1,
                        miss_fraction=miss_fraction,
                    )
                )

            previous_epoch = EpochEvidence(
                epoch_index=epoch_index,
                phase=spec.phase,
                incoming=spec.incoming,
                admitted=admitted,
                backlog_before=backlog_before,
                backlog_after=backlog,
                available=available,
                base_release_limit=base_command.release_limit,
                uncapped_release=uncapped_release,
                protected_release=protected_release,
                actual_release=released,
                execution_binding=uncapped_release > protected_release,
                load_after=released / MAX_RELEASE_REFERENCE,
            )

    return records, eligibility_observations, backlog, digest_mismatches


def med(rows: list[ChallengeRecord], attr: str) -> float:
    if not rows:
        return float("nan")
    return float(median(getattr(row, attr) for row in rows))


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)
    eligible_boundary = MIN_ACTIVE_LOAD * MAX_RELEASE_REFERENCE

    print("diagnostic=readiness_sensor_actuator_compatibility_v0.34")
    print("controller=canonical_v0.30_unchanged")
    print("spent_v030_seeds=true")
    print("policy_promotion=false")
    print("threshold_tuning=false")
    print("controller_phase_blind=true")
    print("phase_labels_external_attribution_only=true")
    print("eligibility_evidence_timing=previous_completed_epoch")
    print("challenge_timing=next_command_epoch")
    print(f"MIN_ACTIVE_LOAD={MIN_ACTIVE_LOAD:.6f}")
    print(f"MAX_RELEASE_REFERENCE={MAX_RELEASE_REFERENCE:.6f}")
    print(f"eligible_released_boundary={eligible_boundary:.3f}")
    print(f"BOOSTED_SAFE_CAP={BOOSTED_SAFE_CAP}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    all_records: list[ChallengeRecord] = []
    eligibility_observations = 0
    terminal_backlogs: list[int] = []
    digest_mismatches = 0

    for seed in SEEDS:
        rows, eligible, terminal_backlog, mismatches = run_seed(
            seed,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        all_records.extend(rows)
        eligibility_observations += eligible
        terminal_backlogs.append(terminal_backlog)
        digest_mismatches += mismatches

    class_counts = Counter(row.transition_class for row in all_records)
    phase_counts = Counter(
        (row.challenge_phase, row.transition_class) for row in all_records
    )
    by_class: dict[str, list[ChallengeRecord]] = defaultdict(list)
    for row in all_records:
        by_class[row.transition_class].append(row)

    observed_binding_count = sum(row.observed_execution_binding for row in all_records)
    successes = [row for row in all_records if row.success]
    failures = [row for row in all_records if not row.success]
    no_op_successes = [
        row
        for row in successes
        if row.transition_class == "NONBINDING_STAYS_NONBINDING"
    ]
    emerged_binding_failures = [
        row
        for row in failures
        if row.transition_class == "NONBINDING_BECOMES_BINDING"
    ]

    print("\n[sensor_actuator_compatibility]")
    print(f"eligibility_observations={eligibility_observations}")
    print(f"rate_challenges={len(all_records)}")
    print(
        f"observed_execution_binding_count={observed_binding_count} "
        f"fraction={observed_binding_count / max(1, len(all_records)):.6f}"
    )

    classes = (
        "NONBINDING_STAYS_NONBINDING",
        "NONBINDING_BECOMES_BINDING",
        "BINDING_STAYS_BINDING",
        "BINDING_BECOMES_NONBINDING",
    )
    for name in classes:
        rows = by_class[name]
        class_successes = sum(row.success for row in rows)
        class_failures = len(rows) - class_successes
        print(
            f"class={name} attempts={len(rows)} "
            f"fraction={len(rows) / max(1, len(all_records)):.6f} "
            f"successes={class_successes} failures={class_failures} "
            f"success_fraction={class_successes / max(1, len(rows)):.6f} "
            f"median_withdrawal_delta={med(rows, 'challenge_withdrawal_delta'):.3f} "
            f"median_incoming_delta={med(rows, 'incoming_delta'):.3f} "
            f"median_challenge_backlog_delta={med(rows, 'challenge_backlog_delta'):.3f} "
            f"median_miss_fraction={med(rows, 'miss_fraction'):.6f}"
        )

    print(
        "phase_class_counts="
        + ",".join(
            f"{phase}/{name}:{phase_counts[(phase, name)]}"
            for phase, name in sorted(phase_counts)
        )
    )
    print(f"all_successes={len(successes)}")
    print(f"all_failures={len(failures)}")
    print(
        "fraction_successes_nonbinding_stays_nonbinding="
        f"{len(no_op_successes) / max(1, len(successes)):.6f}"
    )
    print(
        "fraction_failures_nonbinding_becomes_binding="
        f"{len(emerged_binding_failures) / max(1, len(failures)):.6f}"
    )
    print(f"median_terminal_backlog={median(terminal_backlogs):.1f}")
    print(f"digest_mismatches={digest_mismatches}")

    algebraic_compatibility_rejected = (
        observed_binding_count == 0
        and eligible_boundary < BOOSTED_SAFE_CAP
    )
    emergence_failures_dominate = (
        bool(failures)
        and len(emerged_binding_failures) / len(failures) >= 0.75
    )
    no_op_success_bias = (
        bool(successes)
        and len(no_op_successes) / len(successes) >= 0.50
    )

    if (
        algebraic_compatibility_rejected
        and emergence_failures_dominate
        and no_op_success_bias
    ):
        classification = "one_step_binding_emergence_and_no_op_success_bias"
    elif algebraic_compatibility_rejected and emergence_failures_dominate:
        classification = "one_step_binding_emergence_supported"
    elif algebraic_compatibility_rejected and no_op_success_bias:
        classification = "same_epoch_gate_validates_no_op_withdrawal"
    elif algebraic_compatibility_rejected:
        classification = "same_epoch_sensor_actuator_incompatibility"
    else:
        classification = "mixed_or_ambiguous"

    print("\n[diagnostic_interpretation]")
    print(f"classification={classification}")
    print(
        "same_epoch_sensor_actuator_compatibility_rejected="
        f"{str(algebraic_compatibility_rejected).lower()}"
    )
    print(
        "one_step_binding_emergence_failures_dominate="
        f"{str(emergence_failures_dominate).lower()}"
    )
    print(f"no_op_success_bias={str(no_op_success_bias).lower()}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=not_applicable")
    print(
        "interpretation=v0.34 attributes canonical v0.30 RATE challenges "
        "from previous-epoch LOAD evidence to current-epoch execution binding, "
        "without changing the controller."
    )


if __name__ == "__main__":
    main()
