from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from bardocompute.exchange import ExchangeState, MembraneCommand, regulate_exchange

from bidirectional_homeostasis import (
    BOOST_COST_PER_UNIT,
    BidirectionalHomeostaticMembrane,
    run_bidirectional,
)
from exchange_conservation import FlowPreservingMembrane
from exchange_dynamics import BUFFER_LIMIT, RunStats, build_environment, command_changed
from homeostasis import (
    CRITICAL_STRESS,
    HEAT_PER_UNIT,
    INITIAL_STRESS,
    MAX_STRESS,
    build_relief,
    run_policy,
)

SEEDS = tuple(2_810_079 + i * 31_013 for i in range(12))
ELASTIC_BUFFER_LIMIT = 2048
EXTRA_CAPACITY = ELASTIC_BUFFER_LIMIT - BUFFER_LIMIT
CAPACITY_RENTAL_COST = 0.004


@dataclass(slots=True)
class StorageStats:
    exchange: RunStats
    critical_ticks: int = 0
    max_stress: float = 0.0
    boost_integral: float = 0.0
    extra_capacity_integral: int = 0
    peak_buffer: int = 0

    def total_cost(self) -> float:
        return (
            self.exchange.cost()
            + self.boost_integral * BOOST_COST_PER_UNIT
            + self.extra_capacity_integral * CAPACITY_RENTAL_COST
        )


class ElasticStorageMembrane(BidirectionalHomeostaticMembrane):
    def __init__(self) -> None:
        super().__init__()
        self.storage_active = False
        self.storage_ticks = 0
        self.storage_transitions = 0

    def command(self) -> MembraneCommand:
        base_command = super().command()
        buffered = 0
        if self.base.previous is not None:
            buffered = self.base.previous.buffered

        desired_storage = self.protective or buffered > BUFFER_LIMIT
        if desired_storage != self.storage_active:
            self.storage_active = desired_storage
            self.storage_transitions += 1

        if self.storage_active:
            self.storage_ticks += 1
            buffer_limit = ELASTIC_BUFFER_LIMIT
        else:
            buffer_limit = BUFFER_LIMIT

        return MembraneCommand(
            admission_limit=None,
            release_limit=base_command.release_limit,
            buffer_limit=buffer_limit,
            secondary_fraction=base_command.secondary_fraction,
        )


class AlwaysExpandedMembrane(BidirectionalHomeostaticMembrane):
    def __init__(self) -> None:
        super().__init__()
        self.storage_ticks = 0
        self.storage_transitions = 0

    def command(self) -> MembraneCommand:
        base_command = super().command()
        self.storage_ticks += 1
        return MembraneCommand(
            admission_limit=None,
            release_limit=base_command.release_limit,
            buffer_limit=ELASTIC_BUFFER_LIMIT,
            secondary_fraction=base_command.secondary_fraction,
        )


def run_storage(environment, relief, controller) -> StorageStats:
    exchange_state = ExchangeState()
    exchange_stats = RunStats()
    stats = StorageStats(exchange=exchange_stats)
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
            raise AssertionError("storage reserve forbids admission shedding")

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

        stats.boost_integral += controller.current_boost
        stats.extra_capacity_integral += max(0, command.buffer_limit - BUFFER_LIMIT)
        stats.peak_buffer = max(stats.peak_buffer, result.buffered)

        stress = max(
            0.0,
            min(
                MAX_STRESS,
                stress
                + result.delivered * HEAT_PER_UNIT
                - (hidden_relief + controller.current_boost),
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
    if EXTRA_CAPACITY <= 0:
        raise AssertionError("elastic buffer must exceed baseline buffer")

    baseline_critical_seed_count = 0
    elastic_critical_total = 0

    delivered_vs_baseline: list[float] = []
    lost_vs_baseline: list[float] = []
    cost_vs_baseline: list[float] = []
    lost_vs_v017: list[float] = []
    cost_vs_always: list[float] = []
    storage_occupancy: list[float] = []
    storage_transitions: list[int] = []
    peak_buffers: list[int] = []
    terminal_buffers: list[int] = []

    print("benchmark=elastic_storage_reserve_v0.18")
    print(f"seeds={len(SEEDS)}")
    print(f"baseline_buffer_limit={BUFFER_LIMIT}")
    print(f"elastic_buffer_limit={ELASTIC_BUFFER_LIMIT}")
    print(f"extra_capacity={EXTRA_CAPACITY}")
    print(f"capacity_rental_cost={CAPACITY_RENTAL_COST:.3f}")
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

        v017_controller = BidirectionalHomeostaticMembrane()
        v017 = run_bidirectional(environment, relief, v017_controller)

        always_controller = AlwaysExpandedMembrane()
        always = run_storage(environment, relief, always_controller)

        elastic_controller = ElasticStorageMembrane()
        elastic = run_storage(environment, relief, elastic_controller)
        elastic_critical_total += elastic.critical_ticks

        baseline_delivered_ratio = (
            elastic.exchange.delivered / max(1, baseline.exchange.delivered)
        )
        baseline_lost_ratio = elastic.exchange.lost / max(1, baseline.exchange.lost)
        baseline_cost_ratio = elastic.total_cost() / max(1.0, baseline.exchange.cost())
        v017_lost_ratio = elastic.exchange.lost / max(1, v017.exchange.lost)
        always_cost_ratio = elastic.total_cost() / max(1.0, always.total_cost())
        occupancy = elastic_controller.storage_ticks / len(environment.steps)

        delivered_vs_baseline.append(baseline_delivered_ratio)
        lost_vs_baseline.append(baseline_lost_ratio)
        cost_vs_baseline.append(baseline_cost_ratio)
        lost_vs_v017.append(v017_lost_ratio)
        cost_vs_always.append(always_cost_ratio)
        storage_occupancy.append(occupancy)
        storage_transitions.append(elastic_controller.storage_transitions)
        peak_buffers.append(elastic.peak_buffer)
        terminal_buffers.append(elastic.exchange.terminal_buffer)

        print(
            f"seed={seed} "
            f"baseline_critical={baseline.critical_ticks} "
            f"v017_critical={v017.critical_ticks} "
            f"elastic_critical={elastic.critical_ticks} "
            f"elastic_vs_baseline_delivered={baseline_delivered_ratio:.3f} "
            f"elastic_vs_baseline_lost={baseline_lost_ratio:.3f} "
            f"elastic_vs_baseline_total_cost={baseline_cost_ratio:.3f} "
            f"elastic_vs_v017_lost={v017_lost_ratio:.3f} "
            f"elastic_vs_always_total_cost={always_cost_ratio:.3f} "
            f"storage_occupancy={occupancy:.3f} "
            f"storage_transitions={elastic_controller.storage_transitions} "
            f"peak_buffer={elastic.peak_buffer} "
            f"terminal_buffer={elastic.exchange.terminal_buffer}"
        )

    informative_fraction = baseline_critical_seed_count / len(SEEDS)
    passes = (
        informative_fraction >= 0.75
        and elastic_critical_total == 0
        and median(delivered_vs_baseline) >= 0.95
        and median(lost_vs_baseline) <= 1.05
        and median(cost_vs_baseline) <= 1.35
        and median(lost_vs_v017) <= 0.90
        and median(cost_vs_always) <= 0.90
    )

    print("\n[overall]")
    print(f"baseline_critical_seed_fraction={informative_fraction:.3f}")
    print(f"elastic_critical_ticks_total={elastic_critical_total}")
    print(
        f"median_elastic_vs_v013_delivered={median(delivered_vs_baseline):.3f} "
        f"median_elastic_vs_v013_lost={median(lost_vs_baseline):.3f} "
        f"median_elastic_vs_v013_total_cost={median(cost_vs_baseline):.3f}"
    )
    print(
        f"median_elastic_vs_v017_lost={median(lost_vs_v017):.3f} "
        f"median_elastic_vs_always_total_cost={median(cost_vs_always):.3f}"
    )
    print(
        f"median_storage_occupancy={median(storage_occupancy):.3f} "
        f"median_storage_transitions={median(storage_transitions):.1f} "
        f"median_peak_buffer={median(peak_buffers):.1f} "
        f"median_terminal_buffer={median(terminal_buffers):.1f}"
    )
    print(f"passes_preregistered_acceptance={str(passes).lower()}")

    print(
        "interpretation=v0.18 tests whether temporary paid retention can absorb "
        "backlog created by viability-preserving throttling and later return it "
        "to exchange, rather than forcing irreversible overflow loss or permanent "
        "overprovisioning."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
