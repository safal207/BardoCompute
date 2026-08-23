# Risk-Constrained Orientation v0.7

## Question

Can hazard-aware observation keep its economic value when safety is made lexicographic instead of folded into the same scalar loss?

The recovery-state transfer in v0.6 improved median economic loss, but sometimes increased total time spent with stale authority state. v0.7 therefore adds a predeclared hard constraint:

```text
max undetected authority stale age <= safety_budget
```

The hazard/cadence formula itself is unchanged. Its chosen interval is only clipped by the safety budget.

Safety budgets were frozen before evaluation:

```text
16 / 32 / 64 ticks
```

The comparator for each budget is the strongest fixed cadence satisfying the same budget.

## Hosted result

Dedicated `Recovery State Transfer Benchmark` completed successfully on Python 3.11 and 3.12. Full CI and the ATMAN/Cosmic workflow also completed successfully for the same head.

### Budget 16

```text
EWMA:
  win_rate=.708
  median_loss_ratio=.981
  p90=1.008
  worst=1.033
  median_unsafe_ratio=1.000
  constraint_violations=0
  max_undetected_stale_age=16
  post_probe_false_recoveries=0
  median_unconstrained_gain_preserved=.231

rolling:
  win_rate=.552
  median_loss_ratio=.991
  p90=1.009
  worst=1.077
  median_unsafe_ratio=1.000
  constraint_violations=0
  max_undetected_stale_age=16
  post_probe_false_recoveries=0
  median_unconstrained_gain_preserved=.268
```

### Budget 32

```text
EWMA:
  win_rate=.833
  median_loss_ratio=.916
  p90=1.010
  worst=1.032
  median_unsafe_ratio=1.021
  constraint_violations=0
  max_undetected_stale_age=32
  post_probe_false_recoveries=0
  median_unconstrained_gain_preserved=1.089

rolling:
  win_rate=.729
  median_loss_ratio=.944
  p90=1.000
  worst=1.032
  median_unsafe_ratio=1.041
  constraint_violations=0
  max_undetected_stale_age=32
  post_probe_false_recoveries=0
  median_unconstrained_gain_preserved=1.000
```

### Budget 64

```text
EWMA:
  win_rate=.854
  median_loss_ratio=.912
  p90=1.009
  worst=1.058
  median_unsafe_ratio=1.053
  constraint_violations=0
  max_undetected_stale_age=64
  post_probe_false_recoveries=0
  median_unconstrained_gain_preserved=1.051

rolling:
  win_rate=.812
  median_loss_ratio=.927
  p90=1.000
  worst=1.025
  median_unsafe_ratio=1.059
  constraint_violations=0
  max_undetected_stale_age=64
  post_probe_false_recoveries=0
  median_unconstrained_gain_preserved=1.000
```

## What survived

A hard staleness-age constraint works as intended: zero violations and zero false recoveries after authoritative checks on all tested budgets.

At budget 16, aggregate unsafe exposure also matches the strongest safe fixed comparator at the median, but most of the unconstrained economic gain disappears.

At budgets 32 and 64, most or all economic benefit returns, yet aggregate unsafe exposure can again exceed the safe fixed comparator even though the hard maximum-age constraint is never violated.

## What v0.7 falsified

A bound on the severity/duration of one hidden stale episode is **not equivalent** to a bound on cumulative unsafe exposure.

The experiment therefore rejects:

```text
one scalar safety constraint is enough
```

and supports the narrower distinction:

```text
instantaneous / state-wise safety
!=
cumulative safety exposure
!=
economic utility
```

## Causal consequence

Observation cadence should not be asked to provide an absolute safety guarantee when the safety-relevant authority change is hidden until the next observation.

For any pull-only observer with interval greater than one tick, an authority change immediately after a probe creates an unavoidable stale window before the next probe.

This motivates the next falsification: move enforcement to the action boundary and test whether stale authority can be rejected there while observation cadence remains an economic/freshness mechanism.

## Status

v0.7 is retained as positive evidence for lexicographic constraints and as negative evidence that a maximum stale-age constraint alone controls all safety dimensions.
