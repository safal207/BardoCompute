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

Latest Python runs showed the reference Bardo/Tao object model about 1.10-1.12x slower than the independently implemented conventional epoch-aware control. The semantic result, not Python object speed, is the useful result here.

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

## Signal unpredictability changes the best execution path

The deterministic recovery benchmark showed a tiny 12-entry transition LUT about 2.2-2.5x slower than a branch FSM on a perfectly regular capability trajectory.

That result does **not** generalize to stochastic signals.

Native benchmark:

- 12,000,000 pregenerated signals
- 8 repeats
- identical three-mode/four-signal transition semantics
- branch FSM versus the same 12-entry LUT
- RNG excluded from timed loops

The profile names are workload labels. This benchmark does not estimate formal Shannon entropy for each profile; the later adaptive selector uses a conditional next-signal miss proxy as its online predictability measure.

### Runner A

| Signal profile | Branch s | LUT s | LUT / branch | Interpretation |
|---|---:|---:|---:|---|
| 90% HOLD | 0.018957 | 0.018040 | 0.952x | near parity |
| 60% HOLD | 0.055747 | 0.018049 | 0.324x | LUT ~3.09x faster |
| balanced uniform | 0.065133 | 0.018062 | 0.277x | LUT ~3.61x faster |
| shock-heavy, 10% HOLD | 0.062984 | 0.018026 | 0.286x | LUT ~3.49x faster |

### Runner B

| Signal profile | Branch s | LUT s | LUT / branch | Interpretation |
|---|---:|---:|---:|---|
| 90% HOLD | 0.021318 | 0.020617 | 0.967x | near parity |
| 60% HOLD | 0.063214 | 0.020604 | 0.326x | LUT ~3.07x faster |
| balanced uniform | 0.073865 | 0.020604 | 0.279x | LUT ~3.58x faster |
| shock-heavy, 10% HOLD | 0.072000 | 0.020741 | 0.288x | LUT ~3.47x faster |

All branch/LUT checksums were identical.

## Revised execution hypothesis

```text
execution_path = f(
    graph_complexity,
    trajectory_predictability,
    table_locality,
)
```

For this workload:

- small + highly predictable transition stream: branches can dominate;
- highly skewed stochastic stream: branch and LUT approach parity;
- small + less predictable stochastic transition stream: the 12-entry LUT is roughly 3x to 3.6x faster;
- high-dimensional compact temporal policy: a state-indexed LUT is favorable while its table remains within the measured locality budget.

## Online adaptive execution

A mixed native workload tests whether the machine can adapt **how it executes**, not only what capability mode it is in.

Workload:

- 12,582,912 transitions
- 96 blocks of 131,072 transitions
- 48 calm deterministic blocks
- 48 stochastic uniform blocks
- no block-type hint is given to the online selector
- the first 512 signals of each block are executed and observed inside the timed path
- the selector estimates conditional next-signal unpredictability from a 4x4 transition matrix
- then selects branch or LUT execution for the rest of the block

Controls: branch-only, LUT-only, oracle hybrid, and online adaptive selector. All four paths have identical transition semantics and matching checksums.

### Runner A

The online selector classified exactly 48 blocks as branch and 48 as LUT.

- branch-only: `0.039382 s`
- LUT-only: `0.022352 s`
- oracle hybrid: `0.015300 s`
- online adaptive: `0.017175 s`
- adaptive vs branch: `0.436x` time (~2.29x faster)
- adaptive vs LUT: `0.768x` time (~1.30x faster)
- adaptive vs oracle: `1.123x` time (12.3% overhead)

### Runner B

Again, the selector classified exactly 48 branch blocks and 48 LUT blocks.

- branch-only: `0.044883 s`
- LUT-only: `0.025526 s`
- oracle hybrid: `0.019471 s`
- online adaptive: `0.023866 s`
- adaptive vs branch: `0.532x` time (~1.88x faster)
- adaptive vs LUT: `0.935x` time (~1.07x faster)
- adaptive vs oracle: `1.226x` time (22.6% overhead)

The observation/sampling cost is included in the adaptive timings.

### Defensible result

On this deliberately mixed long-regime workload, online predictability-aware execution selection beat **both static execution strategies on both hosted runners**, while remaining within 12-23% of an oracle that knows the future regime.

The gain belongs to generic adaptive selection between equal-semantic branch and LUT implementations. It is not evidence that Bardo/Tao terminology intrinsically accelerates a CPU.

What the Bardo/Tao/trajectory model contributes is the architectural question and the explicit variable being adapted: the execution mechanism becomes a function of observed transition trajectory.

## Current processor hypothesis

```text
trajectory observation
        ↓
conditional predictability / stochasticity
        ↓
execution orientation
        |
        +-- predictable trajectory -> branch path
        |
        +-- stochastic trajectory  -> indexed/LUT path
        ↓
next capability state
```

Equivalently:

```text
ExecutionMode(t+1) = F(Trajectory(t-window...t))
```

This is the first BardoCompute experiment where **adaptation itself changes the execution path** rather than merely changing a semantic state label.

## Important limitation: adaptation timescale

The mixed workload uses long 131,072-transition regimes and a 512-transition observation window. That gives the selector ample time to amortize its observation cost.

The next falsification target is:

```text
tau_environment / tau_adaptation
```

If the environment changes faster than the selector can observe and react, adaptive execution should lose its advantage.

Next sweep:

- regime length: 128 / 512 / 2K / 8K / 32K / 128K transitions
- observation window: 32 / 64 / 128 / 512 transitions
- classification accuracy
- selector lag
- branch-only / LUT-only / oracle / adaptive execution time

## Scope boundary

The stochastic `epoch` is currently side metadata in the reference model. The existing 16-bit temporal-capability hot word does **not** yet contain an unbounded epoch counter. Packing a bounded generation tag into hot state is a separate future experiment and must include wraparound/replay controls before it can be treated as equivalent.
