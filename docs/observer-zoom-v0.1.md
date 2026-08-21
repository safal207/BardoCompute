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

The architecture separates:

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
                  revisable observation
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

This is not assumed true. `benchmarks/observer_zoom.py` is the first falsification surface.

## Equal-information control

The benchmark includes conventional fixed-window and multiscale algorithms with the same observable stream. Symbolic observer labels receive no extra data or oracle access.

Any advantage shared by conventional and observer-labelled implementations belongs to multiscale observation, not to the vocabulary.

## First negative result: labels are not the mechanism

The first 50,000-episode run compared fixed-32, fixed-512, conventional `32 -> 128 -> 512`, and the labelled observer stack.

The labelled stack did not reduce classification errors versus the equal-information conventional multiscale control. Both used the same mean observation volume (`254.57` samples per episode) and both missed `13,368` adaptation cases in the constructed workload. The observer stack additionally represented `16,481` cross-scale conflicts as `PRESENCE/HOLD` instead of silently forcing a terminal conclusion.

Therefore:

```text
observer vocabulary != measured performance advantage
```

The useful mechanism is scale escalation and explicit revisability, not the names `KNOWLEDGE`, `VISION`, or `PRESENCE`.

## Falsification of one-shot long and early windows

The workload was strengthened so the `late_shift` regime begins at a deterministic-seeded random tick in `144..384`, rather than at a convenient fixed boundary.

Hosted CI #328 on Python 3.12 reproduced:

```text
episodes=50,000

fixed32:
  errors=29,844
  false_adapt=10,000
  missed_adapt=19,844
  mean_observed=32.00

fixed512:
  errors=6,160
  false_adapt=0
  missed_adapt=6,160
  mean_observed=512.00

early_multiscale:
  errors=13,368
  false_adapt=0
  missed_adapt=13,368
  mean_observed=254.57
```

The fixed 512-sample window is not an oracle: sufficiently late shifts are diluted by the earlier quiet prefix. Early multiscale stopping saves observation but can finalize before a later change arrives.

## Event-triggered revisit

`event_triggered_revisit` treats an early `KEEP` as revisable rather than permanent.

After a quiet two-scale decision at tick 128:

1. every following 32-signal interval uses eight evenly spaced sentinel reads;
2. `>=5/8` changed samples trigger inspection of the remainder of that already-arrived interval;
3. a changed interval re-opens adaptation;
4. no future regime length or hidden change boundary is supplied to the policy;
5. observation accounting counts unique reads only.

Hosted CI #328, Python 3.12:

```text
event_triggered_revisit:
  errors=0
  false_adapt=0
  missed_adapt=0
  mean_observed=289.55
  late_detected=10,000
  mean_late_detection_lag=38.04

revisit_observation_vs_fixed512=0.566x
```

Narrow supported conclusion:

> In this constructed workload, a revisable event-triggered observer detects late regime changes that both one-shot early stopping and one-shot long averaging can miss, while consuming 56.6% of the fixed-512 observation volume.

This does **not** establish that the current sentinel, interval, or threshold is optimal or broadly transferable.

## Interpretation of PRESENCE

The result suggests a more useful operational reading of `PRESENCE` / `HOLD`:

```text
HOLD != dead end
HOLD = preserve current action while keeping observation revisable
```

This is stronger than either premature reaction or permanent early commitment, but it remains an engineering control rule rather than a claim about human cognition.

## OPEN boundary

`OPEN` was reached zero times in the current benchmark and therefore has **no measured performance benefit**. It remains descriptive/control-plane semantics only.

If later used, its strict meaning remains:

```text
release model commitment != erase evidence history
```

## Next falsification

The zero-error result is too clean to promote without attack. The next suite must vary independently:

- late-shift amplitude and start distribution;
- gradual versus abrupt drift;
- transient burst duration;
- multiple shocks and reversals;
- sentinel density and trigger threshold;
- adversarial periodic patterns;
- signal distribution shift;
- explicit per-observation cost and missed/false adaptation cost.

The next mechanism should replace the fixed sentinel policy with an observation-payback gate:

```text
re-observe / zoom deeper only when
expected value of additional information > observation cost
```

That would connect observer zoom directly to the Living Process orientation principle.

## Scientific boundary

The project is testing a computational control principle:

> Before changing the system, test whether the apparent change survives an economically useful change of observation scale, and keep earlier conclusions revisable when new evidence arrives.

No claim is made that this is a universal law of life, finance, psychology, biology, or physics. Transfer to unrelated workloads must be demonstrated separately.