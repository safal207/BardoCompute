# Temporal trajectory benchmark v0.1

## Question

Can policy-relevant transition history be retained online without keeping the full temporal log?

The experiment compares three representations for 12,000,000 records with four observed phases per record:

1. **final snapshot only** — retains only the terminal state;
2. **full temporal history** — retains all four phase bytes;
3. **online temporal signature** — incrementally folds policy-relevant trajectory facts into one byte.

The temporal signature currently retains:

- current 3-bit orientation mask;
- whether an orientation regression occurred;
- whether a discontinuity occurred;
- whether the computation was ever deferred;
- two reserved bits.

This is generic online state compression carrying Bardo/Tao trajectory semantics. It is not claimed to be a novel compression primitive by itself.

## Semantic result

All records finish with the same safe-looking final snapshot, but half of the generated histories contain a policy-invalid regression/discontinuity.

Therefore the terminal snapshot alone is intentionally insufficient.

Across both GitHub Actions runners:

- expected safe histories: **6,000,000 / 12,000,000**;
- snapshot-only allowed: **12,000,000**;
- snapshot-only false allows: **6,000,000**;
- full-history false allows: **0**;
- one-byte signature false allows: **0**.

This establishes the narrow semantic claim:

> Equal final states can encode unequal computation histories, and a compact online trajectory signature can preserve policy-relevant path information that the final snapshot loses.

## Native C results

### Runner A (Python 3.11 job environment)

| Representation | Retained bytes | Scan avg | False allows |
| --- | ---: | ---: | ---: |
| Final snapshot | 12,000,000 | 0.001657 s | 6,000,000 |
| Full 4-phase history | 48,000,000 | 0.005485 s | 0 |
| Online 1-byte signature | 12,000,000 | 0.001763 s | 0 |

Derived:

- signature memory vs full history: **0.25x** (4x smaller);
- signature scan vs full history: **0.321x** (~3.11x faster);
- signature retains the same bytes as snapshot-only while recovering the policy distinction snapshot loses.

### Runner B (Python 3.12 job environment)

| Representation | Retained bytes | Scan avg | False allows |
| --- | ---: | ---: | ---: |
| Final snapshot | 12,000,000 | 0.002320 s | 6,000,000 |
| Full 4-phase history | 48,000,000 | 0.008094 s | 0 |
| Online 1-byte signature | 12,000,000 | 0.002334 s | 0 |

Derived:

- signature memory vs full history: **0.25x** (4x smaller);
- signature scan vs full history: **0.288x** (~3.47x faster).

## What this does NOT prove

It does not prove that Bardo/Tao terminology itself causes the performance gain. The compression/update pattern is generic engineering.

It does not prove a universal one-byte trajectory is sufficient. This v0.1 signature only preserves the facts needed by the current policy.

It does not prove hardware speedup, energy reduction, or superiority over an optimized conventional temporal automaton.

## Strong next controls

1. Compare against an equally informative conventional online automaton using the same one-byte budget.
2. Increase the number of policy-relevant temporal predicates until one byte becomes insufficient.
3. Measure update cost per transition, not only retained-state scan cost.
4. Randomize trajectory lengths and event distributions.
5. Add temporal quantities: dwell time, convergence time, orientation velocity and acceleration.
6. Test whether trajectory signatures compose naturally at trigram/group level.

## Current architectural interpretation

The useful object is no longer only a state cell. It is a small stateful reducer:

`signature(t+1) = F(signature(t), transition(t), orientation(t))`

That suggests a processor-level hypothesis worth testing:

> Keep a compact trajectory register close to computation so policy-relevant path information is updated online instead of reconstructed later from RAM/logs.
