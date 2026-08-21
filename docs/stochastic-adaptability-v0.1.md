# Stochastic Adaptability v0.1

This evidence packet records two findings: correctness of capability adaptation under stochastic disturbance, and predictability-aware adaptation of the execution path itself.

## Semantic workload

Seeded 50,000-episode workload (`0xBADA55`):

- 364,305 total ticks
- 15,053 second environment shocks
- 18,672 premature evidence events
- 8,235 stale old-epoch evidence events
- 24,172 duplicate events
- 7,448 episodes intentionally missing final evidence

| Model | Wrong-mode ticks | Unsafe Manifest ticks | Final false recoveries | Correct-mode rate |
|---|---:|---:|---:|---:|
| Fixed Manifest | 313,210 | 313,210 | 7,448 | 0.140253 |
| Naive three-mode FSM, no epoch/order guard | 83,688 | 35,234 | 0 | 0.770280 |
| Conventional equal-information epoch-aware FSM | 0 | 0 | 0 | 1.000000 |
| Bardo/Tao stochastic capability guard | 0 | 0 | 0 | 1.000000 |

The 7,448 unresolved episodes are intentional: missing final evidence must remain unresolved. Bardo/Tao and the conventional epoch-aware control are semantically equivalent. The Python reference object model is slightly slower; no terminology-based speed claim is made.

```text
StochasticAdaptability = (
    correct_mode_rate,
    unsafe_manifest_rate,
    false_recoveries,
    unresolved_episodes,
    execution_cost,
)
```

## Predictability changes the preferred execution mechanism

The deterministic capability cycle makes a 12-entry transition LUT roughly 2.2x slower than the branch FSM. Less predictable pregenerated inputs reverse that ordering.

Native 12M-signal equal-semantic control, RNG excluded from timed loops:

| Profile | Runner A LUT/branch | Runner B LUT/branch |
|---|---:|---:|
| 90% HOLD | 0.952x | 0.967x |
| 60% HOLD | 0.324x | 0.326x |
| balanced uniform | 0.277x | 0.279x |
| shock-heavy, 10% HOLD | 0.286x | 0.288x |

The benchmark does not claim formal Shannon entropy. The operational variable is trajectory predictability, estimated later with a conditional next-signal miss proxy.

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
- no block label given to the online selector
- first 512 transitions per block are executed and observed inside the timed path
- a 4x4 conditional transition matrix estimates predictability
- branch or LUT is then selected for the remainder

All branch-only, LUT-only, oracle-hybrid, and adaptive paths have identical transition semantics and matching checksums.

### Runner A

The selector chose exactly 48 branch and 48 LUT blocks.

- branch-only `0.039382 s`
- LUT-only `0.022352 s`
- oracle `0.015300 s`
- adaptive `0.017175 s`
- adaptive/branch `0.436x` time (~2.29x faster)
- adaptive/LUT `0.768x` time (~1.30x faster)
- adaptive/oracle `1.123x` time (12.3% overhead)

### Runner B

Again 48 branch and 48 LUT blocks.

- branch-only `0.044883 s`
- LUT-only `0.025526 s`
- oracle `0.019471 s`
- adaptive `0.023866 s`
- adaptive/branch `0.532x` time (~1.88x faster)
- adaptive/LUT `0.935x` time (~1.07x faster)
- adaptive/oracle `1.226x` time (22.6% overhead)

Observation cost is included in adaptive timings.

## Defensible result

On this deliberately mixed long-regime workload, online predictability-aware selection beat both static execution strategies on both hosted runners. The gain belongs to generic adaptive selection between equal-semantic branch and LUT implementations, not to Bardo/Tao naming.

The architectural hypothesis is:

```text
Trajectory(t-window...t)
        ↓
Predictability
        ↓
ExecutionMode(t+1)
        +-- predictable -> branch
        +-- stochastic  -> indexed/LUT
```

This is the first BardoCompute experiment where adaptation changes **how computation is executed** rather than only which semantic state is represented.

## Next falsification: adaptation timescale

The current regime length is 131,072 transitions and the observation window is 512. The next experiment must sweep the ratio:

```text
tau_environment / tau_adaptation
```

Planned regime lengths: 128 / 512 / 2K / 8K / 32K / 128K.
Planned observation windows: 32 / 64 / 128 / 512.

Measure classification accuracy, selector lag, and branch-only / LUT-only / oracle / adaptive runtime. If environment regimes become too short, adaptive execution should eventually lose its advantage.

## Scope boundary

The stochastic `epoch` is currently side metadata. The existing 16-bit temporal-capability hot word does **not** include an unbounded epoch counter. A bounded generation tag requires a separate wraparound/replay experiment.
