# Elastic Storage Reserve v0.18

## Status

Pre-registered before evaluation on a new held-out family.

## Motivation

v0.17 bidirectional homeostasis can preserve the synthetic critical-stress boundary while retaining nearly all delivered service, but its first fresh-family sanity result fails the preregistered lost-work guardrail. Temporary protective throttling creates backlog; the fixed 256-unit buffer can overflow before the process reopens.

This exposes a distinct exchange actuator already present in the membrane model but not yet dynamically regulated:

```text
storage / retention capacity
```

## Hypothesis

A process that temporarily slows exchange to preserve internal viability should be able to retain displaced useful work and release it after recovery, rather than forcing a choice between unsafe throughput and irreversible loss.

Short form:

> **when flow must contract temporarily, preserve what can be resumed later.**

## Frozen storage actuator

Baseline buffer remains:

```text
256 units
```

When storage reserve is active:

```text
total buffer limit = 2048 units
extra capacity      = 1792 units
```

Extra capacity is not free:

```text
capacity rental cost = 0.004 per extra-capacity-unit per tick
```

Actual buffered work continues to pay the unchanged v0.13 holding cost as well.

## Activation and release

Reuse v0.17 bidirectional protective mode unchanged.

Storage reserve becomes active when:

```text
protective mode is active
OR
previous buffered work > 256
```

After protective mode exits, elastic storage remains active until the actual buffer has drained back to `<=256`. This prevents artificial loss from shrinking capacity while retained work still occupies it.

No future arrival, capacity, relief, or regime information is used.

Admission shedding remains forbidden.

## Cost accounting

```text
total_operational_cost
  = v0.13 exchange cost
  + relief boost cost
  + extra_capacity_integral * 0.004
```

The existing exchange holding cost still charges actual buffer occupancy separately.

## Fresh validation family

All v0.14-v0.17 validation families are spent evidence.

```text
12 seeds
seed_i = 2810079 + i * 31013
16000 steps / seed
```

Exchange and hidden-relief generators remain structurally unchanged.

## Comparators

On the same fresh family:

```text
v0.13 flow-preserving membrane
v0.17 bidirectional homeostasis with fixed 256 buffer
v0.17 logic with 2048 buffer rented for every tick
v0.18 conditional elastic-storage reserve
```

The always-expanded comparator tests whether dynamic storage activation repays its control complexity relative to permanently buying the extra capacity.

## Predeclared acceptance criteria

Promote v0.18 only if all hold:

1. v0.13 has non-zero critical-stress ticks on at least 75% of seeds;
2. v0.18 has zero critical-stress ticks on every seed;
3. median v0.18 delivered work is at least `0.95x` v0.13 service;
4. median v0.18 lost-work ratio versus v0.13 is at most `1.05x`;
5. median v0.18 total-operational-cost ratio versus v0.13 is at most `1.35x`;
6. median v0.18 lost work is at most `0.90x` v0.17 lost work;
7. median v0.18 total operational cost is at most `0.90x` always-expanded total cost;
8. admission shedding remains disabled;
9. no future hidden information is used.

Report elastic-storage occupancy, transitions, peak buffer occupancy, and terminal buffer as secondary evidence.

Scientific rejection is valid evidence and must not be treated as a software failure.

## Narrow interpretation of a pass

> in the tested bounded workload, temporary paid storage can complement route/rate/relief regulation by preserving work displaced during protective throttling, reducing irreversible loss while retaining the viability invariant.

## What is not claimed

This is not a claim that larger buffers always improve systems. Storage can increase latency, memory cost, stale-work risk, and recovery time; these are exactly why capacity rental and holding costs remain explicit.

## Failure interpretation

If storage does not materially reduce loss, backlog duration or magnitude exceeds the actuator's useful range, or loss occurs for another reason.

If loss improves but total cost fails, storage is technically useful but economically unjustified on this workload.

Do not retune buffer size or rental price on this validation family.