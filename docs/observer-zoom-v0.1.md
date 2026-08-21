# Adaptive Observer Zoom v0.1

## Research question

Can an adaptive system improve orientation by changing not only its action but also the scale and epistemic level at which it observes a changing environment?

The working state is extended from a time-only trajectory to:

```text
X = X(t, s_environment, l_observer)
```

where:

- `t` is time;
- `s_environment` is observation scale / temporal window;
- `l_observer` is an epistemic observer level.

This is an engineering abstraction. The labels below are inspired by the project's research metaphor and are not claims about consciousness, spirituality, or metaphysics.

## Observer levels

### POSITION

One-scale evidence. It describes what is visible from one local position but has no terminal authority by itself.

### KNOWLEDGE

At least two observation scales agree on the same side of a declared change threshold.

### VISION

Three or more scales agree tightly. The observed change survives a wider change of scale.

### PRESENCE

Scales conflict. The system deliberately preserves non-action rather than letting one scale silently dominate. When another wider scale remains available, PRESENCE requests more observation; at the widest declared scale it becomes HOLD.

### OPEN

Repeated strong cross-scale evidence may release commitment to the old model. OPEN is not memory erasure and is not a reset:

```text
release commitment != erase history
```

OPEN has no special performance privilege in v0.1. It remains a control-plane semantic unless future falsification demonstrates a distinct measurable benefit.

## Two independent adaptation problems

The architecture now separates:

```text
1. Where should the system look?
   -> observation scale / zoom

2. What should the system do?
   -> Living Process KEEP / HOLD / ADAPT
```

A scale change is not itself authority to change the execution model.

## Working causal chain

```text
Environment
    ↓
local observation
    ↓
POSITION
    ↓ zoom out when needed
cross-scale evidence
    ├── agreement -> KNOWLEDGE / VISION
    └── disagreement -> PRESENCE / HOLD
                          ↓
                 persistence evidence
                          ↓
                 Living Process payback
                  KEEP / HOLD / ADAPT
                          ↓
                       outcome
                          ↓
                     calibration
```

## Scale-persistence hypothesis

A transient event can be strong at a fine scale yet disappear at a wider scale. A persistent regime change should survive, or propagate through, multiple useful scales.

Working hypothesis:

```text
temporal persistence + scale persistence
    -> better estimate of whether adaptation can repay its cost
```

This is not assumed true. `benchmarks/observer_zoom.py` is a first falsification surface.

## Equal-information control

The benchmark includes a conventional multiscale algorithm with the same `32 / 128 / 512` observations. Symbolic observer labels receive no extra data or oracle access.

Any advantage shared by both implementations belongs to multiscale observation, not to the vocabulary.

## Known v0.1 vulnerability

One-shot early stopping can miss a regime change that begins only after the observer has already accepted two quiet scales. A `late_shift` workload is included deliberately.

If this failure appears, the next mechanism is not a larger fixed window. It is event-triggered re-observation / revisit logic whose cost is measured explicitly.

## Scientific boundary

The project is testing a computational control principle:

> Before changing the system, first test whether the apparent change survives an economically useful change of observation scale.

No claim is made that this is a universal law of life, finance, psychology, biology, or physics. Transfer to unrelated workloads must be demonstrated separately.
