from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import median

from recovery_state_transfer import (
    HAZARDS,
    SEEDS,
    HazardEstimator,
    RecoveryEnvironment,
    build_environment,
    cadence,
)

FIXED_INTERVALS = (1, 8, 16, 32, 64, 128)
COST_PROFILES = ((2.0, 5.0), (8.0, 5.0), (32.0, 5.0))
ACTION_SPACE = 16


@dataclass(frozen=True, slots=True)
class DecisionArtifact:
    decision_ref: int
    authority_epoch: int
    bound_action: int


@dataclass(slots=True)
class AgentStats:
    revalidations: int = 0
    attempted_actions: int = 0
    applied_actions: int = 0
    rejected_actions: int = 0
    stale_authority_effects: int = 0
    wrong_action_effects: int = 0
    replay_effects: int = 0
    unsafe_effects_total: int = 0
    rejected_stale: int = 0
    rejected_wrong_action: int = 0
    rejected_replay: int = 0
    interval_sum: int = 0
    interval_count: int = 0
    interval_by_hazard_sum: dict[float, int] = field(
        default_factory=lambda: {hazard: 0 for hazard in HAZARDS}
    )
    interval_by_hazard_count: dict[float, int] = field(
        default_factory=lambda: {hazard: 0 for hazard in HAZARDS}
    )


def requested_action(step: int) -> int:
    # Four-tick action runs make some replay attacks action-compatible, so replay
    # protection is tested independently rather than always collapsing into a
    # wrong-action rejection.
    return (step // 4) % ACTION_SPACE


def noise(seed: int, step: int) -> tuple[bool, bool]:
    rng = random.Random(seed ^ (step * 0x9E3779B1) ^ 0xA63E11CE)
    wrong_binding = rng.random() < 0.0125
    replay = rng.random() < 0.0180
    return wrong_binding, replay


def living_process_fence(
    decision: DecisionArtifact,
    *,
    current_epoch: int,
    requested: int,
    consumed_refs: set[int],
) -> bool:
    if decision.authority_epoch != current_epoch:
        return False
    if decision.bound_action != requested:
        return False
    if decision.decision_ref in consumed_refs:
        return False
    return True


def conventional_equal_information_fence(
    decision: DecisionArtifact,
    *,
    current_epoch: int,
    requested: int,
    consumed_refs: set[int],
) -> bool:
    # Deliberately independent formulation with exactly the same information.
    epoch_current = decision.authority_epoch == current_epoch
    action_bound = decision.bound_action == requested
    unused_reference = decision.decision_ref not in consumed_refs
    return epoch_current and action_bound and unused_reference


def choose_interval(
    *,
    mode: str,
    estimator: HazardEstimator,
    revalidation_cost: float,
    rejection_cost: float,
    fixed_interval: int | None,
) -> int:
    if fixed_interval is not None:
        return fixed_interval
    return cadence(estimator.value(), revalidation_cost, rejection_cost)


def run_policy(
    environment: RecoveryEnvironment,
    *,
    seed: int,
    mode: str,
    revalidation_cost: float,
    rejection_cost: float,
    fixed_interval: int | None = None,
    fence_impl: str | None,
) -> AgentStats:
    stats = AgentStats()
    estimator = HazardEstimator(mode=mode if mode in {"ewma", "rolling"} else "ewma")
    authority_epoch = 0
    cached_epoch = 0
    last_revalidation_epoch = 0
    last_revalidation_step = 0
    consumed_refs: set[int] = set()
    last_successful_decision: DecisionArtifact | None = None

    interval = choose_interval(
        mode=mode,
        estimator=estimator,
        revalidation_cost=revalidation_cost,
        rejection_cost=rejection_cost,
        fixed_interval=fixed_interval,
    )
    next_revalidation = 0

    for step, restarted in enumerate(environment.restarts):
        if restarted:
            authority_epoch += 1

        if step >= next_revalidation:
            stats.revalidations += 1
            exposure = max(1, step - last_revalidation_step)
            events = authority_epoch - last_revalidation_epoch
            if mode in {"ewma", "rolling"}:
                estimator.update(events, exposure)
            cached_epoch = authority_epoch
            last_revalidation_epoch = authority_epoch
            last_revalidation_step = step

            interval = choose_interval(
                mode=mode,
                estimator=estimator,
                revalidation_cost=revalidation_cost,
                rejection_cost=rejection_cost,
                fixed_interval=fixed_interval,
            )
            stats.interval_sum += interval
            stats.interval_count += 1
            hazard = environment.hazards[step]
            stats.interval_by_hazard_sum[hazard] += interval
            stats.interval_by_hazard_count[hazard] += 1
            next_revalidation = step + interval

        requested = requested_action(step)
        decision = DecisionArtifact(
            decision_ref=(seed << 32) ^ (step + 1),
            authority_epoch=cached_epoch,
            bound_action=requested,
        )

        wrong_binding, replay_attempt = noise(seed, step)
        if replay_attempt and last_successful_decision is not None:
            decision = last_successful_decision
        elif wrong_binding:
            decision = DecisionArtifact(
                decision_ref=decision.decision_ref,
                authority_epoch=decision.authority_epoch,
                bound_action=(requested + 1) % ACTION_SPACE,
            )

        stale = decision.authority_epoch != authority_epoch
        wrong = decision.bound_action != requested
        replayed = decision.decision_ref in consumed_refs
        unsafe = stale or wrong or replayed

        stats.attempted_actions += 1

        if fence_impl is None:
            allowed = True
        elif fence_impl == "living":
            allowed = living_process_fence(
                decision,
                current_epoch=authority_epoch,
                requested=requested,
                consumed_refs=consumed_refs,
            )
        elif fence_impl == "conventional":
            allowed = conventional_equal_information_fence(
                decision,
                current_epoch=authority_epoch,
                requested=requested,
                consumed_refs=consumed_refs,
            )
        else:
            raise ValueError(fence_impl)

        if not allowed:
            stats.rejected_actions += 1
            stats.rejected_stale += int(stale)
            stats.rejected_wrong_action += int(wrong)
            stats.rejected_replay += int(replayed)
            continue

        stats.applied_actions += 1
        stats.stale_authority_effects += int(stale)
        stats.wrong_action_effects += int(wrong)
        stats.replay_effects += int(replayed)
        stats.unsafe_effects_total += int(unsafe)
        consumed_refs.add(decision.decision_ref)
        last_successful_decision = decision

    return stats


def operational_cost(stats: AgentStats, revalidation_cost: float, rejection_cost: float) -> float:
    return stats.revalidations * revalidation_cost + stats.rejected_actions * rejection_cost


def nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def assert_equal_information(a: AgentStats, b: AgentStats) -> None:
    fields = (
        "revalidations",
        "attempted_actions",
        "applied_actions",
        "rejected_actions",
        "stale_authority_effects",
        "wrong_action_effects",
        "replay_effects",
        "unsafe_effects_total",
        "rejected_stale",
        "rejected_wrong_action",
        "rejected_replay",
    )
    for field_name in fields:
        if getattr(a, field_name) != getattr(b, field_name):
            raise AssertionError(
                f"equal-information fence mismatch: {field_name}: "
                f"{getattr(a, field_name)} != {getattr(b, field_name)}"
            )


def main() -> None:
    environments = [(seed, build_environment(seed)) for seed in SEEDS]

    print("benchmark=agent_evidence_decision_action_transfer_v0.11")
    print(f"seeds={len(environments)}")
    print("future_authority_boundaries_and_hazards=hidden")
    print("decision_binding=authority_epoch+bound_action+single_use_decision_ref")
    print("proof_is_dispatch_receipt=false")
    print("state_hash_implies_live_freshness=false")

    # Semantic attack first, using the frozen middle cost profile.
    artifact_rows: list[AgentStats] = []
    per_action_rows: list[AgentStats] = []
    ewma_rows: list[AgentStats] = []
    rolling_rows: list[AgentStats] = []

    semantic_revalidation_cost = 8.0
    semantic_rejection_cost = 5.0

    for seed, environment in environments:
        artifact = run_policy(
            environment,
            seed=seed,
            mode="ewma",
            revalidation_cost=semantic_revalidation_cost,
            rejection_cost=semantic_rejection_cost,
            fence_impl=None,
        )
        artifact_rows.append(artifact)

        per_action = run_policy(
            environment,
            seed=seed,
            mode="fixed",
            revalidation_cost=semantic_revalidation_cost,
            rejection_cost=semantic_rejection_cost,
            fixed_interval=1,
            fence_impl="living",
        )
        per_action_rows.append(per_action)

        for mode, rows in (("ewma", ewma_rows), ("rolling", rolling_rows)):
            living = run_policy(
                environment,
                seed=seed,
                mode=mode,
                revalidation_cost=semantic_revalidation_cost,
                rejection_cost=semantic_rejection_cost,
                fence_impl="living",
            )
            conventional = run_policy(
                environment,
                seed=seed,
                mode=mode,
                revalidation_cost=semantic_revalidation_cost,
                rejection_cost=semantic_rejection_cost,
                fence_impl="conventional",
            )
            assert_equal_information(living, conventional)
            rows.append(living)

    artifact_stale = sum(row.stale_authority_effects for row in artifact_rows)
    artifact_wrong = sum(row.wrong_action_effects for row in artifact_rows)
    artifact_replay = sum(row.replay_effects for row in artifact_rows)
    artifact_unsafe = sum(row.unsafe_effects_total for row in artifact_rows)

    print("\n[semantic_transfer]")
    print(f"artifact_only_stale_authority_effects={artifact_stale}")
    print(f"artifact_only_wrong_action_effects={artifact_wrong}")
    print(f"artifact_only_replay_effects={artifact_replay}")
    print(f"artifact_only_unsafe_effects_total={artifact_unsafe}")

    for name, rows in (
        ("per_action_fenced", per_action_rows),
        ("ewma_fenced", ewma_rows),
        ("rolling_fenced", rolling_rows),
    ):
        unsafe = sum(row.unsafe_effects_total for row in rows)
        print(
            f"{name}: unsafe_effects_total={unsafe} "
            f"median_revalidations={median(row.revalidations for row in rows):.1f} "
            f"median_rejections={median(row.rejected_actions for row in rows):.1f}"
        )

    equal_information_ok = True
    semantic_pass = (
        artifact_stale > 0
        and artifact_wrong > 0
        and artifact_replay > 0
        and all(row.unsafe_effects_total == 0 for row in per_action_rows)
        and all(row.unsafe_effects_total == 0 for row in ewma_rows)
        and all(row.unsafe_effects_total == 0 for row in rolling_rows)
        and median(row.revalidations for row in ewma_rows)
        < median(row.revalidations for row in per_action_rows)
        and median(row.revalidations for row in rolling_rows)
        < median(row.revalidations for row in per_action_rows)
    )
    print(f"equal_information_fence_equivalence={str(equal_information_ok).lower()}")
    print(f"passes_preregistered_semantic_acceptance={str(semantic_pass).lower()}")

    # Secondary economics: adaptive fenced policies versus strongest fixed fenced.
    overall_ratios = {"ewma": [], "rolling": []}
    overall_revalidation_ratios = {"ewma": [], "rolling": []}
    phase_intervals = {
        "ewma": {hazard: [] for hazard in HAZARDS},
        "rolling": {hazard: [] for hazard in HAZARDS},
    }

    print("\n[economic_transfer_secondary]")
    for revalidation_cost, rejection_cost in COST_PROFILES:
        profile_ratios = {"ewma": [], "rolling": []}

        for seed, environment in environments:
            fixed_rows: list[tuple[float, AgentStats, int]] = []
            for fixed_interval in FIXED_INTERVALS:
                fixed = run_policy(
                    environment,
                    seed=seed,
                    mode="fixed",
                    revalidation_cost=revalidation_cost,
                    rejection_cost=rejection_cost,
                    fixed_interval=fixed_interval,
                    fence_impl="living",
                )
                if fixed.unsafe_effects_total != 0:
                    raise AssertionError("fenced fixed policy applied unsafe action")
                fixed_rows.append(
                    (
                        operational_cost(fixed, revalidation_cost, rejection_cost),
                        fixed,
                        fixed_interval,
                    )
                )

            best_fixed_cost, best_fixed_stats, _ = min(fixed_rows, key=lambda row: row[0])

            for mode in ("ewma", "rolling"):
                living = run_policy(
                    environment,
                    seed=seed,
                    mode=mode,
                    revalidation_cost=revalidation_cost,
                    rejection_cost=rejection_cost,
                    fence_impl="living",
                )
                conventional = run_policy(
                    environment,
                    seed=seed,
                    mode=mode,
                    revalidation_cost=revalidation_cost,
                    rejection_cost=rejection_cost,
                    fence_impl="conventional",
                )
                assert_equal_information(living, conventional)
                if living.unsafe_effects_total != 0:
                    raise AssertionError("adaptive fence applied unsafe action")

                cost = operational_cost(living, revalidation_cost, rejection_cost)
                ratio = cost / best_fixed_cost
                profile_ratios[mode].append(ratio)
                overall_ratios[mode].append(ratio)
                overall_revalidation_ratios[mode].append(
                    living.revalidations / max(1, best_fixed_stats.revalidations)
                )

                for hazard in HAZARDS:
                    count = living.interval_by_hazard_count[hazard]
                    if count:
                        phase_intervals[mode][hazard].append(
                            living.interval_by_hazard_sum[hazard] / count
                        )

        print(
            f"[revalidation_cost={revalidation_cost:.0f},rejection_cost={rejection_cost:.0f}]"
        )
        for mode in ("ewma", "rolling"):
            ratios = profile_ratios[mode]
            print(
                f"{mode}: win_rate={sum(value < 1.0 for value in ratios) / len(ratios):.3f} "
                f"median_cost_ratio={median(ratios):.3f} "
                f"p90_cost_ratio={nearest_rank(ratios, .90):.3f} "
                f"worst_cost_ratio={max(ratios):.3f}"
            )

    print("\n[overall_secondary_economics]")
    for mode in ("ewma", "rolling"):
        ratios = overall_ratios[mode]
        print(
            f"{mode}: win_rate={sum(value < 1.0 for value in ratios) / len(ratios):.3f} "
            f"median_cost_ratio={median(ratios):.3f} "
            f"p90_cost_ratio={nearest_rank(ratios, .90):.3f} "
            f"worst_cost_ratio={max(ratios):.3f} "
            f"median_revalidation_ratio_vs_best_fixed="
            f"{median(overall_revalidation_ratios[mode]):.3f}"
        )
        print(
            f"{mode}_median_interval_by_true_hidden_hazard="
            + "/".join(
                f"{hazard:.4f}:{median(phase_intervals[mode][hazard]):.1f}"
                for hazard in HAZARDS
            )
        )

    print(
        "interpretation=A cached proof/decision artifact is not treated as a dispatch "
        "receipt or a live freshness guarantee. Hidden authority changes, wrong-action "
        "bindings, and consumed decision references create unsafe applied effects in "
        "artifact-only execution. Equal-information resource fences reject those "
        "attempts with zero unsafe applied effects, while adaptive evidence "
        "revalidation can remain sparse. Rejections are availability cost, not proof "
        "that dispatch happened."
    )


if __name__ == "__main__":
    main()
