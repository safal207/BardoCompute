from __future__ import annotations

from statistics import median

from bardocompute.exchange import MembraneCommand

from exchange_conservation import FlowPreservingMembrane
from exchange_dynamics import build_environment
from homeostasis import (
    STATIC_CAPS,
    HomeostaticMembrane,
    StaticCapMembrane,
    build_relief,
    run_policy,
)
from trajectory_homeostasis import (
    PROJECTION_HORIZON,
    SLOPE_ALPHA,
    SEEDS as V015_SEEDS,
    TrajectoryHomeostaticMembrane,
)

SEEDS = tuple(1_710_047 + i * 23_003 for i in range(12))
RELIEF_FLOOR = 0.40
HEAT_PER_UNIT = 0.020
SAFE_CAP = int(RELIEF_FLOOR // HEAT_PER_UNIT)
ENTER_PROTECTIVE = 70.0
EXIT_PROTECTIVE = 60.0


class ViabilityReserveMembrane(TrajectoryHomeostaticMembrane):
    """Flow-preserving membrane with a worst-case non-worsening safe mode."""

    def __init__(self) -> None:
        super().__init__()
        self.protective = False
        self.protective_ticks = 0
        self.protective_transitions = 0

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("viability reserve may not shed admitted flow")

        projected = self.stress + max(0.0, self.slope_ema) * PROJECTION_HORIZON
        effective_stress = max(self.stress, projected)

        if not self.protective and effective_stress >= ENTER_PROTECTIVE:
            self.protective = True
            self.protective_transitions += 1
        elif (
            self.protective
            and self.stress <= EXIT_PROTECTIVE
            and self.slope_ema <= 0.0
        ):
            self.protective = False
            self.protective_transitions += 1

        if self.protective:
            self.protective_ticks += 1
            release = min(base.release_limit, SAFE_CAP)
        else:
            release = base.release_limit

        return MembraneCommand(
            admission_limit=None,
            release_limit=release,
            buffer_limit=base.buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )


def main() -> None:
    if set(SEEDS) & set(V015_SEEDS):
        raise AssertionError("v0.16 validation seeds overlap v0.15")
    if SAFE_CAP * HEAT_PER_UNIT > RELIEF_FLOOR + 1e-12:
        raise AssertionError("derived protective cap is not worst-case non-worsening")

    baseline_critical_seed_count = 0
    reserve_critical_total = 0
    level_critical_total = 0
    trajectory_critical_total = 0
    safe_static_exists_count = 0

    reserve_vs_static_delivered: list[float] = []
    reserve_vs_baseline_delivered: list[float] = []
    reserve_vs_baseline_lost: list[float] = []
    reserve_vs_baseline_cost: list[float] = []
    protective_occupancy: list[float] = []
    protective_transitions: list[int] = []

    print("benchmark=viability_reserve_v0.16")
    print(f"seeds={len(SEEDS)}")
    print(f"known_relief_floor={RELIEF_FLOOR:.2f}")
    print(f"heat_per_unit={HEAT_PER_UNIT:.3f}")
    print(f"derived_safe_cap={SAFE_CAP}")
    print(
        f"protective_hysteresis=enter:{ENTER_PROTECTIVE:.0f},"
        f"exit:{EXIT_PROTECTIVE:.0f}"
    )
    print(f"slope_alpha={SLOPE_ALPHA:.2f}")
    print(f"projection_horizon={PROJECTION_HORIZON}")
    print("future_hidden_information=false")
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
        trajectory = run_policy(
            environment,
            relief,
            TrajectoryHomeostaticMembrane(),
        )
        level_critical_total += level.critical_ticks
        trajectory_critical_total += trajectory.critical_ticks

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

        controller = ViabilityReserveMembrane()
        reserve = run_policy(environment, relief, controller)
        reserve_critical_total += reserve.critical_ticks

        static_delivered_ratio = (
            reserve.exchange.delivered / max(1, best_static.exchange.delivered)
        )
        baseline_delivered_ratio = (
            reserve.exchange.delivered / max(1, baseline.exchange.delivered)
        )
        baseline_lost_ratio = reserve.exchange.lost / max(1, baseline.exchange.lost)
        baseline_cost_ratio = reserve.exchange.cost() / max(1.0, baseline.exchange.cost())
        occupancy = controller.protective_ticks / len(environment.steps)

        reserve_vs_static_delivered.append(static_delivered_ratio)
        reserve_vs_baseline_delivered.append(baseline_delivered_ratio)
        reserve_vs_baseline_lost.append(baseline_lost_ratio)
        reserve_vs_baseline_cost.append(baseline_cost_ratio)
        protective_occupancy.append(occupancy)
        protective_transitions.append(controller.protective_transitions)

        print(
            f"seed={seed} "
            f"baseline_critical={baseline.critical_ticks} "
            f"level_critical={level.critical_ticks} "
            f"trajectory_critical={trajectory.critical_ticks} "
            f"reserve_critical={reserve.critical_ticks} "
            f"reserve_max_stress={reserve.max_stress:.1f} "
            f"best_static_safe_cap={best_cap} "
            f"static_safe_exists={str(safe_exists).lower()} "
            f"reserve_vs_static_delivered={static_delivered_ratio:.3f} "
            f"reserve_vs_baseline_delivered={baseline_delivered_ratio:.3f} "
            f"reserve_vs_baseline_lost={baseline_lost_ratio:.3f} "
            f"reserve_vs_baseline_cost={baseline_cost_ratio:.3f} "
            f"protective_occupancy={occupancy:.3f} "
            f"protective_transitions={controller.protective_transitions}"
        )

    informative_fraction = baseline_critical_seed_count / len(SEEDS)
    passes = (
        informative_fraction >= 0.75
        and reserve_critical_total == 0
        and safe_static_exists_count == len(SEEDS)
        and median(reserve_vs_static_delivered) >= 1.08
        and median(reserve_vs_baseline_delivered) >= 0.95
        and median(reserve_vs_baseline_lost) <= 1.10
        and median(reserve_vs_baseline_cost) <= 1.25
    )

    print("\n[overall]")
    print(f"baseline_critical_seed_fraction={informative_fraction:.3f}")
    print(f"v014_level_critical_ticks_total={level_critical_total}")
    print(f"v015_trajectory_critical_ticks_total={trajectory_critical_total}")
    print(f"v016_reserve_critical_ticks_total={reserve_critical_total}")
    print(f"static_safe_exists={safe_static_exists_count}/{len(SEEDS)}")
    print(
        f"median_reserve_vs_static_safe_delivered="
        f"{median(reserve_vs_static_delivered):.3f}"
    )
    print(
        f"median_reserve_vs_v013_delivered="
        f"{median(reserve_vs_baseline_delivered):.3f} "
        f"median_reserve_vs_v013_lost={median(reserve_vs_baseline_lost):.3f} "
        f"median_reserve_vs_v013_exchange_cost={median(reserve_vs_baseline_cost):.3f}"
    )
    print(
        f"median_protective_occupancy={median(protective_occupancy):.3f} "
        f"median_protective_transitions={median(protective_transitions):.1f}"
    )
    print(f"passes_preregistered_acceptance={str(passes).lower()}")

    print(
        "interpretation=v0.16 separates detecting approach to a viability "
        "boundary from possessing an action that can actually preserve the "
        "boundary under the declared disturbance bounds. The emergency release "
        "cap is derived from the known relief floor rather than tuned against "
        "the validation family."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
