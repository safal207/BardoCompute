# Benchmark packet — BardoCompute v0.2

Latest packed-line evidence commit: `06a954393119ae10d2cb35e99d109ec46a2063cd`

CI matrix:

- Python 3.11.16 / Ubuntu 24.04
- Python 3.12.14 / Ubuntu 24.04

Both jobs completed successfully with `18 passed`.

## Benchmark A — transition-aware object vs endpoint-only binary

This benchmark is intentionally asymmetric. The endpoint-only binary baseline carries less information, so it is useful only as a lower-bound cost reference.

The Python reference object is much slower than a terminal integer bit. Across CI runs, the gap is tens to more than one hundred times depending on interpreter/run noise.

### Verdict

No speed advantage for the reference object. This result must not be used to claim a processor performance win.

The comparison mainly quantifies software-object overhead of preserving transition semantics in a high-level Python representation.

## Benchmark B — continuity semantics vs equivalent metadata

The workload contains four distinguishable transition histories:

- `0 -> 1 continuous`
- `0 -> 1 discontinuous`
- `1 -> 0 continuous`
- `1 -> 0 discontinuous`

Endpoint-only binary state collapses these to two terminal classes. Both binary+metadata and Bardo v0.2 preserve all four.

Across the latest CI run:

- endpoint-only binary: 2 distinguishable classes;
- binary + explicit metadata: 4 classes;
- Bardo v0.2 reference object: 4 classes;
- utility gain vs endpoint-only: `2.000x` distinguishable histories.

The reference object remains substantially slower than an ordinary metadata tuple.

The `sys.getsizeof` numbers used by this microbenchmark are shallow Python object sizes only. They are not hardware-memory measurements.

## Benchmark C — recovery/dispatch guard

This benchmark asks a more useful question: can first-class continuity prevent an invalid action without reconstructing provenance from an external table?

Workload:

- 100,000 transitions;
- rising transitions may dispatch only if continuity is preserved;
- half of the rising transitions cross a discontinuity boundary;
- expected valid dispatches: 25,000.

### Correctness

| representation | allowed | false allows | correct |
| --- | ---: | ---: | --- |
| endpoint only, no provenance | 50,000 | 25,000 | no |
| endpoint + external lookup | 25,000 | 0 | yes |
| Bardo reference object | 25,000 | 0 | yes |
| Bardo packed 3-bit code | 25,000 | 0 | yes |

This is the first benchmark where transition continuity changes a downstream decision rather than merely increasing representational richness.

## Three-bit encoding

v0.2 line semantics fit directly into three bits:

`[source][target][discontinuity]`

Used codes:

| code | meaning |
| --- | --- |
| `000` | stable 0 |
| `010` | `0 -> 1` continuous |
| `011` | `0 -> 1` discontinuous |
| `100` | `1 -> 0` continuous |
| `101` | `1 -> 0` discontinuous |
| `110` | stable 1 |

Reserved codes:

- `001`: same-value discontinuity at 0;
- `111`: same-value discontinuity at 1.

Those two states are intentionally deferred rather than silently assigned semantics.

## Packed decision results

Workload construction is outside the timed decision loop. The numbers below measure the guard decision path only.

### Python 3.12

- external continuity lookup: `0.006005 s`
- Bardo reference object: `0.017259 s`
- Bardo packed 3-bit code: `0.003156 s`
- packed / lookup ratio: `0.526x`
- packed / reference-object ratio: `0.183x`

For this run, packed inline state is about `1.90x` faster than the external lookup baseline while preserving correctness.

### Python 3.11

- external continuity lookup: `0.004601 s`
- Bardo reference object: `0.038785 s`
- Bardo packed 3-bit code: `0.003361 s`
- packed / lookup ratio: `0.730x`
- packed / reference-object ratio: `0.087x`

For this run, packed inline state is about `1.37x` faster than the external lookup baseline while preserving correctness.

## Current verdict

### Positive signal

A compact inline transition representation can preserve continuity semantics, eliminate the 25,000 false allows produced by endpoint-only state in this synthetic workload, and beat an external metadata lookup on the timed decision path in both CI interpreters tested.

### What this still does not prove

It does **not** prove that BardoCompute is globally faster than CPUs, GPUs, TPUs, or conventional state machines.

It does not yet include:

- data construction/ingestion cost in the packed-vs-lookup timing;
- deep memory accounting;
- cache behavior;
- branch-prediction effects;
- energy use;
- compiled native code;
- hardware implementation;
- realistic distributed recovery traces.

The result should therefore be treated as a local architectural signal: carrying one continuity bit inline can be cheaper than reconstructing that information through an external lookup for this decision workload.

## Next falsification tests

1. Measure end-to-end cost including construction/encoding.
2. Compare packed Bardo against an equally packed conventional bitfield baseline, not only a dictionary lookup.
3. Run randomized recovery traces and multiple discontinuity rates.
4. Measure branch count/cache behavior in a native implementation.
5. Only after those tests, add higher-order structure such as trigrams, Dragon lifecycle stages, or Five-Phase operation classes.
