# Native evidence packet — BardoCompute v0.2

Evidence commit for the joint trigram policy: `0c5b6f2a72f16c9b3fca7da44e393070dc1b46fa`

CI run: `32475013362`

Environment:

- Ubuntu 24.04 hosted runners
- C compiler invoked as `cc -O3 -std=c11 -Wall -Wextra -pedantic`
- two independent CI matrix jobs
- Python test suite remained green: `18 passed`

This document records native C results separately from the Python reference-object results because the Python object overhead is not representative of a compact processor-level representation.

## 1. Packed transition line

The v0.2 transition semantics are encoded as one byte carrying three logical fields:

`[source][target][discontinuity]`

A conventional explicit C struct carrying the same three `uint8_t` fields occupies three bytes per event in this benchmark. The packed representation occupies one byte per event.

Workload:

- 20,000,000 events
- 8 repeated scans
- equal decision semantics
- checksum verified

### Runner A

| representation | bytes/event | total bytes | build | scan avg |
| --- | ---: | ---: | ---: | ---: |
| explicit equal-information struct | 3 | 60,000,000 | `0.019765 s` | `0.015140 s` |
| packed transition byte | 1 | 20,000,000 | `0.013467 s` | `0.003570 s` |

Ratios:

- memory: `0.333x`
- packed build / explicit build: `0.681x`
- packed scan / explicit scan: `0.236x`
- equivalent scan speedup: about `4.24x`

### Runner B

| representation | bytes/event | total bytes | build | scan avg |
| --- | ---: | ---: | ---: | ---: |
| explicit equal-information struct | 3 | 60,000,000 | `0.016157 s` | `0.009699 s` |
| packed transition byte | 1 | 20,000,000 | `0.011449 s` | `0.002937 s` |

Ratios:

- memory: `0.333x`
- packed build / explicit build: `0.709x`
- packed scan / explicit scan: `0.303x`
- equivalent scan speedup: about `3.30x`

### Interpretation

This is a reproducible native memory-layout result: the same transition information can be retained in one byte instead of three byte-sized fields, and the denser representation scans materially faster in this synthetic workload.

This is **not** evidence that Bardo-specific mathematics makes ordinary bit packing faster. A conventional engineer can also pack three fields into one byte. The BardoCompute contribution being tested here is the transition-state semantic model and whether its useful information admits a compact representation.

## 2. Trigram byte

v0.2 currently has six valid semantic line states.

Therefore a three-line state space contains:

`6^3 = 216`

possible states.

Because `216 < 256`, the entire three-line transition-aware group fits in one `uint8_t` using radix-6 encoding:

`trigram = a + 6*b + 36*c`

where each line is represented by a dense digit `0..5`.

Compared with three independent one-byte line codes:

- independent lines: 3 bytes per group
- trigram code: 1 byte per group
- memory ratio: `0.333x`

Workload:

- 24,000,000 semantic line states
- 8,000,000 trigram states
- 8 repeated scans
- checksum equivalence required

## 3. Negative control — simple independent operation

The first trigram operation merely counted a simple per-line condition. This is deliberately a weak use case for grouping because each line can be processed independently.

### Runner A

- independent line scan: `0.004301 s`
- trigram lookup scan: `0.007217 s`
- trigram / line ratio: `1.678x`

### Runner B

- independent line scan: `0.003546 s`
- trigram lookup scan: `0.007039 s`
- trigram / line ratio: `1.985x`

### Verdict

The trigram representation is about 3x denser but roughly 1.7–2.0x slower for this simple independent operation.

Density alone is not enough to justify using a grouped state representation.

## 4. Joint three-line policy

The second native experiment uses a synthetic policy that genuinely depends on the three lines as one group.

The policy allows a group only when:

1. no line is discontinuous;
2. at least two target values are `1`;
3. at least one line is an actual transition.

The exact rule is not claimed to be special. Its purpose is to test a class of operations whose result depends on the joint three-line state.

Two execution paths are compared:

### Independent-line path

Read three line bytes and evaluate the joint predicate from their fields.

### Trigram path

Read one radix-6 trigram byte and index a precomputed 216-entry policy table.

Both paths produce the same checksum.

### Runner A

- independent-line joint policy: `0.015289 s`
- trigram joint-policy lookup: `0.006833 s`
- trigram / line ratio: `0.447x`
- equivalent speedup: about `2.24x`

Equivalent throughput:

- line path: `1,569.709 million semantic lines/s`
- trigram path: `3,512.198 million semantic lines/s`

### Runner B

- independent-line joint policy: `0.018871 s`
- trigram joint-policy lookup: `0.007212 s`
- trigram / line ratio: `0.382x`
- equivalent speedup: about `2.62x`

Equivalent throughput:

- line path: `1,271.817 million semantic lines/s`
- trigram path: `3,327.782 million semantic lines/s`

## 5. Current native verdict

The strongest result so far is workload-specific:

> A three-line, six-state-per-line group can be represented in one byte. For a joint predicate over all three lines, a 216-state lookup representation was about 2.24–2.62x faster than evaluating the same predicate from three independent packed line bytes on two CI runners, while using one third of the retained state memory.

The same grouped representation was slower for a simple independent per-line operation.

This distinction matters. It suggests that any processor-level value is likely to come from **group-native operations**, not from replacing every binary operation with a trigram operation.

## 6. What belongs to the model, and what is generic engineering

Generic facts:

- bit packing is ordinary computer engineering;
- radix encoding is ordinary mathematics;
- small lookup tables are ordinary implementation techniques;
- any six-state alphabet grouped in threes has `6^3 = 216` combinations.

BardoCompute-specific research questions:

- whether transition direction and continuity deserve first-class state;
- whether useful workloads naturally consume those transition states in three-line groups;
- whether the grouping yields reusable operations, proofs, recovery semantics, or scheduling advantages;
- whether a hardware/software ISA can expose those semantics without paying conversion cost.

The I Ching trigram is treated as inspiration for a three-line grouping and transition ontology, not as a claim that the historical text specifies modern processor architecture.

## 7. Next falsification tests

1. Compare trigram lookup against an optimized conventional packed three-field/group implementation, not only independent bytes.
2. Test several unrelated joint predicates to determine whether the speedup generalizes beyond one synthetic policy.
3. Generate trigram state directly rather than packing from pre-existing line bytes and measure end-to-end lifecycle cost.
4. Measure cache misses, vectorization, branches, instructions, and bytes read with native performance counters where available.
5. Test randomized state distributions and discontinuity rates.
6. If group-native wins survive those controls, test a six-line state. With six semantic states per line, `6^6 = 46,656`, which fits in 16 bits and is exactly two trigram bytes.
7. Keep Dragon lifecycle and Five-Phase operation semantics deferred until the group primitive survives these controls.
