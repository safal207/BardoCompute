# ATMAN Observer + Cosmic Morphology v0.1

## Question

Can the adaptive execution selector improve by importing two ideas from adjacent research layers?

1. **ATMAN-LATTICE-inspired observation discipline**: multiple frozen observation windows, HOLD on disagreement, and post-outcome observer audit/calibration.
2. **Cosmic morphology**: preserve a third environment class between strongly structured and strongly amorphous instead of forcing every regime into a binary branch/LUT choice.

This benchmark intentionally separates inspiration from implementation claims.

- ATMAN-LATTICE contains executable calibration/drift machinery, but this benchmark uses only a minimal observer kernel inspired by those principles rather than importing the full runtime.
- COSMIC-ORGANICS `main` currently contains no executable morphology implementation to import. `STRUCTURED / TRANSITIONAL / AMORPHOUS` is therefore a new BardoCompute engineering abstraction for this experiment.

## Workload

Native C benchmark: `native/atman_cosmic_observer_bench.c`

- 11,796,480 signals
- 90 blocks
- 30 structured blocks
- 30 transitional blocks
- 30 amorphous blocks
- six-block regime persistence
- identical Manifest / Acquire / Adapt transition semantics across every execution path

Environment construction:

```text
STRUCTURED
  deterministic four-signal cycle

TRANSITIONAL
  locally structured and locally random 64-signal regions coexist

AMORPHOUS
  seeded uniform random signal stream
```

The benchmark compares:

1. current fixed-512 binary selector;
2. ATMAN-inspired multi-window binary observer;
3. ATMAN observers + three-way Cosmic morphology;
4. oracle morphology/local-execution ceiling.

## ATMAN observer kernel

Three frozen windows are evaluated:

```text
32 -> 128 -> 512 signals
```

The selector may commit at 128 only when the 32- and 128-signal observers agree on a strong extreme. Disagreement is treated as `HOLD`, not failure, and forces the 512-signal observation.

Observer predictions are audited against resolved workload labels after the fact. Audit does not rewrite the prediction that was made, matching the ATMAN calibration principle that observer error should be measurable without silently rewriting history.

## Reproduced results

### Runner A

| Path | Avg seconds | vs current |
|---|---:|---:|
| Current fixed-512 binary | 0.025385 | 1.000x |
| ATMAN multi-window binary | 0.018706 | **0.737x** |
| ATMAN + Cosmic morphology | 0.023660 | 0.932x |
| Oracle | 0.017183 | 0.677x |

### Runner B

| Path | Avg seconds | vs current |
|---|---:|---:|
| Current fixed-512 binary | 0.024687 | 1.000x |
| ATMAN multi-window binary | 0.018974 | **0.769x** |
| ATMAN + Cosmic morphology | 0.023467 | 0.951x |
| Oracle | 0.016911 | 0.685x |

All paths produced identical transition checksums.

## Observation cost

Current selector:

```text
90 * 512 = 46,080 observed prefix signals
```

ATMAN multi-window observer:

```text
23,040 observed prefix signals
```

So the multi-window observer used exactly:

```text
0.500x
```

of the fixed-prefix observation volume in this workload.

The 32-signal observer alone was not reliable enough:

```text
observer32_accuracy = 0.667
```

The 128-signal observer was sufficient on this constructed workload:

```text
observer128_accuracy = 1.000
```

The 512-signal observer also produced:

```text
observer512_accuracy = 1.000
```

This is the useful ATMAN result: calibration exposes that the shortest observer is cheaper but systematically misses the transitional class, while the mid-scale observer is both cheaper than the old fixed window and sufficient here.

## Cosmic morphology result

The three-way classifier recovered the exact intended block counts on both runners:

```text
structured   = 30
transitional = 30
amorphous    = 30
morphology_errors = 0
```

So the third class carries real information that the old binary selector discards.

However, the v0.1 `TRANSITIONAL` execution path is not efficient enough.

It performs repeated local probing inside the block before choosing branch or LUT for each local region. That added observation/dispatch overhead means:

### Runner A

```text
ATMAN+Cosmic / ATMAN-only = 1.265x
```

### Runner B

```text
ATMAN+Cosmic / ATMAN-only = 1.237x
```

Therefore **Cosmic morphology improves description/classification but does not yet improve execution speed over the simpler ATMAN binary observer**.

It remains modestly faster than the original fixed-512 selector in this workload because it shares the cheaper ATMAN observation plane, not because its hybrid path is faster.

## Current defensible conclusion

### Supported

```text
ATMAN-style multi-scale observation
    -> lower observation volume
    -> lower selector runtime
```

On two hosted runners, the ATMAN-inspired selector is about **23-26% faster** than the old fixed-512 selector while choosing the same binary execution paths.

### Not yet supported

```text
Cosmic transitional morphology
    -> faster execution
```

The morphology is recovered perfectly in the constructed workload, but the first hybrid executor is about **24-27% slower than ATMAN-only**.

This is an execution-policy problem, not a classification failure.

## Revised architecture hypothesis

```text
Bardo temporal trajectory
        ↓
ATMAN observer plane
  short / mid / long windows
  disagreement -> HOLD
  post-outcome calibration
        ↓
Cosmic morphology
  STRUCTURED
  TRANSITIONAL
  AMORPHOUS
        ↓
execution policy
```

The first two execution mappings are already supported:

```text
STRUCTURED -> branch
AMORPHOUS  -> LUT
```

The unresolved research target is:

```text
TRANSITIONAL -> ?
```

A fixed probe-every-64 hybrid is too expensive.

## Next falsification

Replace fixed local probing with **event-triggered re-observation**:

```text
current execution path
      ↓
cheap prediction-error / drift sentinel
      ↓ only when drift accumulates
ATMAN short observer
      ↓ if disagreement persists
ATMAN mid/long observer
      ↓
switch local execution mode
```

This directly reuses the ATMAN distinction:

```text
single drift signal != persistent drift
```

The hypothesis is that transitional morphology becomes useful only if the observer cost is paid on detected change boundaries rather than continuously.

Measure:

- local switch count;
- false switches / thrashing;
- observation signals;
- detection lag;
- total runtime;
- distance to oracle.

If event-triggered observation cannot close the gap, Cosmic morphology should remain a descriptive layer and not enter the hot execution path.
