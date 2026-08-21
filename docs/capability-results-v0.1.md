# Capability Flow Results v0.1

## Question

Can the three capability modes — **Manifest**, **Acquire**, and **Adapt** — be carried by Yin, Yang, and Tao without widening the existing temporal register, and what does that cost when capability policy is evaluated from hot state?

## Semantic model

All three carriers receive the same innate capability potential in v0.1:

```text
Yin  -> {Manifest, Acquire, Adapt}
Yang -> {Manifest, Acquire, Adapt}
Tao  -> {Manifest, Acquire, Adapt}
```

The active mode is selected from temporal context:

1. discontinuity / regression / reorientation -> `ADAPT`
2. missing evidence or stale stall -> `ACQUIRE`
3. otherwise -> `MANIFEST`

A conventional if/else function with exactly the same inputs is the equal-information semantic control.

## Python semantic benchmark

Workload: 120,000 cases.

Expected distribution:

- 30,000 `MANIFEST`
- 30,000 `ACQUIRE`
- 60,000 `ADAPT`

A fixed-Manifest strategy is wrong on 90,000 / 120,000 cases in this deliberately mixed workload.

### Python 3.12 runner

```text
fixed_manifest_errors=90000
conventional_seconds=0.017978
flow_seconds=0.022978
manifest=30000
acquire=30000
adapt=60000
semantic_equivalence_to_conventional=True
carrier_invariant_flow=True
tao_carrier_adds_unique_behavior=False
flow_vs_conventional_time=1.278x
```

### Python 3.11 runner

```text
fixed_manifest_errors=90000
conventional_seconds=0.028998
flow_seconds=0.027952
manifest=30000
acquire=30000
adapt=60000
semantic_equivalence_to_conventional=True
carrier_invariant_flow=True
tao_carrier_adds_unique_behavior=False
flow_vs_conventional_time=0.964x
```

### Semantic conclusion

The three modes are useful as an explicit model of **what the system is doing with its capability now**, but there is no unique behavior from naming Tao a third carrier when all carriers have equal potential.

Under the v0.1 symmetric assumption:

> **Tao-as-carrier adds identity, not a new transition rule.**

The more operational hypothesis is **Tao-as-flow-law**: the rule that moves a carrier between Manifest, Acquire, and Adapt as temporal conditions change.

No stable Python speed advantage exists over the equal-information conventional function.

## 16-bit integration

`TemporalState16` previously used bits 0..13 and reserved bits 14..15.

`CapabilityTemporalState16` fills those two bits:

```text
00 Manifest
01 Acquire
10 Adapt
11 reserved
```

Therefore the active capability mode adds **zero register-width cost**: temporal + capability hot state still fits in one `uint16_t`.

## Native equal-information benchmark

Workload: 12,000,000 records, 12 repeated scans.

Explicit record stores eight one-byte fields. Packed state stores the same policy-relevant information in one 16-bit word. A generic `uint16_t` control is bit-identical to the Bardo/Tao representation.

The full state-indexed policy table has:

```text
2^16 = 65,536 entries
1 byte / verdict
64 KB total
```

The policy includes temporal risk plus whether the active capability mode matches the reference temporal flow law.

### Runner A — Ubuntu 24.04 / CPython 3.12 job

```text
records=12000000
state_bits=16
capability_bits=2
policy_bytes=65536
correct=true
representation_identity=true

explicit:
  bytes_per_record=8
  total_bytes=96000000
  build_seconds=0.036141
  scan_seconds_avg=0.022646

CapabilityTemporalState16 direct decode:
  bytes_per_record=2
  total_bytes=24000000
  build_seconds=0.029610
  scan_seconds_avg=0.040740

CapabilityTemporalState16 + 64KB LUT:
  scan_seconds_avg=0.004238

generic uint16_t + same LUT:
  scan_seconds_avg=0.004229
```

Ratios:

```text
packed_memory_vs_explicit=0.250x
packed_build_vs_explicit=0.819x
direct_scan_vs_explicit=1.799x
lut_scan_vs_explicit=0.187x
lut_scan_vs_direct=0.104x
lut_scan_vs_generic=1.002x
```

Interpretation: 4x less record memory. Direct bit decoding is slower than the explicit struct on this runner, but state-indexed lookup is about **5.34x faster than explicit scanning** and about **9.61x faster than direct packed decoding**.

### Runner B — Ubuntu 24.04 / CPython 3.11 job

```text
records=12000000
state_bits=16
capability_bits=2
policy_bytes=65536
correct=true
representation_identity=true

explicit:
  bytes_per_record=8
  total_bytes=96000000
  build_seconds=0.034990
  scan_seconds_avg=0.054162

CapabilityTemporalState16 direct decode:
  bytes_per_record=2
  total_bytes=24000000
  build_seconds=0.021314
  scan_seconds_avg=0.029573

CapabilityTemporalState16 + 64KB LUT:
  scan_seconds_avg=0.007578

generic uint16_t + same LUT:
  scan_seconds_avg=0.008055
```

Ratios:

```text
packed_memory_vs_explicit=0.250x
packed_build_vs_explicit=0.609x
direct_scan_vs_explicit=0.546x
lut_scan_vs_explicit=0.140x
lut_scan_vs_direct=0.256x
lut_scan_vs_generic=0.941x
```

Interpretation: 4x less record memory. On this runner packed direct decoding is already faster than the explicit struct, and the state-indexed path is about **7.15x faster than explicit scanning** and about **3.90x faster than packed direct decoding**.

## Reproduced result

Across both runners:

- `CapabilityTemporalState16` remains **2 bytes** even after adding three capability modes;
- explicit equal-information state is **8 bytes**, so packed hot state uses **4x less memory**;
- a 64 KB state-indexed policy table remains effective in this workload;
- the LUT path is approximately **5.3x–7.1x faster** than the explicit record scan;
- direct packed decode is compiler/runner sensitive;
- the generic bit-identical `uint16_t + LUT` control performs essentially the same.

## Defensible conclusion

The result does **not** show that Yin, Yang, or Tao intrinsically accelerate computation.

It does show that the project’s temporal + capability semantics can currently be represented as one compact 16-bit hot state and evaluated efficiently through state-indexed execution:

```text
trajectory context
      +
capability mode
      -> 16-bit state
      -> policy lookup
      -> verdict
```

The performance property belongs to **compact state + indexed execution**. Bardo/Tao/Capability3 provide the semantic organization that led us to this state design.

## Next falsification

The current 16-bit word is full. The next benchmark should sweep policy-table sizes around likely cache boundaries rather than add more fields blindly:

- 12 bits -> 4 KB
- 13 bits -> 8 KB
- 14 bits -> 16 KB
- 15 bits -> 32 KB
- 16 bits -> 64 KB
- 17 bits -> 128 KB
- 18 bits -> 256 KB

Sequential and randomized access should be measured separately. This will test whether the current 16-bit / 64-KB design is near a useful architectural boundary or merely a favorable microbenchmark point.
