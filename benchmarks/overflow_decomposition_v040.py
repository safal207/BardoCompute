from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from bardocompute.exchange import ExchangeResult
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

# Fresh family frozen in issue #34 before implementation/results.
SEEDS = (
    23_100_877,
    23_200_883,
    23_300_891,
    23_400_899,
    23_500_907,
    23_600_913,
    23_700_919,
    23_800_927,
)
PAIRED_REPETITIONS = 4
MIN_SIGN_AGREEMENT = 6
DECOMPOSITION_TOLERANCE = 1e-9

PHASES = ("normal", "burst", "degraded", "congested", "recovery")
CELLS = (
    "B_ELASTIC__I_BASE",
    "B_BASE__I_ELASTIC",
    "B_ELASTIC__I_ELASTIC",
    "B_BASE__I_BASE",
)


@dataclass(frozen=True, slots=True)
class AdmissionTrace:
    epoch_index: int
    phase: str
    incoming: int
    pre_admission_backlog: int
    buffer_limit: int
    available_headroom: int
    overflow: int
    release_limit: int
    protective: bool
    withdrawal_stage: int
    relief_active: bool
    elastic_storage_active: bool


@dataclass(slots=True)
class TraceRun:
    stats: CostStats
    trace: list[AdmissionTrace]
    trace_identity_mismatches: int = 0


def overflow_for(backlog: int, incoming: int, buffer_limit: int) -> int:
    return max(0, backlog + incoming - buffer_limit)


def run_trace_policy(
    epochs: tuple[EpochSpec, ...],
    *,
    controller,
    rounds: int,
    deadline_seconds: float,
) -> TraceRun:
    stats = CostStats()
    traces: list[AdmissionTrace] = []
    trace_identity_mismatches = 0
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

        for queue_index, spec in enumerate(queue):
            if spec.phase == "drain" and backlog == 0:
                break

            stats.executed_epochs += 1
            stats.drain_epochs += int(spec.phase == "drain")
            pre_backlog = backlog
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.40 forbids voluntary admission shedding")

            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            actual_overflow = spec.incoming - admitted
            expected_overflow = overflow_for(
                pre_backlog,
                spec.incoming,
                command.buffer_limit,
            )
            trace_identity_mismatches += int(actual_overflow != expected_overflow)

            if spec.phase != "drain":
                traces.append(
                    AdmissionTrace(
                        epoch_index=queue_index,
                        phase=spec.phase,
                        incoming=spec.incoming,
                        pre_admission_backlog=pre_backlog,
                        buffer_limit=command.buffer_limit,
                        available_headroom=available_capacity,
                        overflow=actual_overflow,
                        release_limit=command.release_limit,
                        protective=bool(getattr(controller, "protective", False)),
                        withdrawal_stage=int(
                            getattr(controller, "withdrawal_stage", -1)
                        ),
                        relief_active=bool(
                            getattr(controller, "current_boost", 0.0) > 0.0
                        ),
                        elastic_storage_active=(
                            command.buffer_limit == ELASTIC_BUFFER_LIMIT
                        ),
                    )
                )

            stats.incoming += spec.incoming
            stats.lost += actual_overflow
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

            on_time = p_on + s_on + r_on
            missed = max(0, released - on_time)
            miss_fraction = missed / max(1, released)
            stats.missed_work_total += missed
            stats.released_work_total += released
            stats.severe_excess_total += max(
                0.0,
                miss_fraction - SEVERE_MISS_THRESHOLD,
            ) * released
            if released > 0:
                stats.deadline_miss_epochs += int(miss_fraction >= MISS_THRESHOLD)
                stats.severe_miss_epochs += int(
                    miss_fraction >= SEVERE_MISS_THRESHOLD
                )

            controller.observe(
                ExchangeResult(
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
                    overflow_dropped=actual_overflow,
                )
            )

    stats.terminal_backlog = backlog
    if len(traces) != len(epochs):
        raise AssertionError(
            f"trace length {len(traces)} does not match epoch length {len(epochs)}"
        )
    return TraceRun(
        stats=stats,
        trace=traces,
        trace_identity_mismatches=trace_identity_mismatches,
    )


def decompose_traces(
    binary: list[AdmissionTrace],
    incremental: list[AdmissionTrace],
) -> dict[str, float]:
    if len(binary) != len(incremental):
        raise AssertionError("matched traces have different lengths")

    actual_total = 0.0
    buffer_total = 0.0
    backlog_total = 0.0
    binary_elastic_epochs = 0
    incremental_elastic_epochs = 0
    storage_disadvantage_epochs = 0
    storage_advantage_epochs = 0
    cell_deltas = {cell: 0.0 for cell in CELLS}
    phase_deltas = {phase: 0.0 for phase in PHASES}

    for b, i in zip(binary, incremental, strict=True):
        if (
            b.epoch_index != i.epoch_index
            or b.phase != i.phase
            or b.incoming != i.incoming
        ):
            raise AssertionError("matched trace alignment mismatch")

        incoming = b.incoming
        f_bb_lb = float(
            overflow_for(b.pre_admission_backlog, incoming, b.buffer_limit)
        )
        f_bi_li = float(
            overflow_for(i.pre_admission_backlog, incoming, i.buffer_limit)
        )
        f_bi_lb = float(
            overflow_for(i.pre_admission_backlog, incoming, b.buffer_limit)
        )
        f_bb_li = float(
            overflow_for(b.pre_admission_backlog, incoming, i.buffer_limit)
        )

        actual = f_bi_li - f_bb_lb
        backlog_contribution = 0.5 * (
            (f_bi_lb - f_bb_lb) + (f_bi_li - f_bb_li)
        )
        buffer_contribution = 0.5 * (
            (f_bb_li - f_bb_lb) + (f_bi_li - f_bi_lb)
        )

        actual_total += actual
        buffer_total += buffer_contribution
        backlog_total += backlog_contribution
        binary_elastic_epochs += int(b.elastic_storage_active)
        incremental_elastic_epochs += int(i.elastic_storage_active)

        if b.elastic_storage_active and not i.elastic_storage_active:
            cell = "B_ELASTIC__I_BASE"
            storage_disadvantage_epochs += 1
        elif not b.elastic_storage_active and i.elastic_storage_active:
            cell = "B_BASE__I_ELASTIC"
            storage_advantage_epochs += 1
        elif b.elastic_storage_active and i.elastic_storage_active:
            cell = "B_ELASTIC__I_ELASTIC"
        else:
            cell = "B_BASE__I_BASE"
        cell_deltas[cell] += actual
        if b.phase not in phase_deltas:
            phase_deltas[b.phase] = 0.0
        phase_deltas[b.phase] += actual

    result = {
        "actual_overflow_delta": actual_total,
        "buffer_contribution": buffer_total,
        "backlog_contribution": backlog_total,
        "decomposition_residual": abs(
            actual_total - buffer_total - backlog_total
        ),
        "binary_elastic_epochs": float(binary_elastic_epochs),
        "incremental_elastic_epochs": float(incremental_elastic_epochs),
        "storage_disadvantage_epochs": float(storage_disadvantage_epochs),
        "storage_advantage_epochs": float(storage_advantage_epochs),
        "storage_disadvantage_overflow_delta": cell_deltas[
            "B_ELASTIC__I_BASE"
        ],
        "storage_advantage_overflow_delta": cell_deltas[
            "B_BASE__I_ELASTIC"
        ],
    }
    result.update({f"cell_{key}": value for key, value in cell_deltas.items()})
    result.update({f"phase_{key}": value for key, value in phase_deltas.items()})
    return result


def make_effect(
    *,
    seed: int,
    repetition: int,
    order: str,
    binary: TraceRun,
    incremental: TraceRun,
) -> dict[str, float | int | str]:
    decomposition = decompose_traces(binary.trace, incremental.trace)
    lost_delta = incremental.stats.lost - binary.stats.lost
    row: dict[str, float | int | str] = {
        "seed": seed,
        "repetition": repetition,
        "order": order,
        "completed_ratio": safe_ratio(
            incremental.stats.completed,
            binary.stats.completed,
        ),
        "lost_delta": float(lost_delta),
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
        "lost_identity_residual": abs(
            float(lost_delta) - decomposition["actual_overflow_delta"]
        ),
        "terminal_backlog_violations": int(binary.stats.terminal_backlog != 0)
        + int(incremental.stats.terminal_backlog != 0),
        "digest_mismatches": (
            binary.stats.digest_mismatches
            + incremental.stats.digest_mismatches
        ),
        "trace_identity_mismatches": (
            binary.trace_identity_mismatches
            + incremental.trace_identity_mismatches
        ),
    }
    row.update(decomposition)
    return row


NUMERIC_KEYS = (
    "completed_ratio",
    "lost_delta",
    "seconds_ratio",
    "continuous_missed_delta",
    "continuous_severe_delta",
    "actual_overflow_delta",
    "buffer_contribution",
    "backlog_contribution",
    "decomposition_residual",
    "lost_identity_residual",
    "binary_elastic_epochs",
    "incremental_elastic_epochs",
    "storage_disadvantage_epochs",
    "storage_advantage_epochs",
    "storage_disadvantage_overflow_delta",
    "storage_advantage_overflow_delta",
    *(f"cell_{cell}" for cell in CELLS),
    *(f"phase_{phase}" for phase in PHASES),
)


def aggregate(rows: list[dict[str, float | int | str]]) -> dict[str, float]:
    return {
        key: float(median(float(row.get(key, 0.0)) for row in rows))
        for key in NUMERIC_KEYS
    }


def med(rows: list[dict[str, float | int | str]], key: str) -> float:
    return float(median(float(row.get(key, 0.0)) for row in rows))


def sign(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=counterfactual_overflow_decomposition_v0.40")
    print("controllers=binary_v028_vs_incremental_v037_unchanged")
    print("fresh_seed_family=true")
    print("policy_promotion=false")
    print("controller_changes=false")
    print("controllers_phase_blind=true")
    print("phase_labels=evaluator_only")
    print("decomposition=symmetric_two_factor_shapley")
    print(f"paired_repetitions={PAIRED_REPETITIONS}")
    print(f"MIN_SIGN_AGREEMENT={MIN_SIGN_AGREEMENT}")
    print(f"DECOMPOSITION_TOLERANCE={DECOMPOSITION_TOLERANCE:.1e}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    all_pairs: list[dict[str, float | int | str]] = []
    pairs_by_seed: dict[int, list[dict[str, float | int | str]]] = defaultdict(list)

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
                current[policy] = run_trace_policy(
                    epochs,
                    controller=controller,
                    rounds=rounds,
                    deadline_seconds=deadline_seconds,
                )

            row = make_effect(
                seed=seed,
                repetition=repetition,
                order="BINARY_FIRST" if binary_first else "INCREMENTAL_FIRST",
                binary=current["binary"],
                incremental=current["incremental"],
            )
            all_pairs.append(row)
            pairs_by_seed[seed].append(row)
            print(
                f"pair seed={seed} repetition={repetition} order={row['order']} "
                f"lost_delta={float(row['lost_delta']):.3f} "
                f"buffer_contribution={float(row['buffer_contribution']):.3f} "
                f"backlog_contribution={float(row['backlog_contribution']):.3f} "
                f"residual={float(row['decomposition_residual']):.9f} "
                f"B_elastic={float(row['binary_elastic_epochs']):.0f} "
                f"I_elastic={float(row['incremental_elastic_epochs']):.0f} "
                f"storage_disadvantage_epochs="
                f"{float(row['storage_disadvantage_epochs']):.0f} "
                f"storage_disadvantage_delta="
                f"{float(row['storage_disadvantage_overflow_delta']):.3f}"
            )

    seed_rows = [aggregate(pairs_by_seed[seed]) for seed in SEEDS]

    terminal_backlog_violations = sum(
        int(row["terminal_backlog_violations"]) for row in all_pairs
    )
    digest_mismatches = sum(int(row["digest_mismatches"]) for row in all_pairs)
    trace_identity_mismatches = sum(
        int(row["trace_identity_mismatches"]) for row in all_pairs
    )
    max_decomposition_residual = max(
        float(row["decomposition_residual"]) for row in all_pairs
    )
    max_lost_identity_residual = max(
        float(row["lost_identity_residual"]) for row in all_pairs
    )
    integrity_ok = (
        terminal_backlog_violations == 0
        and digest_mismatches == 0
        and trace_identity_mismatches == 0
        and max_decomposition_residual <= DECOMPOSITION_TOLERANCE
        and max_lost_identity_residual <= DECOMPOSITION_TOLERANCE
    )

    lost_positive_seeds = sum(row["lost_delta"] > 0.0 for row in seed_rows)
    buffer_positive_seeds = sum(
        row["buffer_contribution"] > 0.0 for row in seed_rows
    )
    backlog_nonpositive_seeds = sum(
        row["backlog_contribution"] <= 0.0 for row in seed_rows
    )
    backlog_positive_seeds = sum(
        row["backlog_contribution"] > 0.0 for row in seed_rows
    )
    storage_disadvantage_positive_seeds = sum(
        row["storage_disadvantage_overflow_delta"] > 0.0
        for row in seed_rows
    )

    median_actual = med(seed_rows, "actual_overflow_delta")
    median_buffer = med(seed_rows, "buffer_contribution")
    median_backlog = med(seed_rows, "backlog_contribution")

    storage_supported = (
        med(seed_rows, "lost_delta") > 0.0
        and lost_positive_seeds >= MIN_SIGN_AGREEMENT
        and median_buffer > 0.0
        and buffer_positive_seeds >= MIN_SIGN_AGREEMENT
        and median_backlog <= 0.0
        and backlog_nonpositive_seeds >= MIN_SIGN_AGREEMENT
        and median_buffer >= 0.5 * median_actual
        and med(seed_rows, "storage_disadvantage_overflow_delta") > 0.0
        and integrity_ok
    )
    backlog_supported = (
        med(seed_rows, "lost_delta") > 0.0
        and lost_positive_seeds >= MIN_SIGN_AGREEMENT
        and median_backlog > 0.0
        and backlog_positive_seeds >= MIN_SIGN_AGREEMENT
        and median_backlog >= 0.5 * median_actual
        and integrity_ok
    )
    mixed_supported = (
        median_actual > 0.0
        and median_buffer > 0.0
        and median_backlog > 0.0
        and integrity_ok
        and not storage_supported
        and not backlog_supported
    )

    order_rows = {
        order: [row for row in all_pairs if row["order"] == order]
        for order in ("BINARY_FIRST", "INCREMENTAL_FIRST")
    }
    order_sign_disagreement = any(
        sign(med(order_rows["BINARY_FIRST"], key))
        * sign(med(order_rows["INCREMENTAL_FIRST"], key))
        < 0
        for key in (
            "lost_delta",
            "buffer_contribution",
            "backlog_contribution",
            "storage_disadvantage_overflow_delta",
        )
    )

    if order_sign_disagreement:
        local_classification = "order_sensitive"
    elif storage_supported:
        local_classification = "storage_withdrawal_mediation_supported"
    elif backlog_supported:
        local_classification = "backlog_timing_mediation_supported"
    elif mixed_supported:
        local_classification = "mixed_storage_and_backlog"
    else:
        local_classification = "overflow_difference_unresolved"

    print("\n[overflow_decomposition]")
    print(f"paired_runs={len(all_pairs)}")
    print(f"seed_summaries={len(seed_rows)}")
    for key in NUMERIC_KEYS:
        print(f"median_seed_{key}={med(seed_rows, key):.6f}")
    print(f"lost_positive_seeds={lost_positive_seeds}/{len(SEEDS)}")
    print(f"buffer_positive_seeds={buffer_positive_seeds}/{len(SEEDS)}")
    print(
        f"backlog_nonpositive_seeds="
        f"{backlog_nonpositive_seeds}/{len(SEEDS)}"
    )
    print(f"backlog_positive_seeds={backlog_positive_seeds}/{len(SEEDS)}")
    print(
        f"storage_disadvantage_positive_seeds="
        f"{storage_disadvantage_positive_seeds}/{len(SEEDS)}"
    )

    for order, rows in order_rows.items():
        print(
            f"order={order} n={len(rows)} "
            f"median_lost_delta={med(rows, 'lost_delta'):.3f} "
            f"median_buffer_contribution="
            f"{med(rows, 'buffer_contribution'):.3f} "
            f"median_backlog_contribution="
            f"{med(rows, 'backlog_contribution'):.3f} "
            f"median_storage_disadvantage_delta="
            f"{med(rows, 'storage_disadvantage_overflow_delta'):.3f}"
        )

    print(f"terminal_backlog_violations={terminal_backlog_violations}")
    print(f"digest_mismatches={digest_mismatches}")
    print(f"trace_identity_mismatches={trace_identity_mismatches}")
    print(f"max_decomposition_residual={max_decomposition_residual:.12f}")
    print(f"max_lost_identity_residual={max_lost_identity_residual:.12f}")
    print(f"integrity_ok={str(integrity_ok).lower()}")
    print(f"storage_withdrawal_mediation_supported={str(storage_supported).lower()}")
    print(f"backlog_timing_mediation_supported={str(backlog_supported).lower()}")
    print(f"mixed_storage_and_backlog={str(mixed_supported).lower()}")
    print(f"order_sign_disagreement={str(order_sign_disagreement).lower()}")
    print(f"local_classification={local_classification}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=requires_cross_runtime_interpretation")
    print(
        "interpretation=v0.40 applies exact matched-epoch Shapley "
        "decomposition to unchanged v0.28 and v0.37 admission traces, "
        "separating realized buffer-limit timing from realized backlog timing."
    )


if __name__ == "__main__":
    main()
