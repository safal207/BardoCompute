# Action-Boundary Fencing v0.8

## Status

Pre-registered falsification completed successfully on two independent hosted Python runners (3.11 and 3.12). The result is retained as semantic evidence; no runtime/speed claim is made.

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

The tested separation is:

```text
observation cadence -> freshness / efficiency / recovery latency
action boundary     -> stale-effect safety
```

The action boundary carries a monotonic authority epoch/token and the protected resource rejects an operation if the client token does not equal the resource's current authoritative epoch.

This is analogous to fencing-token patterns in distributed systems: stale holders may remain unaware that their authority changed, but the protected resource refuses stale operations.

## Benchmark

`benchmarks/action_boundary_fencing.py`

## Hosted result

Both Python 3.11 and 3.12 reproduced the same deterministic metrics.

### Adversarial indistinguishability control

```text
interval=1   pull_unsafe_accepted=0   fenced_unsafe_accepted=0
interval=8   pull_unsafe_accepted=7   fenced_unsafe_accepted=0
interval=32  pull_unsafe_accepted=31  fenced_unsafe_accepted=0
interval=128 pull_unsafe_accepted=127 fenced_unsafe_accepted=0
```

A restart immediately after the previous probe creates the expected `interval - 1` stale-action window for every pull-only cadence greater than one tick. The resource fence rejects every stale action in the same window.

### Stochastic recovery transfer

16 seeded recovery environments, with the existing noisy receipt/provenance path and hidden future restart boundaries:

```text
fixed8:
  median_probes=4463.5
  median_pull_unsafe_accepted=1042.0
  median_fenced_unsafe_accepted=0.0
  median_fence_rejections=1042.0
  median_fenced_acceptance_rate=.965382

fixed32:
  median_probes=1115.5
  median_pull_unsafe_accepted=4021.0
  median_fenced_unsafe_accepted=0.0
  median_fence_rejections=4021.0
  median_fenced_acceptance_rate=.878804

EWMA:
  median_probes=2870.0
  median_pull_unsafe_accepted=1377.0
  median_fenced_unsafe_accepted=0.0
  median_fence_rejections=1377.0
  median_fenced_acceptance_rate=.955224

rolling:
  median_probes=3530.5
  median_pull_unsafe_accepted=1196.0
  median_fenced_unsafe_accepted=0.0
  median_fence_rejections=1196.0
  median_fenced_acceptance_rate=.962175
```

## Anti-cheat invariants

For pull and fenced variants of the same policy/environment:

```text
probe count identical
stale-attempt count identical
local-HOLD count identical
```

The benchmark asserts these equalities. Both hosted runs passed them.

The fence therefore did not gain safety by observing authority more often or by receiving future restart information. It changed only the fate of an already-attempted stale action:

```text
pull-only -> stale effect applied
fenced    -> stale effect rejected
```

## Acceptance criteria result

All predeclared semantic acceptance conditions passed:

1. every adversarial cadence `d > 1` had a non-zero pull-only stale-action window;
2. fenced adversarial unsafe accepted actions were zero;
3. stochastic fenced unsafe accepted actions were zero for every tested policy/seed;
4. pull-only stochastic execution produced stale accepted actions for all non-per-action policies;
5. observer schedules remained identical by assertion;
6. fence rejections and acceptance rates were reported explicitly;
7. no runtime/speed advantage is claimed.

## What the result means

The result supports a stronger architectural separation than v0.7:

```text
OBSERVATION answers: when do I learn that authority changed?
FENCING answers:     may this action take effect under current authority?
```

Tightening observation cadence shrinks the stale-information window but cannot remove the underlying observability boundary unless every action is preceded by authoritative observation.

Resource-side authority fencing removes stale **effects** without requiring the observer itself to become per-action.

The cost is moved into availability/backpressure: stale attempts become explicit rejections, and a slower observer causes more rejected work.

## Boundary assumption

The protected resource must possess or synchronously validate the current authoritative epoch/token at the action boundary.

If the resource itself does not know authoritative ordering, resource-side fencing cannot provide the claimed guarantee. The system must then add a stronger authority/coordination mechanism or weaken the guarantee.

This is not a claim that a client-generated random token or a lease alone is sufficient.

## Current causal consequence

Safety should no longer be paid for by adding a larger scalar penalty to stale actions in the observation optimizer.

Instead:

```text
hard action admissibility -> resource fence
freshness / availability  -> observation cadence
recovery correctness      -> epoch/order provenance guard
```

These are causally distinct responsibilities.

## Next falsification

`docs/safe-observation-economics-v0.9.md` freezes the next question before evaluation:

> after unsafe effects are structurally fenced to zero, can adaptive observation still beat the strongest fixed cadence on probe cost plus unavailable/rejected work?

Only if that survives should native runtime cost of the fence be benchmarked.
