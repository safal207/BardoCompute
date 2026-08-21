# Local Action-Fence Cost v0.10

## Status

Corrected `v0.10b` completed successfully on hosted native runners in both compiler configurations:

```text
-O3
-O3 -fno-tree-vectorize
```

All semantic invariants passed for every stale-token profile.

The earlier `v0.10a` equal-load pilot is retained as non-final because it exposed a control-design confound. No stale profile, compiler mode, fence implementation, repeat count, or workload size was changed when correcting the control.

## Question

After v0.8/v0.9 established the semantic role of an authoritative resource fence, what is the local in-memory hot-path cost of enforcing an epoch/token decision after authority classification is already available?

This experiment intentionally does **not** model:

```text
network validation
consensus
replication
lease acquisition
remote storage
cross-process RPC
```

It isolates local token memory access, authority classification, rejection accounting, and conditional application.

## Benchmark

`native/action_fence_cost_bench.c`

```text
8 Mi actions
7 timed repeats per profile
workload construction outside timed loops
```

### Paths

```text
unguarded
  read payload only
  apply every action

token-read control
  read payload + token
  do not classify/enforce authority

classification control
  read payload + token
  classify token == authority
  count accepted/rejected exactly like fence
  apply every payload anyway

branch fence
  same classification
  apply only current-authority actions with a branch

branchless fence
  same semantics as branch fence
  equality becomes a 0/1 mask
```

The primary enforcement comparator is:

```text
fence / classification control
```

## Frozen stale-token profiles

```text
none
periodic 0.1%
random 0.1%
periodic 10%
random 10%
random 50%
```

The periodic/random pairs separate stale frequency from branch predictability.

## Semantic result

For every profile and both compiler configurations:

```text
branch accepted == branchless accepted
branch rejected == branchless rejected
branch accepted checksum == branchless accepted checksum
classification accepted/rejected counts == fenced counts
```

All stale profiles rejected non-zero actions; `none` rejected zero.

No semantic mismatch occurred.

## Hosted runtime — normal `-O3`

Primary ratios relative to classification control:

| stale profile | classification ns/action | branch fence ns/action | branch/classification | branchless ns/action | branchless/classification |
|---|---:|---:|---:|---:|---:|
| none | .343 | .634 | 1.849x | .361 | 1.054x |
| periodic 0.1% | .344 | .642 | 1.866x | .362 | 1.052x |
| random 0.1% | .354 | .649 | 1.834x | .371 | 1.049x |
| periodic 10% | .347 | .608 | 1.753x | .365 | 1.054x |
| random 10% | .342 | 1.295 | 3.789x | .365 | 1.067x |
| random 50% | .340 | 4.011 | 11.802x | .366 | 1.077x |

Additional observation:

```text
branch / branchless
none            1.754x
periodic .1%    1.774x
random .1%      1.749x
periodic 10%    1.663x
random 10%      3.550x
random 50%     10.953x
```

With normal `-O3`, branchless enforcement remains close to classification cost across the entire entropy sweep: approximately 4.9–7.7% additional runtime over classification in this hosted run.

The branching implementation has similar absolute time in predictable profiles but cannot exploit the same vectorized path and degrades sharply under high-entropy stale decisions.

## Hosted runtime — `-O3 -fno-tree-vectorize`

| stale profile | classification ns/action | branch fence ns/action | branch/classification | branchless ns/action | branchless/classification |
|---|---:|---:|---:|---:|---:|
| none | 1.305 | .740 | .567x | 1.580 | 1.211x |
| periodic 0.1% | 1.305 | .732 | .561x | 1.575 | 1.207x |
| random 0.1% | 1.306 | .732 | .560x | 1.576 | 1.206x |
| periodic 10% | 1.307 | .698 | .534x | 1.574 | 1.205x |
| random 10% | 1.303 | 1.544 | 1.185x | 1.576 | 1.209x |
| random 50% | 1.305 | 4.649 | 3.564x | 1.576 | 1.208x |

Without tree vectorization, branchless enforcement is roughly 20.5–21.1% above classification across profiles.

The predictable branch path is cheaper than the scalar classification-control loop on this compiler/run, while random 10% crosses above classification and random 50% rises to 3.564x.

## What v0.10b supports

The result does **not** support a single universal `fencing overhead` number.

Instead it supports a three-part local cost model:

```text
1. authority-state access cost
2. authority classification/accounting cost
3. enforcement execution-form cost
       × branch predictability
       × compiler/vectorization capability
```

The strongest local result is:

> **Once authority classification is already in the hot path, branchless local enforcement can be near classification cost under vectorizing `-O3`, while branch-based enforcement becomes highly sensitive to decision entropy.**

On this hosted `-O3` run the branchless enforcement increment over classification was only about 5–8%, but with vectorization disabled it was about 20–21%. Therefore the low-overhead result is explicitly compiler-sensitive.

## Important compiler conclusion

Absolute branch timings remained in the same broad range between compiler modes for predictable profiles, while classification and branchless paths accelerated dramatically under normal `-O3`.

Therefore:

```text
vectorization is part of the observed mechanism
```

not measurement noise to be hidden.

The result strengthens the earlier execution rule:

```text
predictable low-entropy decision graph -> branch can be excellent
high-entropy decision stream           -> branchless/indexed execution can dominate
```

This is consistent with earlier BardoCompute branch/LUT entropy experiments, but v0.10b establishes it specifically at the authority-enforcement boundary.

## Pilot v0.10a — why it is not the final claim

The original equal-load comparator accumulated a token checksum while fenced paths performed validity counts. It correctly showed that entropy and compiler mode mattered, but arithmetic work differed enough that `fence/equal-load` was not a clean enforcement estimate.

The pilot is retained rather than deleted:

```text
-O3 no-vector pilot:
  predictable branch ~.91-.93x old equal-load
  random 10% branch  ~2.00x
  random 50% branch  ~6.19x
  branchless          ~2.09x

-O3 pilot:
  branchless          ~1.50-1.60x old equal-load
  predictable branch  ~2.6-2.7x
  random 10% branch   ~5.8x
  random 50% branch   ~17.8x
```

Those values are methodological history, not the final enforcement-overhead claim.

## Interpretation guardrails

v0.10b can support statements such as:

> on this hosted CPU/compiler, local enforcement after equal authority classification added about 5–8% in the vectorized branchless path.

It cannot support:

> distributed authority validation costs 5–8%.

or:

> fencing is free in a real distributed system.

The protected resource still needs authoritative ordering, and acquiring/replicating that ordering may dominate the local compare cost.

## Current architectural consequence

The evidence now suggests a clean division:

```text
PROVENANCE
  validate evidence history/order

OBSERVATION
  optimize freshness and availability economics

ORIENTATION
  choose KEEP / HOLD / ADAPT

ACTION FENCE
  enforce authority at the resource

EXECUTION FORM
  choose branch vs branchless/indexed implementation based on local predictability
```

Safety remains non-negotiable, while implementation of the safety boundary can itself adapt to predictable execution structure — provided that changing execution form repays its own cost.

## Next falsification

Transfer this separation into an **agent evidence → decision → action** workload without importing hidden authority information.

Target mapping:

```text
evidence provenance -> receipt validity
observation cadence  -> evidence refresh / revalidation cost
decision reference   -> action binding token
resource fence       -> reject stale / replayed / unbound action
outcome receipt      -> evidence for later calibration
```

The transfer must compare against an equal-information conventional implementation and preserve the rule:

```text
proof / decision artifact != dispatch receipt
state hash != live freshness guarantee
```

No distributed-system performance claim should be made until that transfer has executable evidence.
