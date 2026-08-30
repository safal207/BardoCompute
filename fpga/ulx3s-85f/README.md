# BARDO-TX1 on ULX3S-85F

This directory turns the BARDO-TX1 RTL into independently gated ECP5
bitstreams for the ULX3S-85F board.

## Clock profiles

The physical board oscillator is always 25 MHz. Two build profiles preserve two
different claims instead of silently replacing one with the other:

| Profile | Core clock | Lanes | On-chip roofline | Evidence boundary |
| --- | ---: | ---: | ---: | --- |
| `native_25mhz` | 25 MHz | 71 | 1.775 Gtrigrams/s | Native-clock reference |
| `pll_25_to_75mhz` | 75 MHz | 71 | 5.325 Gtrigrams/s | Generated PLL, timing-gated candidate |

Both numbers are `lanes × clock`. Neither is an end-to-end CPU speedup.

The 75 MHz profile generates its ECP5 PLL with the pinned `ecpll` tool. The
build fails unless the generated primitive retains the frozen 25 → 75 MHz
contract:

```text
CLKI_DIV  = 1
CLKFB_DIV = 3
CLKOP_DIV = 8
PFD       = 25 MHz
VCO       = 600 MHz
output    = 75 MHz
```

A PLL lock loss reasserts the complete self-test reset. It is not treated as a
valid continuation of the stream.

## Fair CPU boundary

The CPU control materializes the complete semantic output and also evaluates a
bounded reduction path. Correctness is checked outside the timed kernels, and
the strongest admissible single-thread path is retained. A serial dependent
checksum cannot be used as the CPU opponent.

`bardocompute.cpu_control` reports only core-level diagnostic ratios. The
separate `bardocompute.hardware_claims` gate keeps both FPGA profiles at:

```text
status=CORE_ROOFLINE_ONLY
claim_allowed=false
```

until an exact SHA-bound bitstream is measured physically with host transfer,
setup, power, latency, and a real same-host workload in scope.

## DSP-free structural gate

The trigram index uses tiny constant radix weights (`*6` and `*36`). An early
mapping inferred two `MULT18X18D` blocks per lane. The RTL now uses explicit
constant decoders, and `check_report.py` fails CI unless:

- `MULT18X18D used == 0`;
- every reported clock meets its nextpnr constraint;
- utilization and timing fields are present.

This preserves all DSP blocks for future arithmetic and makes timing/resource
assumptions executable contracts.

## Continuous self-test

Each profile continuously generates all 512 sparse 9-bit input bundles. Every
one of the 71 lanes receives a distinct offset, so each lane sees the complete
address space during every 512-cycle epoch.

Every output field is folded into the same order-sensitive 64-bit signature:

```text
0xb0058cd5263c1fc3
```

For the native profile, `led[0]` means at least one complete epoch matched and
`led[1]` is sticky failure. The 75 MHz profile additionally exposes PLL lock on
`led[2]`. Both streams continue after the first pass so physical power and
thermal behavior can later be measured under continuous load.

The matching Python derivation and clock contracts live in
`tests/test_fpga_harness.py`.

## Build

The pinned CI flow uses OSS CAD Suite `2026-08-30`.

Native reference profile:

```bash
make -C fpga/ulx3s-85f all
```

75 MHz PLL candidate:

```bash
make -C fpga/ulx3s-85f all-75
```

Both profiles:

```bash
make -C fpga/ulx3s-85f profiles
```

Outputs are isolated in `build/` and `build-75mhz/`. Each directory contains
its own Yosys JSON, nextpnr configuration/report, structural-gate result,
flashable `.bit`, tool record, SHA-256 manifest, CPU-control report, and
claim-gate evidence.

## Interface reality

At the complete 23-bit output boundary, the theoretical stream requirements
are:

| Profile | Input | Output | Round trip |
| --- | ---: | ---: | ---: |
| 25 MHz | 1.997 GB/s | 5.103 GB/s | 7.100 GB/s |
| 75 MHz | 5.991 GB/s | 15.309 GB/s | 21.300 GB/s |

A slow discrete peripheral link would erase the compute advantage. A production
BARDO boundary therefore needs one or more of:

- near-memory or CPU-coherent integration;
- on-device policy filtering and aggregation;
- a compact result contract that exports only consequential decisions.

The bitstreams are implementation artifacts. Physical execution, watts,
temperature, sustained host-fed throughput, and end-to-end CPU competition
remain separate evidence gates.
