# BardoCompute hardware v0.1 — BARDO-TX1

## Decision

The first hardware target is **not** a new universal CPU. It is a narrow,
streaming transition-state coprocessor for workloads where direction,
continuity, settling, and a joint policy are on the hot path.

This boundary follows the strongest current evidence:

- the six line states already have a stable three-bit contract;
- all `6^3 = 216` valid trigrams fit in one byte;
- the project has demonstrated correctness utility for continuity provenance;
- native speed results are compiler-sensitive, so a CPU defeat cannot be
  claimed from software benchmarks alone.

## BARDO-TX1 v0.1 datapath

```text
9 bits / lane
[upper 3][middle 3][lower 3]
              |
              v
      validate six-state codes
              |
       +------+------------------+
       |                         |
       v                         v
 sparse->radix-6            semantic features
  index 0..215          transition / discontinuity /
       |                     target count / settle
       +--------------+----------+
                      v
            fail-closed reference policy
                      |
             one registered stage
```

The top is parameterized by `LANES` and defaults to eight. It uses a
ready/valid streaming interface and holds its output stable under backpressure.
An invalid line code (`001` or `111`) makes that lane invalid and zeros every
derived field, including the policy result.

## Exact state contract

The line-code-to-radix digit map is frozen as:

| Packed code | Meaning | Digit |
| --- | --- | ---: |
| `000` | stable 0 | 0 |
| `010` | rising, continuous | 1 |
| `011` | rising, discontinuous | 2 |
| `100` | falling, continuous | 3 |
| `101` | falling, discontinuous | 4 |
| `110` | stable 1 | 5 |

For ordered lines `(lower, middle, upper)`:

```text
index = lower_digit + 6 * middle_digit + 36 * upper_digit
```

The built-in reference policy is the existing benchmark predicate:

```text
valid
and no discontinuity
and target_count >= 2
and any actual transition
```

The core also exposes the primitive features so later wrappers can implement a
programmable policy table without changing the encoding contract.

## What “competes with a CPU” means

BARDO-TX1 only passes the competition gate when it beats the best equal-
information CPU implementation on a bounded workload. The comparison must
include the interface cost, not only the combinational core.

Required controls:

1. identical input states and identical policy semantics;
2. optimized scalar and SIMD CPU paths, including the best compiler settings;
3. warm-cache and streaming/out-of-cache regimes;
4. host-to-device transfer and DMA cost for a discrete FPGA;
5. throughput, p50/p99 latency, energy per accepted trigram, logic area, and
   bytes transferred;
6. correctness checksums and fail-closed invalid-state tests.

Initial success threshold:

- at least `2x` end-to-end throughput per watt **or**
- at least `2x` p99 latency improvement at equal throughput,

on at least one real transition-heavy workload. A higher core clock or a small
synthetic LUT win is not sufficient.

## Verification boundary

The v0.1 packet contains:

- a bit-exact Python reference model;
- exhaustive Python checks over all 512 sparse bundles;
- an RTL testbench over the same complete space;
- a ready/valid backpressure test;
- Yosys synthesis/check scripts;
- an optimized C baseline with both direct evaluation and a fair 512-entry result LUT.

The RTL has not earned an FPGA frequency, resource, power, or CPU-speedup claim
until CI synthesis and then a board implementation produce those measurements.

## Hardware path

### H0 — synthesizable core

Current slice: portable SystemVerilog, exhaustive simulation, generic Yosys
synthesis.

### H1 — FPGA proof

Wrap BARDO-TX1 in an AXI-Stream or equivalent shell, add counters and a DMA
loopback, then run on one FPGA platform. Measure post-place-and-route frequency,
LUT/FF/BRAM use, sustained streaming throughput, and board power.

### H2 — CPU-attached execution

Two valid integration paths:

- memory-mapped/streaming accelerator next to a small RISC-V core;
- custom RISC-V operations for `pack3`, `settle3`, and `policy3` using only
  custom instruction encoding space.

The coprocessor path comes first because it measures the primitive without
committing to an ISA too early.

### H3 — ASIC exploration

After FPGA evidence, run RTL-to-GDS design-space exploration and compare
power/performance/area across lane counts. No tapeout decision is justified
before the end-to-end CPU comparison passes.

## Next implementation boundary

1. make the current RTL CI green;
2. record generic synthesis cell counts for `LANES=1, 4, 8, 16`;
3. run the included C baseline across scalar/SIMD compiler variants and preserve the fastest path;
4. add a cycle-accurate host/stream model;
5. choose a board only after the interface bandwidth requirement is known.
