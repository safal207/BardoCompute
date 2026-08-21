# Native evidence packet — BardoCompute v0.2

Latest evidence commit: `a699462ea650b11698020cf5c8713d13a1de6b4f`

Latest CI run: `32475388543`

Environment:

- Ubuntu 24.04 hosted runners
- two independent CI matrix jobs
- Python 3.11 and 3.12
- C compiler invoked with `-O3`
- Python test suite: `18 passed` on both jobs

This packet deliberately records positive and negative results. The project should only keep claims that survive equal-information and optimized-control comparisons.

## 1. Transition continuity changes correctness

BardoCompute v0.2 distinguishes transitions that share the same endpoints but differ in continuity.

In the synthetic recovery/dispatch workload:

- endpoint-only state allowed 50,000 actions and produced 25,000 false allows;
- endpoint plus external continuity lookup allowed 25,000 with zero false allows;
- Bardo inline continuity allowed 25,000 with zero false allows.

The defensible semantic result is therefore:

> Transition provenance can be operational state rather than descriptive logging when downstream actions depend on how a state was reached.

This is a correctness result, not a speed claim.

## 2. Packed transition line

The six valid v0.2 line states fit in a byte carrying three logical fields:

`[source][target][discontinuity]`

A conventional explicit C struct carrying the same three `uint8_t` fields occupies three bytes per event in this benchmark. The packed representation occupies one byte per event.

Latest native workload:

- 20,000,000 events;
- 8 repeated scans;
- equal decision semantics;
- checksum verified.

### Python 3.11 matrix runner

- explicit struct: 60 MB, scan `0.010035 s`;
- packed byte: 20 MB, scan `0.002926 s`;
- memory ratio: `0.333x`;
- packed scan ratio: `0.292x` (~3.42x faster).

### Python 3.12 matrix runner

- explicit struct: 60 MB, scan `0.010010 s`;
- packed byte: 20 MB, scan `0.002917 s`;
- memory ratio: `0.333x`;
- packed scan ratio: `0.291x` (~3.43x faster).

### Interpretation

This is a reproducible memory-layout result. It does **not** show that Bardo-specific mathematics makes ordinary bit packing faster. Conventional engineering can pack the same fields. The research question is whether transition semantics are useful enough to deserve first-class compact storage.

## 3. Trigram state space

v0.2 has six valid semantic line states.

A three-line group therefore has:

`6^3 = 216`

possible valid states.

Because `216 < 256`, a complete transition-aware three-line group fits in one byte using radix-6 encoding:

`trigram = a + 6*b + 36*c`

where each line is a dense digit `0..5`.

This gives a natural byte-sized state space for a three-line group. The arithmetic fact is generic: any six-symbol alphabet grouped in threes has 216 combinations.

## 4. Negative control — simple independent operation

For a simple operation that can be evaluated independently on each line, the trigram representation saves memory but loses speed.

Latest results:

### Runner 3.11

- independent line scan: `0.003548 s`;
- trigram lookup: `0.006636 s`;
- trigram ratio: `1.871x` slower.

### Runner 3.12

- independent line scan: `0.003502 s`;
- trigram lookup: `0.007029 s`;
- trigram ratio: `2.007x` slower.

### Verdict

Do not use trigram grouping for work that is naturally line-independent solely because the representation is denser.

## 5. Joint three-line policy versus independent lines

A synthetic group policy was then chosen that genuinely depends on all three lines:

1. no line is discontinuous;
2. at least two target values are `1`;
3. at least one line is an actual transition.

Two paths were compared:

- read three independent line bytes and evaluate the predicate;
- read one radix-6 trigram byte and index a 216-entry policy table.

Latest results:

### Runner 3.11

- line evaluation: `0.018773 s`;
- trigram lookup: `0.007172 s`;
- ratio: `0.382x` (~2.62x faster).

### Runner 3.12

- line evaluation: `0.018746 s`;
- trigram lookup: `0.007175 s`;
- ratio: `0.383x` (~2.61x faster).

This is a real result, but its scope is narrow: the trigram lookup beats **recomputing the group predicate from three separate line records**.

It does not establish superiority over an optimized conventional grouped state machine.

## 6. Strong equal-information grouped control

The stronger control gives conventional computing the same opportunity to group state and use a lookup table.

### Generic grouped representation

Three 3-bit line codes are packed into 9 logical bits and stored in `uint16_t`:

- 16 storage bits/group;
- 512-entry lookup space;
- same 216 valid semantic states used by the workload.

### Dense radix-6 representation

The 216 valid states are stored directly in `uint8_t`:

- 8 storage bits/group;
- 216-entry lookup table;
- same policy and same checksum.

The benchmark warms both paths and alternates measurement order on every repeat to reduce order, frequency, and thermal bias.

### Latest runner 3.11

Generic `uint16_t` group:

- retained memory: 32 MB;
- build: `0.077721 s`;
- scan: `0.005765 s`;
- throughput: `2775.292 M groups/s`.

Radix-6 `uint8_t` group:

- retained memory: 16 MB;
- build: `0.074296 s`;
- scan: `0.013591 s`;
- throughput: `1177.258 M groups/s`.

Ratios:

- memory: `0.500x`;
- build: `0.956x`;
- scan: `2.357x` slower.

### Latest runner 3.12

Generic `uint16_t` group:

- retained memory: 32 MB;
- build: `0.077061 s`;
- scan: `0.005748 s`;
- throughput: `2783.626 M groups/s`.

Radix-6 `uint8_t` group:

- retained memory: 16 MB;
- build: `0.075013 s`;
- scan: `0.013623 s`;
- throughput: `1174.468 M groups/s`.

Ratios:

- memory: `0.500x`;
- build: `0.973x`;
- scan: `2.370x` slower.

### Compiler evidence

With `-fopt-info-vec-optimized`, GCC reports a loop in `group_control.c` vectorized using 16-byte vectors. The grouped-control speed gap survives warmup and alternating measurement order, so the earlier trigram speedup cannot be treated as a general grouped-state advantage.

## 7. Current native verdict

The current evidence supports four separate statements:

1. **Semantic utility:** continuity information prevents invalid downstream decisions in the recovery workload.
2. **Line density:** the transition semantics admit compact packed storage, and compact storage can materially beat a three-field explicit struct.
3. **Trigram density:** six states per line give 216 three-line states, allowing the whole group to fit in one byte — 2x smaller than the fair `uint16_t` 9-bit grouped control and 3x smaller than three independent line bytes.
4. **No general trigram speed win yet:** the trigram lookup beats recomputation from three independent line records, but loses by about 2.36–2.37x to an optimized equal-information grouped `uint16_t` lookup on the current GCC/runner setup.

Therefore the strongest defensible statement is:

> BardoCompute has demonstrated useful transition semantics and compact state representations. Three-line grouping can reduce retained memory and can amortize multi-line policy computation versus independent records, but no speed advantage over an optimized conventional grouped state machine has yet been established.

## 8. What is generic engineering vs project-specific research

Generic engineering/mathematics:

- bit packing;
- radix encoding;
- finite-state machines;
- lookup tables;
- `6^3 = 216`;
- packing 216 ordinals into one byte.

BardoCompute-specific research questions:

- whether direction plus continuity are useful first-class transition semantics;
- which real workloads repeatedly need that information;
- whether three-line grouping is a useful native operation boundary rather than only a compression trick;
- whether provenance/recovery/scheduling rules can be evaluated with less total memory traffic or coordination;
- whether an ISA or accelerator can exploit the state space without conversion overhead.

The I Ching trigram is inspiration for the three-line abstraction. It is not presented as a historical processor specification. "Bardo" is the project term for explicit transitional state; it is not presented as part of the I Ching.

## 9. Next falsification tests

1. Explain the `uint16_t` grouped-control advantage by comparing vectorized and `-fno-tree-vectorize` builds and inspecting compiler output.
2. Test larger retained state sets where the 16 MB vs 32 MB footprint crosses more cache/memory-hierarchy boundaries.
3. Test multiple unrelated joint policies rather than one synthetic predicate.
4. Generate grouped state directly and measure complete build + consume lifecycle cost.
5. Measure instructions, branches, cache misses, and bytes read where performance counters are available.
6. Test randomized state distributions and discontinuity rates.
7. Do **not** add Dragon lifecycle or Five-Phase operation semantics to the execution core until the primitive/group layer survives stronger controls.
