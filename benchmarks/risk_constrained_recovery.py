from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median

from bardocompute.stochastic import StochasticCapabilityState
from recovery_state_transfer import (
    FIXED_INTERVALS,
    HAZARDS,
    PROBE_COSTS,
    SEEDS,
    STALE_REGRETS,
    HazardEstimator,
    RecoveryEnvironment,
    build_environment,
    cadence,
    process_authoritative_probe,
    run as run_unconstrained,
)

SAFETY_BUDGETS = (16, 32, 64)


@dataclass(slots=True)
class ConstrainedStats:
    loss: float = 0.0
    probes: int = 0
    unsafe_ticks: int = 0
    max_undetected_stale_age: int = 0
    constraint_violation_ticks: int = 0
    false_recoveries: int = 0


def run_constrained(
    environment: RecoveryEnvironment,
    *,
    seed: int,
    probe_cost: float,
    stale_regret: float,
    mode: str,
    safety_budget: int,
    fixed_interval: int | None = None,
) -> ConstrainedStats:
    stats = ConstrainedStats()
    estimator = HazardEstimator(mode=mode if mode in {"ewma", "rolling"} else "ewma")
    state = StochasticCapabilityState()
    authority_epoch = 0
    last_probe_epoch = 0
    last_probe_step = 0
    undetected_stale_age = 0

    def selected_interval(step: int) -> int:
        if fixed_interval is not None:
            base = fixed_interval
        elif mode == "oracle":
            base = cadence(environment.hazards[step], probe_cost, stale_regret)
        else:
            base = cadence(estimator.value(), probe_cost, stale_regret)
        return min(base, safety_budget)

    interval = selected_interval(0)
    next_probe = interval

    for step, restarted in enumerate(environment.restarts):
        if restarted:
            authority_epoch += 1

        if state.epoch != authority_epoch:
            undetected_stale_age += 1
        else:
            undetected_stale_age = 0

        stats.max_undetected_stale_age = max(
            stats.max_undetected_stale_age,
            undetected_stale_age,
        )
        stats.constraint_violation_ticks += int(
            undetected_stale_age > safety_budget
        )

        if state.epoch != authority_epoch or state.active_shock:
            stats.loss += stale_regret
            stats.unsafe_ticks += 1

        if step < next_probe:
            continue

        stats.loss += probe_cost
        stats.probes += 1
        exposure = max(1, step - last_probe_step)
        events = authority_epoch - last_probe_epoch
        if mode in {"ewma", "rolling"}:
            estimator.update(events, exposure)

        # Reuse the exact noisy receipt/provenance path from v0.6. The helper
        # expects counters for receipt classes, so a tiny compatible object is
        # attached without changing recovery semantics.
        class ReceiptCounters:
            stale_receipts = 0
            premature_receipts = 0
            duplicate_receipts = 0

        receipt_counters = ReceiptCounters()
        state = process_authoritative_probe(
            state,
            authority_epoch=authority_epoch,
            seed=seed,
            step=step,
            stats=receipt_counters,  # type: ignore[arg-type]
        )
        stats.false_recoveries += int(
            not state.active_shock and state.epoch != authority_epoch
        )
        if state.epoch == authority_epoch:
            undetected_stale_age = 0

        last_probe_epoch = authority_epoch
        last_probe_step = step
        interval = selected_interval(step)
        next_probe = step + interval

    return stats


def nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def summarize(name: str, ratios: list[float], unsafe: list[float]) -> None:
    print(
        f"{name}: win_rate={sum(value < 1.0 for value in ratios) / len(ratios):.3f} "
        f"median_loss_ratio={median(ratios):.3f} "
        f"p90_loss_ratio={nearest_rank(ratios, 0.90):.3f} "
        f"worst_loss_ratio={max(ratios):.3f} "
        f"median_unsafe_ratio={median(unsafe):.3f}"
    )


def main() -> None:
    environments = [(seed, build_environment(seed)) for seed in SEEDS]
    print(f"seeds={len(SEEDS)}")
    print("domain=recovery_state")
    print("safety_constraint=max_undetected_authority_stale_age")
    print("safety_budgets=" + ",".join(str(value) for value in SAFETY_BUDGETS))
    print("economics=unchanged_hazard_cadence_formula_clipped_only_by_safety_budget")
    print("future_restart_boundaries_and_hazards=hidden")

    for budget in SAFETY_BUDGETS:
        overall = {"ewma": [], "rolling": []}
        overall_unsafe = {"ewma": [], "rolling": []}
        all_violations = {"ewma": 0, "rolling": 0}
        max_age = {"ewma": 0, "rolling": 0}
        false_recoveries = {"ewma": 0, "rolling": 0}
        preserved_gain = {"ewma": [], "rolling": []}

        allowed_fixed = tuple(interval for interval in FIXED_INTERVALS if interval <= budget)
        print(f"\n[safety_budget={budget}]")
        print("safe_fixed_candidates=" + ",".join(str(value) for value in allowed_fixed))

        for probe_cost in PROBE_COSTS:
            for stale_regret in STALE_REGRETS:
                profile = {"ewma": [], "rolling": []}
                for seed, environment in environments:
                    steps = len(environment.restarts)
                    safe_fixed_rows = [
                        run_constrained(
                            environment,
                            seed=seed,
                            probe_cost=probe_cost,
                            stale_regret=stale_regret,
                            mode="fixed",
                            safety_budget=budget,
                            fixed_interval=interval,
                        )
                        for interval in allowed_fixed
                    ]
                    best_safe_fixed = min(
                        safe_fixed_rows,
                        key=lambda row: row.loss / steps,
                    )
                    safe_fixed_loss = best_safe_fixed.loss / steps
                    safe_fixed_unsafe = max(1, best_safe_fixed.unsafe_ticks)

                    for mode in ("ewma", "rolling"):
                        constrained = run_constrained(
                            environment,
                            seed=seed,
                            probe_cost=probe_cost,
                            stale_regret=stale_regret,
                            mode=mode,
                            safety_budget=budget,
                        )
                        constrained_loss = constrained.loss / steps
                        ratio = constrained_loss / safe_fixed_loss
                        profile[mode].append(ratio)
                        overall[mode].append(ratio)
                        overall_unsafe[mode].append(
                            constrained.unsafe_ticks / safe_fixed_unsafe
                        )
                        all_violations[mode] += constrained.constraint_violation_ticks
                        max_age[mode] = max(
                            max_age[mode],
                            constrained.max_undetected_stale_age,
                        )
                        false_recoveries[mode] += constrained.false_recoveries

                        unconstrained = run_unconstrained(
                            environment,
                            seed=seed,
                            probe_cost=probe_cost,
                            stale_regret=stale_regret,
                            mode=mode,
                        )
                        unconstrained_loss = unconstrained.loss / steps
                        available_gain = safe_fixed_loss - unconstrained_loss
                        if available_gain > 1e-12:
                            preserved_gain[mode].append(
                                (safe_fixed_loss - constrained_loss) / available_gain
                            )

                print(
                    f"probe={probe_cost:.0f},stale={stale_regret:.0f}: "
                    f"ewma_median={median(profile['ewma']):.3f} "
                    f"rolling_median={median(profile['rolling']):.3f}"
                )

        print("[budget_overall]")
        for mode in ("ewma", "rolling"):
            summarize(mode, overall[mode], overall_unsafe[mode])
            print(f"{mode}_constraint_violation_ticks={all_violations[mode]}")
            print(f"{mode}_max_undetected_stale_age={max_age[mode]}")
            print(f"{mode}_post_probe_false_recoveries={false_recoveries[mode]}")
            if preserved_gain[mode]:
                print(
                    f"{mode}_median_unconstrained_gain_preserved="
                    f"{median(preserved_gain[mode]):.3f}"
                )

    print(
        "interpretation=Risk-Constrained Orientation makes safety lexicographic: "
        "the cadence optimizer may choose any economically useful interval only "
        "inside a predeclared maximum undetected-authority-staleness horizon. The "
        "constraint is not converted into a larger scalar penalty and therefore "
        "cannot be purchased by expected economic gain. A constrained policy earns "
        "promotion only if constraint violations and post-probe false recoveries are "
        "zero while meaningful economic benefit remains versus the strongest fixed "
        "cadence satisfying the same safety budget."
    )


if __name__ == "__main__":
    main()
