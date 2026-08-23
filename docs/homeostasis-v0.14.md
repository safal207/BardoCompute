# Computational Homeostasis v0.14

## Status

Pre-registered before hosted evaluation.

## Question

Can an exchange-regulating process preserve an internal viability variable under hidden external resource fluctuations **without preserving itself by collapsing useful service**?

This is a computational control experiment, not a biological equivalence claim.

## Starting point

v0.13 established the exchange-side hypothesis:

```text
localized route pressure -> change coupling / reroute first
aggregate route pressure -> reduce total release
```

v0.14 adds a separate internal state that the exchange boundary may influence.

The purpose of regulation is no longer only lower exchange cost. The new question is whether exchange can be shaped to keep an internal state within a viable region while useful work continues.

## Internal state

Use a synthetic `internal_stress` variable:

```text
stress[t+1]
  = clamp(
      stress[t]
      + delivered_work[t] * heat_per_unit
      - hidden_relief[t],
      0,
      150,
    )
```

Frozen constants:

```text
initial_stress = 45
heat_per_unit = 0.020
target_high = 70
critical = 100
```

`internal_stress` is an abstract computational load/headroom variable. It may be read as thermal, power, queue-service, or another internal resource pressure only after a domain-specific mapping; the benchmark itself does not claim any one physical interpretation.

## Hidden relief process

Relief is generated independently of exchange-route regimes so the controller cannot infer it directly from route labels.

Hidden relief regimes:

```text
ample       = 1.80 / tick
normal      = 1.25 / tick
constrained = 0.55 / tick
recovery    = 2.20 / tick
```

Each step receives bounded random jitter. Hidden regime durations are randomized. The controller receives neither the relief value before acting nor the regime label nor future boundaries.

The controller observes only its current `internal_stress` plus the same past exchange outcomes available to v0.13.

## Policies

### v0.13 reference

Unchanged flow-preserving membrane.

### Static-cap controls

Wrap v0.13 with a fixed maximum release cap selected from:

```text
24 / 32 / 40 / 48 / 56 / 64 / 80 / 96 / 112 / 128
```

Routing remains the same v0.13 feedback logic. Admission shedding remains disabled.

A `static-safe` comparator means a fixed cap with **zero critical-stress ticks**. The strongest static-safe comparator is the one with the greatest delivered work; exchange cost breaks ties.

### Homeostatic membrane

Reuse v0.13 routing unchanged. Only total release receives internal-state feedback.

Frozen rule:

```text
stress <= 70:
    do not constrain the v0.13 release command

70 < stress < 100:
    dynamic_cap decreases linearly from 96 to 32

stress >= 100:
    dynamic_cap = 32

release = min(v0.13_release, dynamic_cap)
```

No current/future relief or future exchange capacity is used.

## Fresh validation family

Use a new seed family not used by v0.12 or v0.13:

```text
seed_i = 910021 + i * 17011
12 seeds
16000 exchange steps per seed
```

Exchange environments keep the same generator and cost accounting as v0.12/v0.13.

## Metrics

Report separately:

```text
critical_stress_ticks
stress_excess_integral above target_high
mean / max stress
delivered useful work
lost work
exchange cost
control moves
```

Safety/viability is not converted into a large scalar penalty inside the exchange cost.

## Predeclared acceptance criteria

Promote v0.14 only if all are true:

1. the unchanged v0.13 reference has non-zero critical-stress ticks on at least 75% of seeds, so the workload actually exercises homeostasis;
2. the homeostatic membrane has zero critical-stress ticks on every seed;
3. at least one zero-critical static-cap comparator exists for every seed;
4. median homeostatic delivered work is at least `1.08x` the strongest static-safe comparator;
5. median homeostatic delivered work is at least `0.95x` unchanged v0.13 service;
6. median lost-work ratio versus unchanged v0.13 is at most `1.10x`;
7. median exchange-cost ratio versus unchanged v0.13 is at most `1.25x`;
8. admission shedding remains disabled;
9. no future relief, regime, arrival, or route-capacity information is used.

Scientific rejection of the hypothesis is valid evidence and must not be reported as a software/runtime failure.

## Interpretation of a pass

A pass would support only the narrow claim:

> internal-state feedback can regulate exchange intensity so that a changing computational process remains inside a predefined viability region while preserving materially more service than a static safe cap.

It would **not** prove biological life, metabolism, consciousness, or universal homeostasis.

## Interpretation of a failure

If zero critical stress requires service collapse, then the current actuator set is insufficient or the viability target conflicts with the workload.

If a static safe cap delivers as much useful work as adaptive regulation, homeostatic feedback has not earned its complexity on this workload.

If the homeostatic controller repeatedly oscillates around the boundary, the next question should be hysteresis / timescale separation rather than another estimator.