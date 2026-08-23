from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from active_load_gate_v030 import ActiveLoadGatedRateFirstMembrane
from bardocompute.exchange import ExchangeResult
from real_work_queue_transfer import (
    BASE_BUFFER,
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)

# Spent canonical v0.30 (#19) family: diagnostic-only.
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

NO_STORAGE = "NO_ELASTIC_STORAGE"
FULL_PROTECTION = "FULL_PROTECTION"
RATE_RELAXED = "RATE_RELAXED"
RELIEF_WITHDRAWAL = "RELIEF_WITHDRAWAL"
POST_EXIT_TAIL = "POST_EXIT_BACKLOG_TAIL"
STORAGE_REASONS = (
    FULL_PROTECTION,
    RATE_RELAXED,
    RELIEF_WITHDRAWAL,
    POST_EXIT_TAIL,
)


@dataclass(slots=True)
class EpochRecord:
    seed: int
    epoch_index: int
    phase: str
    reason: str
    storage_active: bool
    protective: bool
    buffered_before: int
    buffered_after: int
    backlog_delta: int
    released: int
    on_time: int
    miss_fraction: float
    relief_active: bool
    rate_protection_state: bool


@dataclass(slots=True)
class SeedSummary:
    records: list[EpochRecord]
    first_entry_epoch: int | None
    first_full_exit_epoch: int | None
    storage_contraction_epoch: int | None
    terminal_backlog: int
    digest_mismatches: int


def classify_storage(controller: ActiveLoadGatedRateFirstMembrane, buffer_limit: int) -> str:
    if buffer_limit <= BASE_BUFFER:
        return NO_STORAGE
    if controller.withdrawal_stage == controller.RATE_RELAXED:
        return RATE_RELAXED
    if controller.withdrawal_stage == controller.RELIEF_WITHDRAWAL:
        return RELIEF_WITHDRAWAL
    if controller.protective and controller.withdrawal_stage == controller.PROTECTED:
        return FULL_PROTECTION
    if (not controller.protective) and controller.buffered > BASE_BUFFER:
        return POST_EXIT_TAIL
    raise AssertionError(
        "elastic storage epoch did not match frozen v0.31 attribution reasons: "
        f"protective={controller.protective} stage={controller.withdrawal_stage} "
        f"buffered={controller.buffered} buffer_limit={buffer_limit}"
    )


def run_seed(seed: int, *, rounds: int, deadline_seconds: float) -> SeedSummary:
    controller = ActiveLoadGatedRateFirstMembrane()
    backlog = 0
    records: list[EpochRecord] = []
    first_entry_epoch: int | None = None
    first_full_exit_epoch: int | None = None
    storage_contraction_epoch: int | None = None
    digest_mismatches = 0

    queue = list(build_epochs(seed))
    queue.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()

        for epoch_index, spec in enumerate(queue):
            if spec.phase == "drain" and backlog == 0:
                break

            protective_before_command = controller.protective
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.31 diagnostic forbids voluntary admission shedding")

            if (
                first_entry_epoch is None
                and not protective_before_command
                and controller.protective
            ):
                first_entry_epoch = epoch_index

            storage_active = command.buffer_limit > BASE_BUFFER
            reason = classify_storage(controller, command.buffer_limit)

            if (
                first_full_exit_epoch is not None
                and storage_contraction_epoch is None
                and not storage_active
            ):
                storage_contraction_epoch = epoch_index

            buffered_before = backlog
            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
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

            protective_during_command = controller.protective
            stage_during_command = controller.withdrawal_stage
            controller.observe(result)

            if (
                first_full_exit_epoch is None
                and protective_during_command
                and stage_during_command == controller.RELIEF_WITHDRAWAL
                and not controller.protective
            ):
                first_full_exit_epoch = epoch_index
                if backlog <= BASE_BUFFER:
                    storage_contraction_epoch = epoch_index

            records.append(
                EpochRecord(
                    seed=seed,
                    epoch_index=epoch_index,
                    phase=spec.phase,
                    reason=reason,
                    storage_active=storage_active,
                    protective=protective_during_command,
                    buffered_before=buffered_before,
                    buffered_after=backlog,
                    backlog_delta=backlog - buffered_before,
                    released=released,
                    on_time=on_time,
                    miss_fraction=miss_fraction,
                    relief_active=relief_active,
                    rate_protection_state=(reason == FULL_PROTECTION),
                )
            )

    if first_full_exit_epoch is not None and storage_contraction_epoch is None and backlog == 0:
        storage_contraction_epoch = records[-1].epoch_index if records else first_full_exit_epoch

    return SeedSummary(
        records=records,
        first_entry_epoch=first_entry_epoch,
        first_full_exit_epoch=first_full_exit_epoch,
        storage_contraction_epoch=storage_contraction_epoch,
        terminal_backlog=backlog,
        digest_mismatches=digest_mismatches,
    )


def _median(values: list[float | int]) -> float:
    return float(median(values)) if values else float("nan")


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=storage_occupancy_attribution_v0.31")
    print("controller=canonical_v0.30_ActiveLoadGatedRateFirstMembrane")
    print("seeds_status=spent_canonical_v0.30_diagnostic_only")
    print("policy_promotion_allowed=false")
    print("threshold_tuning_allowed=false")
    print("controllers_phase_blind=true")
    print("external_phase_used_for_attribution_only=true")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    summaries: list[SeedSummary] = []
    for seed in SEEDS:
        summary = run_seed(seed, rounds=rounds, deadline_seconds=deadline_seconds)
        summaries.append(summary)
        storage_records = [row for row in summary.records if row.storage_active]
        reason_counts = Counter(row.reason for row in storage_records)
        print(
            f"seed={seed} executed={len(summary.records)} storage={len(storage_records)} "
            f"storage_occupancy={len(storage_records)/max(1,len(summary.records)):.6f} "
            f"full={reason_counts[FULL_PROTECTION]} rate={reason_counts[RATE_RELAXED]} "
            f"relief={reason_counts[RELIEF_WITHDRAWAL]} tail={reason_counts[POST_EXIT_TAIL]} "
            f"entry={summary.first_entry_epoch} exit={summary.first_full_exit_epoch} "
            f"contract={summary.storage_contraction_epoch} terminal={summary.terminal_backlog} "
            f"digest_mismatches={summary.digest_mismatches}"
        )

    all_records = [row for summary in summaries for row in summary.records]
    storage_records = [row for row in all_records if row.storage_active]
    reason_counts = Counter(row.reason for row in storage_records)
    phase_counts = Counter(row.phase for row in storage_records)

    by_reason: dict[str, list[EpochRecord]] = defaultdict(list)
    for row in storage_records:
        by_reason[row.reason].append(row)

    occupancy_by_seed = [
        sum(row.storage_active for row in summary.records) / max(1, len(summary.records))
        for summary in summaries
    ]
    entry_to_exit = [
        summary.first_full_exit_epoch - summary.first_entry_epoch
        for summary in summaries
        if summary.first_entry_epoch is not None and summary.first_full_exit_epoch is not None
    ]
    exit_to_contraction = [
        summary.storage_contraction_epoch - summary.first_full_exit_epoch
        for summary in summaries
        if summary.first_full_exit_epoch is not None
        and summary.storage_contraction_epoch is not None
    ]

    post_exit_storage = reason_counts[POST_EXIT_TAIL]
    rate_normal_storage = (
        reason_counts[RATE_RELAXED]
        + reason_counts[RELIEF_WITHDRAWAL]
        + reason_counts[POST_EXIT_TAIL]
    )

    print("\n[storage_attribution]")
    print(f"total_executed_epochs={len(all_records)}")
    print(f"elastic_storage_epochs={len(storage_records)}")
    print(f"median_storage_occupancy={median(occupancy_by_seed):.6f}")
    for reason in STORAGE_REASONS:
        count = reason_counts[reason]
        print(
            f"storage_reason_{reason}=count:{count},fraction:{count/max(1,len(storage_records)):.6f}"
        )
    print(
        "storage_epochs_by_phase="
        + ",".join(f"{phase}:{phase_counts[phase]}" for phase in sorted(phase_counts))
    )

    for reason in STORAGE_REASONS:
        rows = by_reason[reason]
        print(
            f"reason={reason} count={len(rows)} "
            f"median_backlog_before={_median([row.buffered_before for row in rows]):.1f} "
            f"median_backlog_after={_median([row.buffered_after for row in rows]):.1f} "
            f"median_backlog_delta={_median([row.backlog_delta for row in rows]):.1f} "
            f"median_miss_fraction={_median([row.miss_fraction for row in rows]):.6f}"
        )

    print(f"median_epochs_entry_to_full_exit={_median(entry_to_exit):.1f}")
    print(f"median_epochs_exit_to_storage_contraction={_median(exit_to_contraction):.1f}")
    print(
        f"fraction_storage_after_protection_exit={post_exit_storage/max(1,len(storage_records)):.6f}"
    )
    print(
        f"fraction_storage_while_rate_normal={rate_normal_storage/max(1,len(storage_records)):.6f}"
    )
    print(f"median_terminal_backlog={median(summary.terminal_backlog for summary in summaries):.1f}")
    print(f"digest_mismatches={sum(summary.digest_mismatches for summary in summaries)}")

    dominant_reason = max(STORAGE_REASONS, key=lambda reason: reason_counts[reason])
    print("\n[diagnostic_interpretation]")
    print(f"dominant_storage_reason={dominant_reason}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=not_applicable")
    print(
        "interpretation=v0.31 attributes canonical-v0.30 elastic-storage occupancy "
        "to controller state or post-exit retained-backlog tail without changing policy."
    )


if __name__ == "__main__":
    main()
