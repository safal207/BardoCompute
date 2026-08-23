# Trajectory kinetics v0.1

## Purpose

A current orientation coordinate does not describe how the computation arrived there or how it is moving now.

BardoCompute therefore separates:

- **position**: `O(t)` — current center of orientation;
- **motion**: `ΔO` — which evidence dimensions changed;
- **time**: `Δt` — how long the change took;
- **phase**: a discrete class of the motion;
- **rate**: how quickly evidence is being resolved or lost.

The current coordinate is:

`O(t) = (authority_missing, continuity_missing, outcome_missing)`

Each component is binary in v0.1.

## Phase step

For consecutive observations `P0` and `P1`:

`ΔO = O(t1) - O(t0)`

A coordinate component:

- `-1` means an evidence requirement was resolved;
- `0` means no change on that axis;
- `+1` means a previously settled requirement became missing again.

`Δt = t1 - t0`

The implementation exposes:

- Hamming movement distance;
- movement rate = `distance / Δt`;
- cleared evidence dimensions;
- added evidence dimensions;
- signed convergence rate = `(cleared - added) / Δt`.

Positive convergence rate means net movement toward fewer missing requirements. Negative means regression. Zero can mean either no motion or reorientation, so rate alone is insufficient.

## Four motion phases

### CONVERGING

At least one missing evidence dimension is cleared and none are added.

### STALLED

No orientation dimension changes.

### REGRESSING

At least one previously settled dimension becomes missing and none are cleared.

### REORIENTING

At least one dimension is cleared while another becomes missing in the same step.

This distinction is important because `STALLED` and `REORIENTING` may both have zero **net** convergence rate while representing very different motion.

## Example

Two computations can share the same current center:

`O(t) = (0, 0, 1)`

but have different previous centers:

- `(1,0,1) -> (0,0,1)` = CONVERGING;
- `(0,0,1) -> (0,0,1)` = STALLED;
- `(0,0,0) -> (0,0,1)` = REGRESSING;
- `(1,0,0) -> (0,0,1)` = REORIENTING.

A current snapshot collapses all four to the same coordinate. A phase-aware temporal model preserves the distinction.

## Trajectory-level quantities

`PhaseTrajectory` now exposes:

- phase sequence;
- convergence rate per step;
- discrete changes in convergence rate;
- net convergence rate;
- peak movement rate;
- total path length;
- regression count;
- discontinuity count;
- convergence time.

These are discrete computational quantities. Terms such as velocity/rate are engineering analogies over event ticks, not claims about physical motion.

## Falsification target

`benchmarks/trajectory_kinetics.py` constructs four equal-sized groups whose current orientation is identical while their temporal phase differs.

The intended narrow claim is:

> Current state alone cannot distinguish temporal direction. One previous orientation observation is sufficient to distinguish convergence, stall, regression, and reorientation in this v0.1 space.

This is not unique to BardoCompute. An equally informative conventional two-snapshot state machine can compute the same phase. The research question is whether Bardo/Tao provenance and phase can be maintained compactly enough to become useful hot state rather than reconstructed metadata.

## Next step

The next representation experiment should use the two remaining bits of the current one-byte temporal signature to encode the current four-way motion phase, then compare it against an equally informative conventional one-byte online automaton.
