# Safe Observation Economics v0.9

## Status

Pre-registered before hosted evaluation.

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

For one policy run:

```text
operational_cost
  = probe_count * probe_cost
  + unavailable_action_ticks * unavailable_cost
```

where:

```text
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

Reuse the v0.6 authority-epoch recovery environments:

```text
16 seeds
hidden hazard regimes: .0005 / .0020 / .0080 / .0250
random regime order
random regime durations
no future restart boundaries exposed
```

Cost grid:

```text
probe_cost       = 2 / 8 / 32
unavailable_cost = 1 / 5 / 25
```

Comparators:

```text
best fixed cadence chosen after the fact per seed/profile from:
1 / 8 / 16 / 32 / 64 / 128 / 256

EWMA hazard cadence
rolling hazard cadence
```

All comparators use the same action fence and the same noisy receipt/provenance path.

## Primary acceptance criteria

An adaptive estimator is promoted in v0.9 only if all conditions hold on the frozen family:

1. `unsafe_accepted_actions == 0` for every run;
2. overall win rate versus strongest fixed >= 0.65;
3. overall median operational-cost ratio < 0.97;
4. p90 operational-cost ratio <= 1.05;
5. no hidden future hazard/regime/boundary information is used;
6. no estimator parameter is retuned against the reported family.

If only one estimator passes, only that estimator is promoted.

## Secondary metrics

Report:

```text
median acceptance rate
median probe ratio vs best fixed
worst operational-cost ratio
interval response to hidden hazard
```

These explain the mechanism but do not replace the primary acceptance criteria.

## Interpretation guardrail

A win would support only this narrow claim:

> once stale effects are independently fenced, adaptive observation can sometimes improve the cost of staying fresh and available.

It would **not** show that fencing is free, that the action-boundary check is universally cheap, or that one hazard estimator is optimal in every workload.

Runtime cost of the fence remains a separate native-system question.
