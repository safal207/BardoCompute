from __future__ import annotations

import math
from statistics import median

from action_boundary_fencing import run as run_actions
from recovery_state_transfer import (
    HAZARDS,
    PROBE_COSTS,
    SEEDS,
    build_environment,
)

UNAVAILABLE_COSTS = (1.0, 5.0, 25.0)
FIXED_INTERVALS = (1, 8, 16, 32, 64, 128, 256)


def nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def operational_cost(stats, probe_cost: float, unavailable_cost: float) -> float:
    unavailable = stats.fence_rejections + stats.local_holds
    return stats.probes * probe_cost + unavailable * unavailable_cost


def main() -> None:
    environments = [(seed, build_environment(seed)) for seed in SEEDS]

    overall_ratios = {"ewma": [], "rolling": []}
    overall_acceptance = {"ewma": [], "rolling": []}
    overall_probe_ratio = {"ewma": [], "rolling": []}
    unsafe_totals = {"ewma": 0, "rolling": 0}
    phase_intervals = {
        "ewma": {hazard: [] for hazard in HAZARDS},
        "rolling": {hazard: [] for hazard in HAZARDS},
    }

    print(f"seeds={len(SEEDS)}")
    print("domain=fenced_authority_epoch_recovery")
    print("safety_invariant=unsafe_accepted_actions_zero")
    print("cost=probe_cost*probes + unavailable_cost*(fence_rejections+local_holds)")
    print("probe_costs=" + ",".join(f"{value:.0f}" for value in PROBE_COSTS))
    print("unavailable_costs=" + ",".join(f"{value:.0f}" for value in UNAVAILABLE_COSTS))
    print("fixed_candidates=" + ",".join(str(value) for value in FIXED_INTERVALS))
    print("future_restart_boundaries_and_hazards=hidden")

    for probe_cost in PROBE_COSTS:
        for unavailable_cost in UNAVAILABLE_COSTS:
            profile_ratios = {"ewma": [], "rolling": []}
            profile_acceptance = {"ewma": [], "rolling": []}

            for seed, environment in environments:
                fixed_rows = []
                for interval in FIXED_INTERVALS:
                    stats = run_actions(
                        environment,
                        seed=seed,
                        probe_cost=probe_cost,
                        stale_regret=unavailable_cost,
                        mode="fixed",
                        fenced=True,
                        fixed_interval=interval,
                    )
                    assert stats.unsafe_accepted_actions == 0
                    fixed_rows.append(
                        (
                            operational_cost(stats, probe_cost, unavailable_cost),
                            stats,
                            interval,
                        )
                    )

                best_fixed_cost, best_fixed_stats, _ = min(
                    fixed_rows,
                    key=lambda row: row[0],
                )
                best_fixed_probes = max(1, best_fixed_stats.probes)

                for mode in ("ewma", "rolling"):
                    adaptive = run_actions(
                        environment,
                        seed=seed,
                        probe_cost=probe_cost,
                        stale_regret=unavailable_cost,
                        mode=mode,
                        fenced=True,
                    )
                    assert adaptive.unsafe_accepted_actions == 0
                    unsafe_totals[mode] += adaptive.unsafe_accepted_actions

                    adaptive_cost = operational_cost(
                        adaptive,
                        probe_cost,
                        unavailable_cost,
                    )
                    ratio = adaptive_cost / best_fixed_cost
                    profile_ratios[mode].append(ratio)
                    profile_acceptance[mode].append(adaptive.acceptance_rate)
                    overall_ratios[mode].append(ratio)
                    overall_acceptance[mode].append(adaptive.acceptance_rate)
                    overall_probe_ratio[mode].append(
                        adaptive.probes / best_fixed_probes
                    )

                    for hazard in HAZARDS:
                        count = adaptive.interval_by_hazard_count[hazard]
                        if count:
                            phase_intervals[mode][hazard].append(
                                adaptive.interval_by_hazard_sum[hazard] / count
                            )

            print(
                f"\n[probe_cost={probe_cost:.0f},unavailable_cost={unavailable_cost:.0f}]"
            )
            for mode in ("ewma", "rolling"):
                ratios = profile_ratios[mode]
                print(
                    f"{mode}: win_rate={sum(value < 1.0 for value in ratios) / len(ratios):.3f} "
                    f"median_cost_ratio={median(ratios):.3f} "
                    f"p90_cost_ratio={nearest_rank(ratios, 0.90):.3f} "
                    f"worst_cost_ratio={max(ratios):.3f} "
                    f"median_acceptance_rate={median(profile_acceptance[mode]):.6f}"
                )

    print("\n[overall_safe_observation_economics]")
    for mode in ("ewma", "rolling"):
        ratios = overall_ratios[mode]
        win_rate = sum(value < 1.0 for value in ratios) / len(ratios)
        median_ratio = median(ratios)
        p90 = nearest_rank(ratios, 0.90)
        passes = (
            unsafe_totals[mode] == 0
            and win_rate >= 0.65
            and median_ratio < 0.97
            and p90 <= 1.05
        )
        print(
            f"{mode}: win_rate={win_rate:.3f} "
            f"median_cost_ratio={median_ratio:.3f} "
            f"p90_cost_ratio={p90:.3f} "
            f"worst_cost_ratio={max(ratios):.3f} "
            f"median_acceptance_rate={median(overall_acceptance[mode]):.6f} "
            f"median_probe_ratio={median(overall_probe_ratio[mode]):.3f} "
            f"unsafe_accepted_total={unsafe_totals[mode]} "
            f"passes_preregistered_acceptance={str(passes).lower()}"
        )
        print(
            f"{mode}_median_interval_by_true_hidden_hazard="
            + "/".join(
                f"{hazard:.4f}:{median(phase_intervals[mode][hazard]):.1f}"
                for hazard in HAZARDS
            )
        )

    print(
        "interpretation=The protected resource owns stale-effect safety and every "
        "tested adaptive run is required to have zero unsafe accepted actions. "
        "Observation cadence is evaluated only on the operational cost of paid "
        "probes versus unavailable work caused by stale-token rejection or local "
        "recovery HOLD. A passing adaptive estimator therefore improves freshness/"
        "availability economics without receiving authority to trade safety for "
        "utility. Fence runtime cost is intentionally left for a separate native "
        "benchmark."
    )


if __name__ == "__main__":
    main()
