from __future__ import annotations

import math
from statistics import median

from bardocompute.exchange import ExchangeResult, MembraneCommand

from exchange_dynamics import (
    BUFFER_LIMIT,
    FIXED_RATES,
    FIXED_SECONDARY,
    FeedbackMembrane,
    build_environment,
    run_environment,
)

SEEDS = tuple(710_003 + i * 13_007 for i in range(12))


class FlowPreservingMembrane:
    """Past-only exchange control that reroutes before throttling.

    Unlike v0.12, this policy may not discard new work at the gate.  It changes
    coupling first when pressure is local to one route and reduces total release
    only when the evidence indicates aggregate capacity is insufficient.
    """

    def __init__(self, *, route_enabled: bool = True) -> None:
        self.rate = 80
        self.secondary_fraction = 0.20 if route_enabled else 0.0
        self.route_enabled = route_enabled
        self.previous: ExchangeResult | None = None

    def command(self) -> MembraneCommand:
        if self.previous is not None:
            prev = self.previous
            primary_pressure = (
                (prev.primary_requested - prev.primary_delivered)
                / max(1, prev.primary_requested)
            )
            secondary_pressure = (
                (prev.secondary_requested - prev.secondary_delivered)
                / max(1, prev.secondary_requested)
            )
            occupancy = prev.buffered / BUFFER_LIMIT
            primary_bad = primary_pressure > 0.02
            secondary_bad = secondary_pressure > 0.02
            rerouted = False

            if self.route_enabled:
                if primary_bad and not secondary_bad and self.secondary_fraction < 0.85:
                    self.secondary_fraction = min(
                        0.85, self.secondary_fraction + 0.10
                    )
                    rerouted = True
                elif secondary_bad and not primary_bad and self.secondary_fraction > 0.0:
                    self.secondary_fraction = max(
                        0.0, self.secondary_fraction - 0.10
                    )
                    rerouted = True
                elif not primary_bad and not secondary_bad and occupancy < 0.25:
                    # Prefer the cheaper primary path when both paths are healthy.
                    self.secondary_fraction += (
                        0.15 - self.secondary_fraction
                    ) * 0.03
            else:
                self.secondary_fraction = 0.0

            if primary_bad and secondary_bad:
                # Evidence says aggregate release exceeds aggregate observed
                # capacity. Track delivered flow with small recovery headroom.
                self.rate = max(16, min(self.rate, prev.delivered + 4))
            elif prev.congestion > 0 and not rerouted:
                self.rate = max(16, min(self.rate, prev.delivered + 6))
            elif prev.congestion == 0:
                # If useful work remains buffered and the last exchange cleared,
                # restore release aggressively instead of preserving throttling.
                if occupancy > 0.50:
                    self.rate = min(128, self.rate + 16)
                elif occupancy > 0.15:
                    self.rate = min(128, self.rate + 8)
                else:
                    self.rate = min(128, self.rate + 3)

        return MembraneCommand(
            admission_limit=None,
            release_limit=self.rate,
            buffer_limit=BUFFER_LIMIT,
            secondary_fraction=self.secondary_fraction,
        )

    def observe(self, result: ExchangeResult) -> None:
        self.previous = result


def nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def main() -> None:
    ratios: list[float] = []
    delivered_ratios: list[float] = []
    loss_ratios: list[float] = []
    rate_only_ratios: list[float] = []
    membrane_rows = []

    print("benchmark=flow_preserving_computational_membrane_v0.13")
    print(f"seeds={len(SEEDS)}")
    print("validation_family=fresh_held_out_after_v0.12_failure")
    print("discretionary_gate_shedding=false")
    print("rule=reroute_local_pressure_before_throttling_total_exchange")
    print("future_regimes_capacities_arrivals=false")

    for seed in SEEDS:
        environment = build_environment(seed)
        fixed_rows = []
        for rate in FIXED_RATES:
            for share in FIXED_SECONDARY:
                stats = run_environment(environment, fixed=(rate, share))
                fixed_rows.append((stats.cost(), stats, rate, share))
        best_fixed_cost, best_fixed, best_rate, best_share = min(
            fixed_rows, key=lambda row: row[0]
        )

        membrane = run_environment(
            environment,
            feedback=FlowPreservingMembrane(route_enabled=True),
        )
        rate_only = run_environment(
            environment,
            feedback=FlowPreservingMembrane(route_enabled=False),
        )
        membrane_rows.append(membrane)

        ratio = membrane.cost() / best_fixed_cost
        delivered_ratio = membrane.delivered / max(1, best_fixed.delivered)
        loss_ratio = membrane.lost / max(1, best_fixed.lost)
        rate_only_ratio = rate_only.cost() / best_fixed_cost

        ratios.append(ratio)
        delivered_ratios.append(delivered_ratio)
        loss_ratios.append(loss_ratio)
        rate_only_ratios.append(rate_only_ratio)

        print(
            f"seed={seed} best_fixed={best_rate}/{best_share:.2f} "
            f"membrane_ratio={ratio:.3f} "
            f"rate_only_ratio={rate_only_ratio:.3f} "
            f"delivered_ratio={delivered_ratio:.3f} "
            f"loss_ratio={loss_ratio:.3f}"
        )

    win_rate = sum(value < 1.0 for value in ratios) / len(ratios)
    route_value = median(ratios) / max(1e-12, median(rate_only_ratios))
    passes = (
        win_rate >= 0.75
        and median(ratios) < 0.95
        and nearest_rank(ratios, 0.90) <= 1.05
        and median(delivered_ratios) >= 0.995
        and median(loss_ratios) <= 1.02
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
        f"rate_only_ablation: median_cost_ratio={median(rate_only_ratios):.3f} "
        f"full_vs_rate_only_median_ratio={route_value:.3f}"
    )
    print(f"passes_preregistered_acceptance={str(passes).lower()}")

    print("\n[membrane_morphology_posthoc]")
    for regime in (
        "normal",
        "burst",
        "primary_degraded",
        "global_congested",
        "recovery",
    ):
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
        "interpretation=v0.13 tests a conservation-aware exchange rule after "
        "v0.12 showed that unconstrained gate control could lower cost by "
        "discarding too much useful flow. The new policy preserves admission, "
        "reroutes local pressure before reducing aggregate release, and only "
        "throttles when observed pressure cannot be relieved by changing route."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
