# TemporalState16 results v0.1

## Question

Can several independent temporal dimensions be kept as one compact hot-state word and evaluated efficiently without replaying history or repeatedly decoding many fields?

`TemporalState16` combines the temporal layers already falsified separately:

- current orientation `O(t)`;
- previous motion phase;
- current motion phase;
- quantized current phase age;
- regression history;
- discontinuity history;
- phase-edge validity;
- current `ALLOW / DEFER / DENY` decision.

## Layout

The current 16-bit layout uses 14 bits and reserves 2:

- bits 0..2: current missing-evidence orientation mask;
- bits 3..4: previous phase;
- bits 5..6: current phase;
- bits 7..8: phase-age bucket;
- bit 9: regression has occurred;
- bit 10: discontinuity has occurred;
- bit 11: ordered phase edge valid;
- bits 12..13: current decision;
- bits 14..15: reserved.

This is a conventional bitfield representation carrying Bardo/Tao temporal semantics. A bit-identical conventional `uint16_t` is used as the equal-information control.

## Mixed-policy semantic result

`benchmarks/temporal_state16.py` creates 100,000 records in five equal groups whose current orientation is identical:

1. safe convergence;
2. current regression;
3. recent regression followed by convergence;
4. stale stall;
5. otherwise-safe path with discontinuity history.

Expected alerts: **80,000**.

A single temporal slice is deliberately insufficient:

- current phase only: 20,000 alerts / **60,000 false negatives**;
- ordered phase edge only: 20,000 / **60,000 false negatives**;
- phase age only: 20,000 / **60,000 false negatives**;
- combined `TemporalState16`: **80,000 / 0 false negatives**.

A conventional `uint16_t` with the identical bits gives the same semantics.

## Native direct-decode control

`native/temporal_state16_bench.c` uses 12,000,000 records and compares an explicit seven-byte equal-information struct with the two-byte packed word.

### Runner A (Python 3.12 job environment)

- explicit record: 84 MB, build `0.027623 s`, scan `0.015954 s`;
- `TemporalState16` direct decode: 24 MB, build `0.019946 s`, scan `0.031360 s`.

Direct packed decoding is therefore:

- **3.5x denser** in retained state;
- faster to build in this workload;
- but **1.966x slower to scan** than the explicit struct.

This negative result matters: compactness alone does not make the multi-condition temporal policy fast.

## Representation-aware policy LUT

Only 14 bits are active, so the full active state space has:

`2^14 = 16,384`

possible codes.

A one-byte verdict for every code therefore requires a **16,384-byte policy lookup table**.

The LUT is generated from exactly the same reference policy used by direct decode. The scan becomes:

`alerts += policy[state & 0x3fff]`

rather than extracting and evaluating several temporal fields on every record.

### Runner A (Python 3.12 job environment)

- policy entries: 16,384;
- policy bytes: 16,384;
- policy build: `0.000040526 s`;
- explicit scan: `0.015954 s`;
- packed direct scan: `0.031360 s`;
- packed LUT scan: `0.006277 s`;
- generic bit-identical `uint16_t` + same LUT: `0.007179 s`.

Derived:

- LUT vs explicit: **0.393x time** = ~**2.54x faster**;
- LUT vs packed direct decode: **0.200x time** = ~**5.0x faster**;
- packed state remains **3.5x smaller** than the explicit seven-byte record.

### Runner B (Python 3.11 job environment)

The second hosted runner independently reproduced the direction:

- explicit scan: approximately `0.015509 s`;
- packed direct scan: approximately `0.030475 s`;
- packed LUT scan: approximately `0.005760 s`.

Derived:

- LUT vs explicit: ~**2.69x faster**;
- LUT vs direct decode: ~**5.29x faster**;
- retained-state density remains **3.5x better** than the explicit record.

## Critical equal-information caveat

The generic `uint16_t` control uses the same bits and the same LUT. It receives the same architectural benefit.

Therefore the defensible performance claim is **not**:

> Bardo/Tao is intrinsically faster.

It is:

> A compact temporal state space can make a complex temporal policy cheap when execution is representation-aware and uses direct state-indexed dispatch rather than repeated field extraction and branching.

Bardo/Tao currently supplies the semantic decomposition that led to the state word. The low-level LUT mechanism itself is conventional engineering.

## Current processor hypothesis

The strongest implementation hypothesis is now a pair:

`Temporal State Register + Temporal Policy Table`

rather than a new scalar value alone.

Conceptually:

`verdict(t) = Policy[TemporalState(t)]`

and state evolves online from new transition/orientation observations.

This resembles a tiny temporal microcode / policy-cache mechanism, but cache residency and hardware behavior have **not** been measured yet.

## Next falsification tests

1. Sweep active state widths from 12 to 16 bits, producing 4 KB / 8 KB / 16 KB / 32 KB / 64 KB policy tables.
2. Measure whether a table-size performance cliff appears.
3. Randomize state distributions instead of using only periodic synthetic classes.
4. Test several unrelated policies against the same temporal word.
5. Measure online state-update cost separately from policy-scan cost.
6. Compare against structure-of-arrays and compiler-friendly explicit controls.
7. If available, collect instructions, branches and cache-miss counters.
8. Only after those controls consider mapping the temporal word/table pair to a hardware ISA proposal.
