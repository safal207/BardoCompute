from __future__ import annotations

from statistics import median

from computational_interoception_v019 import (
    HEALTHY_PAIN,
    RECOVERY_DWELL,
    InteroceptiveMembrane,
)
from exchange_conservation import FlowPreservingMembrane
from real_work_queue_outcome_audit_r3 import OutcomeStats, run_outcome_policy, safe_ratio
from real_work_queue_transfer import build_epochs, calibrate_rounds
from recovery_decoupling_v020 import RecoveryDecoupledMembrane

# Fresh held-out family frozen in docs/recovery-predicate-ablation-v0.21.md.
SEEDS = (9_100_251, 9_200_257, 9_300_263, 9_400_269, 9_500_271, 9_600_277)

# Existing v0.19 promotion bar. No threshold retuning on this family.
MIN_COMPLETED_BASELINE = 1.25
MAX_LOST_BASELINE = 0.75
MAX_SECONDS_BASELINE = 1.15
MAX_MISS_BASELINE = 0.60
MAX_SEVERE_BASELINE = 0.25
MAX_OCCUPANCY = 0.65

# Frozen causal-classification constants from the preregistration.
MIN_OCCUPANCY_REDUCTION = 0.20
MIN_COMPLETED_PRESERVATION = 0.98
MAX_TRAJECTORY_ABLATION_MISS = 1.25
MAX_REDUNDANT_MISS = 1.10
MAX_REDUNDANT_SECONDS = 1.15


class PainOnlyRecoveryMembrane(InteroceptiveMembrane):
    """Exact v0.19 entry semantics with PAIN-only recovery evidence."""

    def observe(self, result) -> None:
        previous_recovery = self.recovery
        super().observe(result)

        # Keep v0.19 PAIN threshold and RECOVERY_DWELL. Only RESERVE and
        # TRAJECTORY are ablated from the recovery predicate.
        healthy_for_recovery = self.pain < HEALTHY_PAIN
        self.recovery = previous_recovery + 1 if healthy_for_recovery else 0


def baseline_ratios(candidate: OutcomeStats, baseline: OutcomeStats) -> dict[str, float]:
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


def candidate_promotable(rows: list[dict[str, float]], stats: list[OutcomeStats]) -> bool:
    return (
        median(row["completed"] for row in rows) >= MIN_COMPLETED_BASELINE
        and median(row["lost"] for row in rows) <= MAX_LOST_BASELINE
        and median(row["seconds"] for row in rows) <= MAX_SECONDS_BASELINE
        and median(row["miss"] for row in rows) <= MAX_MISS_BASELINE
        and median(row["severe"] for row in rows) <= MAX_SEVERE_BASELINE
        and median(row.relief_occupancy() for row in stats) <= MAX_OCCUPANCY
        and median(row.storage_occupancy() for row in stats) <= MAX_OCCUPANCY
        and median(row.terminal_backlog for row in stats) == 0
        and sum(row.digest_mismatches for row in stats) == 0
    )


def summarize(
    name: str,
    rows: list[dict[str, float]],
    stats: list[OutcomeStats],
    transitions: list[int],
) -> bool:
    promotable = candidate_promotable(rows, stats)
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
        f"median_protective_transitions={median(transitions):.1f}"
    )
    print(f"median_terminal_backlog={median(row.terminal_backlog for row in stats):.1f}")
    print(f"digest_mismatches={sum(row.digest_mismatches for row in stats)}")
    print(f"promotable={str(promotable).lower()}")
    return promotable


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=recovery_predicate_ablation_v0.21")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("entry_semantics=unchanged_v0.19")
    print("candidate_A=PAIN+RESERVE+TRAJECTORY")
    print("candidate_B=PAIN+TRAJECTORY")
    print("candidate_C=PAIN_only")
    print(f"recovery_dwell={RECOVERY_DWELL}")
    print("new_actuators=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    rows_a: list[dict[str, float]] = []
    rows_b: list[dict[str, float]] = []
    rows_c: list[dict[str, float]] = []
    stats_a: list[OutcomeStats] = []
    stats_b: list[OutcomeStats] = []
    stats_c: list[OutcomeStats] = []
    transitions_a: list[int] = []
    transitions_b: list[int] = []
    transitions_c: list[int] = []

    b_vs_a_relief: list[float] = []
    b_vs_a_completed: list[float] = []
    b_vs_a_miss: list[float] = []
    b_vs_a_severe: list[float] = []

    c_vs_b_relief: list[float] = []
    c_vs_b_storage: list[float] = []
    c_vs_b_completed: list[float] = []
    c_vs_b_seconds: list[float] = []
    c_vs_b_miss: list[float] = []
    c_vs_b_severe: list[float] = []

    for seed in SEEDS:
        epochs = build_epochs(seed)
        baseline = run_outcome_policy(
            epochs,
            controller=FlowPreservingMembrane(route_enabled=True),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        controller_a = InteroceptiveMembrane()
        a = run_outcome_policy(
            epochs,
            controller=controller_a,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        controller_b = RecoveryDecoupledMembrane()
        b = run_outcome_policy(
            epochs,
            controller=controller_b,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        controller_c = PainOnlyRecoveryMembrane()
        c = run_outcome_policy(
            epochs,
            controller=controller_c,
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        row_a = baseline_ratios(a, baseline)
        row_b = baseline_ratios(b, baseline)
        row_c = baseline_ratios(c, baseline)
        rows_a.append(row_a)
        rows_b.append(row_b)
        rows_c.append(row_c)
        stats_a.append(a)
        stats_b.append(b)
        stats_c.append(c)
        transitions_a.append(controller_a.protective_transitions)
        transitions_b.append(controller_b.protective_transitions)
        transitions_c.append(controller_c.protective_transitions)

        b_vs_a_relief.append(safe_ratio(b.relief_occupancy(), a.relief_occupancy()))
        b_vs_a_completed.append(safe_ratio(b.completed, a.completed))
        b_vs_a_miss.append(safe_ratio(b.deadline_miss_epochs, a.deadline_miss_epochs))
        b_vs_a_severe.append(safe_ratio(b.severe_miss_epochs, a.severe_miss_epochs))

        c_vs_b_relief.append(safe_ratio(c.relief_occupancy(), b.relief_occupancy()))
        c_vs_b_storage.append(safe_ratio(c.storage_occupancy(), b.storage_occupancy()))
        c_vs_b_completed.append(safe_ratio(c.completed, b.completed))
        c_vs_b_seconds.append(
            safe_ratio(c.seconds_per_completion(), b.seconds_per_completion())
        )
        c_vs_b_miss.append(safe_ratio(c.deadline_miss_epochs, b.deadline_miss_epochs))
        c_vs_b_severe.append(safe_ratio(c.severe_miss_epochs, b.severe_miss_epochs))

        print(
            f"seed={seed} "
            f"A_miss={row_a['miss']:.3f} A_relief={a.relief_occupancy():.3f} "
            f"B_miss={row_b['miss']:.3f} B_relief={b.relief_occupancy():.3f} "
            f"C_miss={row_c['miss']:.3f} C_relief={c.relief_occupancy():.3f} "
            f"B_vs_A_completed={b_vs_a_completed[-1]:.3f} "
            f"B_vs_A_miss={b_vs_a_miss[-1]:.3f} "
            f"C_vs_B_completed={c_vs_b_completed[-1]:.3f} "
            f"C_vs_B_miss={c_vs_b_miss[-1]:.3f} "
            f"A_transitions={controller_a.protective_transitions} "
            f"B_transitions={controller_b.protective_transitions} "
            f"C_transitions={controller_c.protective_transitions}"
        )

    promotable_a = summarize("A_full_v019", rows_a, stats_a, transitions_a)
    promotable_b = summarize("B_no_reserve_v020", rows_b, stats_b, transitions_b)
    promotable_c = summarize("C_pain_only", rows_c, stats_c, transitions_c)

    median_b_a_relief = median(b_vs_a_relief)
    median_b_a_completed = median(b_vs_a_completed)
    reserve_self_lock = (
        median_b_a_relief <= (1.0 - MIN_OCCUPANCY_REDUCTION)
        and median_b_a_completed >= MIN_COMPLETED_PRESERVATION
    )

    median_c_b_relief = median(c_vs_b_relief)
    median_c_b_miss = median(c_vs_b_miss)
    median_c_b_severe = median(c_vs_b_severe)
    trajectory_protective = (
        (
            median_c_b_miss > MAX_TRAJECTORY_ABLATION_MISS
            or median_c_b_severe > MAX_TRAJECTORY_ABLATION_MISS
        )
        and median_c_b_relief > (1.0 - MIN_OCCUPANCY_REDUCTION)
    )

    trajectory_redundant = (
        median(c_vs_b_completed) >= MIN_COMPLETED_PRESERVATION
        and median(c_vs_b_seconds) <= MAX_REDUNDANT_SECONDS
        and median_c_b_miss <= MAX_REDUNDANT_MISS
        and median_c_b_severe <= MAX_REDUNDANT_MISS
        and median_c_b_relief <= 1.0
        and median(c_vs_b_storage) <= 1.0
        and median(row.terminal_backlog for row in stats_c) == 0
        and sum(row.digest_mismatches for row in stats_c) == 0
    )

    promoted = [
        name
        for name, value in (
            ("A", promotable_a),
            ("B", promotable_b),
            ("C", promotable_c),
        )
        if value
    ]

    print("\n[causal_ablation]")
    print(
        f"median_B_vs_A_relief={median_b_a_relief:.3f} "
        f"median_B_vs_A_completed={median_b_a_completed:.3f} "
        f"median_B_vs_A_miss={median(b_vs_a_miss):.3f} "
        f"median_B_vs_A_severe={median(b_vs_a_severe):.3f}"
    )
    print(f"reserve_self_locking_recovery_veto={str(reserve_self_lock).lower()}")
    print(
        f"median_C_vs_B_relief={median_c_b_relief:.3f} "
        f"median_C_vs_B_storage={median(c_vs_b_storage):.3f} "
        f"median_C_vs_B_completed={median(c_vs_b_completed):.3f} "
        f"median_C_vs_B_seconds={median(c_vs_b_seconds):.3f} "
        f"median_C_vs_B_miss={median_c_b_miss:.3f} "
        f"median_C_vs_B_severe={median_c_b_severe:.3f}"
    )
    print(f"trajectory_has_protective_recovery_value={str(trajectory_protective).lower()}")
    print(f"trajectory_redundant_for_recovery={str(trajectory_redundant).lower()}")
    print(f"promotable_candidates={','.join(promoted) if promoted else 'none'}")
    print("ablation_complete=true")
    print(
        "interpretation=v0.21 isolates the recovery roles of RESERVE and TRAJECTORY "
        "under frozen entry semantics, thresholds, actuators, and an independent "
        "external outcome vector. No candidate is promoted from a scalar win alone."
    )


if __name__ == "__main__":
    main()
