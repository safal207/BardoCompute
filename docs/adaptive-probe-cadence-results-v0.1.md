# Adaptive Probe Cadence v0.1 — Hosted Results

## Question

Can the observer choose **when to check whether its calibration has become stale** instead of using a fixed probe interval?

The previous Calibration-Aware Payback experiment still used a hand-set cadence (`probe_every=64`). This experiment removes that constant and tests whether cadence itself can be selected economically.

The v0.1 hypothesis was:

```text
cheap probe / high stale-regret -> inspect sooner
expensive probe / low stale-regret -> inspect later
```

## Executable kernel

`src/bardocompute/probe_cadence.py`

The first heuristic uses a classical inspection-cost shape:

```text
cost_rate(interval)
    ~= probe_cost / interval
     + stale_regret_rate * interval / 2
```

with continuous minimum:

```text
interval* = sqrt(2 * probe_cost / stale_regret_rate)
```

The v0.1 stale-regret rate is estimated as:

```text
consequence_scale = 0.5 * (miss_loss + false_action_loss)

stale_regret_rate = consequence_scale
                  * (1 - trust)
                  * drift_score
```

and the selected interval is clipped to `[8, 256]`.

This is an engineering heuristic to falsify, not a claim of universal optimality.

## Benchmark

`benchmarks/adaptive_probe_cadence.py`

Hosted GitHub Actions CI #396, Python 3.11:

```text
120 passed
deployment_steps=120000
segments=stable:30000,moderate:30000,strong:30000,return:30000
policy_input=future regime boundaries and labels are hidden
```

The deployment stream has four generator phases:

1. stable calibration;
2. moderate shift;
3. strong shift;
4. return to the original environment.

The policy does **not** receive the phase labels or boundaries.

Fixed controls use intervals:

```text
8, 16, 32, 64, 128, 256
```

Probe costs are swept over:

```text
2, 8, 32
```

All policies share the same calibration trust, observation-payback, outcome, and online-update logic. The only intended difference is probe scheduling.

## Hosted result

```text
probe_cost,best_fixed_interval,best_fixed_loss,adaptive_loss,adaptive/best_fixed,adaptive_probes,adaptive_mean_interval
2,         8,                  42.047,         42.047,       1.000,              13157,          8.00
8,         8,                  42.705,         42.677,       0.999,              13155,          8.00
32,        16,                 45.263,         45.329,       1.001,              13145,          8.02
```

At probe cost `2`, adaptive cadence is exactly the same effective policy as fixed `8`:

```text
adaptive_mean_interval=8.00
adaptive_loss=42.047
fixed8_loss=42.047
```

At probe cost `8`, the observed loss difference is only about `0.1%`:

```text
adaptive / best fixed = 0.999x
```

This is too small and too structurally saturated to treat as evidence of useful adaptive scheduling.

At probe cost `32`, the best fixed cadence moves to `16`, while the adaptive rule remains near the minimum interval and loses slightly:

```text
best fixed16 = 45.263
adaptive     = 45.329
adaptive / best fixed = 1.001x
adaptive_mean_interval = 8.02
```

## Main result: the v0.1 cadence rule is rejected

The intended adaptive scheduler did **not** meaningfully adapt its cadence.

Across all tested probe costs:

```text
adaptive mean interval ~= 8
```

The square-root rule is therefore dominated by clipping at the minimum interval for this workload.

The correct conclusion is **not** that adaptive cadence is useless. The narrower conclusion is:

> **The current estimate of stale-regret is not an adequate rate model for scheduling future checks.**

Specifically, the v0.1 heuristic multiplies current calibration mismatch by a large consequence scale and treats that result as a per-step hazard. That makes the calculated inspection interval unrealistically short.

## Causal correction

This falsification exposes four quantities that should not be collapsed:

```text
TRUST       = how credible is the current calibration now?
DRIFT       = how much evidence of mismatch exists now?
HAZARD      = how likely is the environment to change before the next check?
CONSEQUENCE = how expensive would being stale be if change occurs?
```

Cadence should depend on **future change hazard** separately from present mismatch.

A better next hypothesis is:

```text
cost_rate(interval)
    ~= probe_cost / interval
     + 0.5 * change_hazard * regret_given_change * interval
```

so that:

```text
interval* = sqrt(
    2 * probe_cost
    / (change_hazard * regret_given_change)
)
```

Here `change_hazard` must be inferred from past/present transition statistics or another online change model. It must not be supplied by the generator or derived from hidden future boundaries.

## Living Process implication

The observation scheduler now needs to distinguish:

```text
How wrong might my current model be?        -> trust / drift
How likely is the world to change soon?     -> hazard
How costly would stale action be?           -> consequence
How expensive is another check?             -> probe cost
```

This prevents a conceptual error:

```text
high consequence != high probability of change
```

and:

```text
low trust now != world will change again immediately
```

The current research chain therefore remains:

```text
TRUST
  ↓
OBSERVE
  ↓
ACT
```

but the timing component of `OBSERVE` must use a separate transition-hazard estimate before it can claim adaptive cadence.

## Negative results retained

- Adaptive cadence v0.1 does not materially beat the best fixed cadence.
- The selected interval saturates at the minimum (`~8`) across the probe-cost sweep.
- A higher probe price of `32` should lengthen cadence; the best fixed control correctly moves to `16`, while the adaptive heuristic largely fails to do so.
- Therefore the current `(1-trust) * drift * consequence` quantity is rejected as a sufficient cadence hazard estimate.

## Next falsification: Hazard-Aware Cadence v0.2

1. Estimate `change_hazard` only from past/present transitions.
2. Keep `trust`, `drift`, `hazard`, and `consequence` separate in the causal graph.
3. Compare several equal-information hazard estimators, starting simple:
   - empirical change frequency / Beta-Bernoulli hazard;
   - EWMA transition hazard;
   - rolling-window change rate;
   - optional change-point detector only if simpler controls fail.
4. Randomize regime lengths and recurrence rather than using only equal 30k generator phases.
5. Sweep probe cost and consequence cost independently.
6. Measure not only total loss but also:
   - time-to-distrust;
   - time-to-retrust;
   - probes per regime;
   - interval distribution by inferred hazard;
   - regret after abrupt and gradual changes.
7. Require the adaptive scheduler to move its cadence materially before claiming success.

## Scientific boundary

This benchmark is a constructed decision-theoretic control. It does not establish a universal law about cognition, finance, biology, relationships, or physics. Its useful result is a falsification: **current calibration mismatch and future change hazard are distinct causal quantities and should not be treated as interchangeable when scheduling observation.**
