from __future__ import annotations

from collections import Counter
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

ACTIVE_STRESS = {"burst", "primary_degraded", "global_congested"}
RECOVERY_DRAIN = {"recovery", "drain"}


@dataclass(slots=True)
class EligibilityRecord:
    seed: int
    protection_episode: int
    epoch_index: int
    phase: str
    resolution_strength: int
    actual_load: float
    shadow_load: float
    actual_backlog_before: int
    shadow_backlog_before: int
    actual_admitted: int = 0
    base_release_limit: int = 0
    protected_release_limit: int = 0
    actual_released: int = 0
    shadow_released: int = 0
    actual_backlog_after: int = 0
    shadow_backlog_after: int = 0
    rate_cap_binding: bool = False
    eligibility_class: str = ""


@dataclass(slots=True)
class EpisodeSummary:
    seed: int
    protection_episode: int
    first_resolution_ready_epoch: int | None = None
    first_actual_eligible_epoch: int | None = None
    first_shadow_eligible_epoch: int | None = None
    peak_actual_minus_shadow_backlog_gap: int = 0
    had_actual_blocked_shadow_eligible: bool = False

    def actual_delay(self) -> int | None:
        if self.first_resolution_ready_epoch is None or self.first_actual_eligible_epoch is None:
            return None
        return max(0, self.first_actual_eligible_epoch - self.first_resolution_ready_epoch)

    def shadow_delay(self) -> int | None:
        if self.first_resolution_ready_epoch is None or self.first_shadow_eligible_epoch is None:
            return None
        return max(0, self.first_shadow_eligible_epoch - self.first_resolution_ready_epoch)


def classify(actual_load: float, shadow_load: float) -> str:
    actual_blocked = actual_load >= MIN_ACTIVE_LOAD
    shadow_blocked = shadow_load >= MIN_ACTIVE_LOAD
    if actual_blocked and shadow_blocked:
        return "BOTH_BLOCKED"
    if actual_blocked and not shadow_blocked:
        return "ACTUAL_BLOCKED_SHADOW_ELIGIBLE"
    if not actual_blocked and shadow_blocked:
        return "ACTUAL_ELIGIBLE_SHADOW_BLOCKED"
    return "BOTH_ELIGIBLE"


def run_seed(
    seed: int,
    *,
    rounds: int,
    deadline_seconds: float,
) -> tuple[list[EligibilityRecord], list[EpisodeSummary], int, int]:
    controller = ActiveLoadGatedRateFirstMembrane()
    epochs = list(build_epochs(seed))
    epochs.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

    records: list[EligibilityRecord] = []
    episodes: list[EpisodeSummary] = []
    active_episode: EpisodeSummary | None = None
    protection_episode = 0

    backlog = 0
    shadow_backlog = 0
    previous_shadow_load: float | None = None
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

            begins_full_protection = (
                controller.protective
                and controller.withdrawal_stage == controller.PROTECTED
            )

            if not begins_full_protection and active_episode is not None:
                episodes.append(active_episode)
                active_episode = None
                previous_shadow_load = None

            pre_record: EligibilityRecord | None = None
            if (
                begins_full_protection
                and active_episode is not None
                and controller.resolution_strength >= RECOVERY_DWELL
                and previous_shadow_load is not None
            ):
                if active_episode.first_resolution_ready_epoch is None:
                    active_episode.first_resolution_ready_epoch = epoch_index
                if (
                    controller.load < MIN_ACTIVE_LOAD
                    and active_episode.first_actual_eligible_epoch is None
                ):
                    active_episode.first_actual_eligible_epoch = epoch_index
                if (
                    previous_shadow_load < MIN_ACTIVE_LOAD
                    and active_episode.first_shadow_eligible_epoch is None
                ):
                    active_episode.first_shadow_eligible_epoch = epoch_index

                eligibility_class = classify(controller.load, previous_shadow_load)
                if eligibility_class == "ACTUAL_BLOCKED_SHADOW_ELIGIBLE":
                    active_episode.had_actual_blocked_shadow_eligible = True

                pre_record = EligibilityRecord(
                    seed=seed,
                    protection_episode=protection_episode,
                    epoch_index=epoch_index,
                    phase=spec.phase,
                    resolution_strength=controller.resolution_strength,
                    actual_load=controller.load,
                    shadow_load=previous_shadow_load,
                    actual_backlog_before=backlog,
                    shadow_backlog_before=shadow_backlog,
                    eligibility_class=eligibility_class,
                )
                records.append(pre_record)

            # Obtain the exact same-state uncapped base command without mutating
            # the canonical controller. The real command() call follows.
            base_copy = deepcopy(controller.base)
            base_command = base_copy.command()
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.33 diagnostic forbids voluntary admission shedding")

            executes_full_protection = (
                controller.protective
                and controller.withdrawal_stage == controller.PROTECTED
            )
            if executes_full_protection and active_episode is None:
                protection_episode += 1
                active_episode = EpisodeSummary(
                    seed=seed,
                    protection_episode=protection_episode,
                )
                shadow_backlog = backlog
                previous_shadow_load = None

            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            backlog += admitted

            released = min(backlog, command.release_limit)
            backlog -= released

            if executes_full_protection:
                shadow_available = shadow_backlog + admitted
                shadow_released = min(shadow_available, base_command.release_limit)
                shadow_backlog = shadow_available - shadow_released
                previous_shadow_load = shadow_released / MAX_RELEASE_REFERENCE
                if active_episode is not None:
                    gap = backlog - shadow_backlog
                    active_episode.peak_actual_minus_shadow_backlog_gap = max(
                        active_episode.peak_actual_minus_shadow_backlog_gap,
                        gap,
                    )
            else:
                shadow_released = 0

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
                pre_record.actual_admitted = admitted
                pre_record.base_release_limit = base_command.release_limit
                pre_record.protected_release_limit = min(
                    base_command.release_limit,
                    BOOSTED_SAFE_CAP,
                )
                pre_record.actual_released = released
                pre_record.shadow_released = shadow_released
                pre_record.actual_backlog_after = backlog
                pre_record.shadow_backlog_after = shadow_backlog
                pre_record.rate_cap_binding = (
                    base_command.release_limit > BOOSTED_SAFE_CAP
                )

            # A transition out of PROTECTED starts a component-withdrawal
            # challenge. Close the current shadow episode even if observe()
            # immediately returns the canonical controller to PROTECTED.
            if (
                begins_full_protection
                and not executes_full_protection
                and active_episode is not None
            ):
                episodes.append(active_episode)
                active_episode = None
                previous_shadow_load = None

    if active_episode is not None:
        episodes.append(active_episode)

    return records, episodes, backlog, digest_mismatches


def med(records: list[EligibilityRecord], attr: str) -> float:
    if not records:
        return float("nan")
    return float(median(getattr(record, attr) for record in records))


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=backlog_mediated_load_gate_attribution_v0.33")
    print("controller=canonical_v0.30_unchanged")
    print("spent_v030_seeds=true")
    print("policy_promotion=false")
    print("threshold_tuning=false")
    print("controller_phase_blind=true")
    print("phase_labels_external_attribution_only=true")
    print("shadow_projection=same_state_uncapped_backlog_only")
    print("shadow_executes_tasks=false")
    print(f"MIN_ACTIVE_LOAD={MIN_ACTIVE_LOAD:.6f}")
    print(f"MAX_RELEASE_REFERENCE={MAX_RELEASE_REFERENCE:.6f}")
    print(f"BOOSTED_SAFE_CAP={BOOSTED_SAFE_CAP}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    all_records: list[EligibilityRecord] = []
    all_episodes: list[EpisodeSummary] = []
    terminal_backlogs: list[int] = []
    digest_mismatches = 0

    for seed in SEEDS:
        records, episodes, terminal_backlog, mismatches = run_seed(
            seed,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        all_records.extend(records)
        all_episodes.extend(episodes)
        terminal_backlogs.append(terminal_backlog)
        digest_mismatches += mismatches

    class_counts = Counter(record.eligibility_class for record in all_records)
    phase_class_counts = Counter(
        (record.phase, record.eligibility_class) for record in all_records
    )

    paired_delays = [
        (actual, shadow)
        for episode in all_episodes
        if (actual := episode.actual_delay()) is not None
        and (shadow := episode.shadow_delay()) is not None
    ]
    peak_gaps = [
        episode.peak_actual_minus_shadow_backlog_gap for episode in all_episodes
    ]
    seeds_with_shadow_earlier = {
        episode.seed
        for episode in all_episodes
        if episode.had_actual_blocked_shadow_eligible
    }

    shadow_earlier_records = [
        record
        for record in all_records
        if record.eligibility_class == "ACTUAL_BLOCKED_SHADOW_ELIGIBLE"
    ]
    shadow_earlier_active = [
        record for record in shadow_earlier_records if record.phase in ACTIVE_STRESS
    ]
    shadow_earlier_recovery = [
        record for record in shadow_earlier_records if record.phase in RECOVERY_DRAIN
    ]

    print("\n[backlog_mediated_attribution]")
    print(f"protection_episodes={len(all_episodes)}")
    print(f"resolution_ready_epochs={len(all_records)}")
    for name in (
        "BOTH_BLOCKED",
        "ACTUAL_BLOCKED_SHADOW_ELIGIBLE",
        "ACTUAL_ELIGIBLE_SHADOW_BLOCKED",
        "BOTH_ELIGIBLE",
    ):
        count = class_counts[name]
        print(
            f"class_{name}=count:{count},"
            f"fraction:{count / max(1, len(all_records)):.6f}"
        )

    print(
        "phase_class_counts="
        + ",".join(
            f"{phase}/{name}:{phase_class_counts[(phase, name)]}"
            for phase, name in sorted(phase_class_counts)
        )
    )

    for name in (
        "BOTH_BLOCKED",
        "ACTUAL_BLOCKED_SHADOW_ELIGIBLE",
        "ACTUAL_ELIGIBLE_SHADOW_BLOCKED",
        "BOTH_ELIGIBLE",
    ):
        rows = [record for record in all_records if record.eligibility_class == name]
        print(
            f"class={name} count={len(rows)} "
            f"median_actual_load={med(rows, 'actual_load'):.6f} "
            f"median_shadow_load={med(rows, 'shadow_load'):.6f} "
            f"median_actual_backlog={med(rows, 'actual_backlog_before'):.3f} "
            f"median_shadow_backlog={med(rows, 'shadow_backlog_before'):.3f} "
            f"median_backlog_gap={median([r.actual_backlog_before - r.shadow_backlog_before for r in rows]) if rows else float('nan'):.3f} "
            f"median_base_release={med(rows, 'base_release_limit'):.3f} "
            f"median_protected_release={med(rows, 'protected_release_limit'):.3f}"
        )

    paired_actual_delays = [actual for actual, _shadow in paired_delays]
    paired_shadow_delays = [shadow for _actual, shadow in paired_delays]
    median_actual_delay = (
        median(paired_actual_delays) if paired_actual_delays else float("nan")
    )
    median_shadow_delay = (
        median(paired_shadow_delays) if paired_shadow_delays else float("nan")
    )
    delay_differences = [actual - shadow for actual, shadow in paired_delays]
    median_delay_difference = (
        median(delay_differences) if delay_differences else float("nan")
    )
    median_peak_gap = median(peak_gaps) if peak_gaps else 0.0

    print(f"episodes_with_paired_delays={len(paired_delays)}")
    print(f"median_actual_ready_to_eligible_delay={median_actual_delay:.3f}")
    print(f"median_shadow_ready_to_eligible_delay={median_shadow_delay:.3f}")
    print(f"median_actual_minus_shadow_delay={median_delay_difference:.3f}")
    print(f"median_peak_actual_minus_shadow_backlog_gap={median_peak_gap:.3f}")
    print(
        f"seeds_with_actual_blocked_shadow_eligible="
        f"{len(seeds_with_shadow_earlier)}/{len(SEEDS)}"
    )
    print(
        f"fraction_shadow_earlier_epochs_active_stress="
        f"{len(shadow_earlier_active) / max(1, len(shadow_earlier_records)):.6f}"
    )
    print(
        f"fraction_shadow_earlier_epochs_recovery_drain="
        f"{len(shadow_earlier_recovery) / max(1, len(shadow_earlier_records)):.6f}"
    )
    print(f"median_terminal_actual_backlog={median(terminal_backlogs):.1f}")
    print(f"digest_mismatches={digest_mismatches}")

    support = (
        bool(paired_delays)
        and median_actual_delay > median_shadow_delay
        and len(seeds_with_shadow_earlier) >= 6
        and median_peak_gap > 0
        and median(terminal_backlogs) == 0
        and digest_mismatches == 0
    )

    if support:
        classification = "backlog_mediated_gate_delay_supported"
    elif (
        class_counts["BOTH_BLOCKED"]
        > class_counts["ACTUAL_BLOCKED_SHADOW_ELIGIBLE"]
        and paired_delays
        and median_delay_difference == 0
    ):
        classification = "cap_plateau_not_decision_relevant"
    elif median_peak_gap > 0 and paired_delays and median_delay_difference == 0:
        classification = "retained_work_without_gate_timing_effect"
    else:
        classification = "mixed_or_ambiguous"

    print("\n[diagnostic_interpretation]")
    print(f"classification={classification}")
    print(f"backlog_mediated_support_rule={str(support).lower()}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=not_applicable")
    print(
        "interpretation=v0.33 uses a same-state uncapped backlog projection "
        "to test whether canonical v0.30 RATE limiting dynamically delays "
        "the existing LOAD gate by retaining work, without changing policy."
    )


if __name__ == "__main__":
    main()
