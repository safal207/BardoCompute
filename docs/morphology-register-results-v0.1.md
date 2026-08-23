# Persistent Morphology Register v0.1

## Question

The first Cosmic transitional executor proved that local environment morphology can contain useful execution information, but repeated per-region probing consumed the gain.

This experiment asks a narrower question:

> Can the system retain the last accepted local morphology and pay only a cheap drift-sentinel cost, rather than re-discovering morphology from scratch on every local region?

The register is deliberately not given true region boundaries.

## Model

Inside a top-level `TRANSITIONAL` environment, the local morphology register is:

```text
M_local(t) in {STRUCTURED, AMORPHOUS}
```

Execution mapping:

```text
STRUCTURED -> branch FSM
AMORPHOUS  -> LUT
```

The register persists across intervals.

A cheap sentinel examines the last eight adjacent signal transitions in each observation interval:

- strong structured evidence -> propose `STRUCTURED`;
- strong amorphous evidence -> propose `AMORPHOUS`;
- ambiguous evidence -> `HOLD` and preserve the current register.

So:

```text
single ambiguous observation != mutation authority
```

This is an ATMAN-inspired drift/governance rule applied to a hot execution state.

## Workload

Native control: `native/morphology_register_bench.c`

- 12,000,000 signals
- 8 repeats
- alternating locally structured / locally amorphous regions
- local coherence lengths: `32 / 64 / 128 / 256 / 512 / 1024`
- register observation intervals: `16 / 32 / 64 / 128` where applicable
- identical Manifest / Acquire / Adapt transition semantics across every execution path

Compared paths:

1. LUT-only;
2. boundary-aware fixed probe control;
3. persistent morphology register, with no boundary labels;
4. oracle local routing.

All transition checksums are identical.

## Reproduced crossover

The important result is a regime-length crossover.

Best persistent-register / LUT ratio by coherence length on the final two-runner run:

| Local coherence | Runner A | Runner B | Result |
|---:|---:|---:|---|
| 32 | 1.517x | 1.486x | register loses |
| 64 | 1.247x | 1.164x | register loses |
| 128 | 1.016x | 1.028x | near boundary, still loses |
| 256 | **0.914x** | **0.961x** | register begins to win |
| 512 | **0.862x** | **0.881x** | 11.9-13.8% faster |
| 1024 | **0.818x** | **0.838x** | 16.2-18.2% faster |

The winner changes between coherence 128 and 256 in this workload.

This is the first hosted-CI result where persistent Cosmic morphology produces a reproducible hot-path speed advantage over the static LUT fallback.

The claim is strictly workload-scoped. It does not imply universal benefit from a morphology register.

## Best 1024-signal operating point

For `coherence=1024` and `interval=32`:

### Runner A

```text
LUT-only                 0.024363 s
persistent register      0.019921 s
oracle                    0.017024 s
register / LUT            0.818x
true boundary detections  11,718
false switches            79
wrong interval rate       0.031891
mean true detection lag   32.44 signals
```

### Runner B

```text
LUT-only                 0.021299 s
persistent register      0.017848 s
oracle                    0.013857 s
register / LUT            0.838x
true boundary detections  11,718
false switches            79
wrong interval rate       0.031891
mean true detection lag   32.44 signals
```

The false-switch count is tiny relative to the number of real boundaries while the register still adapts after roughly one 32-signal observation interval.

## Oracle-gap closure

The oracle pays no morphology-discovery cost.

At `coherence=1024, interval=32`:

### Runner A

```text
available LUT -> oracle gap  = 0.024363 - 0.017024 = 0.007339 s
register improvement         = 0.024363 - 0.019921 = 0.004442 s
fraction of oracle gap closed ~= 60.5%
```

### Runner B

```text
available LUT -> oracle gap  = 0.021299 - 0.013857 = 0.007442 s
register improvement         = 0.021299 - 0.017848 = 0.003451 s
fraction of oracle gap closed ~= 46.4%
```

So the persistent register realizes roughly **46-61% of the available oracle routing opportunity** at the longest tested coherence length.

There remains substantial headroom.

## Why the crossover matters

The result suggests a temporal condition rather than a universal morphology claim:

```text
tau_morphology / tau_observation
```

If morphology changes too quickly, the system spends too much time observing or using stale execution mode.

If morphology persists long enough, retained observer state amortizes its update cost and the local execution choice becomes useful.

In this workload:

```text
coherence <= 128  -> persistent register does not pay
coherence >= 256  -> persistent register begins to pay
```

This is closely related to the broader BardoCompute adaptation-timescale question:

```text
tau_environment / tau_adaptation
```

## Important control result

The boundary-aware fixed-probe control is still faster than the persistent register at the long coherence lengths because it is given extra information: exact local region boundaries.

That comparison is useful as another upper bound, not as a fair deployable baseline.

The persistent register's important property is that it receives no boundary labels and nevertheless beats LUT-only once morphology persists long enough.

## Revised architecture

```text
Bardo temporal trajectory
        ↓
ATMAN calibrated observation
        ↓
Cosmic top-level morphology
        ↓
persistent local MorphologyRegister
        │
        ├─ ambiguous evidence -> HOLD
        └─ persistent drift -> switch
        ↓
branch / LUT execution
```

The operational interpretation is now stronger:

> **Do not repeatedly infer a stable property of the environment from scratch. Keep the last evidence-backed morphology as hot state and revise it only when drift evidence is strong enough.**

## Next falsification

The current sentinel is hand-designed for this constructed signal process. The next tests should attack that assumption:

1. randomize region lengths rather than alternate fixed coherence;
2. use gradual drift instead of clean structured/amorphous boundaries;
3. add bursts that mimic a regime change but revert quickly;
4. vary sentinel size and decision thresholds;
5. compare one-vote switching with persistent multi-vote confirmation;
6. measure false switches, detection lag, runtime, and oracle-gap closure;
7. test whether the register still wins when the transition statistics are not the same ones used to design the sentinel.

If the advantage disappears under those controls, the current result is a specialized predictor optimization rather than a general morphology-state architecture.
