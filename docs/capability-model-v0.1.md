# Capability Flow v0.1

## Hypothesis

BardoCompute treats **Manifest**, **Acquire**, and **Adapt** as capability modes rather than assigning one mode exclusively to Yin or Yang.

The v0.1 hypothesis is:

```text
Carrier in {Yin, Yang, Tao}
Capability potential = {Manifest, Acquire, Adapt}
Active mode in {Manifest, Acquire, Adapt}
```

All three carriers receive the same capability potential by default. This is deliberate: any future claim that Yin, Yang, or Tao has a unique computational capability must be introduced and benchmarked separately.

These names are engineering terminology inspired by the user's conceptual model. They are not claims about a historical Chinese computing system.

## Three modes

- **Manifest** — use capability already available.
- **Acquire** — obtain missing knowledge, evidence, state, or mechanism.
- **Adapt** — change behavior because the trajectory regressed, reoriented, or crossed a discontinuity.

The modes are not terminal identities. A carrier may flow between them:

```text
Acquire -> Adapt -> Manifest
Manifest -> Adapt -> Acquire
... and other transitions allowed by temporal context
```

## Reference flow law

v0.1 maps temporal context to an active capability mode:

1. discontinuity, regression, or reorientation -> `ADAPT`
2. missing evidence, or stale stall -> `ACQUIRE`
3. otherwise -> `MANIFEST`

A conventional if/else policy receiving the same inputs is the equal-information control. If both produce the same output, the semantic value belongs to the explicit capability model, not to the Tao name.

## Tao: two competing models

### Tao as carrier

Tao is a third carrier beside Yin and Yang and has the same three innate capabilities.

Under v0.1's symmetric capability assumptions this adds carrier identity but no unique behavior. The benchmark should therefore report no special computational advantage merely from adding a third carrier.

### Tao as flow law

Tao names the rule that moves a carrier between Manifest, Acquire, and Adapt according to temporal context.

This is a separate hypothesis and currently the more operationally interesting one because it connects capability changes to the already measured temporal trajectory:

```text
O(t) -> phase(t) -> phase edge -> phase age -> capability mode(t)
```

The equal-information control remains a conventional policy function.

## 16-bit integration

`TemporalState16` v0.1 used 14 bits and reserved bits 14..15.

`CapabilityTemporalState16` uses those two bits:

```text
bits  0..13  existing temporal state
bits 14..15  active capability mode
              00 Manifest
              01 Acquire
              10 Adapt
              11 reserved
```

Therefore the capability mode adds **zero storage width** to the current temporal register candidate: the state still fits in `uint16_t`.

The execution tradeoff is different. A complete state-indexed policy table grows from `2^14 = 16,384` entries (16 KB at one byte per verdict) to `2^16 = 65,536` entries (64 KB). The native benchmark tests whether this larger policy table remains useful or crosses a cache boundary.

## Falsification criteria

Capability v0.1 is not evidence for a new processor by itself. It becomes interesting only if at least one of these survives equal-information controls:

- fewer wrong decisions after environmental change;
- fewer external state/history lookups;
- faster recovery to a correct mode;
- lower retained-state cost;
- useful state-indexed execution at realistic table sizes.

If a conventional state machine with the same compact bits and policy table behaves identically, the low-level performance result belongs to the representation/execution technique, while Bardo/Tao remain the semantic organization of that technique.
