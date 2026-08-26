from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median

from event_aligned_trajectory_v041 import (
    SEED_NUMERIC_KEYS as BASE_SEED_NUMERIC_KEYS,
    TraceRun,
    make_pair,
    run_policy,
)
from incremental_rate_weaning_v037 import IncrementalRateWeaningMembrane
from rate_first_recovery_v028 import RateFirstRecoveryMembrane
from real_work_queue_transfer import build_epochs, calibrate_rounds

# Fresh family frozen in issue #37 before implementation/results.
SEEDS = (
    25_100_991,
    25_200_997,
    25_301_003,
    25_401_009,
    25_501_017,
    25_601_021,
    25_701_027,
    25_801_033,
)
PAIRED_REPETITIONS = 4
MIN_SIGN_AGREEMENT = 6

PROTECTED_SOURCES = (
    "INITIAL_PROTECTION",
    "POST_RATE_INTERMEDIATE_FAILURE",
    "POST_RATE_SEVERE_FAILURE",
    "POST_RELIEF_INTERMEDIATE_FAILURE",
    "POST_RELIEF_SEVERE_FAILURE",
    "POST_SUCCESS_REENTRY",
)


@dataclass(slots=True)
class EventAnalysis:
    rate_healthy_success: int
    rate_healthy_progress: int
    rate_intermediate_failures: int
    rate_intermediate_holds: int
    rate_severe_failures: int
    rate_severe_rollbacks: int
    rate_reached_relief: int

    relief_healthy_success: int
    relief_intermediate_failures: int
    relief_severe_failures: int

    protected_sources: Counter[str]
    protected_partition_residual: int
    failure_taxonomy_residual: int
    impossible_transitions: int

    first_rate_failure_epoch: int
    first_rate_failure_evidence: str

    exit_epoch: int
    exit_backlog: int
    first_normal_backlog_epoch: int
    first_base_epoch: int
    normal_backlog_epochs_after_exit: int
    exit_to_base_duration: int


def analyse_trace(run: TraceRun, *, policy: str) -> EventAnalysis:
    if policy not in {"binary", "incremental"}:
        raise ValueError(f"unknown policy: {policy}")

    rate_healthy_success = 0
    rate_healthy_progress = 0
    rate_intermediate_failures = 0
    rate_intermediate_holds = 0
    rate_severe_failures = 0
    rate_severe_rollbacks = 0
    rate_reached_relief = 0

    relief_healthy_success = 0
    relief_intermediate_failures = 0
    relief_severe_failures = 0

    protected_sources: Counter[str] = Counter({key: 0 for key in PROTECTED_SOURCES})
    current_source = "INITIAL_PROTECTION"
    seen_protection = False
    impossible_transitions = 0
    first_rate_failure_epoch = -1
    first_rate_failure_evidence = "NONE"

    exit_epoch = -1
    exit_backlog = -1

    for row in run.trace:
        if row.command_stage == "PROTECTED":
            if row.before_stage == "NORMAL":
                current_source = (
                    "POST_SUCCESS_REENTRY"
                    if seen_protection
                    else "INITIAL_PROTECTION"
                )
            protected_sources[current_source] += 1
            seen_protection = True

        if row.command_stage == "RATE":
            if policy == "binary":
                if row.evidence_class == "HEALTHY" and row.after_stage == "RELIEF":
                    rate_healthy_success += 1
                elif (
                    row.evidence_class == "INTERMEDIATE"
                    and row.after_stage == "PROTECTED"
                ):
                    rate_intermediate_failures += 1
                    current_source = "POST_RATE_INTERMEDIATE_FAILURE"
                    if first_rate_failure_epoch < 0:
                        first_rate_failure_epoch = row.epoch_index
                        first_rate_failure_evidence = "INTERMEDIATE"
                elif (
                    row.evidence_class == "SEVERE"
                    and row.after_stage == "PROTECTED"
                ):
                    rate_severe_failures += 1
                    current_source = "POST_RATE_SEVERE_FAILURE"
                    if first_rate_failure_epoch < 0:
                        first_rate_failure_epoch = row.epoch_index
                        first_rate_failure_evidence = "SEVERE"
                else:
                    impossible_transitions += 1
            else:
                if row.evidence_class == "HEALTHY" and row.after_stage == "RATE":
                    rate_healthy_progress += 1
                elif row.evidence_class == "HEALTHY" and row.after_stage == "RELIEF":
                    rate_reached_relief += 1
                elif (
                    row.evidence_class == "INTERMEDIATE"
                    and row.after_stage == "RATE"
                ):
                    rate_intermediate_holds += 1
                elif (
                    row.evidence_class == "SEVERE"
                    and row.after_stage == "PROTECTED"
                ):
                    rate_severe_rollbacks += 1
                    current_source = "POST_RATE_SEVERE_FAILURE"
                    if first_rate_failure_epoch < 0:
                        first_rate_failure_epoch = row.epoch_index
                        first_rate_failure_evidence = "SEVERE"
                else:
                    impossible_transitions += 1

        if row.command_stage == "RELIEF":
            if row.evidence_class == "HEALTHY" and row.after_stage == "NORMAL":
                relief_healthy_success += 1
                if exit_epoch < 0:
                    exit_epoch = row.epoch_index
                    exit_backlog = row.after_buffered
            elif (
                row.evidence_class == "INTERMEDIATE"
                and row.after_stage == "PROTECTED"
            ):
                relief_intermediate_failures += 1
                current_source = "POST_RELIEF_INTERMEDIATE_FAILURE"
            elif (
                row.evidence_class == "SEVERE"
                and row.after_stage == "PROTECTED"
            ):
                relief_severe_failures += 1
                current_source = "POST_RELIEF_SEVERE_FAILURE"
            else:
                impossible_transitions += 1

    protected_partition_residual = (
        int(run.stage_counts["PROTECTED"])
        - sum(protected_sources[source] for source in PROTECTED_SOURCES)
    )

    if policy == "binary":
        classified_failures = (
            rate_intermediate_failures
            + rate_severe_failures
            + relief_intermediate_failures
            + relief_severe_failures
        )
    else:
        classified_failures = (
            rate_severe_rollbacks
            + relief_intermediate_failures
            + relief_severe_failures
        )
    failure_taxonomy_residual = int(run.failure_count) - classified_failures

    first_normal_backlog_epoch = -1
    first_base_epoch = -1
    normal_backlog_epochs_after_exit = 0
    if exit_epoch >= 0:
        for row in run.trace:
            if row.epoch_index > exit_epoch and row.elastic_reason == "NORMAL_BACKLOG":
                normal_backlog_epochs_after_exit += 1
                if first_normal_backlog_epoch < 0:
                    first_normal_backlog_epoch = row.epoch_index
            if row.epoch_index >= exit_epoch and row.elastic_reason == "BASE":
                if first_base_epoch < 0:
                    first_base_epoch = row.epoch_index

    exit_to_base_duration = (
        first_base_epoch - exit_epoch
        if exit_epoch >= 0 and first_base_epoch >= 0
        else -1
    )

    return EventAnalysis(
        rate_healthy_success=rate_healthy_success,
        rate_healthy_progress=rate_healthy_progress,
        rate_intermediate_failures=rate_intermediate_failures,
        rate_intermediate_holds=rate_intermediate_holds,
        rate_severe_failures=rate_severe_failures,
        rate_severe_rollbacks=rate_severe_rollbacks,
        rate_reached_relief=rate_reached_relief,
        relief_healthy_success=relief_healthy_success,
        relief_intermediate_failures=relief_intermediate_failures,
        relief_severe_failures=relief_severe_failures,
        protected_sources=protected_sources,
        protected_partition_residual=protected_partition_residual,
        failure_taxonomy_residual=failure_taxonomy_residual,
        impossible_transitions=impossible_transitions,
        first_rate_failure_epoch=first_rate_failure_epoch,
        first_rate_failure_evidence=first_rate_failure_evidence,
        exit_epoch=exit_epoch,
        exit_backlog=exit_backlog,
        first_normal_backlog_epoch=first_normal_backlog_epoch,
        first_base_epoch=first_base_epoch,
        normal_backlog_epochs_after_exit=normal_backlog_epochs_after_exit,
        exit_to_base_duration=exit_to_base_duration,
    )


def failure_storage_relation(first_failure: int, first_storage: int) -> int:
    if first_failure < 0:
        return 3  # no binary RATE failure
    if first_storage < 0:
        return 4  # no storage mismatch
    if first_failure < first_storage:
        return 0
    if first_failure == first_storage:
        return 1
    return 2


def extend_pair(
    *,
    seed: int,
    repetition: int,
    order: str,
    binary: TraceRun,
    incremental: TraceRun,
) -> tuple[
    dict[str, float | int | str],
    Counter[str],
    Counter[str],
    EventAnalysis,
    EventAnalysis,
]:
    row, stage_pairs, reason_pairs = make_pair(
        seed=seed,
        repetition=repetition,
        order=order,
        binary=binary,
        incremental=incremental,
    )
    b = analyse_trace(binary, policy="binary")
    i = analyse_trace(incremental, policy="incremental")

    exits_observed = int(b.exit_epoch >= 0 and i.exit_epoch >= 0)
    bases_observed = int(
        exits_observed
        and b.exit_to_base_duration >= 0
        and i.exit_to_base_duration >= 0
    )

    row.update(
        {
            "binary_rate_healthy_success": b.rate_healthy_success,
            "binary_rate_intermediate_failures": b.rate_intermediate_failures,
            "binary_rate_severe_failures": b.rate_severe_failures,
            "incremental_rate_healthy_progress": i.rate_healthy_progress,
            "incremental_rate_intermediate_holds": i.rate_intermediate_holds,
            "incremental_rate_severe_rollbacks": i.rate_severe_rollbacks,
            "incremental_rate_reached_relief": i.rate_reached_relief,
            "binary_relief_healthy_success": b.relief_healthy_success,
            "binary_relief_intermediate_failures": b.relief_intermediate_failures,
            "binary_relief_severe_failures": b.relief_severe_failures,
            "incremental_relief_healthy_success": i.relief_healthy_success,
            "incremental_relief_intermediate_failures": i.relief_intermediate_failures,
            "incremental_relief_severe_failures": i.relief_severe_failures,
            "binary_protected_partition_residual": b.protected_partition_residual,
            "incremental_protected_partition_residual": i.protected_partition_residual,
            "binary_failure_taxonomy_residual": b.failure_taxonomy_residual,
            "incremental_failure_taxonomy_residual": i.failure_taxonomy_residual,
            "impossible_challenge_transitions": (
                b.impossible_transitions + i.impossible_transitions
            ),
            "first_binary_rate_failure": b.first_rate_failure_epoch,
            "first_binary_rate_failure_evidence": b.first_rate_failure_evidence,
            "binary_failure_storage_relation": failure_storage_relation(
                b.first_rate_failure_epoch,
                int(row["first_storage_mismatch"]),
            ),
            "binary_exit_epoch": b.exit_epoch,
            "incremental_exit_epoch": i.exit_epoch,
            "binary_exit_backlog": b.exit_backlog,
            "incremental_exit_backlog": i.exit_backlog,
            "exit_pair_observed": exits_observed,
            "exit_backlog_delta": (
                i.exit_backlog - b.exit_backlog if exits_observed else 0
            ),
            "binary_first_normal_backlog": b.first_normal_backlog_epoch,
            "incremental_first_normal_backlog": i.first_normal_backlog_epoch,
            "binary_normal_backlog_after_exit": (
                b.normal_backlog_epochs_after_exit
            ),
            "incremental_normal_backlog_after_exit": (
                i.normal_backlog_epochs_after_exit
            ),
            "binary_exit_to_base": b.exit_to_base_duration,
            "incremental_exit_to_base": i.exit_to_base_duration,
            "base_pair_observed": bases_observed,
            "exit_to_base_delta": (
                i.exit_to_base_duration - b.exit_to_base_duration
                if bases_observed
                else 0
            ),
        }
    )

    for source in PROTECTED_SOURCES:
        suffix = source.lower()
        row[f"binary_protected_{suffix}"] = b.protected_sources[source]
        row[f"incremental_protected_{suffix}"] = i.protected_sources[source]

    return row, stage_pairs, reason_pairs, b, i


NEW_SEED_NUMERIC_KEYS = (
    "binary_rate_healthy_success",
    "binary_rate_intermediate_failures",
    "binary_rate_severe_failures",
    "incremental_rate_healthy_progress",
    "incremental_rate_intermediate_holds",
    "incremental_rate_severe_rollbacks",
    "incremental_rate_reached_relief",
    "binary_relief_healthy_success",
    "binary_relief_intermediate_failures",
    "binary_relief_severe_failures",
    "incremental_relief_healthy_success",
    "incremental_relief_intermediate_failures",
    "incremental_relief_severe_failures",
    "binary_exit_backlog",
    "incremental_exit_backlog",
    "exit_backlog_delta",
    "binary_normal_backlog_after_exit",
    "incremental_normal_backlog_after_exit",
    "binary_exit_to_base",
    "incremental_exit_to_base",
    "exit_to_base_delta",
) + tuple(
    f"{policy}_protected_{source.lower()}"
    for policy in ("binary", "incremental")
    for source in PROTECTED_SOURCES
)

SEED_NUMERIC_KEYS = BASE_SEED_NUMERIC_KEYS + NEW_SEED_NUMERIC_KEYS


def aggregate_seed(rows: list[dict[str, float | int | str]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in SEED_NUMERIC_KEYS:
        if key in {
            "binary_exit_backlog",
            "incremental_exit_backlog",
            "exit_backlog_delta",
        }:
            values = [
                float(row[key])
                for row in rows
                if int(row["exit_pair_observed"]) == 1
            ]
        elif key in {
            "binary_exit_to_base",
            "incremental_exit_to_base",
            "exit_to_base_delta",
        }:
            values = [
                float(row[key])
                for row in rows
                if int(row["base_pair_observed"]) == 1
            ]
        else:
            values = [float(row[key]) for row in rows]
        result[key] = float(median(values)) if values else 0.0
    return result


def med(rows: list[dict[str, float | int | str]] | list[dict[str, float]], key: str) -> float:
    return float(median(float(row[key]) for row in rows))


def med_pair_rows(
    rows: list[dict[str, float | int | str]],
    key: str,
) -> float:
    if key == "exit_backlog_delta":
        values = [
            float(row[key])
            for row in rows
            if int(row["exit_pair_observed"]) == 1
        ]
    else:
        values = [float(row[key]) for row in rows]
    return float(median(values)) if values else 0.0


def median_or_minus_one(values) -> float:
    data = [float(value) for value in values]
    return float(median(data)) if data else -1.0


def sign(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=evidence_predicate_exit_backlog_handoff_v0.42")
    print("controllers=binary_v028_vs_incremental_v037_unchanged")
    print("fresh_seed_family=true")
    print("policy_promotion=false")
    print("controller_changes=false")
    print("failure_predicate_changes=false")
    print("controllers_phase_blind=true")
    print("phase_labels=evaluator_only")
    print("instrumentation_only=true")
    print(f"paired_repetitions={PAIRED_REPETITIONS}")
    print(f"MIN_SIGN_AGREEMENT={MIN_SIGN_AGREEMENT}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    all_pairs: list[dict[str, float | int | str]] = []
    pairs_by_seed: dict[int, list[dict[str, float | int | str]]] = defaultdict(list)
    analyses_by_policy: dict[str, list[EventAnalysis]] = {
        "binary": [],
        "incremental": [],
    }
    stage_mismatch_pairs: Counter[str] = Counter()
    reason_mismatch_pairs: Counter[str] = Counter()

    for seed in SEEDS:
        epochs = build_epochs(seed)
        for repetition in range(PAIRED_REPETITIONS):
            binary_first = (seed + repetition) % 2 == 0
            policies = (
                ("binary", "incremental")
                if binary_first
                else ("incremental", "binary")
            )
            current: dict[str, TraceRun] = {}
            for policy in policies:
                controller = (
                    RateFirstRecoveryMembrane()
                    if policy == "binary"
                    else IncrementalRateWeaningMembrane()
                )
                current[policy] = run_policy(
                    epochs,
                    policy=policy,
                    controller=controller,
                    rounds=rounds,
                    deadline_seconds=deadline_seconds,
                )

            order = "BINARY_FIRST" if binary_first else "INCREMENTAL_FIRST"
            row, stage_pairs, reason_pairs, b_analysis, i_analysis = extend_pair(
                seed=seed,
                repetition=repetition,
                order=order,
                binary=current["binary"],
                incremental=current["incremental"],
            )
            all_pairs.append(row)
            pairs_by_seed[seed].append(row)
            analyses_by_policy["binary"].append(b_analysis)
            analyses_by_policy["incremental"].append(i_analysis)
            stage_mismatch_pairs.update(stage_pairs)
            reason_mismatch_pairs.update(reason_pairs)

            print(
                f"pair seed={seed} repetition={repetition} order={order} "
                f"elastic_delta={int(row['elastic_epoch_delta'])} "
                f"support_delta={int(row['support_reason_delta'])} "
                f"backlog_delta={int(row['backlog_reason_delta'])} "
                f"binary_rate_intermediate="
                f"{int(row['binary_rate_intermediate_failures'])} "
                f"binary_rate_severe={int(row['binary_rate_severe_failures'])} "
                f"incremental_intermediate_holds="
                f"{int(row['incremental_rate_intermediate_holds'])} "
                f"incremental_severe_rollbacks="
                f"{int(row['incremental_rate_severe_rollbacks'])} "
                f"binary_exit_backlog={int(row['binary_exit_backlog'])} "
                f"incremental_exit_backlog={int(row['incremental_exit_backlog'])} "
                f"first_binary_failure={int(row['first_binary_rate_failure'])} "
                f"failure_evidence={row['first_binary_rate_failure_evidence']} "
                f"first_storage={int(row['first_storage_mismatch'])}"
            )

    seed_rows = [aggregate_seed(pairs_by_seed[seed]) for seed in SEEDS]

    elastic_positive_seeds = sum(
        row["elastic_epoch_delta"] > 0.0 for row in seed_rows
    )
    elastic_negative_seeds = sum(
        row["elastic_epoch_delta"] < 0.0 for row in seed_rows
    )
    intermediate_positive_seeds = sum(
        row["binary_rate_intermediate_failures"] > 0.0 for row in seed_rows
    )
    severe_positive_seeds = sum(
        row["binary_rate_severe_failures"] > 0.0 for row in seed_rows
    )
    intermediate_dominant_seeds = sum(
        row["binary_rate_intermediate_failures"]
        > row["binary_rate_severe_failures"]
        for row in seed_rows
    )
    severe_dominant_seeds = sum(
        row["binary_rate_severe_failures"]
        > row["binary_rate_intermediate_failures"]
        for row in seed_rows
    )
    failure_present_seeds = sum(
        row["binary_rate_intermediate_failures"]
        + row["binary_rate_severe_failures"]
        > 0.0
        for row in seed_rows
    )

    terminal_backlog_violations = sum(
        int(row["terminal_backlog_violations"]) for row in all_pairs
    )
    digest_mismatches = sum(int(row["digest_mismatches"]) for row in all_pairs)
    trace_structure_mismatches = sum(
        int(row["trace_structure_mismatches"]) for row in all_pairs
    )
    max_elastic_residual = max(
        abs(float(row["elastic_accounting_residual"])) for row in all_pairs
    )
    max_protected_partition_residual = max(
        max(
            abs(int(row["binary_protected_partition_residual"])),
            abs(int(row["incremental_protected_partition_residual"])),
        )
        for row in all_pairs
    )
    max_failure_taxonomy_residual = max(
        max(
            abs(int(row["binary_failure_taxonomy_residual"])),
            abs(int(row["incremental_failure_taxonomy_residual"])),
        )
        for row in all_pairs
    )
    impossible_challenge_transitions = sum(
        int(row["impossible_challenge_transitions"]) for row in all_pairs
    )
    missing_exit_pairs = sum(
        int(row["exit_pair_observed"]) == 0 for row in all_pairs
    )
    missing_base_pairs = sum(
        int(row["base_pair_observed"]) == 0 for row in all_pairs
    )

    integrity_ok = (
        terminal_backlog_violations == 0
        and digest_mismatches == 0
        and trace_structure_mismatches == 0
        and max_elastic_residual == 0.0
        and max_protected_partition_residual == 0
        and max_failure_taxonomy_residual == 0
        and impossible_challenge_transitions == 0
    )

    median_elastic = med(seed_rows, "elastic_epoch_delta")
    median_support = med(seed_rows, "support_reason_delta")
    median_backlog = med(seed_rows, "backlog_reason_delta")
    median_intermediate_failures = med(
        seed_rows,
        "binary_rate_intermediate_failures",
    )
    median_severe_failures = med(seed_rows, "binary_rate_severe_failures")

    stable_direction = (
        median_elastic > 0.0 and elastic_positive_seeds >= MIN_SIGN_AGREEMENT
    ) or (
        median_elastic < 0.0 and elastic_negative_seeds >= MIN_SIGN_AGREEMENT
    )

    if (
        integrity_ok
        and median_intermediate_failures > 0.0
        and intermediate_positive_seeds >= MIN_SIGN_AGREEMENT
        and median_intermediate_failures > median_severe_failures
        and intermediate_dominant_seeds >= MIN_SIGN_AGREEMENT
    ):
        failure_origin = "intermediate_rate_failure_origin"
    elif (
        integrity_ok
        and median_severe_failures > 0.0
        and severe_positive_seeds >= MIN_SIGN_AGREEMENT
        and median_severe_failures > median_intermediate_failures
        and severe_dominant_seeds >= MIN_SIGN_AGREEMENT
    ):
        failure_origin = "severe_rate_failure_origin"
    elif integrity_ok and failure_present_seeds >= MIN_SIGN_AGREEMENT:
        failure_origin = "mixed_rate_failure_origin"
    else:
        failure_origin = "no_stable_rate_failure_origin"

    if stable_direction and integrity_ok:
        support_abs = abs(median_support)
        backlog_abs = abs(median_backlog)
        half_total = 0.5 * abs(median_elastic)
        if support_abs >= half_total and support_abs > backlog_abs:
            handoff_class = "support_handoff"
        elif backlog_abs >= half_total and backlog_abs > support_abs:
            handoff_class = "backlog_handoff"
        else:
            handoff_class = "mixed_handoff"
    else:
        handoff_class = "no_stable_handoff"

    order_rows = {
        order: [row for row in all_pairs if row["order"] == order]
        for order in ("BINARY_FIRST", "INCREMENTAL_FIRST")
    }
    order_sign_disagreement = any(
        sign(med_pair_rows(order_rows["BINARY_FIRST"], key))
        * sign(med_pair_rows(order_rows["INCREMENTAL_FIRST"], key))
        < 0
        for key in (
            "elastic_epoch_delta",
            "support_reason_delta",
            "backlog_reason_delta",
            "lost_delta",
            "exit_backlog_delta",
        )
    )

    relation_counts: Counter[int] = Counter(
        int(row["binary_failure_storage_relation"]) for row in all_pairs
    )
    first_failure_evidence_counts: Counter[str] = Counter(
        str(row["first_binary_rate_failure_evidence"]) for row in all_pairs
    )

    print("\n[failure_handoff]")
    print(f"paired_runs={len(all_pairs)}")
    print(f"seed_summaries={len(seed_rows)}")
    for key in SEED_NUMERIC_KEYS:
        print(f"median_seed_{key}={med(seed_rows, key):.6f}")

    print(f"elastic_positive_seeds={elastic_positive_seeds}/{len(SEEDS)}")
    print(f"elastic_negative_seeds={elastic_negative_seeds}/{len(SEEDS)}")
    print(
        f"binary_intermediate_failure_positive_seeds="
        f"{intermediate_positive_seeds}/{len(SEEDS)}"
    )
    print(
        f"binary_severe_failure_positive_seeds="
        f"{severe_positive_seeds}/{len(SEEDS)}"
    )
    print(
        f"binary_intermediate_dominant_seeds="
        f"{intermediate_dominant_seeds}/{len(SEEDS)}"
    )
    print(
        f"binary_severe_dominant_seeds="
        f"{severe_dominant_seeds}/{len(SEEDS)}"
    )
    print(f"binary_rate_failure_present_seeds={failure_present_seeds}/{len(SEEDS)}")

    for policy in ("binary", "incremental"):
        analyses = analyses_by_policy[policy]
        print(
            f"policy={policy} "
            f"median_rate_healthy_success="
            f"{median(a.rate_healthy_success for a in analyses):.3f} "
            f"median_rate_healthy_progress="
            f"{median(a.rate_healthy_progress for a in analyses):.3f} "
            f"median_rate_intermediate_failures="
            f"{median(a.rate_intermediate_failures for a in analyses):.3f} "
            f"median_rate_intermediate_holds="
            f"{median(a.rate_intermediate_holds for a in analyses):.3f} "
            f"median_rate_severe_failures="
            f"{median(a.rate_severe_failures for a in analyses):.3f} "
            f"median_rate_severe_rollbacks="
            f"{median(a.rate_severe_rollbacks for a in analyses):.3f} "
            f"median_rate_reached_relief="
            f"{median(a.rate_reached_relief for a in analyses):.3f}"
        )
        print(
            f"policy={policy} exit "
            f"median_exit_epoch="
            f"{median_or_minus_one(a.exit_epoch for a in analyses if a.exit_epoch >= 0):.3f} "
            f"median_exit_backlog="
            f"{median_or_minus_one(a.exit_backlog for a in analyses if a.exit_backlog >= 0):.3f} "
            f"median_normal_backlog_after_exit="
            f"{median(a.normal_backlog_epochs_after_exit for a in analyses):.3f} "
            f"median_exit_to_base="
            f"{median_or_minus_one(a.exit_to_base_duration for a in analyses if a.exit_to_base_duration >= 0):.3f}"
        )
        print(
            f"policy={policy} protected_sources "
            + " ".join(
                f"{source}="
                f"{median(a.protected_sources[source] for a in analyses):.3f}"
                for source in PROTECTED_SOURCES
            )
        )

    print(
        f"first_binary_failure_before_storage_pairs={relation_counts[0]}/{len(all_pairs)}"
    )
    print(
        f"first_binary_failure_at_storage_pairs={relation_counts[1]}/{len(all_pairs)}"
    )
    print(
        f"first_binary_failure_after_storage_pairs={relation_counts[2]}/{len(all_pairs)}"
    )
    print(f"no_binary_rate_failure_pairs={relation_counts[3]}/{len(all_pairs)}")
    print(f"no_storage_mismatch_pairs={relation_counts[4]}/{len(all_pairs)}")
    for evidence in ("HEALTHY", "INTERMEDIATE", "SEVERE", "NONE"):
        print(
            f"first_binary_failure_evidence_{evidence}="
            f"{first_failure_evidence_counts[evidence]}/{len(all_pairs)}"
        )

    if stage_mismatch_pairs:
        stage_pair, stage_count = stage_mismatch_pairs.most_common(1)[0]
    else:
        stage_pair, stage_count = "NONE", 0
    if reason_mismatch_pairs:
        reason_pair, reason_count = reason_mismatch_pairs.most_common(1)[0]
    else:
        reason_pair, reason_count = "NONE", 0
    print(f"top_stage_mismatch_pair={stage_pair} count={stage_count}")
    print(f"top_reason_mismatch_pair={reason_pair} count={reason_count}")

    for order, rows in order_rows.items():
        print(
            f"order={order} n={len(rows)} "
            f"median_elastic_delta="
            f"{med_pair_rows(rows, 'elastic_epoch_delta'):.3f} "
            f"median_support_delta="
            f"{med_pair_rows(rows, 'support_reason_delta'):.3f} "
            f"median_backlog_delta="
            f"{med_pair_rows(rows, 'backlog_reason_delta'):.3f} "
            f"median_lost_delta={med_pair_rows(rows, 'lost_delta'):.3f} "
            f"median_exit_backlog_delta="
            f"{med_pair_rows(rows, 'exit_backlog_delta'):.3f}"
        )

    print(f"missing_exit_pairs={missing_exit_pairs}")
    print(f"missing_base_pairs={missing_base_pairs}")
    print(f"terminal_backlog_violations={terminal_backlog_violations}")
    print(f"digest_mismatches={digest_mismatches}")
    print(f"trace_structure_mismatches={trace_structure_mismatches}")
    print(f"max_elastic_accounting_residual={max_elastic_residual:.6f}")
    print(
        f"max_protected_partition_residual="
        f"{max_protected_partition_residual}"
    )
    print(f"max_failure_taxonomy_residual={max_failure_taxonomy_residual}")
    print(
        f"impossible_challenge_transitions="
        f"{impossible_challenge_transitions}"
    )
    print(f"integrity_ok={str(integrity_ok).lower()}")
    print(f"stable_elastic_direction={str(stable_direction).lower()}")
    print(f"failure_origin={failure_origin}")
    print(f"handoff_class={handoff_class}")
    print(f"local_classification={failure_origin}__{handoff_class}")
    print(f"order_sign_disagreement={str(order_sign_disagreement).lower()}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=requires_cross_runtime_interpretation")
    print(
        "interpretation=v0.42 classifies unchanged RATE challenge outcomes by "
        "evidence predicate, exactly partitions PROTECTED occupancy by failure "
        "source, and measures the exit-to-backlog handoff."
    )


if __name__ == "__main__":
    main()
