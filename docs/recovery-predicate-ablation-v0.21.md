# Recovery Predicate Ablation v0.21 — preregistration

Status: **frozen before implementation/results**.

## Question

Which internal signal is actually useful for deciding when protection may end on the executed real-work queue?

v0.19 showed that requiring restored RESERVE kept protection active too long. v0.20 removed RESERVE from recovery and cut RELIEF occupancy from about .875 to about .500, but exited too early and worsened deadline-miss outcomes.

v0.21 therefore performs a causal state-machine ablation rather than retuning thresholds.

## Frozen entry semantics

All candidates use the exact v0.19 entry rule:

```text
severe PAIN
OR (PAIN + worsening TRAJECTORY)
OR (low RESERVE + worsening TRAJECTORY)
    -> enter protective RELIEF + STORAGE
```

All PAIN, RESERVE, TRAJECTORY, LOAD and RECOVERY_DWELL thresholds remain unchanged from v0.19/v0.20.

## Recovery predicates under test

A. Full v0.19 recovery:

```text
low PAIN
AND restored RESERVE
AND non-worsening TRAJECTORY
for RECOVERY_DWELL epochs
```

B. v0.20 no-reserve recovery:

```text
low PAIN
AND non-worsening TRAJECTORY
for RECOVERY_DWELL epochs
```

C. PAIN-only ablation:

```text
low PAIN
for RECOVERY_DWELL epochs
```

No threshold value may change between these candidates.

## Existing actuators only

Exactly the existing family is permitted:

```text
ROUTE
RATE
RELIEF
STORAGE
```

Forbidden:

- new worker classes/counts;
- new buffer sizes;
- new relief magnitude;
- admission shedding;
- future phase/regime information;
- threshold tuning on this family;
- collapsing external outcomes into an internal health score.

## Fresh held-out family

```text
9100251
9200257
9300263
9400269
9500271
9600277
```

All prior R1/R2/R3/v0.19/v0.20 seed families are spent and are not reused for promotion.

## External outcome vector

The R3 independent judge remains authoritative:

- completed work;
- lost/overflow work;
- seconds per completion;
- deadline-miss epochs;
- severe deadline-miss epochs;
- terminal backlog;
- digest mismatches;
- RELIEF occupancy;
- STORAGE occupancy.

Also report protective transitions for each candidate.

## Causal interpretation rules

This experiment is primarily diagnostic. It does not promote a new controller merely because one scalar improves.

### RESERVE recovery-veto value

Compare A vs B.

RESERVE is classified as a **self-locking recovery veto** on this workload if removing it:

```text
reduces median RELIEF occupancy by >= 20%
AND
preserves median completed / A >= .98
```

while any worsening in miss/severe-miss outcomes is reported separately rather than hidden.

### TRAJECTORY recovery value

Compare B vs C.

TRAJECTORY has measurable protective value for recovery if removing it causes either:

```text
median deadline-miss epochs / B > 1.25
OR
median severe-miss epochs / B > 1.25
```

without a compensating >= 20% reduction in median RELIEF occupancy.

TRAJECTORY is classified as **redundant for recovery** only if C satisfies all:

```text
completed / B >= .98
seconds-per-completion / B <= 1.15
deadline-miss epochs / B <= 1.10
severe-miss epochs / B <= 1.10
RELIEF occupancy / B <= 1.00
STORAGE occupancy / B <= 1.00
terminal backlog = 0
digest mismatches = 0
```

## Promotion gate

A candidate may be called promotable only if it independently satisfies the existing v0.19 outcome/selectivity bar:

```text
median completed / baseline                 >= 1.25
median lost / baseline                      <= .75
median seconds-per-completion / baseline    <= 1.15
median deadline-miss epochs / baseline      <= .60
median severe-miss epochs / baseline        <= .25
median RELIEF occupancy                     <= .65
median STORAGE occupancy                    <= .65
median terminal backlog                     == 0
all digest mismatches                       == 0
```

If none passes, retain the ablation as diagnostic evidence and do not tune on this family.

## Narrow claims allowed

A result may support only signal-role claims about this executed fault-injected work-queue, for example:

- RESERVE is useful for entry but self-locking as an exit veto;
- TRAJECTORY contributes or does not contribute measurable recovery safety;
- PAIN alone is sufficient or insufficient for recovery under these frozen conditions.

No consciousness, biological equivalence, general-purpose self-awareness, or production optimality claim is permitted.