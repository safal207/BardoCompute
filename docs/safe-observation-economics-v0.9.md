# Safe Observation Economics v0.9

## Status

Pre-registered experiment completed successfully on two hosted Python runners (3.11 and 3.12). Both EWMA and rolling estimators passed all predeclared primary acceptance criteria on the frozen family.

## Question

Once stale effects are prevented at the authoritative action boundary, can hazard-aware observation still reduce operational cost without receiving any authority to trade safety for utility?

## Architecture under test

```text
hidden authority changes
        ↓
TRUST / HAZARD estimate
        ↓
observation cadence
        ↓
local recovery state
        ↓
protected action + authority epoch
        ↓
RESOURCE FENCE
  stale token -> reject
  current token -> apply
```

Safety invariant:

```text
unsafe accepted actions = 0
```

Observation is optimized only for freshness / availability economics.

## Cost model

```text
operational_cost
  = probe_count * probe_cost
  + unavailable_action_ticks * unavailable_cost

unavailable_action_ticks
  = fence_rejections + local_HOLD_ticks
```

No unsafe-action penalty exists in the optimizer because unsafe actions must be structurally rejected by the fence.

The unchanged cadence rule receives `unavailable_cost` as the consequence of remaining stale until the next observation:

```text
cost_rate(d)
  ~= probe_cost / d
   + hazard * unavailable_cost * d / 2

d* = sqrt(2 * probe_cost / (hazard * unavailable_cost))
```

## Frozen family

```text
16 seeds
hidden hazard regimes: .0005 / .0020 / .0080 / .0250
random regime order
random regime durations
no future restart boundaries exposed

probe_cost       = 2 / 8 / 32
unavailable_cost = 1 / 5 / 25

fixed candidates = 1 / 8 / 16 / 32 / 64 / 128 / 256
```

The strongest fixed cadence is chosen after the fact per seed/profile. All fixed and adaptive comparators use the same action fence and the same noisy receipt/provenance path.

## Predeclared primary acceptance criteria

An adaptive estimator passes only if all conditions hold:

1. `unsafe_accepted_actions == 0` for every run;
2. overall win rate versus strongest fixed >= 0.65;
3. overall median operational-cost ratio < 0.97;
4. p90 operational-cost ratio <= 1.05;
5. no hidden future hazard/regime/boundary information is used;
6. no estimator parameter is retuned against the reported family.

## Hosted result

Both hosted runners reproduced the same deterministic metrics.

### Overall

```text
EWMA:
  win_rate=.826
  median_cost_ratio=.917
  p90_cost_ratio=1.046
  worst_cost_ratio=1.131
  median_acceptance_rate=.923583
  median_probe_ratio_vs_best_fixed=.808
  unsafe_accepted_total=0
  passes_preregistered_acceptance=true

rolling:
  win_rate=.792
  median_cost_ratio=.920
  p90_cost_ratio=1.000
  worst_cost_ratio=1.090
  median_acceptance_rate=.922377
  median_probe_ratio_vs_best_fixed=1.000
  unsafe_accepted_total=0
  passes_preregistered_acceptance=true
```

The median operational-cost improvement is approximately 8.3% for EWMA and 8.0% for rolling versus the strongest fixed cadence selected separately for every seed/profile.

### Hidden-hazard response

The adaptive observers still change cadence with the hidden restart regime while receiving no future boundary labels:

```text
EWMA median interval:
  hazard .0005 -> 69.7
  hazard .0020 -> 40.5
  hazard .0080 -> 20.8
  hazard .0250 -> 11.7

rolling median interval:
  hazard .0005 -> 34.2
  hazard .0020 -> 30.1
  hazard .0080 -> 22.0
  hazard .0250 -> 15.1
```

## Profile-level results

```text
probe=2, unavailable=1
  EWMA    win=1.000 median=.864 p90=.903 worst=.921
  rolling win=1.000 median=.890 p90=.911 worst=.938

probe=2, unavailable=5
  EWMA    win=1.000 median=.904 p90=.952 worst=.954
  rolling win=.938  median=.917 p90=.966 worst=1.030

probe=2, unavailable=25
  EWMA    win=.312 median=1.021 p90=1.077 worst=1.118
  rolling win=.000 median=1.000 p90=1.000 worst=1.000

probe=8, unavailable=1
  EWMA    win=1.000 median=.937 p90=.970 worst=.975
  rolling win=1.000 median=.938 p90=.979 worst=.982

probe=8, unavailable=5
  EWMA    win=1.000 median=.880 p90=.912 worst=.923
  rolling win=1.000 median=.882 p90=.923 worst=.937

probe=8, unavailable=25
  EWMA    win=.938 median=.952 p90=.997 worst=1.014
  rolling win=.938 median=.938 p90=.990 worst=1.031

probe=32, unavailable=1
  EWMA    win=.188 median=1.044 p90=1.098 worst=1.131
  rolling win=.250 median=1.042 p90=1.083 worst=1.090

probe=32, unavailable=5
  EWMA    win=1.000 median=.905 p90=.960 worst=.970
  rolling win=1.000 median=.909 p90=.967 worst=.987

probe=32, unavailable=25
  EWMA    win=1.000 median=.881 p90=.924 worst=.943
  rolling win=1.000 median=.910 p90=.950 worst=.969
```

## Negative regions retained

The experiment does **not** support `adaptive cadence always wins`.

Two cost surfaces are especially informative:

```text
cheap probes + very expensive unavailable work
  -> strongest fixed cadence is hard to beat

very expensive probes + cheap unavailable work
  -> frozen adaptive estimators can over-observe
```

These regions are retained and will not be erased by retuning against the reported family.

## What v0.9 supports

The clean supported claim is:

> **Once stale effects are independently fenced to zero, hazard-aware observation can improve the cost of staying fresh and available without receiving authority to trade safety for utility.**

This is stronger than the earlier scalar-utility result because safety is no longer an economic penalty in the optimizer.

The architecture now separates three responsibilities:

```text
epoch/order provenance guard -> is recovery evidence valid?
observation cadence           -> when is freshness worth paying for?
resource authority fence      -> may this action take effect?
```

Adaptation payback remains the rule for changing observation/execution behavior, but it cannot purchase action admissibility.

## Limitations

v0.9 does not show that:

- resource fencing is free;
- a local integer comparison represents network or distributed-consensus cost;
- EWMA or rolling is optimal in every workload;
- a protected resource can create authoritative ordering if none exists;
- the same cost surface transfers unchanged to every domain.

The protected resource must already know or synchronously validate authoritative ordering.

## Next falsification

Measure the native hot-path cost of action-boundary fencing with equal-information controls.

The first native experiment must isolate only local enforcement cost:

```text
unguarded action path
resource-side epoch compare
rare stale-token failures
mixed stale-token failures
```

It must not claim to model remote authority validation, network latency, consensus, storage replication, or lease acquisition.

Only after the local mechanism is measured should a system-level deployment model be proposed.
