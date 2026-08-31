# BARDO LOGOS tree v0.2 — comparison protocol

## Hypothesis

`1 + 1 = n` is treated as a computing contract, not as replacement arithmetic:
two bounded child states can derive several reusable facts, after which the
facts are selected and compressed into one bounded parent word.

For this experiment, every parent remains a fixed 128-bit logical word:

- one 64-bit ordered root;
- span length;
- valid and invalid lane counts;
- transition and discontinuity counts;
- total target count;
- policy-allow count;
- consequential-lane count.

The first target is not to prove that a software tree is faster than a flat CPU
loop. The target is to measure the price of order-sensitive evidence and to
separate three possible advantages:

1. fixed output width instead of one 23-bit result per lane;
2. logarithmic parallel dependency depth;
3. detection of lane/input permutations that a commutative XOR cannot detect.

## Compared paths

| Path | Ordered | Output | Dependency depth for 71 lanes |
| --- | --- | ---: | ---: |
| Full materialization | yes | 1,633 bits | implementation-dependent |
| Flat XOR | no | 23-bit-class signature | 71 in a serial fold |
| Linear ordered LOGOS | yes | 128 bits | 71 |
| Balanced ordered LOGOS | yes | 128 bits | 7 |

The Python and native C benchmarks both operate on identical pre-evaluated
BARDO-TX1 leaves. This isolates reduction-network cost from TX1 decoding. These
measurements are CPU software evidence only; they are not FPGA timing, power,
or end-to-end host/device evidence.

## Required correctness gates

The experiment fails if any of the following occurs:

- balanced and linear reducers disagree on aggregate facts;
- a root exceeds 128 logical bits;
- invalid lanes do not propagate a fail-closed root;
- non-contiguous spans can be merged;
- any distinct pairwise swap in the 71-lane fixture preserves the ordered root;
- any one-bit change in any of the 71 nine-bit input bundles preserves the root;
- the 7-lane permutation fixture produces fewer than `7! = 5,040` ordered roots;
- Python and native C disagree on the frozen baseline and swapped roots;
- the workflow does not expose the flat-XOR permutation collision.

Frozen cross-language roots for deterministic frame zero:

```text
baseline_ordered_root = 9be74091c16044de
swapped_ordered_root  = 69b5d0de81c00d8f
```

## Architectural result fixed by construction

For 71 BARDO-TX1 lanes:

```text
input                    = 71 × 9  =   639 bits/frame
full output              = 71 × 23 = 1,633 bits/frame
LOGOS output                        =   128 bits/frame

output reduction         = 1,633 / 128 = 12.7578125×
output bits removed                     = 92.16%

full round trip          = 639 + 1,633 = 2,272 bits/frame
LOGOS round trip         = 639 +   128 =   767 bits/frame
round-trip reduction     = 2,272 / 767 = 2.962190×
round-trip bits removed                 = 66.24%

linear dependency depth  = 71
balanced dependency depth= ceil(log2(71)) = 7
merge nodes              = 70
```

The `12.76×` figure applies only to the output. The honest external round-trip
reduction is about `2.96×` when the 9-bit-per-lane input is also counted.

A 128-bit root becomes smaller than materializing all 23-bit lane outputs at
six lanes:

```text
5 lanes: 115 output bits — full output is smaller
6 lanes: 138 output bits — LOGOS becomes smaller
```

This suggests an adaptive boundary: preserve full results for tiny frames and
activate LOGOS compression once a frame has at least six lanes.

The tree does not mean less total logic: a 71-lane frame still requires 70
merge nodes. The proposed hardware advantage is that independent merges at each
level can run spatially in parallel and only a bounded root crosses the external
boundary.

## Root-function cost boundary

The v0.2 software oracle uses the SplitMix64 finalizer to get strong deterministic
diffusion and make permutation defects obvious. SplitMix64 contains 64-bit
constant multiplications. Those multipliers are **not** assumed cheap on FPGA
and are excluded from every hardware-efficiency claim.

Before RTL, the root function must either:

- be replaced by a measured hardware-friendly ARX/CRC construction; or
- be synthesized and charged explicitly in LUT/DSP/FF/timing evidence.

## Interpretation rules

A likely and acceptable result is:

- flat XOR is fastest on a scalar CPU;
- linear ordered LOGOS is slower but detects ordering changes;
- balanced LOGOS is also slower in scalar software because the CPU executes the
  tree nodes and moves temporary words sequentially;
- a future RTL tree may recover throughput through spatial parallelism.

Therefore no CPU-competition or efficiency claim follows from this benchmark.
The next admissible gate after this experiment is synthesizable LOGOS-M1 RTL,
post-route timing/resource evidence, and a bandwidth-aware physical workload.
