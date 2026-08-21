# Benchmark packet — BardoCompute v0.2

Commit under test: `926c849547fb7d515d4d782f63ea95aef937f665`

CI matrix:

- Python 3.11.16 / Ubuntu 24.04
- Python 3.12.14 / Ubuntu 24.04

Both jobs completed successfully with `9 passed`.

## Benchmark A — transition-aware object vs endpoint-only binary

This benchmark is intentionally asymmetric. The endpoint-only binary baseline carries less information, so it is useful only as a lower-bound cost reference.

### Python 3.12

- binary: `0.003633 s`
- Bardo: `0.278571 s`
- speed ratio: `76.681x` slower
- shallow object size: binary `28 B`, Bardo `48 B`

### Python 3.11

- binary: `0.002849 s`
- Bardo: `0.413664 s`
- speed ratio: `145.195x` slower
- shallow object size: binary `28 B`, Bardo `48 B`

### Verdict

No speed advantage. This result must not be used to claim a processor performance win.

The comparison mainly quantifies the software-object overhead of preserving transition semantics in the current Python reference implementation.

## Benchmark B — continuity semantics vs equivalent metadata

This is the more important v0.2 comparison because both the ordinary baseline and Bardo carry equivalent logical information.

The workload contains four distinguishable transition histories:

- `0 -> 1 continuous`
- `0 -> 1 discontinuous`
- `1 -> 0 continuous`
- `1 -> 0 discontinuous`

Endpoint-only binary state collapses these to two terminal classes. Both binary+metadata and Bardo v0.2 preserve all four.

### Python 3.12

| representation | time | shallow object size | distinguishable classes |
| --- | ---: | ---: | ---: |
| endpoint-only binary | `0.006667 s` | `28 B` | 2 |
| binary + tuple metadata | `0.015962 s` | `64 B` | 4 |
| Bardo v0.2 | `0.170657 s` | `48 B` | 4 |

Observed ratios:

- utility vs endpoint-only: `2.000x` distinguishable histories
- Bardo speed cost vs equivalent tuple: `10.691x`
- Bardo shallow object size vs tuple: `0.750x`

### Python 3.11

| representation | time | shallow object size | distinguishable classes |
| --- | ---: | ---: | ---: |
| endpoint-only binary | `0.005124 s` | `28 B` | 2 |
| binary + tuple metadata | `0.013086 s` | `64 B` | 4 |
| Bardo v0.2 | `0.277496 s` | `48 B` | 4 |

Observed ratios:

- utility vs endpoint-only: `2.000x` distinguishable histories
- Bardo speed cost vs equivalent tuple: `21.206x`
- Bardo shallow object size vs tuple: `0.750x`

## Interpretation

### What v0.2 proves

The executable model can represent a distinction that a terminal bit or a direction-only transition does not preserve: two transitions with identical endpoints but different continuity semantics.

### What v0.2 does not prove

It does not prove that BardoCompute is faster, smaller, more energy efficient, or superior to ordinary metadata representations.

The current Python implementation is substantially slower than a plain tuple carrying equivalent information.

The `sys.getsizeof` numbers are shallow object sizes only. They do not represent deep memory usage and should not be treated as a hardware-memory result.

## Next falsification test

The next benchmark should ask whether first-class continuity prevents a real downstream cost.

Candidate workload: a recovery/dispatch guard in which execution may continue only after a causally continuous transition.

Compare:

1. endpoint-only state with no provenance — fast but incorrect on broken-continuity cases;
2. endpoint-only state plus an external metadata lookup — correct with lookup cost;
3. Bardo transition carrying continuity inline — correct without external reconstruction.

The useful question is not whether Bardo carries more information. The useful question is whether carrying that information at the transition boundary reduces total system work or prevents invalid actions.
