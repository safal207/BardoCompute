# Viability Reserve / Robust Protective Exchange v0.16

## Status

Pre-registered before evaluation on a new held-out family.

## Why v0.16 exists

v0.14 showed that reacting to current internal stress can reduce critical exposure without eliminating it.

v0.15 added recent stress trajectory and anticipated rising stress earlier. Its first fresh-family sanity result reduced critical exposure further, but still could not make the critical boundary invariant.

The failure mechanism is causal: the protective release floor itself can still increase stress under the lowest admissible relief. Better prediction cannot turn an intrinsically non-protective action into a protective one.

## Hypothesis

Strict homeostasis requires at least one available action whose worst-case local dynamics do not move the internal state farther toward the critical boundary.

Short form:

> **a viability controller needs a genuinely viability-preserving action, not only earlier detection.**

## Bounded environment contract

The hidden relief generator used since v0.14 has:

```text
minimum base relief = 0.55
jitter lower bound  = -0.15
known relief floor  = 0.40 / tick
heat_per_unit       = 0.020
```

The controller does not observe the current/future relief realization. It is allowed to know only the declared lower bound of the environment contract.

A release cap whose worst-case heat does not exceed the known relief floor is:

```text
safe_cap
  = floor(relief_floor / heat_per_unit)
  = floor(0.40 / 0.020)
  = 20
```

At `release <= 20`, the benchmark dynamics satisfy:

```text
delta_stress <= 0
```

for every admissible relief realization.

This is a local invariant statement inside the synthetic benchmark, not a universal physical law.

## Controller

Reuse v0.13 routing and the v0.15 past-only stress-slope estimate.

Protective mode uses hysteresis:

```text
enter protective mode when:
  effective_stress >= 70

exit protective mode only when:
  current_stress <= 60
  and stress_slope_ema <= 0
```

where:

```text
stress_slope_ema alpha = 0.20
projection horizon = 16
```

In protective mode:

```text
release_limit = min(v0.13_release, safe_cap=20)
```

Outside protective mode, v0.13 release and routing are unchanged.

Admission shedding remains forbidden.

## Fresh validation family

The v0.14 and v0.15 families are spent evidence and are not reused.

```text
12 seeds
seed_i = 1710047 + i * 23003
16000 exchange steps / seed
```

Exchange and hidden-relief generators remain structurally unchanged.

## Comparators

On the same fresh family:

```text
v0.13 flow-preserving membrane
v0.14 level-only homeostasis
v0.15 trajectory homeostasis
best post-hoc zero-critical static cap
v0.16 viability-reserve controller
```

Static cap grid remains:

```text
24 / 32 / 40 / 48 / 56 / 64 / 80 / 96 / 112 / 128
```

Note: the static comparator grid intentionally does not include the newly derived `20` emergency action. The static comparator tests previously frozen always-on operating choices; `20` is introduced specifically as a conditional protective action derived from the known bound. The v0.16 result must therefore also be reported versus raw v0.13 service and cost so this does not become a hidden free advantage.

## Predeclared acceptance criteria

Promote v0.16 only if all hold:

1. v0.13 has non-zero critical-stress ticks on at least 75% of seeds;
2. v0.16 has zero critical-stress ticks on every seed;
3. at least one zero-critical previously frozen static cap exists for every seed;
4. median v0.16 delivered work is at least `1.08x` strongest static-safe service;
5. median v0.16 delivered work is at least `0.95x` v0.13 service;
6. median v0.16 lost-work ratio versus v0.13 is at most `1.10x`;
7. median v0.16 exchange-cost ratio versus v0.13 is at most `1.25x`;
8. admission shedding remains disabled;
9. no current/future hidden relief, regime, capacity, or arrival information is used.

Report protective-mode occupancy and transition count as secondary mechanism metrics.

Scientific rejection is valid evidence and must not be treated as a software failure.

## Narrow interpretation of a pass

> under a known bounded disturbance model, combining a flow-preserving exchange membrane with a conditionally invoked worst-case non-worsening action can keep an internal synthetic viability variable below a critical boundary while retaining materially more service than an always-on static safe cap.

## What is not claimed

This does not establish biological life, metabolism, universal robust control, or correctness outside the declared disturbance bounds.

If real relief falls below the declared floor, the invariant no longer follows.

## Failure interpretation

If v0.16 still violates the critical boundary, inspect implementation/order-of-update assumptions before changing parameters: under the declared one-step dynamics, the protective action should be non-worsening once engaged.

If safety holds but service collapses below the preregistered guardrails, robust viability is achievable but the current actuator set does not provide an acceptable safety/service frontier.