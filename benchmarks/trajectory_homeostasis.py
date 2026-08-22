from __future__ import annotations

from statistics import median

from bardocompute.exchange import ExchangeResult, MembraneCommand

from exchange_conservation import FlowPreservingMembrane
from exchange_dynamics import build_environment
from homeostasis import (
    CRITICAL_STRESS,
    SEEDS as V014_SEEDS,
    STATIC_CAPS,
    HomeostaticMembrane,
    StaticCapMembrane,
    build_relief,
    run_policy,
)

SEEDS = tuple(1_310_033 + i * 19_001 for i in range(12))
SLOPE_ALPHA = 0.20
PROJECTION_HORIZON = 16


class TrajectoryHomeostaticMembrane(HomeostaticMembrane):
    """Anticipatory internal-state feedback using only past stress trajectory."""

    def __init__(self) -> None:
        super().__init__()
        self.previous_stress: float | None = None
        self.slope_ema = 0.0

    def set_stress(self, stress: float) -> None:
        if self.previous_stress is not None:
            delta = stress - self.previous_stress
            self.slope_ema = (
                SLOPE_ALPHA * delta + (1.0 - SLOPE_ALPHA) * self.slope_ema
            )
        self.previous_stress = stress
        self.stress = stress

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("trajectory homeostasis may not shed admitted flow")

        projected = self.stress + max(0.0, self.slope_ema) * PROJECTION_HORIZON
        effective_stress = max(self.stress, projected)
        cap = self.dynamic_cap(effective_stress)
        release = base.release_limit if cap is None else min(base.release_limit, cap)

        return MembraneCommand(
            admission_limit=None,
            release_limit=release,
            buffer_limit=base.buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )

    def observe(self, result: ExchangeResult) -> None:
        self.base.observe(result)


def main() -> None:
    if set(SEEDS) & set(V014_SEEDS):
        raise AssertionError("v0.15 validation seeds overlap v0.14")

    baseline_critical_seed_count = 0
    level_critical_total = 0
    trajectory_critical_total = 0
    safe_static_exists_count = 0

    trajectory_vs_static_delivered: list[float] = []
    trajectory_vs_baseline_delivered: list[float] = []
    trajectory_vs_baseline_lost: list[float] = []
    trajectory_vs_baseline_cost: list[float] = []
    level_vs_baseline_delivered: list[float] = []
    level_critical_ratios: list[float] = []
    trajectory_rows = []

    print("benchmark=trajectory_aware_computational_homeostasis_v0.15")
    print(f"seeds={len(SEEDS)}")
    print(f"slope_alpha={SLOPE_ALPHA:.2f}")
    print(f"projection_horizon={PROJECTION_HORIZON}")
    print("trajectory_information=past_stress_values_only")
    print("future_relief_exchange_regimes_capacities_arrivals=false")
    print("admission_shedding=false")

    for seed in SEEDS:
        environment = build_environment(seed)
        relief = build_relief(seed, len(environment.steps))

        baseline = run_policy(
            environment,
            relief,
            FlowPreservingMembrane(route_enabled=True),
        )
        if baseline.critical_ticks > 0:
            baseline_critical_seed_count += 1

        level = run_policy(environment, relief, HomeostaticMembrane())
        level_critical_total += level.critical_ticks

        static_rows = []
        for cap in STATIC_CAPS:
            row = run_policy(environment, relief, StaticCapMembrane(cap))
            static_rows.append((cap, row))
        safe_rows = [row for row in static_rows if row[1].critical_ticks == 0]
        safe_exists = bool(safe_rows)
        safe_static_exists_count += int(safe_exists)
        if safe_rows:
            best_cap, best_static = max(
                safe_rows,
                key=lambda item: (item[1].exchange.delivered, -item[1].exchange.cost()),
            )
        else:
            best_cap, best_static = min(
                static_rows,
                key=lambda item: (
                    item[1].critical_ticks,
                    -item[1].exchange.delivered,
                    item[1].exchange.cost(),
                ),
            )

        trajectory = run_policy(
            environment,
            relief,
            TrajectoryHomeostaticMembrane(),
        )
        trajectory_rows.append(trajectory)
        trajectory_critical_total += trajectory.critical_ticks

        trajectory_static_delivered = (
            trajectory.exchange.delivered / max(1, best_static.exchange.delivered)
        )
        trajectory_baseline_delivered = (
            trajectory.exchange.delivered / max(1, baseline.exchange.delivered)
        )
        trajectory_baseline_lost = (
            trajectory.exchange.lost / max(1, baseline.exchange.lost)
        )
        trajectory_baseline_cost = (
            trajectory.exchange.cost() / max(1.0, baseline.exchange.cost())
        )
        level_baseline_delivered = (
            level.exchange.delivered / max(1, baseline.exchange.delivered)
        )
        level_critical_ratio = level.critical_ticks / max(1, baseline.critical_ticks)

        trajectory_vs_static_delivered.append(trajectory_static_delivered)
        trajectory_vs_baseline_delivered.append(trajectory_baseline_delivered)
        trajectory_vs_baseline_lost.append(trajectory_baseline_lost)
        trajectory_vs_baseline_cost.append(trajectory_baseline_cost)
        level_vs_baseline_delivered.append(level_baseline_delivered)
        level_critical_ratios.append(level_critical_ratio)

        print(
            f"seed={seed} "
            f"baseline_critical={baseline.critical_ticks} "
            f"level_critical={level.critical_ticks} "
            f"trajectory_critical={trajectory.critical_ticks} "
            f"best_static_safe_cap={best_cap} "
            f"static_safe_exists={str(safe_exists).lower()} "
            f"trajectory_max_stress={trajectory.max_stress:.1f} "
            f"trajectory_vs_static_delivered={trajectory_static_delivered:.3f} "
            f"trajectory_vs_baseline_delivered={trajectory_baseline_delivered:.3f} "
            f"trajectory_vs_baseline_lost={trajectory_baseline_lost:.3f} "
            f"trajectory_vs_baseline_cost={trajectory_baseline_cost:.3f}"
        )

    informative_fraction = baseline_critical_seed_count / len(SEEDS)
    passes = (
        informative_fraction >= 0.75
        and trajectory_critical_total == 0
        and safe_static_exists_count == len(SEEDS)
        and median(trajectory_vs_static_delivered) >= 1.08
        and median(trajectory_vs_baseline_delivered) >= 0.95
        and median(trajectory_vs_baseline_lost) <= 1.10
        and median(trajectory_vs_baseline_cost) <= 1.25
    )

    print("\n[overall]")
    print(f"baseline_critical_seed_fraction={informative_fraction:.3f}")
    print(f"v014_level_critical_ticks_total={level_critical_total}")
    print(f"v015_trajectory_critical_ticks_total={trajectory_critical_total}")
    print(f"static_safe_exists={safe_static_exists_count}/{len(SEEDS)}")
    print(
        f"median_trajectory_vs_static_safe_delivered="
        f"{median(trajectory_vs_static_delivered):.3f}"
    )
    print(
        f"median_trajectory_vs_v013_delivered="
        f"{median(trajectory_vs_baseline_delivered):.3f}"
    )
    print(
        f"median_trajectory_vs_v013_lost={median(trajectory_vs_baseline_lost):.3f} "
        f"median_trajectory_vs_v013_exchange_cost="
        f"{median(trajectory_vs_baseline_cost):.3f}"
    )
    print(
        f"v014_median_critical_ratio_vs_v013={median(level_critical_ratios):.3f} "
        f"v014_median_delivered_ratio_vs_v013="
        f"{median(level_vs_baseline_delivered):.3f}"
    )
    print(f"passes_preregistered_acceptance={str(passes).lower()}")

    print("\n[trajectory_release_by_hidden_relief_posthoc]")
    for regime in ("ample", "normal", "constrained", "recovery"):
        releases = [
            value
            for row in trajectory_rows
            for value in row.release_by_relief[regime]
        ]
        print(f"{regime}: median_release={median(releases):.1f}")

    print(
        "interpretation=v0.15 tests whether recent internal-state trajectory "
        "contains actionable information beyond the current stress endpoint. "
        "The controller projects only positive past-measured stress slope over a "
        "fixed short horizon and applies the already-frozen v0.14 cap mapping to "
        "that effective stress."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
