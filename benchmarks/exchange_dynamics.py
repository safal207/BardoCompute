from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import median

from bardocompute.exchange import (
    ExchangeResult,
    ExchangeState,
    ExchangeStep,
    MembraneCommand,
    regulate_exchange,
)

SEEDS = tuple(61001 + i * 7919 for i in range(12))
STEPS = 16_000
BUFFER_LIMIT = 256
FIXED_RATES = (32, 48, 64, 80, 96, 112)
FIXED_SECONDARY = (0.0, 0.25, 0.50, 0.75)

LOSS_COST = 8.0
CONGESTION_COST = 1.5
HOLDING_COST = 0.04
SECONDARY_COST = 0.12
CONTROL_MOVE_COST = 0.50

REGIMES = {
    "normal": (48, 58, 22),
    "burst": (92, 62, 28),
    "primary_degraded": (54, 16, 58),
    "global_congested": (60, 24, 18),
    "recovery": (44, 72, 34),
}


@dataclass(frozen=True, slots=True)
class Environment:
    steps: tuple[ExchangeStep, ...]
    regimes: tuple[str, ...]


@dataclass(slots=True)
class RunStats:
    delivered: int = 0
    lost: int = 0
    congestion: int = 0
    buffer_integral: int = 0
    secondary_delivered: int = 0
    control_moves: int = 0
    terminal_buffer: int = 0
    rate_by_regime: dict[str, list[int]] = field(
        default_factory=lambda: {name: [] for name in REGIMES}
    )
    secondary_by_regime: dict[str, list[float]] = field(
        default_factory=lambda: {name: [] for name in REGIMES}
    )

    def cost(self) -> float:
        return (
            (self.lost + self.terminal_buffer) * LOSS_COST
            + self.congestion * CONGESTION_COST
            + self.buffer_integral * HOLDING_COST
            + self.secondary_delivered * SECONDARY_COST
            + self.control_moves * CONTROL_MOVE_COST
        )


class FeedbackMembrane:
    """Past-only feedback controller for gate/rate/route exchange regulation."""

    def __init__(self, *, route_enabled: bool = True) -> None:
        self.rate = 64
        self.secondary_fraction = 0.15 if route_enabled else 0.0
        self.route_enabled = route_enabled
        self.previous: ExchangeResult | None = None

    def command(self) -> MembraneCommand:
        if self.previous is not None:
            prev = self.previous
            released = max(1, prev.released)
            total_pressure = prev.congestion / released
            primary_pressure = (
                (prev.primary_requested - prev.primary_delivered)
                / max(1, prev.primary_requested)
            )
            secondary_pressure = (
                (prev.secondary_requested - prev.secondary_delivered)
                / max(1, prev.secondary_requested)
            )
            occupancy = prev.buffered / BUFFER_LIMIT

            if self.route_enabled:
                if primary_pressure > max(0.03, secondary_pressure + 0.02):
                    self.secondary_fraction = min(
                        0.85, self.secondary_fraction + 0.12
                    )
                elif secondary_pressure > max(0.03, primary_pressure + 0.02):
                    self.secondary_fraction = max(
                        0.0, self.secondary_fraction - 0.12
                    )
                elif total_pressure == 0.0:
                    # Secondary path is intentionally more expensive; drift back
                    # toward primary when the observed exchange is uncongested.
                    self.secondary_fraction += (
                        0.12 - self.secondary_fraction
                    ) * 0.06
            else:
                self.secondary_fraction = 0.0

            if total_pressure > 0.15:
                self.rate = max(12, int(self.rate * 0.75))
            elif total_pressure > 0.0:
                self.rate = max(12, int(self.rate * 0.90))
            elif occupancy > 0.35:
                self.rate = min(128, self.rate + 8)
            else:
                self.rate = min(128, self.rate + 3)

        occupancy = 0.0
        if self.previous is not None:
            occupancy = self.previous.buffered / BUFFER_LIMIT

        if occupancy > 0.88:
            admission_limit: int | None = max(0, int(self.rate * 0.75))
        elif occupancy > 0.72:
            admission_limit = self.rate
        else:
            admission_limit = None

        return MembraneCommand(
            admission_limit=admission_limit,
            release_limit=self.rate,
            buffer_limit=BUFFER_LIMIT,
            secondary_fraction=self.secondary_fraction,
        )

    def observe(self, result: ExchangeResult) -> None:
        self.previous = result


def build_environment(seed: int) -> Environment:
    rng = random.Random(seed)
    steps: list[ExchangeStep] = []
    labels: list[str] = []
    names = tuple(REGIMES)
    previous: str | None = None

    while len(steps) < STEPS:
        candidates = [name for name in names if name != previous]
        regime = rng.choice(candidates)
        previous = regime
        duration = rng.randint(180, 720)
        incoming_base, primary_base, secondary_base = REGIMES[regime]

        for _ in range(duration):
            if len(steps) >= STEPS:
                break
            incoming = max(0, incoming_base + rng.randint(-8, 8))
            primary = max(0, primary_base + rng.randint(-5, 5))
            secondary = max(0, secondary_base + rng.randint(-4, 4))
            steps.append(
                ExchangeStep(
                    incoming=incoming,
                    primary_capacity=primary,
                    secondary_capacity=secondary,
                )
            )
            labels.append(regime)

    return Environment(tuple(steps), tuple(labels))


def fixed_command(rate: int, secondary_fraction: float) -> MembraneCommand:
    return MembraneCommand(
        release_limit=rate,
        buffer_limit=BUFFER_LIMIT,
        secondary_fraction=secondary_fraction,
        admission_limit=None,
    )


def oracle_command(state: ExchangeState, step: ExchangeStep) -> MembraneCommand:
    # Current-state upper reference only.  It sees the current capacities, which
    # the feedback membrane does not.  It still has no future regime information.
    available = state.buffered + step.incoming
    release = min(available, step.primary_capacity + step.secondary_capacity)
    secondary = max(0, release - step.primary_capacity)
    share = secondary / release if release else 0.0
    return MembraneCommand(
        release_limit=release,
        buffer_limit=BUFFER_LIMIT,
        secondary_fraction=share,
        admission_limit=None,
    )


def command_changed(a: MembraneCommand | None, b: MembraneCommand) -> bool:
    if a is None:
        return False
    return (
        a.release_limit != b.release_limit
        or a.admission_limit != b.admission_limit
        or abs(a.secondary_fraction - b.secondary_fraction) >= 0.025
    )


def run_environment(
    environment: Environment,
    *,
    fixed: tuple[int, float] | None = None,
    feedback: FeedbackMembrane | None = None,
    oracle: bool = False,
) -> RunStats:
    state = ExchangeState()
    stats = RunStats()
    previous_command: MembraneCommand | None = None

    for step, regime in zip(environment.steps, environment.regimes, strict=True):
        if fixed is not None:
            command = fixed_command(*fixed)
        elif feedback is not None:
            command = feedback.command()
        elif oracle:
            command = oracle_command(state, step)
        else:
            raise ValueError("one policy must be selected")

        if command_changed(previous_command, command):
            stats.control_moves += 1
        previous_command = command

        result = regulate_exchange(state, step, command)
        if feedback is not None:
            feedback.observe(result)

        stats.delivered += result.delivered
        stats.lost += result.lost
        stats.congestion += result.congestion
        stats.buffer_integral += result.buffered
        stats.secondary_delivered += result.secondary_delivered
        stats.rate_by_regime[regime].append(command.release_limit)
        stats.secondary_by_regime[regime].append(command.secondary_fraction)

    stats.terminal_buffer = state.buffered
    return stats


def nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def main() -> None:
    environments = [(seed, build_environment(seed)) for seed in SEEDS]
    ratios: list[float] = []
    delivered_ratios: list[float] = []
    loss_ratios: list[float] = []
    rate_only_ratios: list[float] = []
    oracle_ratios: list[float] = []
    membrane_rows: list[RunStats] = []

    print("benchmark=computational_membrane_exchange_dynamics_v0.12")
    print(f"seeds={len(SEEDS)}")
    print(f"steps_per_seed={STEPS}")
    print("controller_information=past_exchange_outcomes+current_buffer_only")
    print("future_regimes=false")
    print("fixed_control=best_posthoc_rate_x_route_split_per_seed")
    print(
        "cost=lost*8 + congestion*1.5 + buffer_integral*.04 "
        "+ secondary_delivered*.12 + control_moves*.50"
    )

    for seed, environment in environments:
        fixed_rows: list[tuple[float, RunStats, int, float]] = []
        for rate in FIXED_RATES:
            for share in FIXED_SECONDARY:
                stats = run_environment(environment, fixed=(rate, share))
                fixed_rows.append((stats.cost(), stats, rate, share))
        best_fixed_cost, best_fixed, best_rate, best_share = min(
            fixed_rows, key=lambda row: row[0]
        )

        membrane = run_environment(
            environment,
            feedback=FeedbackMembrane(route_enabled=True),
        )
        rate_only = run_environment(
            environment,
            feedback=FeedbackMembrane(route_enabled=False),
        )
        oracle_stats = run_environment(environment, oracle=True)
        membrane_rows.append(membrane)

        ratio = membrane.cost() / best_fixed_cost
        rate_only_ratio = rate_only.cost() / best_fixed_cost
        oracle_ratio = oracle_stats.cost() / best_fixed_cost
        delivered_ratio = membrane.delivered / max(1, best_fixed.delivered)
        loss_ratio = membrane.lost / max(1, best_fixed.lost)

        ratios.append(ratio)
        rate_only_ratios.append(rate_only_ratio)
        oracle_ratios.append(oracle_ratio)
        delivered_ratios.append(delivered_ratio)
        loss_ratios.append(loss_ratio)

        print(
            f"seed={seed} best_fixed={best_rate}/{best_share:.2f} "
            f"membrane_ratio={ratio:.3f} rate_only_ratio={rate_only_ratio:.3f} "
            f"oracle_ratio={oracle_ratio:.3f} delivered_ratio={delivered_ratio:.3f} "
            f"loss_ratio={loss_ratio:.3f}"
        )

    win_rate = sum(value < 1.0 for value in ratios) / len(ratios)
    semantic_pass = (
        win_rate >= 0.65
        and median(ratios) < 0.98
        and median(delivered_ratios) >= 0.98
        and median(loss_ratios) <= 1.05
    )

    print("\n[overall]")
    print(
        f"full_membrane: win_rate={win_rate:.3f} "
        f"median_cost_ratio={median(ratios):.3f} "
        f"p90_cost_ratio={nearest_rank(ratios, .90):.3f} "
        f"worst_cost_ratio={max(ratios):.3f} "
        f"median_delivered_ratio={median(delivered_ratios):.3f} "
        f"median_loss_ratio={median(loss_ratios):.3f}"
    )
    print(
        f"rate_only_ablation: win_rate="
        f"{sum(value < 1.0 for value in rate_only_ratios) / len(rate_only_ratios):.3f} "
        f"median_cost_ratio={median(rate_only_ratios):.3f} "
        f"worst_cost_ratio={max(rate_only_ratios):.3f}"
    )
    print(
        f"current_state_oracle: median_cost_ratio={median(oracle_ratios):.3f} "
        f"worst_cost_ratio={max(oracle_ratios):.3f}"
    )
    print(f"passes_preregistered_acceptance={str(semantic_pass).lower()}")

    print("\n[membrane_morphology_posthoc]")
    for regime in REGIMES:
        rates = [
            value
            for row in membrane_rows
            for value in row.rate_by_regime[regime]
        ]
        shares = [
            value
            for row in membrane_rows
            for value in row.secondary_by_regime[regime]
        ]
        print(
            f"{regime}: median_rate={median(rates):.1f} "
            f"median_secondary_fraction={median(shares):.3f}"
        )

    print(
        "interpretation=The membrane is an exchange actuator, not an oracle. "
        "It changes admission, release rate, buffering pressure response, and "
        "routing from past exchange outcomes only. A promoted result requires "
        "lower total exchange cost than a strong post-hoc fixed control without "
        "winning by simply shedding materially more useful flow."
    )

    if not semantic_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
