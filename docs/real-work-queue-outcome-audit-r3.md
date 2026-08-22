# R3 — Outcome-Separated Real Work-Queue Viability Audit

Status: **pre-registered before implementation/results**

## Question

R1 and R2 used the controller's internal scalar `stress` both as a control input and as the reported `critical` outcome. That couples *how the system senses itself* to *how the experiment judges whether the system was viable*.

R3 asks a narrower question:

> When the internal self-sense is removed from the evaluator, do the already-frozen R1/R2 controllers improve independently observable work-queue outcomes?

R3 adds **no actuator** and does **not retune** the R1 or R2 sensor mappings.

## Frozen workload

Use the same real executed SHA-256 work-queue harness as R1/R2:

- two ordinary worker lanes;
- one auxiliary relief lane;
- controlled CPU ballast as route fault injection;
- bounded backlog;
- no admission shedding;
- identical SHA-256 result semantics on every route;
- runner-local task-cost calibration;
- no future phase information.

Fresh held-out seeds:

```text
6100141
6200143
6300149
6400151
6500157
6600163
```

The spent R1/R2 seed families are not reused for tuning.

## Policies

1. `baseline`: `FlowPreservingMembrane(route_enabled=True)`.
2. `r1_sensor`: unchanged `ElasticStorageMembrane` driven by the original R1 scalar sensor.
3. `r2_sensor`: unchanged `ElasticStorageMembrane` driven by the R2 actuator-independent scalar sensor.

No route/rate/relief/storage command values are changed.

## Independent outcome vector

The evaluator does **not** use controller `stress` to decide whether an epoch was bad.

For every epoch record:

```text
released work
on-time work
miss fraction = (released - on_time) / released
overflow work
backlog
wall-clock execution time
```

Report separately:

```text
deadline_miss_epochs  := miss_fraction >= 0.25
severe_miss_epochs    := miss_fraction >= 0.50
overflow_tasks
completed_tasks
seconds_per_completion
peak_backlog
terminal_backlog
digest_mismatches
relief_occupancy
storage_occupancy
```

No weighted scalar `health`, `stress`, or `utility` is constructed from these outcomes.

## Pre-registered promotion gate

A candidate sensor policy is considered to transfer on this family only if, versus baseline, all of the following hold at the median across seeds:

```text
completed_ratio                 >= 0.98
lost_ratio                      <= 0.75
seconds_per_completion_ratio    <= 1.15
deadline_miss_epoch_ratio       <= 0.75
severe_miss_epoch_ratio         <= 0.75
median_terminal_backlog         == 0
digest_mismatches               == 0
```

Actuator occupancy is reported but is **not** folded into the viability gate; it remains an explicit operational-cost dimension.

If neither R1 nor R2 passes, do not tune either sensor on this family. The next step must address the semantics of internal state rather than thresholds.

If one passes and the other does not, retain the causal distinction: internal self-sense quality changes control behavior even though viability is judged externally.

## Interpretation boundary

A pass supports only this claim:

> On this controlled real executed micro-workload, the frozen control pattern improves an independently measured vector of service outcomes.

It does not establish production optimality, biological equivalence, or a general theory of interoception.
