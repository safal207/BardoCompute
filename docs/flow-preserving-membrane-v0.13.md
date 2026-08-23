# Flow-Preserving Computational Membrane v0.13

## Status

Pre-registered before hosted evaluation on a fresh held-out family.

## Why v0.13 exists

The v0.12 controller was intentionally given a gate actuator and was required not to win by shedding useful flow.

Its first validation signal showed the danger directly: exchange cost fell, but useful delivered flow also fell and lost flow increased. Under the v0.12 acceptance rules that is a failure, not a win.

The v0.12 family is therefore treated as spent validation evidence. v0.13 uses a new seed family and does not retune v0.12 against its own validation cases.

## New hypothesis

A membrane should preserve useful exchange unless aggregate observed capacity is genuinely insufficient.

Working rule:

```text
local pressure on one route
    -> change coupling / reroute first

pressure on both routes
    -> reduce total release

buffer remains after clean delivery
    -> restore release faster

voluntary gate shedding
    -> forbidden in v0.13
```

Short form:

> **reroute local pressure before throttling total exchange.**

## Controller information

The v0.13 controller receives only the previous exchange result:

```text
requested per route
delivered per route
congestion
buffer occupancy
```

It does not receive:

```text
current true route capacity
future capacity
future arrivals
regime label
future regime boundary
```

Regime labels are used only after the run to explain command morphology.

## Fresh validation family

```text
12 seeds
seed_i = 710003 + i * 13007
```

The environment generator, regime definitions, jitter, buffer size, cost model, and strongest-fixed control grid remain unchanged from v0.12.

This keeps the workload family comparable while preventing parameter retuning against the original v0.12 validation seeds.

## Strong fixed comparator

Best fixed policy is selected after the fact per seed from:

```text
release rate = 32 / 48 / 64 / 80 / 96 / 112
secondary route fraction = 0 / .25 / .50 / .75
```

Every policy uses the same 256-unit buffer.

## Ablation

`rate_only` uses the same feedback logic but disables secondary routing.

This is secondary evidence for whether changing exchange topology/coupling matters beyond rate control alone.

## Predeclared acceptance criteria

Promote v0.13 only if all conditions hold on the fresh held-out family:

1. win rate vs strongest fixed is at least `0.75`;
2. median total-cost ratio is `< 0.95`;
3. p90 total-cost ratio is `<= 1.05`;
4. median delivered-flow ratio is `>= 0.995`;
5. median lost-flow ratio is `<= 1.02`;
6. voluntary gate shedding remains disabled;
7. no future regime/capacity/arrival information is used;
8. control-move cost remains included.

The rate-only ablation is reported but is not itself part of primary acceptance.

## What would be learned from failure

If v0.13 still lowers cost by losing materially more useful flow, the exchange objective is incomplete and needs an explicit conservation/service constraint rather than another feedback tweak.

If v0.13 preserves flow but cannot beat strong fixed control, adaptive exchange may not repay its regulation cost on this workload.

If routing adds no value over rate-only control, topology/coupling should not be promoted as a core actuator from this evidence.

## Narrow interpretation of a pass

A pass would support:

> a feedback boundary that preserves admission, reroutes localized pressure, and throttles only under aggregate pressure can improve exchange dynamics on changing two-route workloads without buying stability by discarding materially more useful flow.

It would not establish biological equivalence, universal optimality, or transfer to physical/financial/social exchange without separate operational tests.
