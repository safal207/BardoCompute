# Policy LUT Locality Sweep v0.1

## Question

How large can a one-byte state-indexed policy table become before randomized access starts paying a clear locality/cache penalty?

This benchmark is deliberately generic. It does **not** encode Bardo, Tao, trigram, or capability semantics. It isolates the execution technique used by `TemporalState16` and `CapabilityTemporalState16`.

## Workload

- 8,000,000 lookups per scan
- 6 repeated scans
- one byte per policy entry
- table sizes from 4 KB through 8 MB
- two access patterns:
  - sequential/state-local access
  - precomputed pseudo-randomized state access
- alternating measurement order after warmup

The current `CapabilityTemporalState16` policy table is 64 KB (`2^16` one-byte verdicts).

## Runner A — Python 3.11 job / Ubuntu 24.04

| State bits | Table | Sequential s | Randomized s | Random / sequential |
|---:|---:|---:|---:|---:|
| 12 | 4 KB | 0.003743 | 0.005197 | 1.388x |
| 13 | 8 KB | 0.003818 | 0.005056 | 1.324x |
| 14 | 16 KB | 0.003830 | 0.005070 | 1.324x |
| 15 | 32 KB | 0.003735 | 0.005073 | 1.358x |
| 16 | 64 KB | 0.003757 | 0.005056 | 1.346x |
| 17 | 128 KB | 0.003956 | 0.005133 | 1.297x |
| 18 | 256 KB | 0.003789 | 0.005381 | 1.420x |
| 19 | 512 KB | 0.003782 | 0.007286 | 1.926x |
| 20 | 1 MB | 0.003760 | 0.008492 | 2.259x |
| 21 | 2 MB | 0.003743 | 0.008838 | 2.361x |
| 22 | 4 MB | 0.003767 | 0.009056 | 2.404x |
| 23 | 8 MB | 0.003778 | 0.009431 | 2.496x |

## Runner B — Python 3.12 job / Ubuntu 24.04

| State bits | Table | Sequential s | Randomized s | Random / sequential |
|---:|---:|---:|---:|---:|
| 12 | 4 KB | 0.003732 | 0.005146 | 1.379x |
| 13 | 8 KB | 0.003748 | 0.005087 | 1.357x |
| 14 | 16 KB | 0.003750 | 0.005087 | 1.357x |
| 15 | 32 KB | 0.003841 | 0.005062 | 1.318x |
| 16 | 64 KB | 0.003743 | 0.005318 | 1.421x |
| 17 | 128 KB | 0.003753 | 0.005133 | 1.367x |
| 18 | 256 KB | 0.003768 | 0.005235 | 1.389x |
| 19 | 512 KB | 0.003766 | 0.007093 | 1.883x |
| 20 | 1 MB | 0.003780 | 0.007968 | 2.108x |
| 21 | 2 MB | 0.003745 | 0.008403 | 2.244x |
| 22 | 4 MB | 0.003739 | 0.008687 | 2.323x |
| 23 | 8 MB | 0.003874 | 0.009130 | 2.357x |

## Reproduced boundary

Both runners show the same qualitative shape:

1. **4–256 KB:** randomized access is relatively flat, roughly 1.3–1.4x the sequential scan.
2. **512 KB:** a clear first step appears, roughly 1.88–1.93x sequential.
3. **1 MB and above:** randomized lookup settles above roughly 2.1x sequential and continues degrading gradually through 8 MB.
4. Sequential access remains nearly flat across the full range because locality/prefetching can hide table growth in this workload.

This benchmark does not identify a specific hardware cache level because GitHub hosted runner CPU details and scheduling can vary. It does provide a reproducible **workload-level locality boundary around 512 KB** on these two runs.

## Implication for CapabilityTemporalState16

The current complete 16-bit policy table is:

```text
2^16 entries × 1 byte = 64 KB
```

That is well below the observed 512 KB randomized-access step. Therefore the capability extension that filled bits 14..15 did **not** push the current architecture near the measured policy-locality cliff.

This does not mean state bits are free. Full LUT size doubles with every new bit:

```text
16 bits = 64 KB
17 bits = 128 KB
18 bits = 256 KB
19 bits = 512 KB  <- first clear randomized-access step here
20 bits = 1 MB
```

So a naive monolithic LUT becomes increasingly unattractive around 19+ bits in this workload.

## Architectural consequence

The next semantic layer should not automatically widen a single monolithic policy index.

A stronger candidate is a hierarchical execution path:

```text
hot temporal-capability word
        ↓
small first-stage policy
        ↓ only when needed
cold/context extension
```

This keeps the common path near the current 64 KB policy budget while allowing future Dragon/lifecycle, operation-class, or richer capability information to live outside the first-stage index.

## Defensible conclusion

The measured result belongs to generic state-indexed execution and cache/locality behavior, not to Bardo/Tao terminology.

For the current BardoCompute design, however, it gives a concrete engineering constraint:

> **16 bits / 64 KB is comfortably below the first reproduced randomized-policy locality step; blindly expanding toward 19+ indexed bits is likely to pay a meaningful access cost.**
