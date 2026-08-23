# Staged Recovery v0.22 — preregistration

Status: **frozen before benchmark implementation/results**.

## Question

Can the existing v0.19 actuator family satisfy the original external outcome/selectivity bar if recovery is **staged**, so that the process removes the protective RATE restriction before withdrawing auxiliary RELIEF?

No new actuator is added. No actuator magnitude or v0.19 threshold is retuned.

## Why this exists

v0.19 and v0.20/v0.21 expose opposite failure modes.

v0.19:

```text
PAIN + RESERVE + TRAJECTORY recovery
-> strong deadline quality
-> chronic RELIEF/STORAGE occupancy (~.875)
```

v0.20/v0.21 without RESERVE as recovery veto:

```text
PAIN (+ optional TRAJECTORY) recovery
-> RELIEF occupancy falls to about .50-.53
-> completed work remains strong
-> deadline-miss quality regresses
-> retained STORAGE remains around .76
```

The v0.21 ablation also showed that TRAJECTORY's recovery value was not stable across hosted Python 3.11 and 3.12. No predicate A/B/C was promotable.

The current binary state machine couples two distinct de-escalations:

```text
PROTECTIVE:
  release = capped
  RELIEF  = on

NORMAL:
  release = base/full
  RELIEF  = off
```

A single exit therefore simultaneously removes a restriction and removes support.

v0.22 tests a different causal hypothesis:

> Recovery may need to undo protective actions in an order that helps clear the state created by protection.

## Frozen change

Keep v0.19 entry semantics unchanged.

```text
severe PAIN
OR PAIN + worsening TRAJECTORY
OR low RESERVE + worsening TRAJECTORY
  -> enter PROTECTIVE
```

Keep the same existing actuator values.

### State 1 — NORMAL

```text
release = existing base release
RELIEF  = off
STORAGE = baseline unless retained backlog requires elastic storage
```

### State 2 — PROTECTIVE

Exactly the existing v0.19 protective command:

```text
release = min(base release, existing BOOSTED_SAFE_CAP)
RELIEF  = existing BOOST_AMOUNT
STORAGE = existing elastic capacity
```

### State 3 — RECOVERY_PROBE

Use only already-existing actuator magnitudes, but decouple their withdrawal:

```text
release = existing base/full release   # remove protective RATE cap first
RELIEF  = existing BOOST_AMOUNT        # retain support during recovery probe
STORAGE = existing elastic capacity while retained backlog requires it
```

No intermediate release limit and no intermediate relief amount may be invented.

## Recovery transition

Use the existing `HEALTHY_PAIN` threshold and existing `RECOVERY_DWELL` only.

```text
PROTECTIVE
  -- low PAIN for RECOVERY_DWELL --> RECOVERY_PROBE

RECOVERY_PROBE
  -- low PAIN for RECOVERY_DWELL --> NORMAL
```

If the frozen v0.19 entry predicate becomes true while in RECOVERY_PROBE, return to PROTECTIVE.

`RESERVE` remains an entry signal. It is not a mandatory recovery veto.
`TRAJECTORY` remains available to the frozen entry predicate but is not required for recovery promotion.

This deliberately tests staged de-escalation rather than another predicate combination.

## Forbidden

- no new worker lane;
- no new buffer size;
- no new release-limit magnitude;
- no new RELIEF magnitude;
- no admission shedding;
- no future phase/regime information;
- no change to `HEALTHY_PAIN`;
- no change to `RECOVERY_DWELL`;
- no retuning on this family;
- no use of v0.19-v0.21 spent families for promotion.

## Fresh held-out family

```text
10100281
10200283
10300293
10400307
10500311
10600313
```

These seeds are frozen before implementation and become spent after hosted evaluation.

## Comparators

On the exact same v0.22 family:

1. conventional FlowPreserving baseline;
2. frozen v0.19 full recovery predicate;
3. frozen v0.20 recovery-decoupled controller;
4. v0.22 staged recovery controller.

## Independent outcome judge

Use the R3 external outcome vector:

- completed work;
- lost/overflow work;
- seconds per completion;
- deadline-miss epochs;
- severe deadline-miss epochs;
- RELIEF occupancy;
- STORAGE occupancy;
- terminal backlog;
- digest correctness;
- protective/probe transitions and occupancy as diagnostics.

Internal self-state does not define experimental success.

## Preregistered promotion bar

A v0.22 PASS requires the original v0.19 substantive bar:

```text
median completed / baseline                 >= 1.25
median lost / baseline                      <= 0.75
median seconds-per-completion / baseline    <= 1.15
median deadline-miss epochs / baseline      <= 0.60
median severe-miss epochs / baseline        <= 0.25
median RELIEF occupancy                     <= 0.65
median STORAGE occupancy                    <= 0.65
median terminal backlog                     == 0
all digest mismatches                       == 0
```

And it must preserve v0.20's main selectivity gain without materially losing v0.19 quality:

```text
median RELIEF occupancy / v0.19             <= 0.75
median completed / v0.19                    >= 0.98
median deadline-miss epochs / v0.19         <= 1.25
median seconds-per-completion / v0.19       <= 1.15
```

The benchmark must report v0.19 and v0.20 on the same fresh family. No comparator may weaken the absolute gates above.

## Falsification classification

If RELIEF drops but STORAGE remains above .65, staged support withdrawal is not sufficient to clear retained backlog selectively.

If STORAGE drops but deadline quality fails, uncapping earlier is not sufficient to make recovery safe.

If deadline quality passes but RELIEF remains above .65, the recovery probe is merely another chronic-support state.

If all outcome and occupancy gates pass, the result supports only the narrow claim below.

## Narrow claim allowed by a PASS

> On this executed fault-injected work-queue, staged de-escalation — restoring normal release before withdrawing auxiliary relief — preserved preregistered deadline/service quality while making protection selective enough to satisfy the frozen bar.

It would not establish biological equivalence, consciousness, production optimality, or a general-purpose processor.

## Working engineering principle under test

```text
Do not withdraw support before removing the restriction that created retained work.
```
