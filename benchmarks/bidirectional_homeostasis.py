from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from bardocompute.exchange import (
    ExchangeState,
    MembraneCommand,
    regulate_exchange,
)

from exchange_conservation import FlowPreservingMembrane
from exchange_dynamics import RunStats, build_environment, command_changed
from homeostasis import (
    CRITICAL_STRESS,
    HEAT_PER_UNIT,
    INITIAL_STRESS,
    MAX_STRESS,
    build_relief,
    run_policy,
)
from trajectory_homeostasis import PROJECTION_HORIZON, TrajectoryHomeostaticMembrane
from viability_reserve import ViabilityReserveMembrane

SEEDS = tuple(2_210_061 + i * 29_011 for i in range(12))
RELIEF_FLOOR = 0.40
BOOST_AMOUNT = 1.00
BOOST_COST_PER_UNIT = 12.0
BOOSTED_SAFE_CAP = int((RELIEF_FLOOR + BOOST_AMOUNT) // HEAT_PER_UNIT)
ENTER_PROTECTIVE = 70.0
EXIT_PROTECTIVE = 60.0


@dataclass(slots=True)
class BidirectionalStats:
    exchange: RunStats
    critical_ticks: int = 0
    max_stress: float = 0.0
    boost_integral: float = 0.0

    def total_cost(self) -> float:
        return self.exchange.cost() + self.boost_integral * BOOST_COST_PER_UNIT


class BidirectionalHomeostaticMembrane(TrajectoryHomeostaticMembrane):
    """Regulate outgoing work and a costly incoming relief exchange."""

    def __init__(self) -> None:
        super().__init__()
        self.protective = False
        self.protective_ticks = 0
        self.protective_transitions = 0
        self.current_boost = 0.0

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("bidirectional homeostasis may not shed admission")

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
            self.current_boost = BOOST_AMOUNT
            release = min(base.release_limit, BOOSTED_SAFE_CAP)
        else:
            self.current_boost = 0.0
            release = base.release_limit

        return MembraneCommand(
            admission_limit=None,
            release_limit=release,
            buffer_limit=base.buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )


class AlwaysProtectiveMembrane:
    def __init__(self) -> None:
        self.base = FlowPreservingMembrane(route_enabled=True)
        self.current_boost = BOOST_AMOUNT

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("always-protective control may not shed admission")
        return MembraneCommand(
            admission_limit=None,
            release_limit=min(base.release_limit, BOOSTED_SAFE_CAP),
            buffer_limit=base.buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )

    def observe(self, result) -> None:
        self.base.observe(result)


def run_bidirectional(environment, relief, controller) -> BidirectionalStats:
    exchange_state = ExchangeState()
    exchange_stats = RunStats()
    stats = BidirectionalStats(exchange=exchange_stats)
    previous_command: MembraneCommand | None = None
    stress = INITIAL_STRESS

    if hasattr(controller, "set_stress"):
        controller.set_stress(stress)

    for step, regime, hidden_relief in zip(
        environment.steps,
        environment.regimes,
        relief.values,
        strict=True,
    ):
        command = controller.command()
        if command.admission_limit is not None:
            raise AssertionError("bidirectional benchmark forbids admission shedding")

        if command_changed(previous_command, command):
            exchange_stats.control_moves += 1
        previous_command = command

        result = regulate_exchange(exchange_state, step, command)
        controller.observe(result)

        exchange_stats.delivered += result.delivered
        exchange_stats.lost += result.lost
        exchange_stats.congestion += result.congestion
        exchange_stats.buffer_integral += result.buffered
        exchange_stats.secondary_delivered += result.secondary_delivered
        exchange_stats.rate_by_regime[regime].append(command.release_limit)
        exchange_stats.secondary_by_regime[regime].append(command.secondary_fraction)

        boost = controller.current_boost
        stats.boost_integral += boost
        stress = max(
            0.0,
            min(
                MAX_STRESS,
                stress
                + result.delivered * HEAT_PER_UNIT
                - (hidden_relief + boost),
            ),
        )
        if stress >= CRITICAL_STRESS:
            stats.critical_ticks += 1
        stats.max_stress = max(stats.max_stress, stress)

        if hasattr(controller, "set_stress"):
            controller.set_stress(stress)

    exchange_stats.terminal_buffer = exchange_state.buffered
    return stats


def main() -> None:
    if BOOSTED_SAFE_CAP * HEAT_PER_UNIT > RELIEF_FLOOR + BOOST_AMOUNT + 1e-12:
        raise AssertionError("boosted protective action is not worst-case non-worsening")

    baseline_critical_seed_count = 0
    bidirectional_critical_total = 0
    output_only_critical_total = 0

    delivered_vs_baseline: list[float] = []
    lost_vs_baseline: list[float] = []
    cost_vs_baseline: list[float] = []
    delivered_vs_always: list[float] = []
    cost_vs_always: list[float] = []
    boost_occupancy: list[float] = []
    boost_transitions: list[int] = []

    print("benchmark=bidirectional_exchange_homeostasis_v0.17")
    print(f"seeds={len(SEEDS)}")
    print(f"relief_floor={RELIEF_FLOOR:.2f}")
    print(f"boost_amount={BOOST_AMOUNT:.2f}")
    print(f"boost_cost_per_unit={BOOST_COST_PER_UNIT:.1f}")
    print(f"derived_boosted_safe_cap={BOOSTED_SAFE_CAP}")
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
        baseline_critical_seed_count += int(baseline.critical_ticks > 0)

        output_only = run_policy(environment, relief, ViabilityReserveMembrane())
        output_only_critical_total += output_only.critical_ticks

        always = run_bidirectional(environment, relief, AlwaysProtectiveMembrane())

        controller = BidirectionalHomeostaticMembrane()
        adaptive = run_bidirectional(environment, relief, controller)
        bidirectional_critical_total += adaptive.critical_ticks

        baseline_delivered_ratio = (
            adaptive.exchange.delivered / max(1, baseline.exchange.delivered)
        )
        baseline_lost_ratio = adaptive.exchange.lost / max(1, baseline.exchange.lost)
        baseline_cost_ratio = adaptive.total_cost() / max(1.0, baseline.exchange.cost())
        always_delivered_ratio = (
            adaptive.exchange.delivered / max(1, always.exchange.delivered)
        )
        always_cost_ratio = adaptive.total_cost() / max(1.0, always.total_cost())
        occupancy = controller.protective_ticks / len(environment.steps)

        delivered_vs_baseline.append(baseline_delivered_ratio)
        lost_vs_baseline.append(baseline_lost_ratio)
        cost_vs_baseline.append(baseline_cost_ratio)
        delivered_vs_always.append(always_delivered_ratio)
        cost_vs_always.append(always_cost_ratio)
        boost_occupancy.append(occupancy)
        boost_transitions.append(controller.protective_transitions)

        print(
            f"seed={seed} "
            f"baseline_critical={baseline.critical_ticks} "
            f"output_only_critical={output_only.critical_ticks} "
            f"bidirectional_critical={adaptive.critical_ticks} "
            f"adaptive_max_stress={adaptive.max_stress:.1f} "
            f"adaptive_vs_baseline_delivered={baseline_delivered_ratio:.3f} "
            f"adaptive_vs_baseline_lost={baseline_lost_ratio:.3f} "
            f"adaptive_vs_baseline_total_cost={baseline_cost_ratio:.3f} "
            f"adaptive_vs_always_delivered={always_delivered_ratio:.3f} "
            f"adaptive_vs_always_total_cost={always_cost_ratio:.3f} "
            f"boost_occupancy={occupancy:.3f} "
            f"boost_transitions={controller.protective_transitions}"
        )

    informative_fraction = baseline_critical_seed_count / len(SEEDS)
    passes = (
        informative_fraction >= 0.75
        and bidirectional_critical_total == 0
        and median(delivered_vs_baseline) >= 0.95
        and median(lost_vs_baseline) <= 1.10
        and median(cost_vs_baseline) <= 1.35
        and median(delivered_vs_always) >= 1.05
        and median(cost_vs_always) <= 0.90
    )

    print("\n[overall]")
    print(f"baseline_critical_seed_fraction={informative_fraction:.3f}")
    print(f"output_only_v016_critical_ticks_total={output_only_critical_total}")
    print(f"bidirectional_v017_critical_ticks_total={bidirectional_critical_total}")
    print(
        f"median_adaptive_vs_v013_delivered={median(delivered_vs_baseline):.3f} "
        f"median_adaptive_vs_v013_lost={median(lost_vs_baseline):.3f} "
        f"median_adaptive_vs_v013_total_cost={median(cost_vs_baseline):.3f}"
    )
    print(
        f"median_adaptive_vs_always_delivered={median(delivered_vs_always):.3f} "
        f"median_adaptive_vs_always_total_cost={median(cost_vs_always):.3f}"
    )
    print(
        f"median_boost_occupancy={median(boost_occupancy):.3f} "
        f"median_boost_transitions={median(boost_transitions):.1f}"
    )
    print(f"passes_preregistered_acceptance={str(passes).lower()}")

    print(
        "interpretation=v0.17 tests homeostasis with two exchange actuators: "
        "useful-work release and a separately costed auxiliary relief exchange. "
        "The boosted protected cap is derived from declared bounds, while boost "
        "activation uses only current/past internal state."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
