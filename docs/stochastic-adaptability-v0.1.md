# Stochastic Adaptability v0.1

## Question

How well does the capability trajectory remain correct when the environment and its observations become probabilistic, delayed, duplicated, stale, or out of order?

This document uses **stochastic** in the systems sense: uncertainty/probability in the input process. It does not use the word as a synonym for adaptation.

The measured object is therefore **adaptation under stochastic disturbance**.

## Semantic workload

Seeded workload:

- episodes: 50,000
- seed: `0xBADA55` (`12245589`)
- total ticks: 364,305
- second environment shocks: 15,053
- premature evidence events: 18,672
- stale evidence events from a previous epoch: 8,235
- duplicate events: 24,172
- episodes intentionally missing final evidence: 7,448

The stochastic state adds an environment `epoch`, an `active_shock` marker, and whether the current epoch has observed the required `gap` before accepting `EVIDENCE_READY`.

### Results

| Model | Wrong-mode ticks | Unsafe Manifest ticks | Final false recoveries | Correct-mode rate |
|---|---:|---:|---:|---:|
| Fixed Manifest | 313,210 | 313,210 | 7,448 | 0.140253 |
| Naive three-mode FSM, no epoch/order guard | 83,688 | 35,234 | 0 | 0.770280 |
| Conventional equal-information epoch-aware FSM | 0 | 0 | 0 | 1.000000 |
| Bardo/Tao stochastic capability guard | 0 | 0 | 0 | 1.000000 |

The 7,448 unresolved episodes are intentional: the workload withholds the final evidence, so a correct system must remain unresolved rather than claim recovery.

The Bardo/Tao guard is semantically equivalent to the conventional epoch-aware FSM. This is not evidence of unique mathematics or a speed advantage from terminology.

Python execution was slightly slower for the Bardo/Tao reference object model:

- Python 3.11: guard / conventional = `1.145x`
- Python 3.12: guard / conventional = `1.192x`

The semantic result is therefore the useful result here.

## Stochastic adaptability is a vector

For v0.1 we keep the metric explicit rather than hiding tradeoffs in one score:

```text
StochasticAdaptability = (
    correct_mode_rate,
    unsafe_manifest_rate,
    false_recoveries,
    unresolved_episodes,
    execution_cost,
)
```

A future scalar score may be useful for dashboards, but only after weights and failure costs are justified by a workload.

## Signal entropy changes the best execution path

The deterministic recovery benchmark previously showed a tiny 12-entry transition LUT about `2.2x` slower than a branch FSM on a perfectly regular capability trajectory.

That result does **not** generalize to stochastic signals.

Native benchmark:

- 12,000,000 pregenerated signals
- 8 repeats
- identical three-mode/four-signal transition semantics
- branch FSM versus the same 12-entry LUT
- RNG excluded from timed loops

### Runner A

| Signal profile | Branch s | LUT s | LUT / branch | Interpretation |
|---|---:|---:|---:|---|
| 90% HOLD | 0.023848 | 0.023307 | 0.977x | near parity |
| 60% HOLD | 0.074660 | 0.023274 | 0.312x | LUT ~3.21x faster |
| balanced uniform | 0.083664 | 0.023244 | 0.278x | LUT ~3.60x faster |
| shock-heavy, 10% HOLD | 0.081040 | 0.023223 | 0.287x | LUT ~3.49x faster |

### Runner B

| Signal profile | Branch s | LUT s | LUT / branch | Interpretation |
|---|---:|---:|---:|---|
| 90% HOLD | 0.020788 | 0.020627 | 0.992x | near parity |
| 60% HOLD | 0.063448 | 0.020605 | 0.325x | LUT ~3.08x faster |
| balanced uniform | 0.075284 | 0.020609 | 0.274x | LUT ~3.65x faster |
| shock-heavy, 10% HOLD | 0.073960 | 0.020633 | 0.279x | LUT ~3.58x faster |

All branch/LUT checksums were identical.

## Revised execution hypothesis

The earlier rule

```text
small graph -> branch FSM
large/high-dimensional graph -> LUT
```

is too simple.

The evidence now supports a stronger hypothesis:

```text
execution_path = f(
    graph_complexity,
    signal_predictability / entropy,
    table_locality,
)
```

For this workload:

- small + highly predictable transition stream: branch and LUT are competitive, and the deterministic cyclic case strongly favored branches;
- small + stochastic/high-entropy transition stream: the 12-entry LUT is roughly 3x to 3.6x faster;
- high-dimensional compact temporal policy: a state-indexed LUT is already favorable while its table remains within the measured locality budget.

## New processor hypothesis

The execution mechanism itself may be adaptive:

```text
low transition entropy  -> predictable branch path
high transition entropy -> branchless/indexed path
```

This is not yet proven end-to-end because the cost of estimating entropy and switching modes has not been included.

The next falsification test is therefore a mixed workload with calm and stochastic phases, comparing:

1. branch-only,
2. LUT-only,
3. online adaptive branch/LUT selection.

The adaptive selector only wins if its measurement and switching overhead are smaller than the losses avoided in each regime.
