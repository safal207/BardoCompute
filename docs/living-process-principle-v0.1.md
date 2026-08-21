# Living Process Orientation Principle v0.1

## Status

Research hypothesis, not a universal law.

The purpose of this document is to make the project's new center of orientation explicit and falsifiable across unrelated workloads.

## Core question

> When is a detected change persistent, credible, and valuable enough that a system should change itself rather than continue operating under its current model?

A detected change is not, by itself, authority to adapt.

```text
change detected != regime change != profitable adaptation
```

## Three actions

The high-level living-process decision alphabet is:

```text
KEEP  current model
HOLD  gather evidence / preserve optionality
ADAPT change model or execution path
```

This is distinct from the lower Tao evidence decision `ALLOW / DEFER / DENY`.

- Tao asks whether the available evidence can support a terminal claim.
- Living Process asks whether an evidence-backed change is expected to repay the cost of adapting.

A system may therefore have strong evidence that the environment changed and still rationally choose `KEEP` if the new regime is expected to be too short-lived or too expensive to exploit.

## Minimal executable hypothesis

For evidence at time `t`:

```text
expected_benefit = confidence
                 * expected_remaining_regime_lifetime
                 * saving_per_step

expected_cost = observation_cost
              + switch_cost
              + error_cost

orientation_score = expected_benefit - expected_cost
```

With a hysteresis band `h`:

```text
score >  h  -> ADAPT
|score| <= h -> HOLD
score < -h  -> KEEP
```

Break-even persistence is:

```text
break_even_steps = expected_cost / (confidence * saving_per_step)
```

when the denominator is positive.

The equation is intentionally small. Future evidence may require nonlinear risk, asymmetric losses, changing confidence, discounting, or explicit value-of-information terms.

## Causal spine

Only mechanisms that improve or falsify this chain should enter the core research path:

```text
Environment change
        ↓
Observable trajectory
        ↓
Drift evidence
        ↓
Observer confidence
        ↓
Morphology / regime belief
        ↓
Expected persistence
        ↓
Expected adaptation payoff
        ↓
KEEP / HOLD / ADAPT
        ↓
Execution outcome
        ↓
Calibration
        └──────────────→ observer / model update
```

The shortest causal statement is:

```text
Persistence
    -> Detectability
    -> Confidence
    -> Adaptation payoff
    -> Action
    -> Outcome
```

## Layer responsibilities

### Bardo

Preserves how the system reached its current state: continuity, discontinuity, regression, transition provenance, and temporal trajectory.

### ATMAN-inspired observer plane

Estimates whether observed change is credible across time scales. Disagreement is evidence to `HOLD`, not automatic mutation authority.

### Cosmic morphology

Represents the current form of the environment. Current engineering classes are:

```text
STRUCTURED / TRANSITIONAL / AMORPHOUS
```

The labels are research abstractions. `TRANSITIONAL` is primarily an uncertainty / changing-form condition; it does not require a dedicated third hot executor.

### MorphologyRegister

Retains evidence-backed environment form so the system does not pay to rediscover the same morphology continuously.

### Tao

Represents evidence orientation and unresolved evidence. Tao is not forced to be another execution mode or another physical carrier.

### Capability3

Represents the system's active mode of capability use:

```text
MANIFEST -> ADAPT -> ACQUIRE -> MANIFEST
```

### Living Process Orientation

Combines persistence, confidence, execution advantage, and adaptation cost into the final high-level choice:

```text
KEEP / HOLD / ADAPT
```

## Timescale center

The strongest current dimension is not raw change magnitude but the relationship between environmental lifetime and adaptation time/cost.

```text
tau_environment / tau_adaptation
```

and, more specifically for morphology:

```text
tau_morphology / tau_observation
```

The working principle is:

> Adaptation is useful only when the expected remaining lifetime and value of the new regime can repay the cost of knowing about it and changing behavior.

## What is deliberately excluded from the core for now

- a dedicated `TRANSITIONAL` executor without evidence of net benefit;
- full POMDP or Bayesian changepoint solvers in the hot path;
- large banks of morphology labels;
- metaphysical or historical claims about ancient computation;
- any layer that cannot move correctness, utility, proof, cost, speed, observation volume, or adaptation lag.

These ideas may remain useful as controls, oracles, offline models, or future work.

## Falsification gates

A proposed mechanism stays in the architecture only if it survives at least one of these tests:

1. **Correctness:** fewer unsafe or wrong actions at equal information.
2. **Observation efficiency:** lower evidence-gathering cost at equal decision quality.
3. **Adaptation efficiency:** lower regret / higher realized utility after paying observation and switch cost.
4. **Execution efficiency:** lower runtime or memory at equal semantics.
5. **Robustness:** survives randomized dwell, gradual drift, false bursts, out-of-order events, and distribution shift.
6. **Transfer:** improves more than one unrelated workload without changing the principle to fit each case.

If a layer fails these gates, remove it from the hot architecture or demote it to descriptive/control-plane status.

## Cross-domain transfer test

The principle is interesting only if the same causal rule transfers without redefining it.

Planned domains:

```text
A. native execution
   branch / LUT / morphology register

B. systems / recovery
   retry / stale state / recovery / continuity

C. agent decisions
   authority / evidence / delayed outcome / replay

D. later economic-risk control
   only after A-C establish the general mechanism
```

Domain D is not evidence yet. Finance, relationships, organizations, and economics are analogies until separate data and operational definitions are supplied.

## v0.1 executable artifact

`src/bardocompute/living_process.py` implements the minimal orientation equation.

`benchmarks/orientation_payback.py` compares:

1. reactive adaptation after every detected change;
2. noisy persistence-aware `KEEP / HOLD / ADAPT` orientation;
3. an oracle with true remaining persistence as an upper-bound control.

The benchmark asks a narrow question:

> Can a persistence/payback gate avoid economically losing switches while retaining useful long-lived adaptations?

A positive result supports the payback hypothesis only on the constructed workload. It does not establish a universal adaptive law.

## Research trajectory

```text
1. Prove payback gate against reactive adaptation.
2. Replace fixed persistence with online run-length / dwell estimation.
3. Attack with random regime lengths and gradual drift.
4. Add false bursts and distribution shift.
5. Sweep observation / adaptation costs.
6. Build a phase diagram of KEEP / HOLD / ADAPT regions.
7. Run ablations: Bardo, ATMAN, morphology, persistence, orientation.
8. Transfer the unchanged rule to systems and agent workloads.
9. Only then discuss a general living-process principle.
```

## Current center of orientation

The project should now optimize for one question, not for the number of concepts it can contain:

> **Is the expected future value of changing the system greater than the full cost and risk of knowing, switching, and being wrong?**

Everything else is supporting evidence, representation, observation, execution, or calibration around that question.
