from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from math import floor
from statistics import median

from active_load_gate_v030 import ActiveLoadGatedRateFirstMembrane
from bardocompute.exchange import ExchangeResult
from bidirectional_homeostasis import BOOSTED_SAFE_CAP
from computational_interoception_v019 import (
    HEALTHY_PAIN,
    MIN_ACTIVE_LOAD,
    RECOVERY_DWELL,
    RECOVERY_TRAJECTORY,
    RESTORED_RESERVE,
)
from real_work_queue_transfer import (
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)
from storage_reserve import ELASTIC_BUFFER_LIMIT

# Fresh family frozen in issue #28 before implementation/results.
SEEDS = (
    19_100_677,
    19_200_681,
    19_300_687,
    19_400_693,
    19_500_699,
    19_600_707,
    19_700_711,
    19_800_719,
)
MAX_CANDIDATES_PER_SEED = 3
DOSE_BLOCKS = 3
DOSE_FRACTIONS = (0.0, 0.25, 0.50, 0.75, 1.0)


@dataclass(frozen=True, slots=True)
class Candidate:
    seed: int
    ordinal: int
    epoch_index: int
    phase: str
    pain: float
    load: float
    reserve: float
    trajectory: float
    resolution_strength: int
    backlog: int
    incoming: int
    admitted: int
    available: int
    base_release_limit: int
    protected_release: int
    uncapped_release: int
    withdrawal_delta: int
    secondary_fraction: float
    relief_active: bool
    primary_multiplier: float
    secondary_multiplier: float


@dataclass(frozen=True, slots=True)
class DoseArm:
    label: str
    fraction: float
    release: int


@dataclass(frozen=True, slots=True)
class ArmResult:
    label: str
    fraction: float
    released: int
    on_time_primary: int
    on_time_secondary: int
    on_time_relief: int
    total_on_time: int
    total_missed: int
    miss_fraction: float
    wall_seconds: float
    digest_mismatches: int


@dataclass(frozen=True, slots=True)
class DoseRun:
    candidate: Candidate
    block: int
    order_position: int
    order_signature: str
    result: ArmResult


@dataclass(frozen=True, slots=True)
class DosePoint:
    candidate: Candidate
    label: str
    fraction: float
    release: float
    on_time: float
    missed: float
    miss_fraction: float
    wall_seconds: float


@dataclass(frozen=True, slots=True)
class MarginalEffect:
    candidate: Candidate
    interval: str
    low_fraction: float
    high_fraction: float
    marginal_release: float
    marginal_on_time_gain: float
    marginal_additional_missed: float
    marginal_miss_fraction: float
    marginal_wall_seconds: float
    marginal_on_time_yield: float
    marginal_miss_yield: float


@dataclass(frozen=True, slots=True)
class FullEffect:
    candidate: Candidate
    additional_release: float
    net_on_time_gain: float
    additional_missed: float
    miss_fraction_delta: float
    wall_seconds_delta: float
    on_time_yield: float
    miss_yield: float


def round_half_up(value: float) -> int:
    if value < 0:
        raise ValueError("round_half_up expects non-negative values")
    return int(floor(value + 0.5))


def dose_arms(candidate: Candidate) -> tuple[list[DoseArm], int]:
    by_release: dict[int, DoseArm] = {}
    for index, fraction in enumerate(DOSE_FRACTIONS):
        release = candidate.protected_release + round_half_up(
            fraction * candidate.withdrawal_delta
        )
        release = max(
            candidate.protected_release,
            min(candidate.uncapped_release, release),
        )
        # Preserve the first nominal dose that maps to a given integer release.
        # Endpoints are guaranteed by the frozen construction.
        by_release.setdefault(
            release,
            DoseArm(label=f"D{index}", fraction=fraction, release=release),
        )

    arms = sorted(by_release.values(), key=lambda arm: arm.release)
    if not arms or arms[0].release != candidate.protected_release:
        raise AssertionError("D0 protected endpoint missing")
    if arms[-1].release != candidate.uncapped_release:
        # If D4 rounded onto an existing release, retain the endpoint semantics.
        existing = by_release[candidate.uncapped_release]
        arms[-1] = DoseArm(
            label="D4",
            fraction=1.0,
            release=existing.release,
        )
    deduplicated = len(DOSE_FRACTIONS) - len(arms)
    return arms, deduplicated


def execute_arm(
    candidate: Candidate,
    arm: DoseArm,
    *,
    rounds: int,
    deadline_seconds: float,
) -> ArmResult:
    released = arm.release
    relief_count = 0
    if candidate.relief_active and released:
        relief_count = min(
            released,
            int(round(released * RELIEF_TASK_FRACTION)),
        )
    ordinary = released - relief_count
    secondary_count = min(
        ordinary,
        max(0, int(round(ordinary * candidate.secondary_fraction))),
    )
    primary_count = ordinary - secondary_count

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()
        elapsed, p_on, s_on, r_on, mismatches = _execute_batch(
            primary=primary,
            secondary=secondary,
            relief=relief,
            primary_count=primary_count,
            secondary_count=secondary_count,
            relief_count=relief_count,
            rounds=rounds,
            primary_multiplier=candidate.primary_multiplier,
            secondary_multiplier=candidate.secondary_multiplier,
            deadline_seconds=deadline_seconds,
        )

    total_on_time = p_on + s_on + r_on
    total_missed = max(0, released - total_on_time)
    return ArmResult(
        label=arm.label,
        fraction=arm.fraction,
        released=released,
        on_time_primary=p_on,
        on_time_secondary=s_on,
        on_time_relief=r_on,
        total_on_time=total_on_time,
        total_missed=total_missed,
        miss_fraction=total_missed / max(1, released),
        wall_seconds=elapsed,
        digest_mismatches=mismatches,
    )


def collect_candidates(
    seed: int,
    *,
    rounds: int,
    deadline_seconds: float,
) -> tuple[list[Candidate], int, int]:
    controller = ActiveLoadGatedRateFirstMembrane()
    queue = list(build_epochs(seed))
    queue.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

    candidates: list[Candidate] = []
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

        for epoch_index, spec in enumerate(queue):
            if spec.phase == "drain" and backlog == 0:
                break

            pre_full_protection = (
                controller.protective
                and controller.withdrawal_stage == controller.PROTECTED
            )
            base_copy = deepcopy(controller.base)
            base_command = base_copy.command()

            protected_capacity = max(0, ELASTIC_BUFFER_LIMIT - backlog)
            predicted_admitted = min(spec.incoming, protected_capacity)
            predicted_available = backlog + predicted_admitted
            predicted_uncapped = min(
                predicted_available,
                base_command.release_limit,
            )
            predicted_protected = min(predicted_uncapped, BOOSTED_SAFE_CAP)
            binding = predicted_uncapped > predicted_protected

            if (
                len(candidates) < MAX_CANDIDATES_PER_SEED
                and pre_full_protection
                and controller.resolution_strength >= RECOVERY_DWELL
                and binding
            ):
                candidates.append(
                    Candidate(
                        seed=seed,
                        ordinal=len(candidates) + 1,
                        epoch_index=epoch_index,
                        phase=spec.phase,
                        pain=controller.pain,
                        load=controller.load,
                        reserve=controller.reserve,
                        trajectory=controller.trajectory,
                        resolution_strength=controller.resolution_strength,
                        backlog=backlog,
                        incoming=spec.incoming,
                        admitted=predicted_admitted,
                        available=predicted_available,
                        base_release_limit=base_command.release_limit,
                        protected_release=predicted_protected,
                        uncapped_release=predicted_uncapped,
                        withdrawal_delta=predicted_uncapped - predicted_protected,
                        secondary_fraction=base_command.secondary_fraction,
                        relief_active=True,
                        primary_multiplier=spec.primary_multiplier,
                        secondary_multiplier=spec.secondary_multiplier,
                    )
                )

            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.36 canonical path forbids admission shedding")

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
                    overflow_dropped=overflow,
                )
            )

    return candidates, backlog, digest_mismatches


def build_points(
    candidate: Candidate,
    runs: list[DoseRun],
) -> list[DosePoint]:
    by_release: dict[int, list[ArmResult]] = defaultdict(list)
    labels: dict[int, tuple[str, float]] = {}
    for run in runs:
        result = run.result
        by_release[result.released].append(result)
        labels[result.released] = (result.label, result.fraction)

    points: list[DosePoint] = []
    for release in sorted(by_release):
        rows = by_release[release]
        label, fraction = labels[release]
        points.append(
            DosePoint(
                candidate=candidate,
                label=label,
                fraction=fraction,
                release=float(median(row.released for row in rows)),
                on_time=float(median(row.total_on_time for row in rows)),
                missed=float(median(row.total_missed for row in rows)),
                miss_fraction=float(median(row.miss_fraction for row in rows)),
                wall_seconds=float(median(row.wall_seconds for row in rows)),
            )
        )
    return points


def build_marginals(points: list[DosePoint]) -> list[MarginalEffect]:
    effects: list[MarginalEffect] = []
    for low, high in zip(points, points[1:]):
        marginal_release = high.release - low.release
        on_time_gain = high.on_time - low.on_time
        additional_missed = high.missed - low.missed
        effects.append(
            MarginalEffect(
                candidate=low.candidate,
                interval=f"{low.label}->{high.label}",
                low_fraction=low.fraction,
                high_fraction=high.fraction,
                marginal_release=marginal_release,
                marginal_on_time_gain=on_time_gain,
                marginal_additional_missed=additional_missed,
                marginal_miss_fraction=high.miss_fraction - low.miss_fraction,
                marginal_wall_seconds=high.wall_seconds - low.wall_seconds,
                marginal_on_time_yield=on_time_gain / max(1.0, marginal_release),
                marginal_miss_yield=additional_missed / max(1.0, marginal_release),
            )
        )
    return effects


def build_full_effect(points: list[DosePoint]) -> FullEffect:
    if len(points) < 2:
        raise ValueError("candidate has fewer than two unique dose points")
    low = points[0]
    high = points[-1]
    additional_release = high.release - low.release
    on_time_gain = high.on_time - low.on_time
    additional_missed = high.missed - low.missed
    return FullEffect(
        candidate=low.candidate,
        additional_release=additional_release,
        net_on_time_gain=on_time_gain,
        additional_missed=additional_missed,
        miss_fraction_delta=high.miss_fraction - low.miss_fraction,
        wall_seconds_delta=high.wall_seconds - low.wall_seconds,
        on_time_yield=on_time_gain / max(1.0, additional_release),
        miss_yield=additional_missed / max(1.0, additional_release),
    )


def med(rows: list[object], attr: str) -> float:
    if not rows:
        return float("nan")
    return float(median(getattr(row, attr) for row in rows))


def print_interval_group(
    dimension: str,
    value: str,
    interval: str,
    rows: list[MarginalEffect],
) -> None:
    print(
        f"group={dimension}:{value} interval={interval} n={len(rows)} "
        f"median_marginal_release={med(rows, 'marginal_release'):.3f} "
        f"median_marginal_on_time_gain={med(rows, 'marginal_on_time_gain'):.3f} "
        f"median_marginal_additional_missed={med(rows, 'marginal_additional_missed'):.3f} "
        f"median_marginal_on_time_yield={med(rows, 'marginal_on_time_yield'):.6f} "
        f"median_marginal_miss_yield={med(rows, 'marginal_miss_yield'):.6f}"
    )


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("diagnostic=partial_rate_withdrawal_dose_response_v0.36")
    print("controller=canonical_v0.30_unchanged")
    print("fresh_seed_family=true")
    print("policy_promotion=false")
    print("risk_budget_selection=false")
    print("threshold_tuning=false")
    print("controller_phase_blind=true")
    print("phase_labels_external_attribution_only=true")
    print("probe_results_update_canonical_state=false")
    print(f"dose_fractions={','.join(f'{value:.2f}' for value in DOSE_FRACTIONS)}")
    print(f"dose_blocks={DOSE_BLOCKS}")
    print(f"max_candidates_per_seed={MAX_CANDIDATES_PER_SEED}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")

    candidates: list[Candidate] = []
    terminal_backlogs: list[int] = []
    canonical_digest_mismatches = 0
    for seed in SEEDS:
        rows, terminal_backlog, mismatches = collect_candidates(
            seed,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        candidates.extend(rows)
        terminal_backlogs.append(terminal_backlog)
        canonical_digest_mismatches += mismatches

    all_runs: list[DoseRun] = []
    by_candidate_runs: dict[tuple[int, int], list[DoseRun]] = defaultdict(list)
    total_deduplicated_arms = 0
    probe_digest_mismatches = 0

    for candidate in candidates:
        arms, deduplicated = dose_arms(candidate)
        total_deduplicated_arms += deduplicated
        for block in range(DOSE_BLOCKS):
            offset = (candidate.seed + candidate.ordinal + block) % len(arms)
            ordered = arms[offset:] + arms[:offset]
            signature = ">".join(arm.label for arm in ordered)
            for position, arm in enumerate(ordered):
                result = execute_arm(
                    candidate,
                    arm,
                    rounds=rounds,
                    deadline_seconds=deadline_seconds,
                )
                probe_digest_mismatches += result.digest_mismatches
                run = DoseRun(
                    candidate=candidate,
                    block=block,
                    order_position=position,
                    order_signature=signature,
                    result=result,
                )
                all_runs.append(run)
                by_candidate_runs[(candidate.seed, candidate.ordinal)].append(run)

    all_points: list[DosePoint] = []
    all_marginals: list[MarginalEffect] = []
    full_effects: list[FullEffect] = []
    for candidate in candidates:
        key = (candidate.seed, candidate.ordinal)
        points = build_points(candidate, by_candidate_runs[key])
        all_points.extend(points)
        all_marginals.extend(build_marginals(points))
        full_effects.append(build_full_effect(points))

    seeds_with_candidates = {candidate.seed for candidate in candidates}
    phase_counts = Counter(candidate.phase for candidate in candidates)
    interval_rows: dict[str, list[MarginalEffect]] = defaultdict(list)
    for effect in all_marginals:
        interval_rows[effect.interval].append(effect)

    print("\n[dose_response]")
    print(f"seeds_with_binding_candidate={len(seeds_with_candidates)}/{len(SEEDS)}")
    print(f"binding_candidates={len(candidates)}")
    print(f"nominal_arms_per_candidate={len(DOSE_FRACTIONS)}")
    print(f"total_deduplicated_arms={total_deduplicated_arms}")
    print(f"executed_arm_runs={len(all_runs)}")
    print(
        "candidate_phase_counts="
        + ",".join(f"{name}:{phase_counts[name]}" for name in sorted(phase_counts))
    )

    for label in ("D0", "D1", "D2", "D3", "D4"):
        rows = [point for point in all_points if point.label == label]
        if not rows:
            continue
        print(
            f"dose={label} n={len(rows)} "
            f"median_fraction={med(rows, 'fraction'):.2f} "
            f"median_release={med(rows, 'release'):.3f} "
            f"median_on_time={med(rows, 'on_time'):.3f} "
            f"median_missed={med(rows, 'missed'):.3f} "
            f"median_miss_fraction={med(rows, 'miss_fraction'):.6f} "
            f"median_wall_seconds={med(rows, 'wall_seconds'):.6f}"
        )

    standard_intervals = ("D0->D1", "D1->D2", "D2->D3", "D3->D4")
    for interval in sorted(interval_rows):
        rows = interval_rows[interval]
        print(
            f"interval={interval} n={len(rows)} "
            f"median_marginal_release={med(rows, 'marginal_release'):.3f} "
            f"median_marginal_on_time_gain={med(rows, 'marginal_on_time_gain'):.3f} "
            f"median_marginal_additional_missed={med(rows, 'marginal_additional_missed'):.3f} "
            f"median_marginal_on_time_yield={med(rows, 'marginal_on_time_yield'):.6f} "
            f"median_marginal_miss_yield={med(rows, 'marginal_miss_yield'):.6f} "
            f"median_marginal_miss_fraction={med(rows, 'marginal_miss_fraction'):.6f} "
            f"median_marginal_wall_seconds={med(rows, 'marginal_wall_seconds'):.6f} "
            f"fraction_positive_on_time_gain="
            f"{sum(row.marginal_on_time_gain > 0 for row in rows) / max(1, len(rows)):.6f} "
            f"fraction_nonpositive_additional_missed="
            f"{sum(row.marginal_additional_missed <= 0 for row in rows) / max(1, len(rows)):.6f}"
        )

    print(
        f"full_median_withdrawal_delta={med(full_effects, 'additional_release'):.3f}"
    )
    print(
        f"full_median_net_on_time_gain={med(full_effects, 'net_on_time_gain'):.3f}"
    )
    print(
        f"full_median_additional_missed={med(full_effects, 'additional_missed'):.3f}"
    )
    print(f"full_median_on_time_yield={med(full_effects, 'on_time_yield'):.6f}")
    print(f"full_median_miss_yield={med(full_effects, 'miss_yield'):.6f}")

    position_rows: dict[int, list[DoseRun]] = defaultdict(list)
    for run in all_runs:
        position_rows[run.order_position].append(run)
    print("\n[arm_order]")
    for position in sorted(position_rows):
        rows = position_rows[position]
        print(
            f"position={position} n={len(rows)} "
            f"median_wall_seconds={median(run.result.wall_seconds for run in rows):.6f} "
            f"median_on_time={median(run.result.total_on_time for run in rows):.3f} "
            f"median_missed={median(run.result.total_missed for run in rows):.3f}"
        )

    grouped: dict[tuple[str, str, str], list[MarginalEffect]] = defaultdict(list)
    for effect in all_marginals:
        candidate = effect.candidate
        grouped[("phase", candidate.phase, effect.interval)].append(effect)
        grouped[
            (
                "pain",
                "low" if candidate.pain <= HEALTHY_PAIN else "high",
                effect.interval,
            )
        ].append(effect)
        grouped[
            (
                "load",
                "low" if candidate.load < MIN_ACTIVE_LOAD else "high",
                effect.interval,
            )
        ].append(effect)
        grouped[
            (
                "reserve",
                "restored" if candidate.reserve >= RESTORED_RESERVE else "low",
                effect.interval,
            )
        ].append(effect)
        grouped[
            (
                "trajectory",
                "nonworsening"
                if candidate.trajectory <= RECOVERY_TRAJECTORY
                else "worsening",
                effect.interval,
            )
        ].append(effect)
        grouped[
            ("resolution_strength", str(candidate.resolution_strength), effect.interval)
        ].append(effect)

    print("\n[preexisting_signal_groups]")
    for (dimension, value, interval), rows in sorted(grouped.items()):
        print_interval_group(dimension, value, interval, rows)

    print(f"median_terminal_canonical_backlog={median(terminal_backlogs):.1f}")
    print(f"canonical_digest_mismatches={canonical_digest_mismatches}")
    print(f"probe_digest_mismatches={probe_digest_mismatches}")

    enough_candidates = len(seeds_with_candidates) >= 6
    complete_standard_curve = all(interval in interval_rows for interval in standard_intervals)
    on_time_yields = [
        med(interval_rows[interval], "marginal_on_time_yield")
        for interval in standard_intervals
        if interval in interval_rows
    ]
    miss_yields = [
        med(interval_rows[interval], "marginal_miss_yield")
        for interval in standard_intervals
        if interval in interval_rows
    ]
    front_loaded_directional = (
        complete_standard_curve
        and all(
            on_time_yields[index] >= on_time_yields[index + 1]
            for index in range(len(on_time_yields) - 1)
        )
        and all(
            miss_yields[index] <= miss_yields[index + 1]
            for index in range(len(miss_yields) - 1)
        )
        and on_time_yields[0] > on_time_yields[-1]
        and miss_yields[0] < miss_yields[-1]
    )
    back_loaded_directional = (
        complete_standard_curve
        and all(
            on_time_yields[index] <= on_time_yields[index + 1]
            for index in range(len(on_time_yields) - 1)
        )
        and all(
            miss_yields[index] >= miss_yields[index + 1]
            for index in range(len(miss_yields) - 1)
        )
        and on_time_yields[0] < on_time_yields[-1]
        and miss_yields[0] > miss_yields[-1]
    )

    if not enough_candidates:
        classification = "underpowered_binding_opportunities"
    elif front_loaded_directional:
        classification = "front_loaded_directional"
    elif back_loaded_directional:
        classification = "back_loaded_directional"
    else:
        classification = "mixed_or_requires_cross_runtime_review"

    print("\n[diagnostic_interpretation]")
    print(f"classification={classification}")
    print(f"candidate_power_sufficient={str(enough_candidates).lower()}")
    print(f"complete_standard_curve={str(complete_standard_curve).lower()}")
    print("diagnostic_complete=true")
    print("passes_preregistered_acceptance=not_applicable")
    print(
        "interpretation=v0.36 measures a preregistered matched partial-withdrawal "
        "dose-response curve without changing the canonical controller or "
        "selecting a production dose."
    )


if __name__ == "__main__":
    main()
