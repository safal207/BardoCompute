from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from hazard_cadence_robustness import (
    FIXED_INTERVALS,
    PROBE_COSTS,
    SEEDS,
    STALE_REGRETS,
    HazardEstimator,
    build_environment,
    mean_loss,
    percentile_nearest_rank,
    run,
)
from bardocompute.headroom_gate import (
    HeadroomGateEvidence,
    evaluate_headroom_gate,
)


@dataclass(slots=True)
class GatedStats:
    loss: float = 0.0
    probes: int = 0
    stale_steps: int = 0
    interval_sum: int = 0
    interval_count: int = 0
    gated_decisions: int = 0


def recent_confidence_counts(estimator: HazardEstimator) -> tuple[int, int]:
    # Same weak prior as the robustness estimator, plus only recent paid probes.
    events = 1 + sum(events for events, _ in estimator.rolling)
    exposure = 128 + sum(exposure for _, exposure in estimator.rolling)
    return events, exposure


def gated_ewma_run(environment, *, probe_cost: float, stale_regret: float) -> GatedStats:
    stats = GatedStats()
    estimator = HazardEstimator(mode="ewma")
    current_epoch = 0
    calibrated_epoch = 0
    last_probe_epoch = 0
    last_probe_step = 0

    events, exposure = recent_confidence_counts(estimator)
    first = evaluate_headroom_gate(
        HeadroomGateEvidence(
            point_hazard=estimator.value(),
            recent_events=events,
            recent_exposure=exposure,
            regret_given_change=stale_regret,
            probe_cost=probe_cost,
            min_interval=8,
            max_interval=256,
        )
    )
    interval = first.interval
    stats.gated_decisions += int(first.gated_to_minimum)
    next_probe = interval

    for step, changed in enumerate(environment.changes):
        if changed:
            current_epoch += 1
        if current_epoch != calibrated_epoch:
            stats.loss += stale_regret
            stats.stale_steps += 1
        if step < next_probe:
            continue

        stats.loss += probe_cost
        stats.probes += 1
        probe_exposure = max(1, step - last_probe_step)
        probe_events = current_epoch - last_probe_epoch
        estimator.update(probe_events, probe_exposure)
        calibrated_epoch = current_epoch
        last_probe_epoch = current_epoch
        last_probe_step = step

        events, exposure = recent_confidence_counts(estimator)
        decision = evaluate_headroom_gate(
            HeadroomGateEvidence(
                point_hazard=estimator.value(),
                recent_events=events,
                recent_exposure=exposure,
                regret_given_change=stale_regret,
                probe_cost=probe_cost,
                min_interval=8,
                max_interval=256,
            )
        )
        interval = decision.interval
        stats.gated_decisions += int(decision.gated_to_minimum)
        stats.interval_sum += interval
        stats.interval_count += 1
        next_probe = step + interval

    return stats


def gated_mean_loss(stats: GatedStats, steps: int) -> float:
    return stats.loss / steps


def summarize(name: str, ratios: list[float], closures: list[float]) -> None:
    wins = sum(value < 1.0 for value in ratios)
    ties = sum(abs(value - 1.0) < 1e-12 for value in ratios)
    print(
        f"{name}: win_rate={wins / len(ratios):.3f} ties={ties} "
        f"median_ratio={median(ratios):.3f} "
        f"p90_ratio={percentile_nearest_rank(ratios, 0.90):.3f} "
        f"worst_ratio={max(ratios):.3f} "
        f"median_oracle_gap_closed={median(closures):.3f}"
    )


def main() -> None:
    environments = [(seed, build_environment(seed)) for seed in SEEDS]
    names = ("ewma", "rolling", "gated_ewma")
    overall = {name: [] for name in names}
    overall_gap = {name: [] for name in names}
    gated_fractions: list[float] = []

    print(f"seeds={len(SEEDS)}")
    print("profiles=3_probe_costs_x_3_stale_regrets")
    print("seed_family_and_cost_grid=frozen_from_hazard_cadence_robustness_v0.3")
    print("gate_input=EWMA point hazard + Wilson upper bound from recent paid probes only")
    print("best_fixed_control=chosen_after_the_fact_per_seed_profile")

    for probe_cost in PROBE_COSTS:
        for stale_regret in STALE_REGRETS:
            profile = {name: [] for name in names}
            profile_gap = {name: [] for name in names}
            gated_profile: list[float] = []
            losers = {name: [] for name in names}

            for seed, environment in environments:
                steps = len(environment.changes)
                fixed_rows = [
                    run(
                        environment,
                        probe_cost=probe_cost,
                        stale_regret=stale_regret,
                        mode="fixed",
                        fixed_interval=interval,
                    )
                    for interval in FIXED_INTERVALS
                ]
                best_fixed_loss = min(mean_loss(row, steps) for row in fixed_rows)
                oracle = run(
                    environment,
                    probe_cost=probe_cost,
                    stale_regret=stale_regret,
                    mode="oracle",
                )
                oracle_loss = mean_loss(oracle, steps)
                available_gap = max(1e-12, best_fixed_loss - oracle_loss)

                for name in ("ewma", "rolling"):
                    adaptive = run(
                        environment,
                        probe_cost=probe_cost,
                        stale_regret=stale_regret,
                        mode=name,
                    )
                    loss = mean_loss(adaptive, steps)
                    ratio = loss / best_fixed_loss
                    closure = (best_fixed_loss - loss) / available_gap
                    profile[name].append(ratio)
                    profile_gap[name].append(closure)
                    overall[name].append(ratio)
                    overall_gap[name].append(closure)
                    if ratio >= 1.0:
                        losers[name].append(seed)

                gated = gated_ewma_run(
                    environment,
                    probe_cost=probe_cost,
                    stale_regret=stale_regret,
                )
                loss = gated_mean_loss(gated, steps)
                ratio = loss / best_fixed_loss
                closure = (best_fixed_loss - loss) / available_gap
                profile["gated_ewma"].append(ratio)
                profile_gap["gated_ewma"].append(closure)
                overall["gated_ewma"].append(ratio)
                overall_gap["gated_ewma"].append(closure)
                fraction = gated.gated_decisions / max(1, gated.interval_count + 1)
                gated_profile.append(fraction)
                gated_fractions.append(fraction)
                if ratio >= 1.0:
                    losers["gated_ewma"].append(seed)

            print(f"\n[probe_cost={probe_cost:.0f},stale_regret={stale_regret:.0f}]")
            for name in names:
                summarize(name, profile[name], profile_gap[name])
                if losers[name]:
                    print(
                        f"  {name}_nonwins="
                        + ",".join(hex(seed) for seed in losers[name])
                    )
            print(f"  gated_ewma_median_gate_fraction={median(gated_profile):.3f}")

    print("\n[overall_288_seed_profiles]")
    for name in names:
        summarize(name, overall[name], overall_gap[name])
    print(f"gated_ewma_overall_median_gate_fraction={median(gated_fractions):.3f}")

    ewma_median = median(overall["ewma"])
    gated_median = median(overall["gated_ewma"])
    ewma_worst = max(overall["ewma"])
    gated_worst = max(overall["gated_ewma"])
    print(f"gated_vs_ewma_median_delta={gated_median - ewma_median:+.3f}")
    print(f"gated_vs_ewma_worst_delta={gated_worst - ewma_worst:+.3f}")
    print(
        "interpretation=The headroom gate earns its place only if a conservative "
        "recent-hazard bound reduces EWMA's downside tail without erasing its median "
        "advantage. The benchmark reuses the frozen v0.3 seed/cost family and retains "
        "all losing seed/profile cases."
    )


if __name__ == "__main__":
    main()
