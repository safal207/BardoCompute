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
              Observation Payback
               SKIP / HOLD / REVISIT
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

## Adaptive Observation Payback result

The hard-coded `5/8` revisit threshold was then replaced by an economic decision kernel in `src/bardocompute/observation_payback.py` and tested in `benchmarks/observation_payback.py`.

The gate asks:

```text
expected value of beneficial correction
- expected harm of false correction
- deeper observation cost
```

and returns:

```text
REVISIT / HOLD / SKIP
```

Its calibration comes only from past seeded episodes plus the current sentinel hit count. A conventional formula with identical information produces identical actions.

Hosted CI #340, Python 3.12, passed 94 tests and the full benchmark matrix.

The broad claim that adaptive payback always beats a fixed threshold was falsified. Under cheap, balanced, and expensive observation costs, the calibration-trained global threshold was slightly cheaper overall even though adaptive payback eliminated almost all missed adaptations.

A narrower positive result appeared when false adaptation was very expensive:

```text
false_action_cost=500

in distribution:
trained fixed 8/8 mean_loss=169.733
adaptive payback  mean_loss=161.677
ratio=0.953x
```

But distribution shift reversed the result:

```text
trained fixed 8/8 mean_loss=184.801
adaptive payback  mean_loss=199.415
ratio=1.079x

trained fixed false_adapt=1023
adaptive false_adapt=2302
```

The static payback calibration stayed highly sensitive (`3` missed adaptations versus `4,625`) but underestimated harmful-correction risk after the environment changed.

Therefore the next bottleneck is not another observer label or a more aggressive zoom policy. It is **calibration trust under change**.

Detailed evidence: `docs/observation-payback-results-v0.1.md`.

## Interpretation of PRESENCE

The result suggests a more useful operational reading of `PRESENCE` / `HOLD`:

```text
HOLD != dead end
HOLD = preserve current action while keeping observation revisable
```

The payback result adds a second requirement:

```text
revisable != always re-observe
re-observe only when estimated value of information repays cost
```

This is an engineering control rule rather than a claim about human cognition.

## OPEN boundary

`OPEN` was reached zero times in the original observer benchmark and therefore has **no measured performance benefit**. It remains descriptive/control-plane semantics only.

If later used, its strict meaning remains:

```text
release model commitment != erase evidence history
```

## Next falsification

The next suite should attack calibration itself:

- uncertainty-aware probability estimates;
- shrink sparse context cells toward base rates;
- online calibration-error monitoring;
- distribution-shift severity sweeps;
- bounded online recalibration without future leakage;
- explicit cost for detecting drift and updating calibration.

Compare:

```text
global trained threshold
static context-conditioned payback
uncertainty-shrunk payback
online drift-aware payback
```

Measure economic loss, false/missed adaptation, observation volume, calibration error, and detection lag together.

## Scientific boundary

The project is testing a computational control principle:

> Before changing the system, test whether the apparent change survives an economically useful change of observation scale, keep earlier conclusions revisable when new evidence arrives, and buy additional evidence only when its calibrated expected value can repay its cost.

The new distribution-shift failure shows that this rule is incomplete without calibration uncertainty and drift handling.

No claim is made that this is a universal law of life, finance, psychology, biology, or physics. Transfer to unrelated workloads must be demonstrated separately.