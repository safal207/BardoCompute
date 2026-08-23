# Tao decision layer v0.1

## Status

Experimental, falsifiable decision/orientation-layer semantics for BardoCompute.

This document uses **Tao** as project terminology for an oriented but unresolved decision state. It is not a claim that historical Daoist texts define ternary computer logic.

## Motivation

Binary decision systems often collapse an unresolved situation into a terminal value too early:

- optimistic mapping: unknown -> allow;
- conservative mapping: unknown -> deny.

Both are lossy when evidence is genuinely incomplete.

BardoCompute already models how a state was reached (direction and continuity). Tao asks two separate questions:

1. Can a downstream decision remain explicitly non-terminal until required evidence arrives?
2. Can that non-terminal state retain **orientation** — what evidence is missing and which future event can settle it?

## Decision alphabet

`ALLOW | DEFER | DENY`

`DEFER` is not a third truth value and does not predict the eventual result. It means no terminal claim should be emitted yet.

## Tao v0.1 — simple defer

Given:

`E = (authority_valid, continuity_preserved, outcome)`

1. invalid authority -> `DENY`;
2. broken continuity -> `DENY`;
3. unresolved outcome -> `DEFER`;
4. resolved success -> `ALLOW`;
5. resolved failure -> `DENY`.

### Forced-binary benchmark

`benchmarks/tao_defer.py` uses 120,000 cases, including 40,000 genuinely unresolved outcomes.

Latest Python 3.12 CI result:

- optimistic binary (`pending -> allow`): **20,000 false allows**;
- conservative binary (`pending -> deny`): **20,000 false denies**;
- Tao: **0 premature false allows**, **0 premature false denies**;
- Tao deferred 40,000 cases and resolved all 40,000 correctly after evidence arrived.

This demonstrates the value of **not forcing an unresolved state into a terminal decision**.

## Equal-information PENDING control

`benchmarks/tao_equal_information_control.py` compares Tao with conventional:

`ALLOW | PENDING | DENY`

Latest Python 3.12 result:

- both pending/deferred: 40,000;
- both errors: 0;
- both resolved correctly: 40,000;
- conventional runtime: `0.035434 s`;
- Tao reference runtime: `0.184187 s`;
- Tao / conventional: **5.198x**.

`semantic_equivalence=true`.

### Verdict

Simple `DEFER` is useful against forced binary terminalization, but it is **not novel computational behavior** compared with an equally informative conventional pending-state machine. The current Python Tao API is also slower.

## Tao v0.2 hypothesis — oriented defer

The stronger form records *why* a decision is unresolved.

Evidence dimensions are encoded as a bit mask:

- `AUTHORITY = 001`
- `CONTINUITY = 010`
- `OUTCOME = 100`

An oriented deferred state therefore carries:

`Tao = (DEFER, missing_evidence_mask)`

Example:

`DEFER + AUTHORITY + OUTCOME`

means that continuity is already known-good, but authority and outcome evidence are still required.

This is implemented by `OrientedTao` / `EvidenceKind` in `src/bardocompute/tao.py`.

## Orientation-routing benchmark

`benchmarks/tao_orientation_routing.py` creates 150,000 deferred records:

- 50,000 waiting for authority;
- 50,000 waiting for continuity;
- 50,000 waiting for outcome.

Then an `OUTCOME` evidence event arrives.

### Plain undifferentiated PENDING queue

- records touched: **150,000**;
- relevant/resolved: 50,000;
- route time: `0.006790 s`.

### Oriented Tao bucket

- records touched: **50,000**;
- relevant/resolved: 50,000;
- touch ratio vs plain queue: **0.333x**;
- index build: `0.425283 s`;
- route time: `0.002339 s`.

### Equal-information conventional indexed PENDING

- records touched: **50,000**;
- relevant/resolved: 50,000;
- index build: `0.145326 s`;
- route time: `0.002257 s`.

`indexed_semantic_equivalence=true`.

### Interpretation

Orientation can reduce event fan-out relative to an undifferentiated pending queue, but this is not Tao-specific. A conventional indexed pending workflow carrying the same missing-evidence metadata achieves the same routing and is cheaper in the current Python reference implementation.

Therefore the defensible result is:

> The useful object is not a mystical third truth value. It is an unresolved state that carries explicit settlement orientation. That orientation can reduce irrelevant reevaluation, but no advantage over an equally informative conventional indexed state machine has yet been shown.

## Separation from Bardo line state

Tao is deliberately **not** a seventh Bardo line state.

The Bardo v0.2 line alphabet remains six semantic states, preserving:

`6^3 = 216`

for the existing trigram experiments.

Tao sits above that representation as a decision/orientation layer.

## Next research target: Bardo + Tao compact record

The next falsifiable hypothesis is to combine transition provenance and settlement orientation without external metadata:

`Record = (source, target, discontinuity, missing_evidence_mask)`

The current fields require:

- 3 logical bits for Bardo transition semantics;
- 3 bits for Tao missing-evidence orientation.

So the combined semantic record fits in **6 logical bits**, leaving two bits free in a byte for future proof/expiry classes or reserved states.

The next benchmark should compare:

1. external transition metadata + external pending index;
2. equally informative conventional packed record;
3. Bardo+Tao 6-bit inline record;
4. group-native/trigram forms of those records.

The critical control remains the same: if an equally informative generic 6-bit record performs identically, the performance property belongs to compact inline representation, not to the Bardo/Tao names.

## Current conclusion

- **Yin/Yang** can remain the settled endpoint distinction.
- **Bardo** represents how the endpoint is being/recently was reached.
- **Tao** is most useful here as settlement orientation: what is still missing before the system may safely collapse to a terminal decision.

That three-layer ontology is worth testing further, but claims remain limited to executable evidence.
