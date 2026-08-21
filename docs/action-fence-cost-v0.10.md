# Local Action-Fence Cost v0.10

## Status

Pre-registered before hosted benchmark results are inspected.

## Question

After v0.8/v0.9 established the semantic role of an authoritative resource fence, what is the local in-memory hot-path cost of checking an epoch/token on every protected action?

This experiment intentionally does **not** model:

```text
network validation
consensus
replication
lease acquisition
remote storage
cross-process RPC
```

It isolates only the cost of a local resource-side token read, equality check, rejection accounting, and conditional application.

## Benchmark

`native/action_fence_cost_bench.c`

8 Mi actions, seven timed repeats per profile. Workload construction is outside timed loops.

### Paths

```text
unguarded
  read payload only
  apply every action

equal-load control
  read payload + token
  do not enforce authority

branch fence
  read payload + token
  if token == current epoch: apply
  else: reject

branchless fence
  same semantics as branch fence
  equality becomes a 0/1 mask
```

The primary runtime comparator is **fence vs equal-load**, not fence vs unguarded, because the unguarded path does not fetch token state.

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

Run on hosted Python-independent native jobs with:

```text
-O3
-O3 -fno-tree-vectorize
```

If branchless performance depends materially on auto-vectorization, the result must be reported as compiler-sensitive rather than a universal execution property.

## Semantic acceptance criteria

For every profile and compiler configuration:

1. branch and branchless fences must have identical accepted counts;
2. branch and branchless fences must have identical rejected counts;
3. branch and branchless fences must have identical accepted-payload checksums;
4. stale-token profiles must reject non-zero actions;
5. `none` must reject zero actions.

Any semantic mismatch fails the benchmark.

## Performance reporting rules

Report, but do not predeclare a required win:

```text
ns/action for each path
fence / equal-load ratio
branch / branchless ratio
periodic vs random sensitivity
vectorized vs no-vectorization behavior
```

No fence implementation is promoted solely because it is faster on one compiler/run.

A useful result is a stable map of where enforcement cost comes from.

## Interpretation guardrails

This benchmark can support statements such as:

> local epoch fencing adds X relative overhead beyond reading the same token stream on this hosted CPU/compiler.

It cannot support statements such as:

> distributed authority validation costs X ns/action.

or:

> fencing is free in a real distributed system.

## Next step only after v0.10

If local enforcement cost is modest and semantics remain correct, transfer the architecture to an agent-evidence/action workload where:

```text
evidence provenance -> receipt validity
observation cadence  -> evidence refresh cost
execution binding    -> action token / decision reference
resource fence       -> reject stale/unbound action
```

If local enforcement itself is costly or highly compiler-sensitive, first test batching/capability-scoped validation rather than adding another adaptive estimator.
