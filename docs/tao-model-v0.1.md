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

## Benchmark A — forced binary terminalization

`benchmarks/tao_defer.py` compares three policies on a 120,000-case workload containing 40,000 genuinely unresolved outcomes.

Latest Python 3.12 CI result:

- binary optimistic (`pending -> allow`): **20,000 false allows**, 0 false denies;
- binary conservative (`pending -> deny`): 0 false allows, **20,000 false denies**;
- Tao (`pending -> defer`): **0 premature false allows**, **0 premature false denies**;
- Tao deferred 40,000 cases and resolved all 40,000 correctly after outcome evidence arrived.

Timing in that run:

- optimistic binary: `0.025096 s`;
- conservative binary: `0.024742 s`;
- Tao reference API including second-pass resolution: `0.161669 s`.

### Interpretation

The useful result is semantic, not predictive:

> When an outcome is genuinely unresolved, refusing to emit a terminal decision can avoid the error introduced by forcing unknown into either allow or deny.

The cost is explicit: deferral requires later resolution and the current Python reference implementation is slower.

## Benchmark B — equal-information conventional PENDING control

`benchmarks/tao_equal_information_control.py` compares Tao with a conventional three-state machine:

`ALLOW | PENDING | DENY`

Both implementations receive the same evidence and use the same two-pass resolution semantics.

Latest Python 3.12 CI result:

- conventional pending decisions: 40,000;
- Tao deferred decisions: 40,000;
- errors: 0 for both;
- deferred/pending cases resolved correctly: 40,000 for both;
- conventional runtime: `0.027285 s`;
- Tao runtime: `0.156191 s`;
- Tao / conventional runtime: **5.724x**.

`semantic_equivalence=true` is asserted by the benchmark.

### Verdict

Tao v0.1 has **not** demonstrated a computational advantage over an equally informative conventional `PENDING` state machine.

The defensible claim is narrower:

> Tao is currently a project ontology/API for explicit non-terminal orientation. Its semantic value is the refusal to collapse unresolved evidence into a false terminal claim. That capability is conventional when compared with an explicit pending-state machine, and the current Python Tao API is slower.

This negative control is intentional.

## Research direction

The next useful question is no longer whether `DEFER` is valuable by itself. Conventional systems already know how to represent `PENDING`.

The stronger hypothesis is whether Tao becomes useful when it carries **orientation**, not merely incompleteness. For example, a deferred state may retain:

- which evidence is missing;
- which transitions are still admissible;
- what observation would settle the state;
- an expiry/deadline;
- provenance binding to the Bardo transition that produced the unresolved condition.

A candidate form is:

`Tao = (decision=DEFER, missing_evidence, admissible_edges, settle_condition, deadline, provenance)`

That object should then be compared against an equally informative conventional workflow/state-machine representation.

## Next controls

1. Add a cost function for false allow, false deny, and defer latency.
2. Vary the fraction of unresolved outcomes.
3. Vary time-to-resolution distributions.
4. Add **oriented defer**: encode what evidence can settle the state and what transitions remain legal.
5. Compare oriented Tao against an equally informative conventional pending-workflow record.
6. Only claim performance/compactness if it survives that equal-information control.
