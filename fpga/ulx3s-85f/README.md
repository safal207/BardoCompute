# BARDO-TX1 on ULX3S-85F

This directory turns the BARDO-TX1 RTL into a place-and-routed ECP5 bitstream
for the ULX3S-85F board.

## Why 71 lanes at 25 MHz

Seventy-one parallel lanes at the native board clock provide an explicit
on-chip capacity boundary:

```text
71 lanes * 25 MHz = 1.775 Gtrigrams/s
```

That number is a core roofline, not an end-to-end CPU victory. The earlier
`867.029 Mtrigrams/s` CPU figure kept a serial dependent checksum inside every
timed iteration, so it is retained only as a legacy diagnostic. A replacement
CPU control must materialize equivalent outputs and verify them outside the
timed kernel before any speedup claim is made.

## DSP-free structural gate

The trigram index uses tiny constant radix weights (`*6` and `*36`). The first
ECP5 mapping inferred two `MULT18X18D` DSP blocks per lane and consumed 142 of
156 DSPs for 71 lanes. The RTL now expresses those weights as explicit six-way
constant decoders.

`check_report.py` fails CI unless:

- `MULT18X18D used == 0`;
- every reported clock meets its nextpnr constraint;
- utilization and timing fields are present rather than silently missing.

This preserves DSPs for future arithmetic and turns the resource assumption
into a checked hardware contract.

## Self-test

The board harness continuously generates all 512 possible sparse 9-bit input
bundles. Each of the 71 lanes receives a distinct offset; over every 512-cycle
epoch, each lane sees the full address space.

Every output field is folded into an order-sensitive 64-bit signature. A green
`led[0]` means at least one complete epoch matched
`0xb0058cd5263c1fc3`; `led[1]` is a sticky failure indicator. The stream keeps
running after the first pass so board power and thermal behavior can be
measured under continuous load.

The matching Python derivation lives in `tests/test_fpga_harness.py`; this keeps
the RTL constant from becoming an unexplained magic value.

## Build

The pinned CI flow uses OSS CAD Suite `2026-08-30`:

```bash
make -C fpga/ulx3s-85f all
```

Outputs include the Yosys ECP5 JSON, nextpnr text configuration and timing
report, structural gate result, packed `.bit` file, tool versions, checksums,
and a claim-boundary manifest.

## Honest boundary

This is an FPGA **core-throughput** benchmark with on-chip generation and
reduction. It proves that a real ECP5 image can sustain the selected spatial
architecture if place-and-route passes timing. It does not yet prove a host
application can feed and drain the full result stream.

At 1.775 Gtrigrams/s, the raw 9-bit input alone is about `2.00 GB/s`; exporting
all 23 result bits would add about `5.10 GB/s`. A discrete slow peripheral link
would erase the advantage. The production architecture therefore needs one of
these boundaries:

- near-memory or CPU-coherent integration;
- on-device policy filtering and aggregation;
- a compact result contract that returns only consequential decisions.

The `.bit` artifact is ready to flash after CI succeeds, but physical-board
execution, measured watts, temperature, and host end-to-end speed remain
separate evidence gates.
