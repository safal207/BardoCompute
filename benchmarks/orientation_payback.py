from __future__ import annotations

import random

from bardocompute.living_process import (
    OrientationAction,
    OrientationEvidence,
    evaluate_orientation,
)


EPISODES = 200_000
SEED = 0xBADA
OBSERVATION_LAG = 32.0
OBSERVATION_COST = 32.0
SWITCH_COST = 80.0
ERROR_COST = 16.0
SAVING_PER_STEP = 1.0
CONFIDENCE = 0.85
HOLD_MARGIN = 8.0

# Deliberately mixed short and long-lived regimes. Repetition implements the
# weighting without depending on random.choices floating-point details.
REGIME_POPULATION = (
    [16] * 10
    + [32] * 10
    + [64] * 9
    + [96] * 8
    + [128] * 8
    + [192] * 7
    + [256] * 7
    + [384] * 6
    + [512] * 6
    + [768] * 5
    + [1024] * 4
    + [1536] * 3
    + [2048] * 2
)


def main() -> None:
    rng = random.Random(SEED)

    reactive_utility = 0.0
    orientation_utility = 0.0
    oracle_utility = 0.0

    reactive_switches = 0
    orientation_switches = 0
    oracle_switches = 0

    reactive_losing_switches = 0
    orientation_losing_switches = 0

    keep_count = 0
    hold_count = 0
    adapt_count = 0

    for _ in range(EPISODES):
        regime_length = REGIME_POPULATION[rng.randrange(len(REGIME_POPULATION))]
        true_remaining = max(0.0, regime_length - OBSERVATION_LAG)

        # The orientation layer never sees true persistence. It gets a noisy
        # estimate, while the oracle receives true remaining lifetime only as
        # an upper-bound control.
        estimate_noise = rng.uniform(0.55, 1.45)
        estimated_remaining = true_remaining * estimate_noise

        realized_adapt_utility = (
            true_remaining * SAVING_PER_STEP
            - OBSERVATION_COST
            - SWITCH_COST
            - ERROR_COST
        )

        # Reactive control: every detected regime change triggers adaptation.
        reactive_switches += 1
        reactive_utility += realized_adapt_utility
        if realized_adapt_utility < -OBSERVATION_COST:
            reactive_losing_switches += 1

        result = evaluate_orientation(
            OrientationEvidence(
                confidence=CONFIDENCE,
                expected_remaining_steps=estimated_remaining,
                saving_per_step=SAVING_PER_STEP,
                observation_cost=OBSERVATION_COST,
                switch_cost=SWITCH_COST,
                error_cost=ERROR_COST,
                hold_margin=HOLD_MARGIN,
            )
        )

        if result.action is OrientationAction.ADAPT:
            adapt_count += 1
            orientation_switches += 1
            orientation_utility += realized_adapt_utility
            if realized_adapt_utility < -OBSERVATION_COST:
                orientation_losing_switches += 1
        elif result.action is OrientationAction.HOLD:
            hold_count += 1
            orientation_utility -= OBSERVATION_COST
        else:
            keep_count += 1
            orientation_utility -= OBSERVATION_COST

        # Oracle control: after paying the same observation cost, switch only
        # if true future savings can repay switch + error cost.
        if true_remaining * SAVING_PER_STEP > SWITCH_COST + ERROR_COST:
            oracle_switches += 1
            oracle_utility += realized_adapt_utility
        else:
            oracle_utility -= OBSERVATION_COST

    oracle_gap = oracle_utility - reactive_utility
    orientation_gain = orientation_utility - reactive_utility
    gap_closed = orientation_gain / oracle_gap if oracle_gap > 0.0 else 0.0

    print(f"episodes={EPISODES}")
    print(f"seed={SEED}")
    print(f"reactive_utility={reactive_utility:.0f}")
    print(f"orientation_utility={orientation_utility:.0f}")
    print(f"oracle_utility={oracle_utility:.0f}")
    print(f"orientation_vs_reactive={orientation_utility / reactive_utility:.3f}x")
    print(f"oracle_gap_closed={gap_closed:.3f}")
    print(f"reactive_switches={reactive_switches}")
    print(f"orientation_switches={orientation_switches}")
    print(f"oracle_switches={oracle_switches}")
    print(f"reactive_losing_switches={reactive_losing_switches}")
    print(f"orientation_losing_switches={orientation_losing_switches}")
    print(f"keep={keep_count}")
    print(f"hold={hold_count}")
    print(f"adapt={adapt_count}")
    print(
        "interpretation=Detected change is not sufficient reason to adapt. "
        "The orientation-payback gate asks whether noisy estimated persistence "
        "can repay observation, switching, and error costs."
    )

    assert orientation_utility > reactive_utility
    assert oracle_utility >= orientation_utility
    assert orientation_losing_switches < reactive_losing_switches
    assert keep_count > 0 and hold_count > 0 and adapt_count > 0


if __name__ == "__main__":
    main()
