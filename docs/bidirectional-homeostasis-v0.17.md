# Bidirectional Exchange Homeostasis v0.17

## Status

Pre-registered before evaluation on a new held-out family.

## Motivation

v0.16 introduces a protective action derived from the declared worst-case relief bound. That action can make the synthetic critical-stress boundary invariant, but its first fresh-family sanity result preserves viability by suppressing useful work too aggressively.

This exposes a missing actuator class.

A process interacting with an environment may regulate both:

```text
outgoing demand / work release
and
incoming relief / resource exchange
```

A homeostatic system that can only reduce demand may have a poor safety/service frontier even when a safe state is reachable.

## Hypothesis

When internal viability is threatened, combining bounded demand reduction with a costly auxiliary relief exchange can preserve the critical boundary while retaining more useful service than output throttling alone.

Short form:

> **regulate both sides of the exchange, not only consumption.**

## Auxiliary relief actuator

Freeze one additional actuator:

```text
max relief boost = +1.00 / tick
boost cost       = 12.0 per boost-unit per tick
```

The hidden environment relief floor remains:

```text
0.40 / tick
```

With boost active, the worst-case available relief is therefore:

```text
0.40 + 1.00 = 1.40
```

At `heat_per_unit=0.020`, the worst-case non-worsening protected release cap is derived as:

```text
boosted_safe_cap
  = floor(1.40 / 0.020)
  = 70
```

The controller does not know the current hidden relief realization. It knows only the declared disturbance floor and actuator capacity.

## Controller

Reuse v0.15 past-only stress trajectory and v0.16 hysteresis:

```text
enter protective mode:
  effective_stress >= 70

exit protective mode:
  current_stress <= 60
  and stress_slope_ema <= 0
```

Outside protective mode:

```text
v0.13 release/routing unchanged
relief boost = 0
```

Inside protective mode:

```text
relief boost = 1.00
release = min(v0.13_release, 70)
```

Admission shedding remains forbidden.

## Cost accounting

Report exchange cost unchanged from v0.13 plus explicit relief-actuation cost:

```text
total_operational_cost
  = exchange_cost
  + boost_integral * 12.0
```

No safety penalty is inserted into this scalar cost. Critical-stress admissibility is checked separately.

## Fresh validation family

The v0.14, v0.15, and v0.16 families are spent evidence and are not reused.

```text
12 seeds
seed_i = 2210061 + i * 29011
16000 exchange steps / seed
```

Exchange and hidden-relief generators remain structurally unchanged.

## Comparators

Run on the same fresh family:

```text
v0.13 flow-preserving membrane
v0.16 output-only viability reserve
always-protective bidirectional control:
    boost=1.00 every tick
    release cap=70 every tick
v0.17 conditional bidirectional homeostasis
```

The always-protective control tests whether adaptive activation actually earns its complexity versus paying for auxiliary relief continuously.

## Predeclared acceptance criteria

Promote v0.17 only if all hold:

1. v0.13 has non-zero critical-stress ticks on at least 75% of seeds;
2. v0.17 has zero critical-stress ticks on every seed;
3. median v0.17 delivered work is at least `0.95x` v0.13 service;
4. median v0.17 lost-work ratio versus v0.13 is at most `1.10x`;
5. median v0.17 total-operational-cost ratio versus v0.13 is at most `1.35x`;
6. median v0.17 delivered work is at least `1.05x` always-protective service;
7. median v0.17 total operational cost is at most `0.90x` always-protective total cost;
8. admission shedding remains disabled;
9. no current/future hidden relief, route capacity, regime, or arrival information is used.

Report protective/boost occupancy and transitions as secondary mechanism evidence.

Scientific rejection is valid evidence and must not be treated as a software failure.

## Narrow interpretation of a pass

> in the tested bounded synthetic environment, a process can preserve internal viability with less service sacrifice by regulating both useful-work release and a costly external relief exchange, activating the auxiliary exchange only when internal state/trajectory requires it.

## What is not claimed

This does not establish biological metabolism or universal homeostasis. `relief boost` is an abstract actuator that could map to cooling, power, capacity acquisition, memory pressure relief, external assistance, or another domain-specific exchange only after separate modeling.

## Failure interpretation

If v0.17 remains unsafe, the combined protected action is not actually invariant under the implemented update order/bounds.

If safety holds but service/cost guardrails fail, the auxiliary exchange is too weak or too expensive for this workload, and the result should be retained rather than retuned on the same family.