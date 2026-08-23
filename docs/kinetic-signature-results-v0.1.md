# Kinetic signature results v0.1

## Question

Can the current center of orientation **and** its current temporal phase be kept as compact hot state, without retaining a multi-field record or reconstructing the phase later?

The v0.1 kinetic state carries:

- bits 0..2: current missing-evidence orientation mask;
- bit 3: regression has occurred;
- bit 4: discontinuity has occurred;
- bits 5..6: current motion phase;
- bit 7: phase-valid flag.

Current phase uses four states:

- `STALLED`;
- `CONVERGING`;
- `REGRESSING`;
- `REORIENTING`.

The existing `TemporalSignature` remains unchanged; `KineticSignature` is a separate one-byte specialization that spends its remaining bit budget on current motion rather than `ever_deferred`.

## Semantic control

`benchmarks/trajectory_kinetics.py` creates 100,000 records whose current orientation is identical (`OUTCOME` missing) but whose previous orientation differs.

Expected classes:

- 25,000 converging;
- 25,000 stalled;
- 25,000 regressing;
- 25,000 reorienting.

Observed on both CI runners:

- current-orientation snapshot distinguishable classes: **1**;
- trajectory-kinetics distinguishable classes: **4**;
- snapshot regression false negatives: **25,000**;
- kinetics regression false negatives: **0**.

This supports only the narrow statement:

> The same current center `O(t)` can have different temporal motion. One previous orientation observation is sufficient to distinguish four motion classes in the current model.

An equally informative conventional two-snapshot state machine can compute the same classes.

## Native equal-information control

`native/kinetic_signature_bench.c` compares:

1. an explicit five-byte record (`current_missing`, `had_regression`, `had_discontinuity`, `phase`, `phase_valid`);
2. the one-byte Bardo/Tao kinetic signature;
3. a generic one-byte control using deliberately identical bits.

The packed Bardo/Tao byte and generic control are verified byte-for-byte identical before timing.

### Runner A (Python 3.12 job environment)

| Representation | Memory | Build | Scan |
| --- | ---: | ---: | ---: |
| Explicit 5-byte record | 60 MB | 0.022267 s | 0.013017 s |
| Kinetic 1-byte | 12 MB | 0.017324 s | 0.009654 s |
| Generic 1-byte control | 12 MB | 0.016896 s | 0.010094 s |

Derived:

- kinetic memory vs explicit: **0.200x** = 5x smaller;
- kinetic build vs explicit: **0.778x** (~1.29x faster);
- kinetic scan vs explicit: **0.742x** (~1.35x faster);
- kinetic build vs generic: **1.025x**;
- kinetic scan vs generic: **0.956x**.

### Runner B (Python 3.11 job environment)

| Representation | Memory | Build | Scan |
| --- | ---: | ---: | ---: |
| Explicit 5-byte record | 60 MB | 0.021846 s | 0.011909 s |
| Kinetic 1-byte | 12 MB | 0.015904 s | 0.009363 s |
| Generic 1-byte control | 12 MB | 0.016152 s | 0.009330 s |

Derived:

- kinetic memory vs explicit: **0.200x** = 5x smaller;
- kinetic build vs explicit: **0.728x** (~1.37x faster);
- kinetic scan vs explicit: **0.786x** (~1.27x faster);
- kinetic build vs generic: **0.985x**;
- kinetic scan vs generic: **1.004x**.

## Defensible result

> For this synthetic workload, current orientation + current motion phase + two history guards fit in one byte. The one-byte online form is 5x denser and moderately faster than an explicit five-byte representation on two CI runners. An intentionally identical generic one-byte control performs essentially the same, so the performance property belongs to compact online representation, not to Bardo/Tao terminology.

## Why this matters to the processor hypothesis

The project is moving from a conventional `state_now` model toward a compact online dynamical state:

`K(t) = [O(t), phase(t), history_guards(t)]`

This allows a downstream policy to ask not only:

- where is the computation now?

but also:

- is it converging, stalled, regressing, or reorienting?
- has it crossed a discontinuity?
- has a regression happened earlier?

without replaying a temporal log.

## Next falsification target

Current phase is a first-order temporal quantity. The next layer should test whether **change of convergence rate / phase transition over time** contains useful information beyond current phase alone.

Candidate quantities:

- `V(t) = ΔO / Δt` — orientation motion;
- signed convergence rate;
- `ΔV` / change in convergence rate;
- phase-transition edge `phase(t-1) -> phase(t)`;
- dwell time in phase;
- oscillation/reversal count.

The next benchmark should construct cases with the same current orientation **and the same current phase** but different prior kinetics, then test whether a small trend signature can detect stalls/reversals earlier than current-phase state alone.
