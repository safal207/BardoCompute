# Tao decision layer v0.1

## Status

Experimental, falsifiable decision-layer semantics for BardoCompute.

This document uses **Tao** as project terminology for an oriented but unresolved decision state. It is not a claim that historical Daoist texts define ternary computer logic.

## Motivation

Binary decision systems often collapse an unresolved situation into a terminal value too early:

- optimistic mapping: unknown -> allow;
- conservative mapping: unknown -> deny.

Both are lossy when the evidence is genuinely incomplete.

BardoCompute already models how a state was reached (direction and continuity). Tao v0.1 asks a separate question:

> Can a downstream decision remain explicitly non-terminal until the evidence required for a terminal decision arrives?

## Decision alphabet

`ALLOW | DEFER | DENY`

`DEFER` is not a third truth value and does not predict the eventual result. It means:

- current authority is still valid;
- continuity is preserved;
- the outcome required to settle the decision is not yet known;
- no terminal claim should be emitted yet.

## Minimal rule

Given evidence:

`E = (authority_valid, continuity_preserved, outcome)`

where `outcome in {true, false, unresolved}`:

1. invalid authority -> `DENY`;
2. broken continuity -> `DENY`;
3. unresolved outcome -> `DEFER`;
4. resolved success -> `ALLOW`;
5. resolved failure -> `DENY`.

## Separation from Bardo line state

Tao v0.1 is deliberately **not** added as a seventh line state.

The Bardo v0.2 line alphabet remains six semantic states, so the existing trigram experiment remains:

`6^3 = 216`

Tao sits above the line/trigram representation as a decision/orientation layer. This isolates its utility and cost from the state-density experiments.

## Falsification benchmark

`benchmarks/tao_defer.py` compares three policies on the same workload:

- binary optimistic: unresolved -> allow;
- binary conservative: unresolved -> deny;
- Tao: unresolved -> defer, then resolve after evidence arrives.

Metrics:

- false allows;
- false denies;
- number of deferred decisions;
- correctness after deferred resolution;
- execution time.

The intended claim is narrow:

> If the environment contains genuinely unresolved outcomes, a non-terminal decision state can avoid premature false allow/deny decisions by paying a deferral/latency cost.

This is not evidence that three-valued logic is new, nor that Tao is universally faster than binary logic.

## Next controls

1. Add a cost function for false allow, false deny, and defer latency.
2. Vary the fraction of unresolved outcomes.
3. Vary time-to-resolution distributions.
4. Compare against conventional explicit `PENDING` state machines.
5. Test whether Tao provides any implementation advantage over an equally informative conventional `ALLOW/PENDING/DENY` baseline. If not, retain Tao only as project ontology rather than a performance claim.
