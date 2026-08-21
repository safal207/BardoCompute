# Stochastic Adaptability v0.1

## Question

How well does the capability trajectory remain correct when the environment and its observations become probabilistic, delayed, duplicated, stale, or out of order?

**Stochastic** is used here in the systems sense: uncertainty/probability in the input process, not as a synonym for adaptation. The measured object is **adaptation under stochastic disturbance**.

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

| Model | Wrong-mode ticks | Unsafe Manifest ticks | Final false recoveries | Correct-mode rate |
|---|---:|---:|---:|---:|
| Fixed Manifest | 313,210 | 313,210 | 7,448 | 0.140253 |
| Naive three-mode FSM, no epoch/order guard | 83,688 | 35,234 | 0 | 0.770280 |
| Conventional equal-information epoch-aware FSM | 0 | 0 | 0 | 1.000000 |
| Bardo/Tao stochastic capability guard | 0 | 0 | 0 | 1.000000 |

The 7,448 unresolved episodes are intentional: final evidence is withheld, so a correct system must remain unresolved rather than claim recovery.

The Bardo/Tao guard is semantically equivalent to the conventional epoch-aware FSM. Latest Python runs put the reference Bardo/Tao object model about 1.10-1.12x slower than the independent conventional control. The useful result here is semantic correctness under disturbance, not Python object speed.

## Stochastic adaptability metric

```text
StochasticAdaptability = (
    correct_mode_rate,
    unsafe_manifest_rate,
    false_recoveries,
    unresolved_episodes,
    execution_cost,
)
```

A scalar score would require justified workload-specific weights.

## Signal unpredictability changes the best execution path

A perfectly regular capability trajectory previously made a tiny 12-entry transition LUT about 2.2-2.5x slower than a branch FSM. That result does not generalize to less predictable input.

Native equal-semantic workload: 12,000,000 pregenerated signals, 8 repeats, RNG excluded from timed loops. The profile names are workload labels; this test does not compute formal Shannon entropy. The later online selector uses a conditional next-signal miss proxy.

### Runner A

| Profile | Branch s | LUT s | LUT / branch |
|---|---:|---:|---:|
| 90% HOLD | 0.018957 | 0.018040 | 0.952x |
| 60% HOLD | 0.055747 | 0.018049 | 0.324x |
| balanced uniform | 0.065133 | 0.018062 | 0.277x |
| shock-heavy, 10% HOLD | 0.062984 | 0.018026 | 0.286x |

### Runner B

| Profile | Branch s | LUT s | LUT / branch |
|---|---:|---:|---:|
| 90% HOLD | 0.021318 | 0.020617 | 0.967x |
| 60% HOLD | 0.063214 | 0.020604 | 0.326x |
| balanced uniform | 0.073865 | 0.020604 | 0.279x |
| shock-heavy, 10% HOLD | 0.072000 | 0.020741 | 0.288x |

All branch/LUT checksums were identical.

```text
execution_path = f(
    graph_complexity,
    trajectory_predictability,
    table_locality,
)
```

## Online adaptive execution

Mixed workload:

- 12,582,912 transitions
- 96 blocks × 131,072 transitions
- 48 calm deterministic blocks
- 48 stochastic uniform blocks
- no block-type hint supplied to the selector
- first 512 transitions per block are executed and observed inside the timed path
- conditional next-signal predictability is estimated with a 4x4 transition matrix
- selector chooses branch or LUT for the remainder

Controls: branch-only, LUT-only, future-informed oracle hybrid, and online adaptive selector. All paths have identical transition semantics and matching checksums.

### Runner A

Selector chose exactly 48 branch and 48 LUT blocks.

- branch-only: `0.039382 s`
- LUT-only: `0.022352 s`
- oracle: `0.015300 s`
- adaptive: `0.017175 s`
- adaptive / branch: `0.436x` time (~2.29x faster)
- adaptive / LUT: `0.768x` time (~1.30x faster)
- adaptive / oracle: `1.123x` time (12.3% overhead)

### Runner B

Selector again chose exactly 48 branch and 48 LUT blocks.

- branch-only: `0.044883 s`
- LUT-only: `0.025526 s`
- oracle: `0.019471 s`
- adaptive: `0.023866 s`
- adaptive / branch: `0.532x` time (~1.88x faster)
- adaptive / LUT: `0.935x` time (~1.07x faster)
- adaptive / oracle: `1.226x` time (22.6% overhead)

Observation cost is included in adaptive timings.

## Defensible result

On this deliberately mixed long-regime workload, online predictability-aware selection beat **both static execution strategies on both hosted runners**, while remaining within 12-23% of an oracle that knows the future regime.

The speed gain belongs to generic adaptation between equal-semantic branch and LUT implementations. It is not evidence that Bardo/Tao terminology intrinsically accelerates a CPU.

```text
Trajectory(t-window...t)
        ↓
Predictability
        ↓
ExecutionMode(t+1)
        |
        +-- predictable -> branch
        +-- stochastic  -> indexed/LUT
```

This is the first BardoCompute experiment where adaptation changes **how computation is executed**, not only the semantic mode being represented.

## Next falsification: adaptation timescale

```text
tau_environment / tau_adaptation
```

The current 131,072-transition regimes are long relative to the 512-transition observation window. Sweep regime length 128 / 512 / 2K / 8K / 32K / 128K and observation window 32 / 64 / 128 / 512 to locate the break-even point.

## Scope boundary

The stochastic `epoch` is currently side metadata. The 16-bit temporal-capability hot word does **not** contain an unbounded epoch counter. A bounded generation tag is a separate future experiment requiring explicit wraparound and replay controls.
