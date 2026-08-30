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
4. host-to-device transfer and setup cost for a discrete FPGA;
5. throughput, p50/p99 latency, energy per accepted trigram, logic area, and
   bytes transferred;
6. correctness checksums and fail-closed invalid-state tests;
7. a physical measurement bound to the exact CI bitstream SHA-256.

Initial success threshold:

- at least `2x` end-to-end throughput per watt **or**
- at least `2x` p99 latency improvement at equal throughput,

on at least one real transition-heavy workload. A higher core clock, an on-chip
self-test, or a synthetic LUT win is not sufficient.

## Current implementation evidence

The ULX3S-85F implementation uses 71 lanes at the native 25 MHz board clock.
The current reproducible CI artifact reports:

```text
core roofline:              1,775.000 Mtrigrams/s
post-route achieved clock:     84.717 MHz (25 MHz constraint)
TRELLIS_COMB:                4,143
TRELLIS_FF:                  1,327
DP16KD:                          0
MULT18X18D:                      0
```

The achieved clock is a nextpnr timing estimate, not a measured board clock.
The 1.775 Gtrigrams/s figure is `lanes × clock` with inputs generated and results
reduced on chip. At the full 23-bit result boundary it implies approximately:

```text
input:       1.997 GB/s
output:      5.103 GB/s
round trip:  7.100 GB/s
```

That bandwidth requirement is why the hardware must filter, aggregate, or sit
near the workload rather than behave as a slow USB calculator.

## Machine-enforced claim gate

`bardocompute.hardware_claims` consumes the FPGA manifest, nextpnr report,
bitstream checksum, CPU control, and an optional physical measurement. It emits
both JSON and Markdown evidence and fails closed on mismatched clocks,
resources, semantics, or bitstream identity.

```bash
PYTHONPATH=src python -m bardocompute.hardware_claims \
  --fpga-evidence fpga/ulx3s-85f/build/evidence.txt \
  --cpu-evidence hardware/build/cpu-baseline.log \
  --nextpnr-report fpga/ulx3s-85f/build/nextpnr-report.json \
  --sha256s fpga/ulx3s-85f/build/SHA256SUMS \
  --json-output fpga/ulx3s-85f/build/claim-gate.json \
  --markdown-output fpga/ulx3s-85f/build/claim-gate.md
```

The statuses are deliberately narrow:

| Status | Meaning | CPU claim allowed? |
| --- | --- | ---: |
| `CORE_ROOFLINE_ONLY` | RTL/P&R plus CPU control; no physical host stream | No |
| `PHYSICAL_SELF_TEST_ONLY` | Exact bitstream passed on-board self-test | No |
| `END_TO_END_NOT_PROVEN` | Host stream measured, but one or more gates are missing or below threshold | No |
| `CPU_COMPETITIVE_PASS` | Exact bitstream, real same-workload comparison, and a 2x energy or p99 gate | Yes |

`--require-competitive` turns the last row into a mandatory release gate. It is
not enabled in ordinary CI while the physical host-fed measurement is absent.

## Verification boundary

The v0.1 packet contains:

- a bit-exact Python reference model;
- exhaustive Python checks over all 512 sparse bundles;
- an RTL testbench over the same complete space;
- a ready/valid backpressure test;
- generic Yosys synthesis and ECP5 place-and-route;
- a DSP-free structural gate;
- a flashable bitstream with SHA-256 manifest;
- an optimized C control with direct and 512-entry LUT paths;
- a claim gate that cannot promote core roofline into end-to-end speedup.

What remains unproven is physical board execution, host-fed sustained
throughput, power, temperature, p99 latency, and a real-workload CPU win.

## Hardware path

### H0 — synthesizable core: complete

Portable SystemVerilog, exhaustive simulation, generic synthesis, and a frozen
software/RTL encoding contract are present.

### H1a — FPGA implementation artifact: complete

The ULX3S-85F target completes Yosys ECP5 synthesis, nextpnr place-and-route,
resource/timing checks, and bitstream packaging in CI.

### H1b — physical FPGA evidence: open

Flash the exact SHA-bound bitstream, record completed self-test epochs, then add
a host-fed streaming shell and counters. Measure sustained throughput, bytes,
power, temperature, and latency with transfer and setup included.

### H2 — CPU-attached execution

Two valid integration paths:

- memory-mapped/streaming accelerator next to a small RISC-V core;
- custom RISC-V operations for `pack3`, `settle3`, and `policy3` using only
  custom instruction encoding space.

The coprocessor path comes first because it measures the primitive without
committing to an ISA too early.

### H3 — ASIC exploration

After physical FPGA evidence, run RTL-to-GDS design-space exploration and
compare power/performance/area across lane counts. No tapeout decision is
justified before the end-to-end CPU comparison passes.

## Next implementation boundary

1. flash the current bitstream and record a SHA-bound `on_chip_self_test`
   measurement;
2. implement a host-fed streaming boundary that includes counters and exact byte
   accounting;
3. choose one real transition-heavy workload and run the same workload on the
   same host CPU;
4. measure board and CPU power plus p99 latency;
5. run the gate with `--require-competitive`; only then promote a CPU claim.
