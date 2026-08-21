# Hazard-Aware Cadence v0.2 — Hosted Results

## Question

Can the observer adapt **when** it checks its knowledge by estimating the environment's transition hazard from past/present probe history, rather than using current calibration mismatch as a proxy for future change probability?

This follows the negative Adaptive Probe Cadence v0.1 result, where the cadence rule collapsed `trust`, current `drift`, and consequence into one stale-regret rate and saturated near the minimum interval.

The v0.2 causal separation is:

```text
TRUST       = credibility of the current calibration now
DRIFT       = current mismatch evidence
HAZARD      = probability/rate of an environment transition before the next check
CONSEQUENCE = regret if the system remains stale after such a transition
```

The key correction is:

```text
high consequence != high probability of change
current drift    != future transition hazard
```

## Executable kernel

`src/bardocompute/hazard_cadence.py`

The scheduling hypothesis is:

```text
cost_rate(interval)
    ~= probe_cost / interval
     + change_hazard * regret_given_change * interval / 2
```

with continuous minimum:

```text
interval* = sqrt(
    2 * probe_cost
    / (change_hazard * regret_given_change)
)
```

The formula is an engineering approximation to falsify, not a universal scheduling law.

## Benchmark

`benchmarks/hazard_aware_cadence.py`

Hosted GitHub Actions CI #410, Python 3.12:

```text
130 passed
deployment_steps=137422
phases=
  calm:        33797 @ hazard=0.001
  volatile:    34459 @ hazard=0.020
  calm_return: 33824 @ hazard=0.001
  moderate:    35342 @ hazard=0.005
```

The phase lengths are deterministic-seeded but randomized. The online policies do **not** receive phase labels, phase boundaries, or future hazards.

A paid probe reveals only information available at that time:

```text
current environment epoch
number of transitions since the previous probe
```

The same environment/change sequence is used for every policy.

Staying calibrated to an obsolete epoch costs:

```text
stale_regret_per_step = 10
```

Fixed controls use intervals:

```text
8, 16, 32, 64, 128, 256
```

Probe costs:

```text
2, 8, 32
```

Online hazard estimators:

1. cumulative transition rate;
2. exposure-aware EWMA transition rate;
3. rolling recent transition rate.

An `oracle_current_hazard` row receives the generator's current hazard and is an upper control only; it is not a deployable policy.

## Hosted result

### Probe cost = 2

Best fixed policy:

```text
fixed_8 loss = 0.5565
```

Online policies:

```text
cumulative hazard loss = 0.5445  (0.978x best fixed)
EWMA hazard       loss = 0.5225  (0.939x best fixed)
rolling hazard    loss = 0.5309  (0.954x best fixed)
oracle hazard     loss = 0.5073  (0.912x best fixed)
```

EWMA mean cadence by hidden generator phase:

```text
calm / volatile / calm-return / moderate
21.6 / 8.0 / 21.2 / 9.3
```

The EWMA policy contracts its observation interval after entering the volatile phase and expands it again after returning to calm.

### Probe cost = 8

Best fixed policy:

```text
fixed_16 loss = 1.0565
```

Online policies:

```text
cumulative hazard loss = 1.0251  (0.970x best fixed)
EWMA hazard       loss = 0.9535  (0.903x best fixed)
rolling hazard    loss = 0.9821  (0.930x best fixed)
oracle hazard     loss = 0.8906  (0.843x best fixed)
```

EWMA phase cadences:

```text
43.4 / 9.0 / 41.5 / 18.0
```

This is a material schedule change rather than minimum-interval clipping.

### Probe cost = 32

Best fixed policy:

```text
fixed_32 loss = 1.9751
```

Online policies:

```text
cumulative hazard loss = 1.9359  (0.980x best fixed)
EWMA hazard       loss = 1.8155  (0.919x best fixed)
rolling hazard    loss = 1.8193  (0.921x best fixed)
oracle hazard     loss = 1.7181  (0.870x best fixed)
```

EWMA phase cadences:

```text
86.6 / 17.9 / 82.7 / 36.1
```

Rolling reacts faster around phase changes in this run, while EWMA produces slightly lower total economic loss:

```text
probe cost 32:
  EWMA volatile contraction lag  = 2126 steps
  rolling contraction lag        = 279 steps

  EWMA calm-return expansion lag = 890 steps
  rolling expansion lag          = 137 steps
```

Rolling pays for that responsiveness with more probes.

## Main result

The deployable EWMA hazard estimator beats the best single fixed cadence at every tested probe cost in this seeded hidden-phase workload:

```text
probe cost 2  : EWMA / best fixed = 0.939x  (~6.1% lower loss)
probe cost 8  : EWMA / best fixed = 0.903x  (~9.7% lower loss)
probe cost 32 : EWMA / best fixed = 0.919x  (~8.1% lower loss)
```

This is qualitatively different from Adaptive Probe Cadence v0.1:

```text
v0.1: cadence ~= minimum interval across the sweep
v0.2: cadence materially contracts and expands with inferred transition hazard
```

The narrow supported conclusion is:

> **In this constructed nonstationary environment, scheduling observation from an online estimate of transition hazard plus stale consequence can reduce total probe-plus-staleness loss relative to the best global fixed cadence.**

The result supports the causal separation of **hazard** from current **trust/drift**. It does not establish that the square-root formula or EWMA estimator is universally optimal.

## What the negative and positive results say together

```text
current uncertainty tells us whether knowledge may be wrong now
transition hazard tells us how quickly knowledge is likely to become wrong again
```

Those are different questions.

The emerging Living Process timing stack is:

```text
transition history
      ↓
HAZARD ESTIMATE
      ↓
WHEN TO OBSERVE
      ↓
probe / zoom evidence
      ↓
TRUST / RECALIBRATION
      ↓
WHAT TO OBSERVE MORE DEEPLY
      ↓
KEEP / HOLD / ADAPT
```

The observer therefore has at least two distinct clocks:

```text
knowledge age / trust clock
world-transition / hazard clock
```

## Estimator-memory result

The three online estimators expose another tradeoff:

- cumulative history is slow to forget old regimes and reacts poorly after change;
- rolling history reacts quickly but pays more probes / variance;
- EWMA gives the lowest total loss in this run across all three probe-cost settings;
- oracle hazard remains better, showing remaining headroom.

Therefore **how quickly the observer forgets old hazard evidence** is itself a new falsification surface, not a settled parameter.

## Next falsification: robustness, not more feature layers

Before integrating hazard cadence into the full Living Process stack, reproduce the result across a predeclared multi-seed environment family:

1. 32–64 deterministic seeds;
2. randomly ordered hidden hazard regimes;
3. random regime lengths;
4. hazard levels sampled from a fixed set such as `0.0005, 0.001, 0.0025, 0.005, 0.01, 0.02`;
5. independent sweeps of probe cost and stale consequence;
6. compare fixed, cumulative, EWMA, rolling, and oracle controls;
7. report win rate, median loss ratio, p90 loss ratio, transition contraction/expansion lag, and oracle-gap closure;
8. retain any seeds where adaptive scheduling loses.

Only if the advantage reproduces should the cadence kernel be coupled back into Observation Payback and the full `TRUST -> OBSERVE -> ACT` pipeline.

## Scientific boundary

This is a constructed decision-theoretic benchmark. It does not establish a universal law of cognition, relationships, finance, biology, economics, or physics. The useful engineering claim is narrower: **the cadence of checking a model can rationally depend on an inferred rate of environmental transition separately from the cost of being stale.**
