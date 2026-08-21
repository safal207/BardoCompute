from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass
from statistics import median

from hazard_cadence_robustness import (
    FIXED_INTERVALS,
    PROBE_COSTS,
    SEEDS,
    STALE_REGRETS,
    HazardEstimator,
    build_environment,
    cadence,
    mean_loss,
    percentile_nearest_rank,
    run,
)
from bardocompute.policy_orientation import PolicyOrientation

BLOCK_SIZE = 1024
EXPLORATION = 0.08
LEARNING_RATE = 0.04
SHARE = 0.03
SWITCH_COST_PROBES = 4.0
HELDOUT_SEEDS = tuple(0xD5E000 + index * 6151 for index in range(32))
POLICY_NAMES = tuple(f"fixed_{interval}" for interval in FIXED_INTERVALS) + ("ewma", "rolling")


@dataclass(slots=True)
class SelectorStats:
    loss: float = 0.0
    probes: int = 0
    stale_steps: int = 0
    switches: int = 0
    blocks: int = 0
    selections: Counter[str] | None = None

    def __post_init__(self) -> None:
        if self.selections is None:
            self.selections = Counter()


def interval_for_policy(
    policy: int,
    *,
    ewma: HazardEstimator,
    rolling: HazardEstimator,
    probe_cost: float,
    stale_regret: float,
) -> int:
    if policy < len(FIXED_INTERVALS):
        return FIXED_INTERVALS[policy]
    if policy == len(FIXED_INTERVALS):
        hazard = ewma.value()
    else:
        hazard = rolling.value()
    return cadence(hazard, probe_cost, stale_regret)


def run_selector(environment, *, probe_cost: float, stale_regret: float, seed: int) -> SelectorStats:
    rng = random.Random(seed ^ 0x50A1C7)
    selector = PolicyOrientation(
        policy_count=len(POLICY_NAMES),
        exploration=EXPLORATION,
        learning_rate=LEARNING_RATE,
        share=SHARE,
    )
    ewma = HazardEstimator(mode="ewma")
    rolling = HazardEstimator(mode="rolling")
    stats = SelectorStats()

    current_epoch = 0
    calibrated_epoch = 0
    last_probe_epoch = 0
    last_probe_step = 0
    next_probe = 0
    previous_policy: int | None = None
    switch_cost = SWITCH_COST_PROBES * probe_cost

    steps = len(environment.changes)
    block_count = math.ceil(steps / BLOCK_SIZE)
    for block in range(block_count):
        start = block * BLOCK_SIZE
        stop = min(steps, start + BLOCK_SIZE)
        policy, probability = selector.choose(rng)
        stats.blocks += 1
        assert stats.selections is not None
        stats.selections[POLICY_NAMES[policy]] += 1

        block_loss = 0.0
        if previous_policy is not None and policy != previous_policy:
            stats.switches += 1
            stats.loss += switch_cost
            block_loss += switch_cost
        previous_policy = policy

        interval = interval_for_policy(
            policy,
            ewma=ewma,
            rolling=rolling,
            probe_cost=probe_cost,
            stale_regret=stale_regret,
        )
        # A policy switch can request an earlier next check, but never gets a
        # free retrospective probe.
        next_probe = min(next_probe, max(start, last_probe_step + interval)) if block > 0 else start + interval

        for step in range(start, stop):
            if environment.changes[step]:
                current_epoch += 1
            if current_epoch != calibrated_epoch:
                stats.loss += stale_regret
                block_loss += stale_regret
                stats.stale_steps += 1

            if step < next_probe:
                continue

            stats.loss += probe_cost
            block_loss += probe_cost
            stats.probes += 1
            exposure = max(1, step - last_probe_step)
            events = current_epoch - last_probe_epoch

            # The probe happened in the real selected trajectory, so its
            # transition evidence is common paid evidence. Both hazard views
            # may update from it without receiving counterfactual losses.
            ewma.update(events, exposure)
            rolling.update(events, exposure)

            calibrated_epoch = current_epoch
            last_probe_epoch = current_epoch
            last_probe_step = step
            interval = interval_for_policy(
                policy,
                ewma=ewma,
                rolling=rolling,
                probe_cost=probe_cost,
                stale_regret=stale_regret,
            )
            next_probe = step + interval

        maximum_block_loss = (
            BLOCK_SIZE * stale_regret
            + math.ceil(BLOCK_SIZE / min(FIXED_INTERVALS)) * probe_cost
            + switch_cost
        )
        normalized_loss = min(1.0, max(0.0, block_loss / max(1.0, maximum_block_loss)))
        selector.observe(policy, normalized_loss, probability)

    return stats


def summarize(values: list[float]) -> tuple[float, float, float, float]:
    return (
        sum(value < 1.0 for value in values) / len(values),
        median(values),
        percentile_nearest_rank(values, 0.90),
        max(values),
    )


def run_family(name: str, seeds: tuple[int, ...]) -> dict[str, tuple[float, float, float, float]]:
    ratios = {"ewma": [], "rolling": [], "selector": []}
    closures = {"ewma": [], "rolling": [], "selector": []}
    switch_rates: list[float] = []
    policy_counts: Counter[str] = Counter()

    print(f"\n[{name}]")
    print(f"seeds={len(seeds)}")
    for probe_cost in PROBE_COSTS:
        for stale_regret in STALE_REGRETS:
            profile_selector: list[float] = []
            for seed in seeds:
                environment = build_environment(seed)
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

                for mode in ("ewma", "rolling"):
                    adaptive = run(
                        environment,
                        probe_cost=probe_cost,
                        stale_regret=stale_regret,
                        mode=mode,
                    )
                    loss = mean_loss(adaptive, steps)
                    ratios[mode].append(loss / best_fixed_loss)
                    closures[mode].append((best_fixed_loss - loss) / available_gap)

                selected = run_selector(
                    environment,
                    probe_cost=probe_cost,
                    stale_regret=stale_regret,
                    seed=seed ^ int(probe_cost * 101) ^ int(stale_regret * 1009),
                )
                selected_loss = selected.loss / steps
                selected_ratio = selected_loss / best_fixed_loss
                ratios["selector"].append(selected_ratio)
                profile_selector.append(selected_ratio)
                closures["selector"].append((best_fixed_loss - selected_loss) / available_gap)
                switch_rates.append(selected.switches / max(1, selected.blocks - 1))
                assert selected.selections is not None
                policy_counts.update(selected.selections)

            profile_stats = summarize(profile_selector)
            print(
                f"probe={probe_cost:.0f},stale={stale_regret:.0f}: "
                f"selector_win={profile_stats[0]:.3f} median={profile_stats[1]:.3f} "
                f"p90={profile_stats[2]:.3f} worst={profile_stats[3]:.3f}"
            )

    result: dict[str, tuple[float, float, float, float]] = {}
    print(f"\n[{name}_overall_{len(seeds) * len(PROBE_COSTS) * len(STALE_REGRETS)}_profiles]")
    for mode in ("ewma", "rolling", "selector"):
        stats = summarize(ratios[mode])
        result[mode] = stats
        print(
            f"{mode}: win_rate={stats[0]:.3f} median_ratio={stats[1]:.3f} "
            f"p90_ratio={stats[2]:.3f} worst_ratio={stats[3]:.3f} "
            f"median_oracle_gap_closed={median(closures[mode]):.3f}"
        )
    print(f"selector_median_switch_rate={median(switch_rates):.3f}")
    print(
        "selector_policy_share="
        + ",".join(
            f"{policy}={policy_counts[policy] / max(1, sum(policy_counts.values())):.3f}"
            for policy in POLICY_NAMES
        )
    )

    # Relative acceptance criteria avoid tuning to absolute numbers from the
    # frozen family: retain >= half of EWMA's median gain versus fixed, and cut
    # at least half of the distance from EWMA's worst case toward rolling's.
    ewma = result["ewma"]
    rolling = result["rolling"]
    selector_result = result["selector"]
    median_limit = 1.0 - 0.5 * max(0.0, 1.0 - ewma[1])
    worst_limit = ewma[3] - 0.5 * max(0.0, ewma[3] - rolling[3])
    print(f"acceptance_median_limit={median_limit:.3f}")
    print(f"acceptance_worst_limit={worst_limit:.3f}")
    print(f"acceptance_median_pass={selector_result[1] <= median_limit}")
    print(f"acceptance_worst_pass={selector_result[3] <= worst_limit}")
    return result


def main() -> None:
    print(f"policies={','.join(POLICY_NAMES)}")
    print(f"block_size={BLOCK_SIZE}")
    print(f"exploration={EXPLORATION:.3f}")
    print(f"learning_rate={LEARNING_RATE:.3f}")
    print(f"share={SHARE:.3f}")
    print(f"switch_cost_in_probe_units={SWITCH_COST_PROBES:.1f}")
    print("feedback=selected-policy realized loss only; paid probe evidence is common")
    print("selector_parameters=predeclared_not_tuned_on_frozen_or_heldout_family")

    run_family("frozen_v03_family", SEEDS)
    run_family("heldout_family", HELDOUT_SEEDS)

    print(
        "\ninterpretation=This benchmark tests whether policy plurality plus partial-feedback "
        "regret learning can preserve EWMA's median advantage while approaching rolling's "
        "tail behavior after explicit policy-switch cost. Failure is retained; no selector "
        "parameter is retuned on either reported family."
    )


if __name__ == "__main__":
    main()
