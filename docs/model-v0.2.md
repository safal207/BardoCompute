# BardoCompute model v0.2

## Hypothesis

A transition can carry computationally useful information beyond its source and target: whether the target is causally continuous with the source or reached across a boundary such as a reset, interrupt, exception, external event, or restored state.

The v0.2 question is deliberately narrow:

> If two transitions have the same endpoints, does retaining continuity as first-class state improve distinguishability enough to justify its cost?

## State model

A line is represented as:

`L = (state, mode)`

where:

- `state ∈ {0, 1, 0->1, 1->0}`
- `mode ∈ {stable, continuous, discontinuous}`

Valid combinations in v0.2 are:

| State | Mode | Meaning |
| --- | --- | --- |
| `0` | `stable` | stable zero |
| `1` | `stable` | stable one |
| `0->1` | `continuous` | rising transition preserving causal continuity |
| `0->1` | `discontinuous` | rising transition crossing a causal boundary |
| `1->0` | `continuous` | falling transition preserving causal continuity |
| `1->0` | `discontinuous` | falling transition crossing a causal boundary |

This yields six valid semantic line states in v0.2.

## Why direction and continuity are separate axes

These two histories have identical endpoints:

`0 --continuous--> 1`

`0 --discontinuous--> 1`

A terminal binary value cannot distinguish them. A direction-only transition model also cannot distinguish them. Bardo v0.2 can.

This is the first place where the project uses "Bardo" in a precise engineering sense: an explicit transition state whose semantics include how continuity was preserved or broken.

## Scope boundary

`continuous` and `discontinuous` are BardoCompute engineering terms. They are not presented as historical categories from the Book of Changes or from Tibetan descriptions of bardo.

The Book of Changes is an inspiration for representing change as structured state. Bardo is an inspiration for treating transition itself as a first-class region. The executable semantics, validation rules, and benchmarks are new model choices made by this project.

## Benchmark

`benchmarks/continuity_vs_metadata.py` compares three representations:

1. endpoint-only binary state;
2. ordinary binary state plus explicit metadata tuple;
3. Bardo v0.2 first-class transition mode.

The benchmark reports:

- distinguishable history classes (utility);
- execution time (speed cost);
- Python object size (representation cost).

The equivalent-information metadata baseline is important. BardoCompute should not claim an advantage merely because the binary baseline was denied information that Bardo retained.

## Falsification rule

v0.2 is not considered an improvement merely because it distinguishes more histories.

A useful result requires at least one workload where continuity information either:

- avoids a later lookup or reconstruction step;
- prevents an invalid state/action;
- reduces branching or coordination elsewhere;
- improves provenance/recovery semantics;
- or enables a measurable end-to-end benefit that compensates for representation cost.

If no such workload is found, continuity remains descriptive metadata rather than a processor-level primitive.

## Deferred

Still intentionally deferred:

- same-value discontinuous events (`1 -> 1` across reset, for example);
- Dragon lifecycle states;
- Five-Phase operation classes;
- dynamic hexagrams;
- proof/provenance receipts;
- hardware encoding;
- claims of speedup over CPUs/GPUs/TPUs.
