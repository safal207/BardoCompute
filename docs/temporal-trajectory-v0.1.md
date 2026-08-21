# Temporal orientation trajectory v0.1

## Hypothesis

A current state is not always sufficient to determine whether a computation may safely continue. Two computations can end at the same endpoint with the same current evidence while having different transition histories.

BardoCompute therefore models a time-indexed trajectory:

`X(t) = (Bardo(t), Tao(t))`

where:

- `Bardo(t)` records endpoint/direction/continuity semantics;
- `Tao(t)` records terminal decision or missing-evidence orientation;
- `t` is a monotonic logical time tick.

## Center of orientation

The Tao missing-evidence mask is mapped to a three-axis coordinate:

`O(t) = (authority_missing, continuity_missing, outcome_missing)`

Each coordinate is in `{0, 1}`.

Examples:

- `(1, 0, 1)` = authority and outcome are unresolved;
- `(0, 0, 1)` = only outcome is unresolved;
- `(0, 0, 0)` = no evidence dimension is missing.

This makes the **center of orientation through time** a path through an 8-point Boolean cube.

The geometry is an engineering representation, not a historical/philosophical claim.

## Temporal metrics

For consecutive points `O(t_i), O(t_{i+1})`:

- **orientation distance** = Hamming distance;
- **path length** = sum of orientation distances;
- **resolved dimensions** = missing bits cleared over time;
- **regressions** = previously settled dimensions that become missing again;
- **discontinuities** = Bardo discontinuous transition events;
- **convergence time** = first terminal tick minus initial tick;
- **orientation velocity** = path length / duration.

## Why time matters

Consider two histories with the same terminal snapshot.

Monotone:

`(AUTHORITY + OUTCOME) -> OUTCOME -> NONE`

Regressive:

`OUTCOME -> NONE -> (AUTHORITY + OUTCOME) -> NONE`

Both can end at `NONE / ALLOW`, but the second history contains an evidence regression. A snapshot-only policy cannot distinguish them after the final state is reached.

The same principle applies to Bardo continuity: a final endpoint can be identical even if one path contains a discontinuous transition.

## Processor-oriented interpretation

A full trajectory may be too expensive to keep in a hot execution path. The research target is therefore two-layered:

1. retain an auditable trajectory when needed;
2. derive compact temporal signatures online for branch/recovery/safety decisions.

A candidate one-byte temporal signature could reserve bits for:

- current Tao orientation mask: 3 bits;
- regression-seen flag: 1 bit;
- discontinuity-seen flag: 1 bit;
- transition/defer history flags or phase class: remaining bits.

This is generic state compression unless a Bardo/Tao-specific workload shows a measurable advantage. Equal-information controls remain mandatory.

## Next benchmark

Compare:

1. current snapshot only;
2. external full-history scan;
3. online compact temporal signature.

Use histories that deliberately share the same final snapshot but differ in regression/discontinuity history. Measure correctness, memory traffic proxy, update cost, and decision cost.
