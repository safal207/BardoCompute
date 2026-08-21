# Adaptive Observation Payback v0.1 — Hosted Results

## Question

Can a revisable observer decide whether a deeper observation is worth buying instead of using one fixed sentinel threshold for every context?

The v0.1 decision kernel is:

```text
expected_benefit =
    P(beneficial correction)
    * max(0, recoverable_miss_loss - action_cost)

expected_harm =
    P(harmful correction)
    * (false_action_loss + action_cost)

observation_score =
    expected_benefit
    - expected_harm
    - observation_cost
```

with:

```text
positive score -> REVISIT
near zero      -> HOLD
negative score -> SKIP
```

The probabilities are estimated from past calibration plus current sentinel evidence. The benchmark does not provide the hidden future of the current episode to the decision rule.

## Benchmark design

`benchmarks/observation_payback.py`

- 10,500 seeded calibration episodes;
- 14,000 in-distribution test episodes;
- 14,000 distribution-shift test episodes;
- seven regimes: `stable`, `transient`, `persistent`, `gradual`, `late_shift`, `weak_shift`, `reversal`;
- 512-signal episodes;
- an initial 128-signal observation;
- after an initial KEEP, every 32-signal interval exposes eight evenly spaced sentinel reads;
- buying the deeper observation reads the remaining 24 samples in that already-arrived interval;
- a 108-cell calibration table is indexed by `(interval_index, sentinel_hits)`;
- three-outcome Laplace smoothing is used for beneficial / harmful / neutral correction frequencies.

Equal-information controls:

1. one-shot long observation (`fixed512`);
2. a fixed sentinel threshold chosen from `1/8 ... 8/8` on the **same calibration data** for each cost profile;
3. an explicit conventional implementation of the same payback equation.

The symbolic payback implementation and the conventional formula produced identical actions across all cost profiles and all 108 calibration cells:

```text
semantic_equivalence_to_conventional=True
```

Therefore any decision benefit belongs to context-conditioned value-of-information gating, not to terminology.

## Hosted CI

GitHub Actions CI #340, Python 3.12:

```text
94 passed in 0.26s
calibration_episodes=10500
test_episodes_per_distribution=14000
calibration_source=past seeded episodes only
semantic_equivalence_to_conventional=True
```

The full CI matrix passed on Python 3.11 and Python 3.12.

## Results

### Cheap observation

Costs:

```text
sample_cost=0.10
miss_cost=120
false_action_cost=80
adapt_cost=20
```

The calibration-trained fixed control selected `5/8`. The adaptive payback policy revisited 80 of 108 context cells.

In distribution:

```text
fixed512          mean_loss=81.671   mean_observed=457.14  false=0     missed=3434
trained fixed 5/8 mean_loss=45.445   mean_observed=195.31  false=1993  missed=35
adaptive payback  mean_loss=47.176   mean_observed=214.90  false=1996  missed=0
```

Distribution shift:

```text
fixed512          mean_loss=99.333   mean_observed=437.97  false=699   missed=5476
trained fixed 5/8 mean_loss=50.167   mean_observed=193.60  false=2628  missed=85
adaptive payback  mean_loss=53.111   mean_observed=224.04  false=2698  missed=1
```

Negative result: payback bought extra sensitivity but did not repay its additional observation cost versus the tuned fixed threshold.

### Balanced costs

Costs:

```text
sample_cost=0.50
miss_cost=120
false_action_cost=80
adapt_cost=20
```

The trained fixed control again selected `5/8`; payback revisited 65 of 108 context cells.

In distribution:

```text
fixed512          mean_loss=264.529  mean_observed=457.14  false=0     missed=3434
trained fixed 5/8 mean_loss=123.568  mean_observed=195.31  false=1993  missed=35
adaptive payback  mean_loss=125.215  mean_observed=199.13  false=1991  missed=0
```

Distribution shift:

```text
fixed512          mean_loss=274.521  mean_observed=437.97  false=699   missed=5476
trained fixed 5/8 mean_loss=127.607  mean_observed=193.60  false=2628  missed=85
adaptive payback  mean_loss=131.181  mean_observed=200.99  false=2693  missed=3
```

Again, payback reduced misses almost to zero but did not minimize total economic loss.

### False-adapt-sensitive costs

Costs:

```text
sample_cost=0.50
miss_cost=120
false_action_cost=500
adapt_cost=20
```

The calibration-trained global threshold became much more conservative: `8/8`. Payback revisited 43 of 108 context cells.

#### In distribution — positive result

```text
fixed512          mean_loss=264.529  mean_observed=457.14  false=0     missed=3434
trained fixed 8/8 mean_loss=169.733  mean_observed=207.73  false=898   missed=2952
adaptive payback  mean_loss=161.677  mean_observed=205.11  false=1284  missed=0
```

Adaptive payback reduced mean loss by about 4.7% versus the strong calibration-trained global threshold:

```text
161.677 / 169.733 = 0.953x
```

It did this by accepting 386 additional false adaptations while eliminating 2,952 missed adaptations. The useful property here is not simply greater sensitivity: the context-conditioned policy can choose different revisit behavior for different time/hit cells, whereas a single global threshold cannot.

#### Distribution shift — falsification

```text
fixed512          mean_loss=295.491  mean_observed=437.97  false=699   missed=5476
trained fixed 8/8 mean_loss=184.801  mean_observed=204.68  false=1023  missed=4625
adaptive payback  mean_loss=199.415  mean_observed=204.92  false=2302  missed=3
```

The advantage reverses. Static calibrated payback is about 7.9% more expensive than the simple trained threshold:

```text
199.415 / 184.801 = 1.079x
```

The payback policy remains extremely sensitive (`3` misses versus `4,625`) but its stale calibration underestimates harmful correction risk (`2,302` false adaptations versus `1,023`).

This is the strongest new falsification result.

### Expensive observation

Costs:

```text
sample_cost=2.00
miss_cost=120
false_action_cost=80
adapt_cost=20
```

The trained global threshold selected `5/8`; payback revisited only 44 of 108 cells.

In distribution:

```text
trained fixed 5/8 mean_loss=416.528  mean_observed=195.31  false=1993  missed=35
adaptive payback  mean_loss=419.895  mean_observed=198.12  false=1711  missed=0
```

Distribution shift:

```text
trained fixed 5/8 mean_loss=418.005  mean_observed=193.60  false=2628  missed=85
adaptive payback  mean_loss=422.073  mean_observed=196.27  false=2526  missed=8
```

The dynamic gate reacts to observation price by shrinking its revisit region, but the trained fixed control remains slightly cheaper in this workload.

## What survived falsification

The broad claim "adaptive payback is better than a fixed threshold" is **not supported**.

A narrower claim survives:

> A context-conditioned value-of-information gate can outperform a calibration-trained global observation threshold when error costs are asymmetric and calibration matches deployment, but stale calibration under distribution shift can reverse the advantage.

This is useful because it identifies the next bottleneck precisely:

```text
not observation policy alone
but calibration trust under change
```

The measured crossover is especially informative because observation volume is almost identical in the false-adapt-sensitive shifted case (`204.92` versus `204.68`). The loss reversal is therefore not explained by simply spending more samples. It is primarily a **decision-calibration failure**: the stale context table routes too many shifted episodes into adaptation.

## Two economic gates

The architecture now separates two purchases:

```text
cheap evidence / sentinel
        ↓
Observation Payback
SKIP / HOLD / REVISIT
        ↓ if REVISIT
additional observation / zoom
        ↓
Living Process Orientation
KEEP / HOLD / ADAPT
        ↓
execution + outcome
        ↓
calibration feedback
```

Gate 1 asks:

```text
Is more knowledge worth buying?
```

Gate 2 asks:

```text
Is changed behavior worth buying?
```

The result suggests that both gates need explicit uncertainty and calibration provenance.

## Next falsification: calibration-aware payback

The next experiment should compare:

1. calibration-trained global threshold;
2. static context-conditioned payback (current v0.1);
3. uncertainty-shrunk / Bayesian payback;
4. online drift-aware recalibrated payback.

Without future leakage, sweep distribution-shift severity and measure:

- mean economic loss;
- false adaptations;
- missed adaptations;
- observation volume;
- deep-inspection frequency;
- calibration error (for example Brier score);
- detection lag;
- the crossover point where static payback stops beating the simpler fixed threshold.

A new adaptive method only survives if its improvement remains after the cost of drift detection and recalibration is included.

## Current bottleneck

```text
Bardo / trajectory tells us that history matters.
Observer zoom tells us that scale matters.
Observation payback tells us that knowledge has a price.
Distribution shift now tells us that the price estimate itself has a lifetime.
```

The next core state is therefore not another symbolic layer. It is an explicit, testable notion of **calibration freshness / trust**.

## Scientific boundary

The result is a decision-theoretic engineering finding in constructed workloads. It does not establish a universal law of observation, intelligence, cognition, finance, biology, or physics.

The negative distribution-shift result is part of the evidence and must remain visible.