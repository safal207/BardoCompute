# Recovery Decoupling v0.20 — preregistration

Status: **frozen before benchmark implementation/results**.

## Question

Can the v0.19 multi-signal self-state preserve R2-quality real-work outcomes while becoming materially more selective if **recovery is decoupled from temporary reserve depletion caused by the protective action itself**?

No new actuator is added. No v0.19 threshold is retuned on this experiment family.

## Why this exists

Hosted v0.19 preserved strong external outcomes but failed selectivity:

```text
Python 3.12: RELIEF/STORAGE occupancy = .875
Python 3.11: RELIEF/STORAGE occupancy = .877
preregistered maximum               = .650
```

The code exposes a causal self-lock candidate:

```text
enter protective mode
  -> cap useful-work release
  -> backlog grows while arrivals continue
  -> RESERVE falls because RESERVE uses baseline backlog headroom
  -> recovery requires RESERVE >= .75
  -> protective mode cannot exit until backlog is already nearly drained
  -> protective cap itself delays that drain
```

This is not threshold tuning. It is a semantic separation question:

> A signal may be useful for deciding **when to enter protection** without being a valid veto on **when protection can safely end**.

## Frozen change

Keep the v0.19 entry semantics unchanged:

```text
severe PAIN
  OR
(PAIN + worsening TRAJECTORY)
  OR
(low RESERVE + worsening TRAJECTORY)
      -> enter protective RELIEF + STORAGE
```

Keep all actuators and magnitudes unchanged:

```text
ROUTE   = existing FlowPreservingMembrane routing
RATE    = existing release control
RELIEF  = existing auxiliary worker / boost amount
STORAGE = existing 256 -> 2048 elastic backlog capacity
```

Change only the recovery predicate.

v0.19 recovery:

```text
low PAIN
AND restored RESERVE
AND non-worsening TRAJECTORY
for RECOVERY_DWELL epochs
```

v0.20 recovery:

```text
low PAIN
AND non-worsening TRAJECTORY
for the same RECOVERY_DWELL epochs
```

`RESERVE` remains present and remains allowed to trigger entry. It is removed only as an exit veto.

Expanded STORAGE is still retained while backlog exceeds the baseline buffer even after RELIEF is turned off, so decoupling recovery does not discard retained work.

## Forbidden

- no new worker classes or worker counts;
- no new buffer sizes;
- no new relief magnitude;
- no admission shedding;
- no future phase/regime information;
- no change to PAIN, RESERVE, TRAJECTORY, LOAD, or dwell thresholds;
- no retuning after observing this seed family.

## Workload

Same executed SHA-256 work-queue class used by R1–R3 and v0.19.

Fresh held-out seeds:

```text
8100211
8200223
8300227
8400229
8500233
8600239
```

The v0.19 family is spent and is not reused for promotion.

## Comparators

On the exact same v0.20 family:

1. conventional flow-preserving baseline;
2. frozen R2 scalar sensor + v0.18 controller;
3. frozen v0.19 interoceptive controller;
4. v0.20 recovery-decoupled controller.

## Independent outcomes

The R3 external outcome vector remains the judge:

- completed work;
- lost/overflow work;
- seconds per completion;
- deadline-miss epochs;
- severe deadline-miss epochs;
- terminal backlog;
- digest mismatches;
- RELIEF occupancy;
- STORAGE occupancy.

Internal self-state is not the viability judge.

## Preregistered acceptance

Use the same substantive gates as v0.19. v0.20 passes only if all are true:

```text
median completed / baseline                 >= 1.25
median lost / baseline                      <= 0.75
median seconds-per-completion / baseline    <= 1.15
median deadline-miss epochs / baseline      <= 0.60
median severe-miss epochs / baseline        <= 0.25
median terminal backlog                     == 0
all digest mismatches                       == 0

median RELIEF occupancy                     <= 0.65
median STORAGE occupancy                    <= 0.65
median RELIEF occupancy / R2                <= 0.75
median STORAGE occupancy / R2               <= 0.75

median completed / R2                       >= 0.98
median deadline-miss epochs / R2            <= 1.25
median seconds-per-completion / R2           <= 1.15
```

Diagnostic rows must also report v0.19 occupancy on the same family, but v0.19 is not used to weaken these gates.

## Falsification

If v0.20 fails, retain the result. Do not change recovery dwell or thresholds on this family. The next step is signal/state-machine ablation, not gate relaxation.

## Narrow claim allowed by a PASS

A PASS would support only:

> On this executed fault-injected work-queue, separating **entry reserve** from **recovery evidence** removed a self-lock in the v0.19 protective state machine while preserving preregistered external outcome quality.

It would not establish consciousness, biological equivalence, general-purpose self-awareness, or production optimality.
