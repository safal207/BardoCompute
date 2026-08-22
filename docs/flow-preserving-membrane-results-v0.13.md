# Flow-Preserving Computational Membrane v0.13 — Hosted Results

## Status

Supported on hosted Python 3.11 and 3.12 after the preregistered v0.13 design was frozen.

The first hosted attempt was infrastructure-invalid because the dedicated workflow had not installed `pytest`; the benchmark never ran. The workflow dependency was fixed without changing controller logic, seeds, workload, comparator, or acceptance criteria. The rerun then completed successfully on both hosted Python versions.

## Why v0.13 exists

v0.12 reduced exchange cost but failed its own conservation guardrail because it could improve stability by shedding too much useful flow at the admission gate.

v0.13 therefore forbids discretionary admission shedding and tests the narrower rule:

```text
local pressure on one route
    -> reroute / change coupling first

pressure on both routes
    -> throttle aggregate release

clean delivery with buffered work
    -> restore release
```

Short form:

> **reroute local pressure before throttling total exchange.**

## Frozen validation family

```text
12 fresh held-out seeds
16000 steps / seed
future regime, capacity and arrival information hidden
best fixed release-rate x route-split control selected post hoc per seed
```

The v0.12 validation family was not reused for parameter retuning.

## Hosted result

Python 3.11 and 3.12 reproduced the same reported summary:

```text
win_rate=1.000
median_cost_ratio=0.587
p90_cost_ratio=0.629
worst_cost_ratio=0.633
median_delivered_ratio=1.000
median_loss_ratio=0.996
passes_preregistered_acceptance=true
```

Every one of the 12 held-out seeds beat its strongest fixed comparator on total exchange cost.

The result did not come from discarding materially more useful exchange:

```text
median delivered work = 1.000x strongest fixed
median lost work      = 0.996x strongest fixed
```

## Topology / coupling ablation

The same feedback rule with secondary routing disabled produced:

```text
rate_only_median_cost_ratio=2.170
full_vs_rate_only_median_ratio=0.270
```

On this workload, rate regulation alone was not sufficient. Dynamic route coupling was the dominant useful actuator.

## Post-hoc command morphology

Regime labels were hidden from the controller and used only after the run to explain behavior.

```text
normal:
  median release = 128
  median secondary fraction = .150

burst:
  median release = 92
  median secondary fraction = .333

primary degraded:
  median release = 128
  median secondary fraction = .770

global congested:
  median release = 44
  median secondary fraction = .450

recovery:
  median release = 128
  median secondary fraction = .150
```

The qualitative phase structure matched the preregistered mechanism:

- localized primary degradation changed route coupling rather than suppressing total exchange;
- aggregate congestion reduced release;
- recovery reopened the exchange path.

## Narrow supported claim

> A feedback boundary that preserves admission, reroutes localized pressure, and throttles only under aggregate pressure can improve exchange dynamics on the tested changing two-route workloads without buying stability by discarding materially more useful flow.

## What is not claimed

This result does not establish:

```text
biological equivalence
universal optimality
transfer to physical metabolism
transfer to financial or social exchange
network-level production performance
```

Those require separate operational mappings and falsification.

## Next falsification

v0.14 adds an independent internal viability variable and asks whether exchange regulation can preserve internal viability without collapsing useful service.

The v0.14 design was preregistered separately in `docs/homeostasis-v0.14.md`.