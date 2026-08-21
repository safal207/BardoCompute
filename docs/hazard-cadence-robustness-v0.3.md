# Hazard Cadence Robustness v0.3 — Multi-Seed Hosted Results

## Question

Does the Hazard-Aware Cadence v0.2 advantage survive a predeclared family of environments, costs, and regime orders, or was the earlier single-stream result a favorable seed?

This experiment deliberately strengthens the fixed control. For every seed and cost profile, the best fixed cadence is selected **after the fact** from:

```text
8, 16, 32, 64, 128, 256
```

The adaptive policy therefore competes against the fixed cadence that would have been best if the whole run had been known in hindsight.

## Predeclared environment family

`benchmarks/hazard_cadence_robustness.py`

Hosted GitHub Actions CI #422, Python 3.11:

```text
130 passed
seeds=32
hazard_levels=0.0005,0.0010,0.0025,0.0050,0.0100,0.0200
regime_order=randomized_per_seed
regime_length=uniform_integer_4000_to_8000
probe_costs=2,8,32
stale_regrets=2,10,50
seed_profiles=32 * 3 * 3 = 288
```

Each seed contains all six hidden hazard regimes, but in a different order and with independently randomized durations.

Online estimators receive only paid past/present transition counts. They do **not** receive regime labels, boundaries, future hazard, or future duration.

Compared strategies:

1. hindsight-selected best fixed cadence;
2. cumulative transition-rate estimate;
3. EWMA transition-hazard estimate;
4. rolling recent-hazard estimate;
5. oracle current hazard as a non-deployable upper control.

Any adaptive non-win is retained and printed by the benchmark rather than averaged away.

## Overall result — 288 seed/profile comparisons

```text
strategy    win_rate  ties  median_ratio  p90_ratio  worst_ratio  median_oracle_gap_closed
cumulative   0.500     32      1.000        1.042       1.152              0.002
EWMA         0.788      0      0.950        1.026       1.239              0.537
rolling      0.729     64      0.953        1.000       1.031              0.425
```

Ratios are adaptive loss divided by the hindsight-selected best fixed loss. Lower than `1.0` is better.

### EWMA

EWMA wins `78.8%` of all seed/profile comparisons.

Its median ratio is:

```text
0.950x
```

or about **5.0% lower median total loss** than the strongest fixed control.

It closes a median:

```text
53.7%
```

of the gap between the hindsight-selected fixed control and the current-hazard oracle.

However, EWMA is not universally safer:

```text
p90 = 1.026x
worst = 1.239x
```

The losing tail is real and must be part of the model.

### Rolling

Rolling has slightly lower win rate and slightly weaker median efficiency:

```text
win_rate = 72.9%
median   = 0.953x
```

but a much tighter losing tail:

```text
p90   = 1.000x
worst = 1.031x
```

Its `64` ties are informative: in several high-consequence / cheap-probe profiles, rolling collapses to the same minimum cadence as the best fixed control. It gains nothing there, but also avoids a large estimation penalty.

### Cumulative

Cumulative history is essentially neutral overall:

```text
win_rate = 50.0%
median   = 1.000x
```

and closes almost none of the oracle gap. Slow forgetting makes it a weak control for repeatedly changing hazard regimes.

## Representative phase regions

### Low stale consequence: strong adaptive headroom

At `probe_cost=8, stale_regret=2`:

```text
EWMA:
  win_rate = 1.000
  median   = 0.912x
  p90      = 0.963x
  worst    = 0.983x

rolling:
  win_rate = 1.000
  median   = 0.916x
  p90      = 0.948x
  worst    = 0.976x
```

Both adaptive estimators beat the hindsight-best fixed cadence on every seed.

### Balanced region: EWMA remains strong

At `probe_cost=8, stale_regret=10`:

```text
EWMA:
  win_rate = 1.000
  median   = 0.923x
  p90      = 0.961x
  worst    = 0.997x

rolling:
  win_rate = 0.938
  median   = 0.939x
  p90      = 0.984x
  worst    = 1.006x
```

### Cheap probes + very expensive staleness: adaptive headroom collapses

At `probe_cost=2, stale_regret=50`:

```text
EWMA:
  win_rate = 0.125
  median   = 1.024x
  p90      = 1.102x
  worst    = 1.239x

rolling:
  win_rate = 0.000
  ties     = 32
  median   = 1.000x
  worst    = 1.000x
```

This is not evidence that the hazard idea disappears. It exposes a **saturation region**: when observation is cheap and stale action is extremely expensive, the best policy is already near the minimum allowed cadence. There is little or no cadence headroom left for an estimator to exploit.

An estimator can then only:

```text
match the floor
or
make an estimation error and move away from it
```

## Emerging dimensionless orientation ratio

The v0.2 scheduling approximation is:

```text
d* = sqrt(
    2 * probe_cost
    / (change_hazard * regret_given_change)
)
```

Define:

```text
rho = change_hazard * regret_given_change / probe_cost
```

Then:

```text
d* = sqrt(2 / rho)
```

This exposes a compact candidate phase coordinate.

For a minimum allowed cadence `d_min`:

```text
d* <= d_min
```

when:

```text
rho >= 2 / d_min^2
```

With the current `d_min=8`:

```text
rho_floor = 2 / 64 = 0.03125
```

Above that approximate boundary, the unconstrained economic optimum is already at or below the minimum cadence. Adaptive cadence therefore has little theoretical room to improve over a minimum-cadence fixed control.

This boundary is derived from the current approximation and must itself be tested; it is not a universal constant.

## Risk/efficiency tradeoff between hazard memories

The robustness sweep shows that hazard-memory choice matters:

```text
EWMA    -> better median efficiency / larger losing tail
rolling -> slightly weaker median / much safer tail
```

This suggests that **how the observer forgets old transition evidence is itself an orientation decision**.

The current data do not justify automatically adapting that memory rule yet. First we should determine whether results collapse onto the `rho` coordinate across hazards, costs, and stale consequences.

## Main supported conclusion

The v0.2 single-stream result survives broadly but not universally:

> **Online hazard-aware observation cadence can outperform even a hindsight-selected global fixed cadence across many nonstationary environments, but its value is phase-dependent. When the economic optimum saturates at the minimum cadence, adaptive scheduling has little or no headroom and estimation error can dominate.**

This is stronger and more useful than `adaptive cadence always wins`.

## Living Process implication

The current observation path becomes:

```text
transition history
      ↓
change HAZARD
      ↓
HEADROOM CHECK
  is cadence optimization still possible?
      ↓
WHEN TO OBSERVE
      ↓
TRUST / DRIFT / RECALIBRATION
      ↓
WHAT TO OBSERVE / ZOOM
      ↓
KEEP / HOLD / ADAPT
```

The headroom check is not yet a new runtime layer; it is a causal hypothesis derived from the phase boundary.

The broader Living Process rule becomes more precise:

> **Adapt only where adaptation has remaining economic degrees of freedom. If the optimum is already pinned to a hard boundary, extra adaptivity can add estimation cost without adding useful choice.**

## Next falsification: phase-coordinate collapse

Do not add another semantic subsystem yet.

Next test:

1. sweep hazard, stale regret, and probe cost more densely;
2. compute `rho = hazard * stale_regret / probe_cost` for every environment/profile;
3. plot best fixed, EWMA, rolling, and oracle loss ratio against `rho`;
4. test whether profiles with different raw parameters collapse onto a common phase curve;
5. test the predicted floor boundary near `rho = 2 / d_min^2`;
6. separately test ceiling saturation at `d_max`;
7. retain estimator-specific deviations and losing tails;
8. only then integrate cadence with the full `TRUST -> OBSERVE -> ACT` stack.

If the data do not collapse meaningfully by `rho`, the proposed compact coordinate should be rejected or expanded rather than promoted.

## Scientific boundary

These are constructed decision-theoretic benchmarks. They do not establish a universal law of cognition, relationships, finance, biology, economics, or physics. The current evidence supports a narrower engineering claim about the economic scheduling of observation in nonstationary systems.