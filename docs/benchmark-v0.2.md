# Benchmark packet — BardoCompute v0.2

Latest equal-information control commit: `b9c4cd1aef43a6ec12fcb311f59fdf789e6be520`

CI matrix:

- Python 3.11.16 / Ubuntu 24.04
- Python 3.12.14 / Ubuntu 24.04

Both jobs completed successfully with `18 passed` and all four benchmark programs completed.

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

## Packed decision result versus external lookup

Workload construction is outside the timed decision loop here.

### Python 3.12

Latest run:

- external continuity lookup: `0.006340 s`
- Bardo reference object: `0.018231 s`
- Bardo packed 3-bit code: `0.004042 s`
- packed / lookup ratio: `0.638x`

Packed inline state was about `1.57x` faster than the external lookup decision path while preserving correctness.

### Python 3.11

Latest run:

- external continuity lookup: `0.003294 s`
- Bardo reference object: `0.031023 s`
- Bardo packed 3-bit code: `0.002448 s`
- packed / lookup ratio: `0.743x`

Packed inline state was about `1.35x` faster than the external lookup decision path while preserving correctness.

This reproduces the earlier local signal: inline continuity can beat reconstruction through a dictionary lookup in this synthetic guard.

## Benchmark D — equal-information control

The external-lookup comparison is not enough. A fairer control gives an ordinary representation the same information and avoids the dictionary.

`equal_information_control.py` compares:

1. conventional tuple metadata `(target, discontinuous)`;
2. a generic three-bit field written without BardoCompute helpers;
3. `BardoCompute.pack_line()` producing exactly the same three-bit codes;
4. an explicit streaming baseline that retains no transition record.

The benchmark asserts:

`generic_packed_events == bardo_packed_events`

Therefore the generic packed and Bardo packed representations are byte-for-byte identical at the logical code level. Any scan-time property belongs to the bitfield representation, not to the Bardo name.

### Python 3.12

| representation | build | scan | total |
| --- | ---: | ---: | ---: |
| tuple metadata | `0.018831 s` | `0.002360 s` | `0.021191 s` |
| generic packed 3-bit | `0.019203 s` | `0.003261 s` | `0.022464 s` |
| Bardo `pack_line` API | `0.025610 s` | `0.003299 s` | `0.028910 s` |
| streaming explicit fields | — | — | `0.007794 s` |

Ratios:

- generic packed / tuple scan: `1.382x` — packed scan slower;
- generic packed / tuple total: `1.060x` — packed total about 6% slower;
- Bardo API / generic packed total: `1.287x`;
- generic packed / streaming total: `2.882x`.

### Python 3.11

| representation | build | scan | total |
| --- | ---: | ---: | ---: |
| tuple metadata | `0.013461 s` | `0.001647 s` | `0.015109 s` |
| generic packed 3-bit | `0.010987 s` | `0.002239 s` | `0.013226 s` |
| Bardo `pack_line` API | `0.016526 s` | `0.002224 s` | `0.018750 s` |
| streaming explicit fields | — | — | `0.005133 s` |

Ratios:

- generic packed / tuple scan: `1.359x` — packed scan slower;
- generic packed / tuple total: `0.875x` — packed total about 12.5% faster;
- Bardo API / generic packed total: `1.418x`;
- generic packed / streaming total: `2.576x`.

## Current verdict

### Proven so far

1. Continuity is executable semantics, not just prose: it changes recovery/dispatch correctness.
2. Endpoint-only state is insufficient for the constructed recovery workload and produces 25,000 false allows out of 100,000 events.
3. Carrying continuity inline removes those false allows without an external lookup.
4. A compact inline bitfield can beat a dictionary-based reconstruction path on the decision-only benchmark.
5. The same compact bitfield does **not** show a stable speed advantage over an equally informed conventional tuple representation across both Python versions.
6. `BardoCompute.pack_line()` currently adds validation/function-call overhead versus constructing the identical generic bitfield directly.
7. If transition state does not need to be retained, the streaming conventional baseline is substantially faster than every retained representation tested here.

### Interpretation

The first defensible result is not "Bardo is faster than binary computing."

It is narrower:

> When downstream correctness depends on transition provenance, carrying that provenance inline can remove reconstruction work. The compact representation is promising specifically where the alternative is an external lookup or a richer retained object; its value is not yet demonstrated against an optimized equally informed conventional representation.

This is a useful boundary because it tells the project where to search next: workloads in which transition provenance must survive and would otherwise require coordination, memory indirection, recovery reconstruction, or additional state fetches.

### What this does not prove

It does **not** prove that BardoCompute is globally faster than CPUs, GPUs, TPUs, or conventional state machines.

It does not yet include:

- native compiled code;
- cache-miss/performance-counter evidence;
- deep memory accounting;
- energy use;
- realistic distributed recovery traces;
- multi-core contention;
- hardware implementation;
- a demonstrated advantage from trigrams, Dragon lifecycle states, or Five-Phase operation classes.

## Next falsification tests

1. Re-run the equal-information benchmark across randomized traces and discontinuity rates.
2. Move the packed control into native C or Rust and inspect generated machine code.
3. Measure cache misses, branches, bytes touched, and throughput — not only Python wall time.
4. Test a workload where provenance lives in a separate memory structure large enough to produce realistic cache/coordination cost.
5. Only after that, test whether a three-line trigram can amortize transition metadata or express useful multi-state operations more efficiently than independent fields.
6. Keep Dragon and Five-Phase layers deferred until the primitive earns them experimentally.
