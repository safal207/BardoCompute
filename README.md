# BardoCompute

**Experimental transition-state computing inspired by the Book of Changes.**

BardoCompute asks a narrow engineering question:

> Can transition itself be treated as first-class computational information rather than discarded as an intermediate state?

The project separates three layers deliberately:

1. **Historical source model** — yin/yang lines, trigrams, hexagrams, changing lines, and selected transformation imagery from the *Book of Changes*.
2. **Bardo transition model** — a new computational interpretation of stable, continuous-transition, and discontinuous-transition states. This is an engineering construct, not a historical claim about the *I Ching*.
3. **Benchmarks** — executable comparisons against ordinary binary/state-machine baselines.

## v0.1 hypothesis

A conventional bit records a stable value:

```text
0 | 1
```

A Bardo line records stable values plus directed transition:

```text
0
1
0 -> 1
1 -> 0
```

The first experiments test whether retaining transition state provides measurable utility in provenance, recovery, event processing, or verification — and what it costs in memory, operations, and runtime.

## Benchmark axes

- **Utility** — useful state information retained
- **Proof** — ability to explain/reconstruct state origin
- **Cost** — memory and operation overhead
- **Speed** — execution time / throughput

## Hardware track

`BARDO-TX1` is the first synthesizable execution boundary. It is a
parameterized streaming coprocessor for three-line transition groups, not a
claim that BardoCompute already replaces a general-purpose CPU.

The hardware slice validates the six legal packed line states, fails closed on
reserved codes, emits the dense radix-6 trigram index, settles target states,
exposes transition features, and evaluates the existing joint reference
policy. See [`docs/hardware-v0.1.md`](docs/hardware-v0.1.md).

Any CPU-competition claim must beat the fastest equal-information CPU baseline
end to end, including memory and host/device interface costs.

Current CI produces exact-SHA-bound implementation artifacts and deliberately
stops at `CORE_ROOFLINE_ONLY` with `claim_allowed=false`. Its self-produced
checksum manifests verify listed pre-gate bytes; they are not signatures or
standalone source-provenance attestations. No physical-board result or
CPU-competitive result is claimed.

## Roadmap

```text
Bit
 -> Bardo Line
 -> Dynamic Trigram
 -> Benchmark
 -> Dynamic Hexagram
 -> Dragon lifecycle experiments
 -> Five-phase operation experiments
 -> Processor / accelerator architecture hypotheses
```

## Scientific boundary

BardoCompute uses traditional symbolic systems as inspiration for formal transition models. Claims of computational advantage require executable evidence. Symbolic analogy alone is not treated as proof.

## Status

Research prototype. The repository contains the original executable algebra,
software/native falsification experiments, and a first synthesizable hardware
slice. FPGA frequency, power, area, and CPU speedup remain unclaimed until
measured.
