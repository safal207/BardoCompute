from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import median

from bardocompute.exchange import (
    ExchangeResult,
    ExchangeState,
    MembraneCommand,
    regulate_exchange,
)

from exchange_conservation import FlowPreservingMembrane
from exchange_dynamics import RunStats, build_environment, command_changed

SEEDS = tuple(910_021 + i * 17_011 for i in range(12))
STATIC_CAPS = (24, 32, 40, 48, 56, 64, 80, 96, 112, 128)

INITIAL_STRESS = 45.0
HEAT_PER_UNIT = 0.020
TARGET_HIGH = 70.0
CRITICAL_STRESS = 100.0
MAX_STRESS = 150.0

RELIEF_REGIMES = {
    "ample": 1.80,
    "normal": 1.25,
    "constrained": 0.55,
    "recovery": 2.20,
}
RELIEF_WEIGHTS = {
    "ample": 2,
    "normal": 4,
    "constrained": 2,
    "recovery": 2,
}


@dataclass(frozen=True, slots=True)
class ReliefEnvironment:
    values: tuple[float, ...]
    regimes: tuple[str, ...]


@dataclass(slots=True)
class HomeostasisStats:
    exchange: RunStats
    critical_ticks: int = 0
    stress_excess_integral: float = 0.0
    stress_sum: float = 0.0
    max_stress: float = 0.0
    release_by_relief: dict[str, list[int]] = field(
        default_factory=lambda: {name: [] for name in RELIEF_REGIMES}
    )

    @property
    def mean_stress(self) -> float:
        count = sum(len(values) for values in self.release_by_relief.values())
        return self.stress_sum / max(1, count)


class StaticCapMembrane:
    """v0.13 routing with one fixed release ceiling."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.base = FlowPreservingMembrane(route_enabled=True)

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.13 unexpectedly enabled admission shedding")
        return MembraneCommand(
            admission_limit=None,
            release_limit=min(base.release_limit, self.cap),
            buffer_limit=base.buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )

    def observe(self, result: ExchangeResult) -> None:
        self.base.observe(result)


class HomeostaticMembrane:
    """v0.13 exchange topology plus internal-stress release feedback.

    The controller sees current internal stress and past exchange outcomes only.
    It does not receive current or future relief.
    """

    def __init__(self) -> None:
        self.base = FlowPreservingMembrane(route_enabled=True)
        self.stress = INITIAL_STRESS

    @staticmethod
    def dynamic_cap(stress: float) -> int | None:
        if stress <= TARGET_HIGH:
            return None
        if stress >= CRITICAL_STRESS:
            return 32
        progress = (stress - TARGET_HIGH) / (CRITICAL_STRESS - TARGET_HIGH)
        cap = 96.0 - progress * (96.0 - 32.0)
        return max(32, min(96, int(round(cap))))

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("homeostasis may not shed admitted flow")
        cap = self.dynamic_cap(self.stress)
        release = base.release_limit if cap is None else min(base.release_limit, cap)
        return MembraneCommand(
            admission_limit=None,
            release_limit=release,
            buffer_limit=base.buffer_limit,
            secondary_fraction=base.secondary_fraction,
        )

    def observe(self, result: ExchangeResult) -> None:
        self.base.observe(result)

    def set_stress(self, stress: float) -> None:
        self.stress = stress


def build_relief(seed: int, steps: int) -> ReliefEnvironment:
    rng = random.Random(seed ^ 0x71A9_5EED)
    values: list[float] = []
    labels: list[str] = []
    previous: str | None = None
    names = tuple(RELIEF_REGIMES)

    while len(values) < steps:
        candidates = [name for name in names if name != previous]
        weights = [RELIEF_WEIGHTS[name] for name in candidates]
        regime = rng.choices(candidates, weights=weights, k=1)[0]
        previous = regime
        duration = rng.randint(180, 520)
        base = RELIEF_REGIMES[regime]

        for _ in range(duration):
            if len(values) >= steps:
                break
            relief = max(0.0, base + rng.uniform(-0.15, 0.15))
            values.append(relief)
            labels.append(regime)

    return ReliefEnvironment(tuple(values), tuple(labels))


def _record_exchange(
    stats: RunStats,
    result: ExchangeResult,
    command: MembraneCommand,
    previous_command: MembraneCommand | None,
    regime: str,
) -> None:
    if command_changed(previous_command, command):
        stats.control_moves += 1
    stats.delivered += result.delivered
    stats.lost += result.lost
    stats.congestion += result.congestion
    stats.buffer_integral += result.buffered
    stats.secondary_delivered += result.secondary_delivered
    stats.rate_by_regime[regime].append(command.release_limit)
    stats.secondary_by_regime[regime].append(command.secondary_fraction)


def run_policy(environment, relief: ReliefEnvironment, policy) -> HomeostasisStats:
    if len(environment.steps) != len(relief.values):
        raise AssertionError("exchange and relief lengths differ")

    exchange_state = ExchangeState()
    exchange_stats = RunStats()
    stats = HomeostasisStats(exchange=exchange_stats)
    stress = INITIAL_STRESS
    previous_command: MembraneCommand | None = None

    if hasattr(policy, "set_stress"):
        policy.set_stress(stress)

    for step, exchange_regime, hidden_relief, relief_regime in zip(
        environment.steps,
        environment.regimes,
        relief.values,
        relief.regimes,
        strict=True,
    ):
        command = policy.command()
        if command.admission_limit is not None:
            raise AssertionError("homeostasis benchmark forbids admission shedding")

        result = regulate_exchange(exchange_state, step, command)
        policy.observe(result)

        _record_exchange(
            exchange_stats,
            result,
            command,
            previous_command,
            exchange_regime,
        )
        previous_command = command

        stress = max(
            0.0,
            min(
                MAX_STRESS,
                stress + result.delivered * HEAT_PER_UNIT - hidden_relief,
            ),
        )
        if stress >= CRITICAL_STRESS:
            stats.critical_ticks += 1
        stats.stress_excess_integral += max(0.0, stress - TARGET_HIGH)
        stats.stress_sum += stress
        stats.max_stress = max(stats.max_stress, stress)
        stats.release_by_relief[relief_regime].append(command.release_limit)

        if hasattr(policy, "set_stress"):
            policy.set_stress(stress)

    exchange_stats.terminal_buffer = exchange_state.buffered
    return stats


def nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def main() -> None:
    baseline_critical_seed_count = 0
    homeostatic_critical_total = 0
    safe_static_exists_count = 0

    homeo_vs_static_delivered: list[float] = []
    homeo_vs_baseline_delivered: list[float] = []
    homeo_vs_baseline_lost: list[float] = []
    homeo_vs_baseline_cost: list[float] = []
    homeo_excess_vs_baseline: list[float] = []
    homeo_rows: list[HomeostasisStats] = []

    print("benchmark=computational_homeostasis_v0.14")
    print(f"seeds={len(SEEDS)}")
    print("exchange_controller=v0.13_flow_preserving_membrane")
    print("internal_state=synthetic_computational_stress")
    print("future_relief_exchange_regimes_capacities=false")
    print("admission_shedding=false")
    print(
        f"stress_constants=initial:{INITIAL_STRESS:.0f},target_high:{TARGET_HIGH:.0f},"
        f"critical:{CRITICAL_STRESS:.0f},heat_per_unit:{HEAT_PER_UNIT:.3f}"
    )

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

        static_rows: list[tuple[int, HomeostasisStats]] = []
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

        homeo = run_policy(environment, relief, HomeostaticMembrane())
        homeo_rows.append(homeo)
        homeostatic_critical_total += homeo.critical_ticks

        static_delivered_ratio = (
            homeo.exchange.delivered / max(1, best_static.exchange.delivered)
        )
        baseline_delivered_ratio = (
            homeo.exchange.delivered / max(1, baseline.exchange.delivered)
        )
        baseline_lost_ratio = homeo.exchange.lost / max(1, baseline.exchange.lost)
        baseline_cost_ratio = homeo.exchange.cost() / max(1.0, baseline.exchange.cost())
        baseline_excess_ratio = homeo.stress_excess_integral / max(
            1e-9, baseline.stress_excess_integral
        )

        homeo_vs_static_delivered.append(static_delivered_ratio)
        homeo_vs_baseline_delivered.append(baseline_delivered_ratio)
        homeo_vs_baseline_lost.append(baseline_lost_ratio)
        homeo_vs_baseline_cost.append(baseline_cost_ratio)
        homeo_excess_vs_baseline.append(baseline_excess_ratio)

        print(
            f"seed={seed} "
            f"baseline_critical={baseline.critical_ticks} "
            f"baseline_max_stress={baseline.max_stress:.1f} "
            f"best_static_safe_cap={best_cap} "
            f"static_safe_exists={str(safe_exists).lower()} "
            f"homeo_critical={homeo.critical_ticks} "
            f"homeo_max_stress={homeo.max_stress:.1f} "
            f"homeo_vs_static_delivered={static_delivered_ratio:.3f} "
            f"homeo_vs_baseline_delivered={baseline_delivered_ratio:.3f} "
            f"homeo_vs_baseline_lost={baseline_lost_ratio:.3f} "
            f"homeo_vs_baseline_cost={baseline_cost_ratio:.3f}"
        )

    informative_fraction = baseline_critical_seed_count / len(SEEDS)
    passes = (
        informative_fraction >= 0.75
        and homeostatic_critical_total == 0
        and safe_static_exists_count == len(SEEDS)
        and median(homeo_vs_static_delivered) >= 1.08
        and median(homeo_vs_baseline_delivered) >= 0.95
        and median(homeo_vs_baseline_lost) <= 1.10
        and median(homeo_vs_baseline_cost) <= 1.25
    )

    print("\n[overall]")
    print(f"baseline_critical_seed_fraction={informative_fraction:.3f}")
    print(f"homeostatic_critical_ticks_total={homeostatic_critical_total}")
    print(f"static_safe_exists={safe_static_exists_count}/{len(SEEDS)}")
    print(
        f"median_homeo_vs_static_safe_delivered="
        f"{median(homeo_vs_static_delivered):.3f}"
    )
    print(
        f"median_homeo_vs_v013_delivered={median(homeo_vs_baseline_delivered):.3f} "
        f"p10={nearest_rank(homeo_vs_baseline_delivered, .10):.3f}"
    )
    print(
        f"median_homeo_vs_v013_lost={median(homeo_vs_baseline_lost):.3f} "
        f"median_homeo_vs_v013_exchange_cost={median(homeo_vs_baseline_cost):.3f}"
    )
    print(
        f"median_stress_excess_ratio_vs_v013={median(homeo_excess_vs_baseline):.3f}"
    )
    print(f"passes_preregistered_acceptance={str(passes).lower()}")

    print("\n[homeostatic_release_by_hidden_relief_posthoc]")
    for regime in RELIEF_REGIMES:
        releases = [
            value
            for row in homeo_rows
            for value in row.release_by_relief[regime]
        ]
        print(f"{regime}: median_release={median(releases):.1f}")

    print(
        "interpretation=Homeostasis is tested as internal-state feedback over an "
        "already flow-preserving membrane. Viability is reported separately from "
        "exchange cost, admission shedding is forbidden, and the adaptive "
        "controller must preserve materially more useful service than the "
        "strongest zero-critical static release cap."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
