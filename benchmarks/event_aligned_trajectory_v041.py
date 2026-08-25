from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from bardocompute.exchange import ExchangeResult
from computational_interoception_v019 import HEALTHY_PAIN
from continuous_miss_burden_v026 import MISS_THRESHOLD, SEVERE_MISS_THRESHOLD
from cost_mediation_v039 import CostStats, safe_ratio
from incremental_rate_weaning_v037 import IncrementalRateWeaningMembrane
from rate_first_recovery_v028 import RateFirstRecoveryMembrane
from real_work_queue_transfer import (
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)
from storage_reserve import ELASTIC_BUFFER_LIMIT

# Fresh family frozen in issue #36 before implementation/results.
SEEDS = (
    24_100_929,
    24_200_933,
    24_300_941,
    24_400_949,
    24_500_957,
    24_600_967,
    24_700_973,
    24_800_981,
)
PAIRED_REPETITIONS = 4
MIN_SIGN_AGREEMENT = 6

STAGES = ("NORMAL", "PROTECTED", "RATE", "RELIEF")
ELASTIC_REASONS = (
    "SUPPORT_PROTECTED",
    "SUPPORT_RATE",
    "RELIEF_BACKLOG",
    "NORMAL_BACKLOG",
)


@dataclass(frozen=True, slots=True)
class EpochTrace:
    epoch_index: int
    phase: str
    incoming: int

    before_protective: bool
    before_stage: str
    before_resolution: int
    before_step_resolution: int
    before_weaning_limit: int
    before_pain: float
    before_reserve: float
    before_trajectory: float
    before_buffered: int

    command_protective: bool
    command_stage: str
    release_limit: int
    buffer_limit: int
    elastic_storage_active: bool
    elastic_reason: str

    released: int
    delivered: int
    miss_fraction: float
    evidence_class: str

    after_protective: bool
    after_stage: str
    after_resolution: int
    after_step_resolution: int
    after_pain: float
    after_reserve: float
    after_trajectory: float
    after_buffered: int


@dataclass(slots=True)
class TraceRun:
    stats: CostStats
    trace: list[EpochTrace]
    stage_counts: Counter[str]
    reason_counts: Counter[str]
    first_protection_entry: int
    first_rate_stage: int
    first_relief_stage: int
    first_successful_exit: int
    first_post_success_reentry: int
    first_base_after_protection: int
    protection_episodes: int
    failure_count: int
    relief_failure_count: int
    post_success_reentries: int

    def elastic_epochs(self) -> int:
        return sum(self.reason_counts[reason] for reason in ELASTIC_REASONS)

    def support_epochs(self) -> int:
        return (
            self.reason_counts["SUPPORT_PROTECTED"]
            + self.reason_counts["SUPPORT_RATE"]
        )

    def backlog_elastic_epochs(self) -> int:
        return (
            self.reason_counts["RELIEF_BACKLOG"]
            + self.reason_counts["NORMAL_BACKLOG"]
        )


def normalized_stage(controller) -> str:
    stage = int(getattr(controller, "withdrawal_stage", 0))
    protective = bool(getattr(controller, "protective", False))
    if not protective and stage == 0:
        return "NORMAL"
    if stage == 0:
        return "PROTECTED"
    if stage == 1:
        return "RATE"
    if stage == 2:
        return "RELIEF"
    raise AssertionError(f"unknown withdrawal stage: {stage}")


def elastic_reason(stage: str, buffer_limit: int) -> str:
    if buffer_limit != ELASTIC_BUFFER_LIMIT:
        return "BASE"
    if stage == "PROTECTED":
        return "SUPPORT_PROTECTED"
    if stage == "RATE":
        return "SUPPORT_RATE"
    if stage == "RELIEF":
        return "RELIEF_BACKLOG"
    return "NORMAL_BACKLOG"


def first_epoch(trace: list[EpochTrace], predicate) -> int:
    for row in trace:
        if predicate(row):
            return row.epoch_index
    return -1


def build_run_summary(
    *,
    policy: str,
    controller,
    stats: CostStats,
    trace: list[EpochTrace],
) -> TraceRun:
    stage_counts: Counter[str] = Counter(row.command_stage for row in trace)
    reason_counts: Counter[str] = Counter(row.elastic_reason for row in trace)

    protection_entries = [
        row.epoch_index
        for row in trace
        if row.before_stage == "NORMAL" and row.command_stage != "NORMAL"
    ]
    exit_epochs = [
        row.epoch_index
        for row in trace
        if row.command_stage != "NORMAL" and row.after_stage == "NORMAL"
    ]
    first_exit = exit_epochs[0] if exit_epochs else -1
    reentries = [epoch for epoch in protection_entries if first_exit >= 0 and epoch > first_exit]

    seen_protection = False
    first_base_after = -1
    for row in trace:
        if row.command_stage != "NORMAL":
            seen_protection = True
        if seen_protection and row.elastic_reason == "BASE":
            first_base_after = row.epoch_index
            break

    if policy == "binary":
        failure_count = int(getattr(controller, "rate_relaxed_failure", 0)) + int(
            getattr(controller, "relief_withdrawal_failure", 0)
        )
    else:
        failure_count = int(getattr(controller, "step_rollbacks", 0)) + int(
            getattr(controller, "relief_withdrawal_failure", 0)
        )

    return TraceRun(
        stats=stats,
        trace=trace,
        stage_counts=stage_counts,
        reason_counts=reason_counts,
        first_protection_entry=protection_entries[0] if protection_entries else -1,
        first_rate_stage=first_epoch(trace, lambda row: row.command_stage == "RATE"),
        first_relief_stage=first_epoch(trace, lambda row: row.command_stage == "RELIEF"),
        first_successful_exit=first_exit,
        first_post_success_reentry=reentries[0] if reentries else -1,
        first_base_after_protection=first_base_after,
        protection_episodes=len(protection_entries),
        failure_count=failure_count,
        relief_failure_count=int(getattr(controller, "relief_withdrawal_failure", 0)),
        post_success_reentries=int(getattr(controller, "post_success_reentries", 0)),
    )


def run_policy(
    epochs: tuple[EpochSpec, ...],
    *,
    policy: str,
    controller,
    rounds: int,
    deadline_seconds: float,
) -> TraceRun:
    stats = CostStats()
    trace: list[EpochTrace] = []
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

        for epoch_index, spec in enumerate(queue):
            if spec.phase == "drain" and backlog == 0:
                break

            stats.executed_epochs += 1
            stats.drain_epochs += int(spec.phase == "drain")

            before_protective = bool(getattr(controller, "protective", False))
            before_stage = normalized_stage(controller)
            before_resolution = int(getattr(controller, "resolution_strength", 0))
            before_step_resolution = int(getattr(controller, "step_resolution", 0))
            before_weaning_limit = int(getattr(controller, "weaning_limit", 0))
            before_pain = float(getattr(controller, "pain", 0.0))
            before_reserve = float(getattr(controller, "reserve", 1.0))
            before_trajectory = float(getattr(controller, "trajectory", 0.0))
            before_buffered = int(getattr(controller, "buffered", backlog))

            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.41 forbids voluntary admission shedding")
            command_stage = normalized_stage(controller)
            command_protective = bool(getattr(controller, "protective", False))
            reason = elastic_reason(command_stage, command.buffer_limit)

            stats.incoming += spec.incoming
            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            stats.lost += overflow
            backlog += admitted

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
            stats.wall_seconds += elapsed
            stats.completed += released
            stats.digest_mismatches += mismatches

            delivered = p_on + s_on + r_on
            missed = max(0, released - delivered)
            miss_fraction = missed / max(1, released)
            severe = released > 0 and miss_fraction >= SEVERE_MISS_THRESHOLD

            stats.missed_work_total += missed
            stats.released_work_total += released
            stats.severe_excess_total += max(
                0.0,
                miss_fraction - SEVERE_MISS_THRESHOLD,
            ) * released
            if released > 0:
                stats.deadline_miss_epochs += int(miss_fraction >= MISS_THRESHOLD)
                stats.severe_miss_epochs += int(severe)

            controller.observe(
                ExchangeResult(
                    admitted=admitted,
                    gate_rejected=0,
                    released=released,
                    primary_requested=primary_count,
                    secondary_requested=secondary_count,
                    primary_delivered=p_on,
                    secondary_delivered=s_on,
                    delivered=delivered,
                    congestion=missed,
                    buffered=backlog,
                    overflow_dropped=overflow,
                )
            )

            after_pain = float(getattr(controller, "pain", miss_fraction))
            if severe:
                evidence = "SEVERE"
            elif after_pain < HEALTHY_PAIN:
                evidence = "HEALTHY"
            else:
                evidence = "INTERMEDIATE"

            trace.append(
                EpochTrace(
                    epoch_index=epoch_index,
                    phase=spec.phase,
                    incoming=spec.incoming,
                    before_protective=before_protective,
                    before_stage=before_stage,
                    before_resolution=before_resolution,
                    before_step_resolution=before_step_resolution,
                    before_weaning_limit=before_weaning_limit,
                    before_pain=before_pain,
                    before_reserve=before_reserve,
                    before_trajectory=before_trajectory,
                    before_buffered=before_buffered,
                    command_protective=command_protective,
                    command_stage=command_stage,
                    release_limit=command.release_limit,
                    buffer_limit=command.buffer_limit,
                    elastic_storage_active=(
                        command.buffer_limit == ELASTIC_BUFFER_LIMIT
                    ),
                    elastic_reason=reason,
                    released=released,
                    delivered=delivered,
                    miss_fraction=miss_fraction,
                    evidence_class=evidence,
                    after_protective=bool(getattr(controller, "protective", False)),
                    after_stage=normalized_stage(controller),
                    after_resolution=int(
                        getattr(controller, "resolution_strength", 0)
                    ),
                    after_step_resolution=int(
                        getattr(controller, "step_resolution", 0)
                    ),
                    after_pain=after_pain,
                    after_reserve=float(getattr(controller, "reserve", 1.0)),
                    after_trajectory=float(
                        getattr(controller, "trajectory", 0.0)
                    ),
                    after_buffered=int(getattr(controller, "buffered", backlog)),
                )
            )

    stats.terminal_backlog = backlog
    return build_run_summary(
        policy=policy,
        controller=controller,
        stats=stats,
        trace=trace,
    )


def first_common_mismatches(
    binary: TraceRun,
    incremental: TraceRun,
) -> tuple[int, int, int, str, Counter[str], Counter[str], int, int]:
    b_by_epoch = {row.epoch_index: row for row in binary.trace}
    i_by_epoch = {row.epoch_index: row for row in incremental.trace}
    common = sorted(set(b_by_epoch) & set(i_by_epoch))

    first_evidence = -1
    first_stage = -1
    first_storage = -1
    first_storage_cell = "NONE"
    stage_pairs: Counter[str] = Counter()
    reason_pairs: Counter[str] = Counter()
    structure_mismatches = 0

    for epoch in common:
        b = b_by_epoch[epoch]
        i = i_by_epoch[epoch]
        if b.phase != i.phase or b.incoming != i.incoming:
            structure_mismatches += 1
        if first_evidence < 0 and b.evidence_class != i.evidence_class:
            first_evidence = epoch
        if first_stage < 0 and b.command_stage != i.command_stage:
            first_stage = epoch
        if b.elastic_storage_active != i.elastic_storage_active:
            cell = (
                f"B_{'ELASTIC' if b.elastic_storage_active else 'BASE'}__"
                f"I_{'ELASTIC' if i.elastic_storage_active else 'BASE'}"
            )
            stage_pair = f"B_{b.command_stage}__I_{i.command_stage}"
            reason_pair = f"B_{b.elastic_reason}__I_{i.elastic_reason}"
            stage_pairs[stage_pair] += 1
            reason_pairs[reason_pair] += 1
            if first_storage < 0:
                first_storage = epoch
                first_storage_cell = cell

    unmatched_epochs = sorted(set(b_by_epoch) ^ set(i_by_epoch))
    unpaired_tail_epochs = len(unmatched_epochs)
    for epoch in unmatched_epochs:
        row = b_by_epoch.get(epoch) or i_by_epoch.get(epoch)
        if row is not None and row.phase != "drain":
            structure_mismatches += 1

    if first_storage < 0:
        evidence_relation = 3  # no storage mismatch
    elif first_evidence < 0 or first_evidence > first_storage:
        evidence_relation = 2  # no evidence mismatch before storage
    elif first_evidence == first_storage:
        evidence_relation = 1  # evidence mismatch at storage mismatch
    else:
        evidence_relation = 0  # evidence mismatch before storage mismatch

    return (
        first_evidence,
        first_stage,
        first_storage,
        first_storage_cell,
        stage_pairs,
        reason_pairs,
        structure_mismatches,
        unpaired_tail_epochs,
        evidence_relation,
    )


def make_pair(
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
]:
    (
        first_evidence,
        first_stage,
        first_storage,
        first_storage_cell,
        stage_pairs,
        reason_pairs,
        structure_mismatches,
        unpaired_tail_epochs,
        evidence_relation,
    ) = first_common_mismatches(binary, incremental)

    protected_delta = (
        incremental.reason_counts["SUPPORT_PROTECTED"]
        - binary.reason_counts["SUPPORT_PROTECTED"]
    )
    rate_delta = (
        incremental.reason_counts["SUPPORT_RATE"]
        - binary.reason_counts["SUPPORT_RATE"]
    )
    relief_backlog_delta = (
        incremental.reason_counts["RELIEF_BACKLOG"]
        - binary.reason_counts["RELIEF_BACKLOG"]
    )
    normal_backlog_delta = (
        incremental.reason_counts["NORMAL_BACKLOG"]
        - binary.reason_counts["NORMAL_BACKLOG"]
    )
    elastic_delta = incremental.elastic_epochs() - binary.elastic_epochs()
    component_sum = (
        protected_delta
        + rate_delta
        + relief_backlog_delta
        + normal_backlog_delta
    )

    row: dict[str, float | int | str] = {
        "seed": seed,
        "repetition": repetition,
        "order": order,
        "completed_ratio": safe_ratio(
            incremental.stats.completed,
            binary.stats.completed,
        ),
        "lost_delta": incremental.stats.lost - binary.stats.lost,
        "seconds_ratio": safe_ratio(
            incremental.stats.seconds_per_completion(),
            binary.stats.seconds_per_completion(),
        ),
        "continuous_missed_delta": (
            incremental.stats.missed_work_fraction()
            - binary.stats.missed_work_fraction()
        ),
        "continuous_severe_delta": (
            incremental.stats.severe_excess_fraction()
            - binary.stats.severe_excess_fraction()
        ),
        "elastic_epoch_delta": elastic_delta,
        "protected_reason_delta": protected_delta,
        "rate_reason_delta": rate_delta,
        "relief_backlog_reason_delta": relief_backlog_delta,
        "normal_backlog_reason_delta": normal_backlog_delta,
        "support_reason_delta": protected_delta + rate_delta,
        "backlog_reason_delta": relief_backlog_delta + normal_backlog_delta,
        "elastic_accounting_residual": elastic_delta - component_sum,
        "binary_failure_count": binary.failure_count,
        "incremental_failure_count": incremental.failure_count,
        "binary_minus_incremental_failure_delta": (
            binary.failure_count - incremental.failure_count
        ),
        "binary_post_success_reentries": binary.post_success_reentries,
        "incremental_post_success_reentries": incremental.post_success_reentries,
        "binary_first_protection": binary.first_protection_entry,
        "incremental_first_protection": incremental.first_protection_entry,
        "binary_first_rate": binary.first_rate_stage,
        "incremental_first_rate": incremental.first_rate_stage,
        "binary_first_relief": binary.first_relief_stage,
        "incremental_first_relief": incremental.first_relief_stage,
        "binary_first_exit": binary.first_successful_exit,
        "incremental_first_exit": incremental.first_successful_exit,
        "binary_first_base": binary.first_base_after_protection,
        "incremental_first_base": incremental.first_base_after_protection,
        "first_evidence_mismatch": first_evidence,
        "first_stage_mismatch": first_stage,
        "first_storage_mismatch": first_storage,
        "first_storage_cell": first_storage_cell,
        "evidence_relation": evidence_relation,
        "trace_structure_mismatches": structure_mismatches,
        "unpaired_tail_epochs": unpaired_tail_epochs,
        "terminal_backlog_violations": int(binary.stats.terminal_backlog != 0)
        + int(incremental.stats.terminal_backlog != 0),
        "digest_mismatches": (
            binary.stats.digest_mismatches
            + incremental.stats.digest_mismatches
        ),
    }
    return row, stage_pairs, reason_pairs


SEED_NUMERIC_KEYS = (
    "completed_ratio",
    "lost_delta",
    "seconds_ratio",
    "continuous_missed_delta",
    "continuous_severe_delta",
    "elastic_epoch_delta",
    "protected_reason_delta",
    "rate_reason_delta",
    "relief_backlog_reason_delta",
    "normal_backlog_reason_delta",
    "support_reason_delta",
    "backlog_reason_delta",
    "elastic_accounting_residual",
    "binary_failure_count",
    "incremental_failure_count",
    "binary_minus_incremental_failure_delta",
    "binary_post_success_reentries",
    "incremental_post_success_reentries",
    "unpaired_tail_epochs",
)


def aggregate_seed(rows: list[dict[str, float | int | str]]) -> dict[str, float]:
    return {
        key: float(median(float(row[key]) for row in rows))
        for key in SEED_NUMERIC_KEYS
    }


def med(rows: list[dict[str, float | int | str]], key: str) -> float:
    return float(median(float(row[key]) for row in rows))


def sign(value: float, center: float = 0.0) -> int:
    if value > center:
        return 1
    if value < center:
        return -1
    return 0


def median_event(runs: list[TraceRun], attr: str) -> float:
    values = [float(getattr(run, attr)) for run in runs if getattr(run, attr) >= 0]
    return float(median(values)) if values else -1.0


def top_counter(counter: Counter[str]) -> tuple[str, int]:
    if not counter:
        return "NONE", 0
    return counter.most_common(1)[0]


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=event_aligned_support_trajectory_v0.41")
    print("controllers=binary_v028_vs_incremental_v037_unchanged")
    print("fresh_seed_family=true")
    print("policy_promotion=false")
    print("controller_changes=false")
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
    runs_by_policy: dict[str, list[TraceRun]] = {
        "binary": [],
        "incremental": [],
    }
    stage_mismatch_pairs: Counter[str] = Counter()
    reason_mismatch_pairs: Counter[str] = Counter()
    storage_cells: Counter[str] = Counter()

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
                runs_by_policy[policy].append(current[policy])

            row, stage_pairs, reason_pairs = make_pair(
                seed=seed,
                repetition=repetition,
                order="BINARY_FIRST" if binary_first else "INCREMENTAL_FIRST",
                binary=current["binary"],
                incremental=current["incremental"],
            )
            all_pairs.append(row)
            pairs_by_seed[seed].append(row)
            stage_mismatch_pairs.update(stage_pairs)
            reason_mismatch_pairs.update(reason_pairs)
            storage_cells[str(row["first_storage_cell"])] += 1

            print(
                f"pair seed={seed} repetition={repetition} order={row['order']} "
                f"elastic_delta={int(row['elastic_epoch_delta'])} "
                f"protected_delta={int(row['protected_reason_delta'])} "
                f"rate_delta={int(row['rate_reason_delta'])} "
                f"relief_backlog_delta={int(row['relief_backlog_reason_delta'])} "
                f"normal_backlog_delta={int(row['normal_backlog_reason_delta'])} "
                f"failure_delta="
                f"{int(row['binary_minus_incremental_failure_delta'])} "
                f"first_evidence={int(row['first_evidence_mismatch'])} "
                f"first_stage={int(row['first_stage_mismatch'])} "
                f"first_storage={int(row['first_storage_mismatch'])} "
                f"storage_cell={row['first_storage_cell']} "
                f"lost_delta={int(row['lost_delta'])} "
                f"missed_delta={float(row['continuous_missed_delta']):.6f}"
            )

    seed_rows = [aggregate_seed(pairs_by_seed[seed]) for seed in SEEDS]

    elastic_positive_seeds = sum(
        row["elastic_epoch_delta"] > 0.0 for row in seed_rows
    )
    elastic_negative_seeds = sum(
        row["elastic_epoch_delta"] < 0.0 for row in seed_rows
    )
    failure_excess_positive_seeds = sum(
        row["binary_minus_incremental_failure_delta"] > 0.0
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
    integrity_ok = (
        terminal_backlog_violations == 0
        and digest_mismatches == 0
        and trace_structure_mismatches == 0
        and max_elastic_residual == 0.0
    )

    median_elastic = med(seed_rows, "elastic_epoch_delta")
    median_support = med(seed_rows, "support_reason_delta")
    median_rate = med(seed_rows, "rate_reason_delta")
    median_backlog = med(seed_rows, "backlog_reason_delta")
    stable_positive = (
        median_elastic > 0.0 and elastic_positive_seeds >= MIN_SIGN_AGREEMENT
    )
    stable_negative = (
        median_elastic < 0.0 and elastic_negative_seeds >= MIN_SIGN_AGREEMENT
    )

    incremental_rate_extension = (
        stable_positive
        and median_rate > 0.0
        and median_rate >= 0.5 * median_elastic
        and integrity_ok
    )
    binary_support_extension = (
        stable_negative
        and median_support < 0.0
        and abs(median_support) >= 0.5 * abs(median_elastic)
        and integrity_ok
    )
    post_support_backlog = (
        (stable_positive or stable_negative)
        and abs(median_backlog) >= 0.5 * abs(median_elastic)
        and integrity_ok
    )

    order_rows = {
        order: [row for row in all_pairs if row["order"] == order]
        for order in ("BINARY_FIRST", "INCREMENTAL_FIRST")
    }
    order_sign_disagreement = any(
        sign(med(order_rows["BINARY_FIRST"], key), center)
        * sign(med(order_rows["INCREMENTAL_FIRST"], key), center)
        < 0
        for key, center in (
            ("elastic_epoch_delta", 0.0),
            ("support_reason_delta", 0.0),
            ("rate_reason_delta", 0.0),
            ("lost_delta", 0.0),
        )
    )

    binary_support_subclass = "not_applicable"
    if order_sign_disagreement:
        local_classification = "order_sensitive"
    elif incremental_rate_extension:
        local_classification = "incremental_rate_stage_extension"
    elif binary_support_extension:
        local_classification = "binary_support_extension"
        if (
            med(seed_rows, "binary_minus_incremental_failure_delta") > 0.0
            and failure_excess_positive_seeds >= MIN_SIGN_AGREEMENT
        ):
            binary_support_subclass = "binary_failure_reprotection"
        else:
            binary_support_subclass = "binary_evidence_or_dwell_extension"
    elif post_support_backlog:
        local_classification = "post_support_backlog_retention"
    elif (stable_positive or stable_negative) and integrity_ok:
        local_classification = "mixed_support_trajectory"
    else:
        local_classification = "no_stable_trajectory_direction"

    evidence_before = sum(int(row["evidence_relation"]) == 0 for row in all_pairs)
    evidence_at = sum(int(row["evidence_relation"]) == 1 for row in all_pairs)
    no_evidence_before = sum(int(row["evidence_relation"]) == 2 for row in all_pairs)
    no_storage_mismatch = sum(int(row["evidence_relation"]) == 3 for row in all_pairs)

    top_stage_pair, top_stage_count = top_counter(stage_mismatch_pairs)
    top_reason_pair, top_reason_count = top_counter(reason_mismatch_pairs)
    top_storage_cell, top_storage_count = top_counter(storage_cells)

    print("\n[event_aligned_trajectory]")
    print(f"paired_runs={len(all_pairs)}")
    print(f"seed_summaries={len(seed_rows)}")
    for key in SEED_NUMERIC_KEYS:
        print(f"median_seed_{key}={med(seed_rows, key):.6f}")
    print(f"elastic_positive_seeds={elastic_positive_seeds}/{len(SEEDS)}")
    print(f"elastic_negative_seeds={elastic_negative_seeds}/{len(SEEDS)}")
    print(
        f"failure_excess_positive_seeds="
        f"{failure_excess_positive_seeds}/{len(SEEDS)}"
    )

    for policy in ("binary", "incremental"):
        runs = runs_by_policy[policy]
        print(
            f"policy={policy} "
            f"median_elastic_epochs={median(run.elastic_epochs() for run in runs):.3f} "
            f"median_support_epochs={median(run.support_epochs() for run in runs):.3f} "
            f"median_backlog_elastic_epochs="
            f"{median(run.backlog_elastic_epochs() for run in runs):.3f} "
            f"median_PROTECTED_epochs="
            f"{median(run.stage_counts['PROTECTED'] for run in runs):.3f} "
            f"median_RATE_epochs={median(run.stage_counts['RATE'] for run in runs):.3f} "
            f"median_RELIEF_epochs="
            f"{median(run.stage_counts['RELIEF'] for run in runs):.3f} "
            f"median_NORMAL_epochs="
            f"{median(run.stage_counts['NORMAL'] for run in runs):.3f} "
            f"median_failure_count={median(run.failure_count for run in runs):.3f} "
            f"median_protection_episodes="
            f"{median(run.protection_episodes for run in runs):.3f}"
        )
        print(
            f"policy={policy} events "
            f"first_protection={median_event(runs, 'first_protection_entry'):.3f} "
            f"first_rate={median_event(runs, 'first_rate_stage'):.3f} "
            f"first_relief={median_event(runs, 'first_relief_stage'):.3f} "
            f"first_exit={median_event(runs, 'first_successful_exit'):.3f} "
            f"first_reentry="
            f"{median_event(runs, 'first_post_success_reentry'):.3f} "
            f"first_base="
            f"{median_event(runs, 'first_base_after_protection'):.3f}"
        )

    print(f"evidence_before_storage_pairs={evidence_before}/{len(all_pairs)}")
    print(f"evidence_at_storage_pairs={evidence_at}/{len(all_pairs)}")
    print(f"no_evidence_before_storage_pairs={no_evidence_before}/{len(all_pairs)}")
    print(f"no_storage_mismatch_pairs={no_storage_mismatch}/{len(all_pairs)}")
    print(f"top_stage_mismatch_pair={top_stage_pair} count={top_stage_count}")
    print(f"top_reason_mismatch_pair={top_reason_pair} count={top_reason_count}")
    print(f"top_first_storage_cell={top_storage_cell} count={top_storage_count}")

    for order, rows in order_rows.items():
        print(
            f"order={order} n={len(rows)} "
            f"median_elastic_delta={med(rows, 'elastic_epoch_delta'):.3f} "
            f"median_support_delta={med(rows, 'support_reason_delta'):.3f} "
            f"median_rate_delta={med(rows, 'rate_reason_delta'):.3f} "
            f"median_lost_delta={med(rows, 'lost_delta'):.3f}"
        )

    print(f"terminal_backlog_violations={terminal_backlog_violations}")
    print(f"digest_mismatches={digest_mismatches}")
    print(f"trace_structure_mismatches={trace_structure_mismatches}")
    print(f"max_elastic_accounting_residual={max_elastic_residual:.6f}")
    print(f"integrity_ok={str(integrity_ok).lower()}")
    print(f"stable_positive_direction={str(stable_positive).lower()}")
    print(f"stable_negative_direction={str(stable_negative).lower()}")
    print(
        f"incremental_rate_stage_extension="
        f"{str(incremental_rate_extension).lower()}"
    )
    print(f"binary_support_extension={str(binary_support_extension).lower()}")
    print(f"post_support_backlog_retention={str(post_support_backlog).lower()}")
    print(f"order_sign_disagreement={str(order_sign_disagreement).lower()}")
    print(f"local_classification={local_classification}")
    print(f"binary_support_subclass={binary_support_subclass}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=requires_cross_runtime_interpretation")
    print(
        "interpretation=v0.41 event-aligns unchanged v0.28 and v0.37 "
        "controller traces and exactly accounts for their elastic-storage "
        "duration difference by state-machine occupancy reason."
    )


if __name__ == "__main__":
    main()
