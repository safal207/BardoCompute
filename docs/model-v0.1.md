# BardoCompute Model v0.1

## Scope

v0.1 deliberately models only stable binary values and directed transitions. It does not yet claim computational advantage and does not yet encode Dragon lifecycle states, Five-Phase operations, discontinuous Bardo, hexagrams, or proof metadata.

## Line algebra

A line belongs to the set:

```text
L = {0, 1, 0->1, 1->0}
```

Each line exposes:

```text
source(L)
target(L)
is_transition(L)
settle(L)
```

with these invariants:

```text
source(0) = target(0) = 0
source(1) = target(1) = 1
source(0->1) = 0
target(0->1) = 1
source(1->0) = 1
target(1->0) = 0
settle(0->1) = 1
settle(1->0) = 0
```

## Dynamic trigram

A dynamic trigram is an ordered tuple of three Bardo lines:

```text
T = (L0, L1, L2)
```

Because each line has four states, the logical state space is:

```text
4^3 = 64 dynamic trigrams
```

This count is a representation property, not evidence of performance benefit.

## Experimental question

The first benchmark asks whether preserving the directed transition produces useful information that a final-value-only baseline does not preserve, and measures the overhead required to retain it.

Measurements begin with:

- final-state equivalence
- transition observability
- runtime
- object memory footprint

## Planned extensions

Future experiments may add, one at a time:

1. continuous vs discontinuous transition classes (Bardo operator)
2. six-line dynamic hexagrams
3. lifecycle-state abstractions inspired by the dragon imagery associated with Qian
4. operation classes inspired by Five-Phase correspondence systems
5. proof/provenance metadata
6. hardware-oriented encodings and finite-state-machine comparisons

Each extension must enter through a benchmarkable hypothesis rather than symbolic analogy alone.
