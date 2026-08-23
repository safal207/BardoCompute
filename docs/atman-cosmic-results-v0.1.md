# ATMAN Observer + Cosmic Morphology v0.1

## Question

Can the adaptive execution selector improve by importing two ideas from adjacent research layers?

1. **ATMAN-LATTICE-inspired observation discipline**: multiple frozen observation windows, HOLD on disagreement, and post-outcome observer audit/calibration.
2. **Cosmic morphology**: preserve a third environment class between strongly structured and strongly amorphous instead of forcing every regime into a binary branch/LUT choice.

This benchmark intentionally separates inspiration from implementation claims.

- ATMAN-LATTICE contains executable calibration/drift machinery, but this benchmark uses a minimal hot-path observer kernel inspired by those principles rather than importing the full runtime.
- COSMIC-ORGANICS `main` currently contains no executable morphology implementation to import. `STRUCTURED / TRANSITIONAL / AMORPHOUS` is therefore a new BardoCompute engineering abstraction for this experiment.

## Workload

Native C benchmark: `native/atman_cosmic_observer_bench.c`

- 11,796,480 signals
- 90 blocks
- 30 structured blocks
- 30 transitional blocks
- 30 amorphous blocks
- identical Manifest / Acquire / Adapt transition semantics across every execution path

Environment construction:

```text
STRUCTURED
  deterministic four-signal cycle

TRANSITIONAL
  locally structured and locally random regions coexist

AMORPHOUS
  seeded uniform random signal stream
```

The benchmark compares:

1. current fixed-512 binary selector;
2. ATMAN-inspired multi-window binary observer;
3. ATMAN observers + three-way Cosmic morphology;
4. oracle morphology/local-execution ceiling.

## ATMAN observer kernel

Frozen observation windows:

```text
32 -> 128 -> 512 signals
```

The selector may commit at 128 only when the 32- and 128-signal observers agree on a strong extreme. Disagreement is `HOLD`, not failure, and escalates to the longer window.

Observer predictions are audited against resolved workload labels after the fact. Audit does not rewrite the prediction that was made.

## Latest two-runner result

Workflow: `ATMAN Cosmic Observer Benchmark`, run `32491914388`.

### Runner A

| Path | Avg seconds | vs current |
|---|---:|---:|
| Current fixed-512 binary | 0.024825 | 1.000x |
| ATMAN multi-window binary | 0.020686 | **0.833x** |
| ATMAN + Cosmic morphology | 0.023793 | 0.958x |
| Oracle | 0.017675 | 0.712x |

### Runner B

| Path | Avg seconds | vs current |
|---|---:|---:|
| Current fixed-512 binary | 0.019425 | 1.000x |
| ATMAN multi-window binary | 0.016031 | **0.825x** |
| ATMAN + Cosmic morphology | 0.018521 | 0.953x |
| Oracle | 0.013754 | 0.708x |

All paths produced identical transition checksums.

## Observation cost and calibration

Current selector:

```text
90 * 512 = 46,080 observed prefix signals
```

ATMAN multi-window observer:

```text
23,040 observed prefix signals
```

So the multi-window observer uses exactly:

```text
0.500x
```

of the fixed-prefix observation volume in this workload.

Observer audit on both runners:

```text
observer32_accuracy  = 0.667
observer128_accuracy = 1.000
observer512_accuracy = 1.000
```

The useful ATMAN result is therefore not merely a smaller window. Calibration exposes that the shortest observer is insufficient, while the middle observer is sufficient for this constructed workload and avoids paying the full 512-signal observation cost.

Across the latest two hosted runners, ATMAN multi-window execution is about **16.7-17.5% faster** than the current fixed-512 selector while using **half the observation volume** and preserving identical transition semantics.

## Cosmic morphology result

The three-way classifier recovered the intended block counts on both runners:

```text
structured   = 30
transitional = 30
amorphous    = 30
morphology_errors = 0
```

The third class therefore carries information discarded by the old binary selector.

However, the v0.1 transitional executor repeatedly probes local regions before selecting branch or LUT. On the latest two-runner result:

```text
Runner A: ATMAN+Cosmic / ATMAN-only = 1.150x
Runner B: ATMAN+Cosmic / ATMAN-only = 1.155x
```

So Cosmic morphology is currently about **15% slower than ATMAN-only** despite perfect morphology classification. It remains slightly faster than the original fixed-512 selector only because it shares ATMAN's cheaper observation plane.

This is an important negative result: the third morphology is informative, but its current hot execution path does not yet pay for itself.

## Cosmic temporal-coherence sweep

Native control: `native/cosmic_hybrid_sweep.c`

The transitional environment alternates locally structured and locally amorphous regions. We sweep their persistence length:

```text
32 / 64 / 128 / 256 / 512 / 1024 signals
```

For each persistence length, probe-based hybrid execution is compared with:

- branch-only;
- LUT-only;
- oracle local branch/LUT routing;
- multiple probe sizes.

All checksums are identical.

Best measured probe-hybrid / LUT ratio for each coherence length:

| Local coherence | Runner A | Runner B |
|---:|---:|---:|
| 32 | 1.546x | 1.530x |
| 64 | 1.343x | 1.314x |
| 128 | 1.148x | 1.168x |
| 256 | 1.099x | 1.088x |
| 512 | 1.034x | 1.028x |
| 1024 | **1.017x** | **1.007x** |

The shape is reproducible: as local morphology persists longer, the cost of probing is amortized and hybrid execution approaches LUT parity.

But it does **not** beat LUT on either hosted runner, even at 1024-signal persistence.

A local pre-CI run had suggested a hybrid speedup at longer persistence. The two hosted runners did not reproduce it, so that local speedup is **not counted as evidence**.

## Oracle gap

The oracle already knows each local region's morphology and pays no probe/classification cost. Its runtime relative to LUT-only is approximately:

```text
0.72x - 0.80x
```

across the coherence sweep.

That means there is a real execution opportunity in the constructed transitional workload: choosing branch for structured local regions and LUT for amorphous local regions can be roughly 20-28% faster than LUT-only **if routing were free**.

The current probe-hybrid fails to realize that opportunity because observation/routing overhead consumes the gain.

This narrows the Cosmic research problem substantially:

> The bottleneck is no longer whether a transitional morphology contains useful information. It is whether that morphology can be maintained cheaply enough to avoid re-discovering it on every local region.

## Current defensible conclusion

### Supported

```text
ATMAN-style multi-scale observation
    -> 0.5x observation volume
    -> same semantic decisions
    -> ~16.7-17.5% lower runtime on latest two hosted runners
```

### Supported semantically, not yet in speed

```text
Cosmic three-way morphology
    -> exact structured/transitional/amorphous classification
    -> exposes local execution opportunity
```

### Not yet supported

```text
probe-based Cosmic transitional executor
    -> faster execution than ATMAN binary/LUT fallback
```

The hosted evidence rejects that claim for v0.1.

## Revised architecture hypothesis

```text
Bardo temporal trajectory
        ↓
ATMAN observer plane
  short / mid / long evidence
  disagreement -> HOLD
  calibration against later outcome
        ↓
persistent environment morphology M(t)
  STRUCTURED
  TRANSITIONAL
  AMORPHOUS
        ↓
execution policy
  branch / hybrid / LUT
```

The important word is now **persistent**.

Repeatedly probing every local region is too expensive. The next candidate is a morphology register updated online:

```text
M(t+1) = F(M(t), local evidence, confidence, persistent drift)
```

with re-observation triggered only when a cheap drift sentinel accumulates enough evidence.

## Next falsification

Implement a persistent `MorphologyRegister` and compare:

1. LUT-only;
2. fixed per-region probe hybrid;
3. persistent observer hybrid;
4. oracle local routing.

Sweep the same coherence lengths and measure:

- morphology errors;
- local switch count;
- false switches / thrashing;
- observation volume;
- detection lag;
- runtime;
- distance to oracle.

If persistent observer state cannot close the oracle gap, Cosmic morphology should remain a descriptive/control-plane layer rather than enter the hot execution path.
