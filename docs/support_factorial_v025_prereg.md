# v0.25 Support Component Factorial Ablation — preregistration

Status: **frozen before implementation/results**.

## Prior evidence

v0.24 staged withdrawal was hosted on Python 3.11 and 3.12 and rejected the frozen promotion bar.

Stable staged pattern:

```text
Stage 1: RELIEF off, RATE cap retained -> usually succeeds
Stage 2: RELIEF off, base RATE restored -> substantially more failures
```

This localizes a dependency near RATE restoration but does not identify whether RATE cap is uniquely necessary because the complementary `RELIEF-on + base-RATE` condition was not tested.

## Hypothesis

The existing support components have separable causal value. A 2x2 factorial ablation of RELIEF and RATE cap, with STORAGE held constant, can identify whether outcome protection is driven primarily by RATE cap, RELIEF, their interaction, or neither.

## Frozen support matrix

All four policies use:

```text
ROUTE = existing FlowPreservingMembrane secondary_fraction
STORAGE = existing ELASTIC_BUFFER_LIMIT
admission shedding = forbidden
future phase information = forbidden
```

Only the already-existing RELIEF and RATE states vary:

```text
A FULL_SUPPORT:
  RELIEF = existing BOOST_AMOUNT
  RATE   = existing BOOSTED_SAFE_CAP

B RATE_CAP_ONLY:
  RELIEF = 0
  RATE   = existing BOOSTED_SAFE_CAP

C RELIEF_ONLY:
  RELIEF = existing BOOST_AMOUNT
  RATE   = base FlowPreservingMembrane release_limit

D STORAGE_ONLY:
  RELIEF = 0
  RATE   = base FlowPreservingMembrane release_limit
```

No new actuator magnitude, threshold, worker count, buffer size, or intermediate rate is introduced.

This is a component-value audit, not a new adaptive recovery policy. The four support configurations are held fixed over the same executed fault-injected workload so their marginal effects are directly comparable.

## Fresh held-out family

```text
13100401
13200409
13300419
13400421
13500431
13600433
```

These seeds must never be used for post-result tuning.

## Independent outcome judge

Use the R3 external outcome vector:

```text
completed work
lost / overflow work
seconds per completion
deadline-miss epochs
severe deadline-miss epochs
RELIEF occupancy
STORAGE occupancy
peak backlog
terminal backlog
digest mismatches
```

## Causal outputs

Report, on the same seeds:

```text
B vs A  -> marginal value of RELIEF while RATE cap is present
C vs A  -> marginal value of RATE cap while RELIEF is present
D vs B  -> marginal value of RATE cap when RELIEF is absent
D vs C  -> marginal value of RELIEF when RATE cap is absent
```

Primary causal classification:

```text
rate_cap_has_independent_value
relief_has_independent_value
support_interaction_present
```

Classification must be based on miss/severe-miss and completion/loss preservation together, not on one scalar.

## Promotion rule

No factorial arm is promoted as the new adaptive controller from this benchmark alone.

The experiment succeeds scientifically when all four arms execute correctly and causal comparisons are reported. A simpler support set may be *eligible for the next preregistered adaptive experiment* only if it preserves:

```text
completed / FULL_SUPPORT >= .98
lost / FULL_SUPPORT      <= 1.10
seconds / FULL_SUPPORT   <= 1.15
miss / FULL_SUPPORT      <= 1.25
severe / FULL_SUPPORT    <= 1.25
terminal backlog         == 0
digest mismatches        == 0
```

These eligibility gates do not replace the existing final v0.19 promotion bar.

## Falsification

If neither single-component arm preserves FULL_SUPPORT outcome quality, conclude that support interaction matters and do not introduce a graded actuator on this seed family.

If RATE_CAP_ONLY preserves quality while RELIEF_ONLY does not, the next adaptive experiment may test RELIEF pruning while retaining RATE cap.

If RELIEF_ONLY preserves quality while RATE_CAP_ONLY does not, the next adaptive experiment may test RATE-cap pruning while retaining RELIEF.

If both single-component arms preserve quality, the next question is cost/selectivity rather than necessity.

No biological, emotional, conscious, or neuroscience-equivalence claim follows from any result.
