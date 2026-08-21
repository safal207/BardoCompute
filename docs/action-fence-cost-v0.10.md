# Local Action-Fence Cost v0.10

## Status

Protocol correction recorded before inspecting hosted results from the corrected benchmark (`v0.10b`).

The first hosted pilot (`v0.10a`) exposed a control-design confound: the intended equal-load comparator read the token stream by accumulating a token checksum, while fenced paths performed authority classification and rejection accounting. Its timing ratios are retained as a pilot but are **not** accepted as the final fence-overhead estimate.

No stale profile, compiler mode, fence implementation, repeat count, or workload size was changed in response to the pilot.

`v0.10b` adds one control only:

```text
classification control
  read the same payload + token streams
  compute token == authority
  compute the same accepted/rejected counts
  still apply every payload
```

The new primary comparator is **fence vs classification control**. This correction is methodological, not parameter tuning.

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

8 Mi actions, seven timed repeats per profile. Workload construction is outside timed loops.

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

Comparator roles:

```text
token-read / unguarded
  -> rough cost of bringing token state into the loop, with arithmetic caveat

classification / token-read
  -> classification + count cost, compiler dependent

fence / classification
  -> primary enforcement comparator
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

## Compiler controls

Hosted native jobs:

```text
-O3
-O3 -fno-tree-vectorize
```

If branchless performance depends materially on auto-vectorization, it must be reported as compiler-sensitive rather than universal.

## Semantic acceptance criteria

For every profile and compiler configuration:

1. branch and branchless fences must have identical accepted counts;
2. branch and branchless fences must have identical rejected counts;
3. branch and branchless fences must have identical accepted-payload checksums;
4. classification control must report the same accepted/rejected counts as both fenced implementations;
5. stale-token profiles must reject non-zero actions;
6. `none` must reject zero actions.

Any semantic mismatch fails the benchmark.

## Performance reporting rules

Report, without requiring a predeclared win:

```text
ns/action for every path
branch fence / classification ratio
branchless fence / classification ratio
branch / branchless ratio
periodic vs random sensitivity
vectorized vs no-vectorization behavior
```

No implementation is promoted from one runner/compiler result alone.

The goal is to locate enforcement cost, not manufacture a speedup.

## Pilot v0.10a — retained but non-final

Before the classification-control correction, hosted `-O3 -fno-tree-vectorize` showed:

```text
predictable branch fence ~0.91–0.93x old equal-load control
random 10% branch       ~2.00x
random 50% branch       ~6.19x
branchless              ~2.09x across profiles
```

Hosted normal `-O3` showed strong compiler/vectorization sensitivity:

```text
branchless / old equal-load ~1.50–1.60x
branch / old equal-load:
  predictable profiles ~2.6–2.7x
  random 10%           ~5.8x
  random 50%            ~17.8x
```

These numbers are useful evidence that predictability and vectorization matter, but the old equal-load comparator performed different arithmetic. Therefore they are not used as final enforcement-overhead claims.

## Interpretation guardrails

A corrected result may support statements such as:

> on this hosted CPU/compiler, local enforcement after equal authority classification adds X relative cost under a given token-entropy profile.

It cannot support:

> distributed authority validation costs X ns/action.

or:

> fencing is free in a real distributed system.

## Next step only after corrected v0.10b

If local enforcement is modest in some regimes and semantics remain correct, transfer the architecture to an agent-evidence/action workload:

```text
evidence provenance -> receipt validity
observation cadence  -> evidence refresh cost
execution binding    -> action token / decision reference
resource fence       -> reject stale/unbound action
```

If local enforcement remains highly entropy/compiler sensitive, test batching or capability-scoped validation before adding any new adaptive estimator.
