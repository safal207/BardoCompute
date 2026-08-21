# Native evidence packet — BardoCompute v0.2

Latest evidence commit: `de4439453698e106821d4d1ba8a12d110f9f25cd`

Latest CI run: `32475614976`

Environment:

- Ubuntu 24.04 hosted runners
- two independent CI matrix jobs
- Python 3.11 and 3.12
- Python test suite: `18 passed` on both jobs
- native controls built with GCC-compatible `cc`

This packet deliberately records positive and negative results. Claims are narrowed whenever a stronger equal-information control explains an earlier win.

## 1. Semantic utility: continuity changes correctness

In the synthetic recovery/dispatch workload:

- endpoint-only state: 50,000 allows / 25,000 false allows;
- endpoint + external continuity lookup: 25,000 / 0 false allows;
- Bardo inline continuity: 25,000 / 0 false allows.

Defensible result:

> Transition provenance can be operational state rather than descriptive logging when downstream actions depend on how a state was reached.

This is a correctness result, not a speed claim.

## 2. Packed transition line

The six valid v0.2 line states fit in a byte carrying three logical fields:

`[source][target][discontinuity]`

Latest native 20M-event runs compare a three-`uint8_t` explicit struct with a one-byte packed representation carrying equivalent information.

### Runner 3.11

- explicit: 60 MB, scan `0.010081 s`;
- packed: 20 MB, scan `0.002928 s`;
- memory ratio: `0.333x`;
- scan ratio: `0.290x` (~3.44x faster).

### Runner 3.12

- explicit: 60 MB, scan `0.012921 s`;
- packed: 20 MB, scan `0.003410 s`;
- memory ratio: `0.333x`;
- scan ratio: `0.264x` (~3.79x faster).

Bit packing is generic engineering. The project-specific question is whether the transition semantics are useful enough to deserve compact first-class storage.

## 3. Trigram state space

Six semantic line states imply:

`6^3 = 216`

valid three-line states.

Because 216 is below 256, a complete three-line transition state fits in one byte using radix-6 encoding:

`trigram = a + 6*b + 36*c`

The arithmetic is generic. The I Ching trigram is inspiration for the three-line abstraction, not a historical processor claim.

## 4. Simple operation: negative result

For a condition that is naturally evaluated independently per line, dense trigram lookup remains slower than scanning independent packed line bytes.

Latest examples:

- runner 3.11: `0.003632 s` lines vs `0.007051 s` trigram — trigram `1.941x` slower;
- runner 3.12: `0.003947 s` lines vs `0.006487 s` trigram — trigram `1.644x` slower.

Density alone does not justify grouping line-independent operations.

## 5. Joint three-line policy versus independent records

Synthetic policy:

1. no discontinuity in the three-line group;
2. at least two target values are `1`;
3. at least one actual transition.

When the baseline reads three independent line bytes and computes the policy, while the trigram reads one group byte and indexes a 216-entry table:

- runner 3.11: `0.018973 s` -> `0.007164 s`, trigram ratio `0.378x` (~2.65x faster);
- runner 3.12: `0.014393 s` -> `0.006484 s`, trigram ratio `0.450x` (~2.22x faster).

This proves only that pre-grouped state can amortize joint-policy reconstruction versus three independent records.

## 6. Equal-information grouped control

A stronger conventional baseline also groups all three line states and uses a lookup table.

### Conventional grouped representation

- three 3-bit line codes;
- 9 logical bits stored in `uint16_t`;
- 512-entry lookup address space;
- same 216 valid semantic states.

### Dense radix-6 representation

- one `uint8_t` ordinal;
- 216 valid states;
- 216-entry lookup table;
- same policy and checksum.

Both paths are warmed and measurement order alternates across 12 repeats.

### Normal `-O3` build

Runner 3.11:

- generic `uint16_t`: 32 MB, `0.005753 s`;
- dense `uint8_t`: 16 MB, `0.013594 s`;
- dense memory: `0.500x`;
- dense scan: `2.363x` slower.

Runner 3.12:

- generic `uint16_t`: 32 MB, `0.004714 s`;
- dense `uint8_t`: 16 MB, `0.013053 s`;
- dense memory: `0.500x`;
- dense scan: `2.769x` slower.

Under ordinary `-O3`, the conventional grouped representation is decisively faster despite twice the retained memory.

## 7. Compiler-sensitivity control

The same source was then compiled with:

`-O3 -fno-tree-vectorize`

No algorithm, data, policy, or measurement order changed.

### Scalar runner 3.11

- generic `uint16_t`: `0.007862 s`;
- dense `uint8_t`: `0.005709 s`;
- dense ratio: `0.726x`;
- dense speedup: ~`1.38x`;
- dense memory: `0.500x`.

### Scalar runner 3.12

- generic `uint16_t`: `0.006972 s`;
- dense `uint8_t`: `0.004607 s`;
- dense ratio: `0.661x`;
- dense speedup: ~`1.51x`;
- dense memory: `0.500x`.

This reverses the winner on both runners.

Compiler diagnostics under normal `-O3` report `native/group_control.c:68` vectorized using 16-byte vectors. Line 68 is the loop inside `scan_u8`.

Important interpretation:

> The grouped result is compiler-sensitive. Dense `uint8_t` state is faster in the scalar build, but the current GCC auto-vectorized code path makes it substantially slower, while the generic `uint16_t` representation benefits enough to win the normal `-O3` comparison.

Therefore neither representation has a universal speed advantage at this stage.

## 8. Strongest current conclusion

The evidence now supports five separate statements:

1. **Semantic utility:** continuity provenance prevents invalid decisions in the recovery workload.
2. **Line density:** the six-state transition model admits compact one-byte storage.
3. **Trigram density:** 216 valid three-line states fit in one byte, half the storage of the fair `uint16_t` grouped control.
4. **Group amortization:** a pre-grouped trigram can beat recomputing a joint predicate from three independent records.
5. **Compiler sensitivity:** against an equally informed grouped lookup, dense state wins in scalar code (~1.38–1.51x) but loses badly under the current GCC `-O3` vectorized build (~2.36–2.77x slower).

The defensible statement is:

> BardoCompute has demonstrated useful transition semantics and compact grouped state. The dense three-line representation has a scalar execution advantage and a 2x memory advantage over a conventional 9-bit/`uint16_t` grouped control in this synthetic policy, but current compiler vectorization reverses the speed result. The next research problem is therefore representation-aware execution/code generation, not adding more symbolic states.

## 9. What is generic vs project-specific

Generic:

- finite-state machines;
- bit packing;
- radix encoding;
- lookup tables;
- `6^3 = 216`;
- storing 216 ordinals in one byte.

Project-specific research:

- direction + continuity as first-class transition semantics;
- workloads where that provenance is operationally necessary;
- three-line grouping as a native operation boundary;
- representation-aware code generation / ISA support;
- reducing total memory traffic, recovery reconstruction, or coordination cost.

"Bardo" is the project term for explicit transitional state. It is not claimed to be part of the I Ching. Dragon and Five-Phase layers remain conceptual candidates, not execution-core facts.

## 10. Next falsification tests

1. Build a representation-aware tuned binary: keep the best normal optimization for `uint16_t`, disable the harmful vectorization only for dense `uint8_t`, and compare best-known paths in one executable.
2. Inspect generated assembly / vectorization diagnostics for both scan loops.
3. Test larger state sets where 16 MB vs 32 MB crosses more memory-hierarchy boundaries.
4. Test several unrelated joint policies.
5. Measure instructions, branches, cache misses, and bytes read where counters are available.
6. Test randomized state distributions.
7. Do not add Dragon lifecycle or Five-Phase operation semantics to the execution core until this primitive execution boundary is understood.
