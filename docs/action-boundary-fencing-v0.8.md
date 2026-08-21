# Action-Boundary Fencing v0.8

## Status

Pre-registered falsification. Results are not filled in until the hosted workflow completes.

## Question

Can pull-based observation cadence alone guarantee that no action is applied under stale authority when authority changes are hidden until the next probe?

## Hypothesis

No.

If the client can only discover an authority change through a later probe, then any observation interval greater than one tick admits two worlds that are locally indistinguishable before the next probe:

```text
world A: authority unchanged
world B: authority changed immediately after the previous probe
```

A client that continues acting in both worlds cannot guarantee zero stale effects in world B.

The proposed separation is:

```text
observation cadence -> freshness / efficiency / recovery latency
action boundary     -> stale-effect safety
```

The action boundary carries a monotonic authority epoch/token and the protected resource rejects an operation if the client token does not equal the resource's current authoritative epoch.

This is analogous to fencing-token patterns in distributed systems: stale holders may remain unaware that their authority changed, but the protected resource refuses stale operations.

## Benchmark

`benchmarks/action_boundary_fencing.py`

### Adversarial indistinguishability control

For fixed cadence:

```text
1 / 8 / 32 / 128
```

place an authority restart one tick after a probe and allow the client to act until the next probe.

Expected lower bound:

```text
pull-only unsafe accepted = interval - 1
fenced unsafe accepted    = 0
```

for every interval greater than one.

### Stochastic recovery transfer

Reuse the v0.6 authority-epoch recovery environments and existing noisy receipt/provenance path.

Compare identical observer schedules under:

```text
pull-only execution
resource-side epoch fencing
```

Policies:

```text
fixed 8
fixed 32
EWMA hazard cadence
rolling hazard cadence
```

The middle existing cost profile is used only to instantiate the already-frozen adaptive cadence formula. v0.8 does not optimize or report a new scalar utility objective.

## Anti-cheat invariants

For pull and fenced variants of the same policy/environment:

```text
probe count must be identical
stale-attempt count must be identical
local-HOLD count must be identical
```

The fence may alter only whether an already-attempted stale action is applied or rejected.

The benchmark asserts these equalities.

## Predeclared acceptance criteria

v0.8 supports the semantic separation only if all conditions hold:

1. every adversarial cadence `d > 1` has a non-zero pull-only stale-action window;
2. fenced adversarial unsafe accepted actions are zero;
3. stochastic fenced unsafe accepted actions are zero for every tested policy/seed;
4. pull-only stochastic execution exhibits stale accepted actions for at least one non-per-action policy;
5. observer schedules remain identical by assertion;
6. fence rejections and action acceptance are reported as availability cost rather than hidden;
7. no runtime/speed advantage is claimed from this semantic benchmark.

## Boundary assumption

The protected resource must possess or synchronously validate the current authoritative epoch/token at the action boundary.

If the resource itself does not know the authoritative ordering, resource-side fencing cannot provide the claimed guarantee. In that case the system must add a stronger authority/coordination mechanism or weaken the guarantee.

## What would falsify the direction

The direction is rejected or narrowed if:

- stale effects remain possible after correct resource-side epoch comparison;
- the fence changes observation information or secretly probes authority more often;
- zero unsafe effects require hidden future restart information;
- availability/rejection cost makes the mechanism unusable for the target workload;
- the resource cannot maintain authoritative monotonic ordering in the intended deployment model.

## Next step only if semantics survive

Measure the actual cost of boundary enforcement and rejected stale work against:

```text
per-action authoritative probing
fixed sparse probing
adaptive sparse probing + fence
```

with equal-information native controls.
