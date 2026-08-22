# Computational Membrane / Exchange Dynamics v0.12

## Status

Pre-registered before hosted benchmark results.

## Question

Can a computational process improve the dynamics of an exchange by actively regulating the boundary between source and sink rather than merely observing state and choosing a terminal action?

The mechanism under test is deliberately small:

```text
gate   -> how much new flow may enter
rate   -> how much buffered + admitted flow may be released
buffer -> how much unresolved flow may be retained
route  -> how release is split across primary / secondary paths
```

This is an engineering abstraction inspired by regulated exchange. It is not a biological-cell claim.

## Core primitive

`src/bardocompute/exchange.py`

The primitive has no policy and no future information. It only executes one exchange command and returns explicit accounting for:

```text
admitted
rejected at gate
released
primary / secondary requested
primary / secondary delivered
congestion
buffered
buffer overflow
```

Unserved downstream work is retained when buffer capacity exists. It is never silently counted as completed work.

## Workload

`benchmarks/exchange_dynamics.py`

Twelve seeded environments, 16,000 steps each. Regimes are randomly ordered and randomly sized:

```text
normal
burst
primary_degraded
global_congested
recovery
```

Each regime changes incoming flow and primary/secondary exchange capacity with per-step jitter.

The adaptive membrane does **not** receive regime labels, current true capacity, future regime boundaries, or future arrivals.

Its decision at step `t` uses only:

```text
result of step t-1
current buffer occupancy carried by that result
```

Regime labels are used only after execution to report the morphology of the chosen commands.

## Controllers

### Strong fixed control

For every seed, choose the best fixed policy after the fact from:

```text
release rate = 32 / 48 / 64 / 80 / 96 / 112
secondary route fraction = 0 / .25 / .50 / .75
```

All fixed policies receive the same 256-unit buffer.

### Full feedback membrane

Past-only feedback can alter:

```text
admission limit
release rate
secondary route fraction
```

The buffer remains 256 units for every policy.

### Rate-only ablation

Same feedback law, but secondary routing is disabled. This tests whether exchange-shape control adds value beyond rate throttling alone.

### Current-state oracle reference

A non-comparable upper reference may use **current** primary/secondary capacities when constructing the command. It still receives no future information. The oracle is not used for acceptance.

## Cost model

```text
cost
  = 8.0 * (gate_rejected + buffer_overflow + terminal_buffer)
  + 1.5 * downstream_congestion_attempts
  + 0.04 * buffer_integral
  + 0.12 * secondary_delivered
  + 0.50 * control_moves
```

Interpretation:

- lost/unresolved flow is expensive;
- repeatedly pushing into unavailable capacity is not free;
- buffering creates delay/holding cost;
- secondary routing is useful but more expensive;
- changing the membrane command has a control cost.

## Anti-cheat rule

The membrane may not win by simply discarding useful flow.

Therefore cost is not the only acceptance metric. Delivered flow and lost flow are compared with the strongest fixed control.

## Predeclared acceptance criteria

Promote the full membrane mechanism only if, across the frozen twelve-seed family:

1. win rate against the post-hoc strongest fixed control is at least `0.65`;
2. median total-cost ratio is `< 0.98`;
3. median delivered-flow ratio is `>= 0.98`;
4. median lost-flow ratio is `<= 1.05`;
5. no future regime/capacity/arrival information is used;
6. control-move cost is included rather than hidden.

If these criteria fail, the feedback law is rejected or narrowed. Parameters are not to be retuned against this validation family and then reported as if pre-registered.

## What this can support

A passing result would support only:

> a bounded feedback mechanism that regulates gate/rate/buffer/route can change exchange dynamics in a measurable way and may outperform a strong fixed boundary policy on changing workloads after accounting for regulation cost.

It would **not** establish that:

- the mechanism is biologically equivalent to a cell membrane;
- the controller is optimal;
- the same parameters transfer to networks, money, energy, social systems, or physical biology;
- more regulation is always better;
- exchange should be optimized by one scalar objective in safety-critical domains.

## Connection to the Living Process architecture

The new actuator sits after orientation and before effect:

```text
PROVENANCE
  -> TRUST
  -> HAZARD
  -> OBSERVE
  -> ORIENT
  -> EXCHANGE COMMAND
       gate / rate / buffer / route
  -> EXCHANGE
  -> EFFECT
  -> OUTCOME
  -> feedback
```

The intended conceptual distinction is:

```text
ORIENT = should the process intervene?
EXCHANGE COMMAND = how should the interaction boundary change?
```

This keeps decision-to-intervene separate from the geometry/dynamics of the intervention itself.
