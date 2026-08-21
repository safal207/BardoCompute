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

Research prototype. v0.1 is focused on the smallest executable algebra and a reproducible binary-vs-transition benchmark.
