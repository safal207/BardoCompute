# Computational Interoception v0.19 — preregistration

Status: **frozen before benchmark implementation/results**.

## Question

Can a real executed work-queue use a **multi-signal internal self-state** to preserve the independently measured outcome quality seen in R2 while avoiding R2's near-always-on protective mode?

This experiment adds **no new actuator**. It changes only the internal state representation and the policy that decides when already-existing route/rate/relief/storage actuators are used.

## Why this exists

R1 and R2 exposed two separate methodological problems:

1. an actuator must not silently redefine the scale of the sensor used to judge itself;
2. internal self-sense must not also be the external judge of viability.

R3 separated those roles. On fresh hosted work, both R1 and R2 passed the external outcome-vector gate, while R2 achieved stronger deadline/loss outcomes by leaving RELIEF and STORAGE active for roughly 98% of executed epochs.

Therefore v0.19 asks a narrower question:

> Can internal state become **more selective**, not merely more alarmed?

## Self-state

The controller receives only completed-past-epoch observations. No future phase/regime labels are available.

Signals are kept separate rather than collapsed into one scalar health score:

```text
LOAD       = released work relative to the existing release range
PAIN       = deadline-miss fraction from the previous epoch
RESERVE    = remaining baseline backlog headroom
TRAJECTORY = EMA of worsening/recovery in miss + backlog pressure
RECOVERY   = consecutive healthy observed epochs
```

`RESERVE` uses the immutable baseline service buffer as its reference. Expanded storage is an actuator/resource and does not redefine the baseline-health scale.

## Existing actuators only

v0.19 may use the same actuator family already present in v0.18:

```text
ROUTE   — secondary_fraction through FlowPreservingMembrane
RATE    — release_limit through FlowPreservingMembrane
RELIEF  — existing auxiliary worker activation and existing boost magnitude
STORAGE — existing 256 -> 2048 elastic backlog capacity
```

Forbidden:

- new worker classes or new worker counts;
- new buffer sizes;
- new relief magnitude;
- admission shedding;
- future phase information;
- retuning on the v0.19 seed family after observing results.

## Control semantics

Protection is entered only from combinations of independently meaningful signals, not one scalar threshold. The frozen qualitative rules are:

```text
severe PAIN
  OR
(PAIN + worsening TRAJECTORY)
  OR
(low RESERVE + worsening TRAJECTORY)
      -> protective RELIEF + STORAGE

localized congestion without viability combination
      -> existing ROUTE/RATE response only

sustained low PAIN + restored RESERVE + non-worsening TRAJECTORY
      -> leave protective mode after a recovery dwell
```

All thresholds used by the executable implementation are declared in the benchmark source and may not be changed on this seed family.

## Workload

Same real executed micro-workload class as R1–R3:

- actual SHA-256 payload execution;
- two ordinary single-worker lanes;
- one auxiliary relief lane;
- controlled CPU ballast by route as fault injection;
- self-calibrated task cost per hosted runner;
- wall-clock deadline;
- bounded real backlog;
- identical digest semantics on every route.

Fresh held-out seeds:

```text
7100171
7200173
7300179
7400181
7500187
7600191
```

The spent R1/R2/R3 seed families are not reused for tuning.

## Comparators

On the exact same v0.19 seed family, run:

1. conventional flow-preserving baseline;
2. R1 sensor + frozen v0.18 controller;
3. R2 sensor + frozen v0.18 controller;
4. v0.19 multi-signal interoceptive controller.

The R1/R2 rows are controls, not training data.

## Independent outcomes

The external judge remains separate from internal self-state and reports:

- completed work;
- overflow/lost work;
- seconds per completion;
- deadline-miss epochs;
- severe deadline-miss epochs;
- peak backlog;
- terminal backlog;
- digest mismatches;
- RELIEF occupancy;
- STORAGE occupancy.

No scalar `health score` is permitted in the outcome judge.

## Preregistered acceptance

v0.19 passes only if all are true across the fresh seed family:

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

Interpretation of the bar:

- R2-quality outcomes must mostly survive;
- protective resources must become materially selective;
- a controller that simply leaves emergency resources on nearly all the time fails even if throughput is excellent.

## Falsification

If v0.19 fails, keep the result. Do not tune thresholds on this seed family. The next step must diagnose which internal signal or state-transition assumption failed, not loosen the acceptance gate.

## Narrow claim allowed by a PASS

A PASS would support only:

> On this real executed fault-injected work-queue, a separated multi-signal self-state can preserve most R2 outcome quality while using existing protective resources more selectively than the near-always-on R2 scalar sensor.

It would **not** establish consciousness, biological equivalence, general-purpose self-awareness, or production optimality.
