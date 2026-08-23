# Capability Recovery Results v0.1

## Question

If Manifest, Acquire, and Adapt can flow into one another, what is the smallest explicit recovery trajectory and which execution form is appropriate for it?

The v0.1 recovery path is:

```text
MANIFEST
  -- environment change --> ADAPT
  -- gap detected -------> ACQUIRE
  -- evidence ready -----> MANIFEST
```

This is deliberately implemented as an ordinary finite-state machine. A conventional FSM with the same states and signals is the equal-information control.

## Signals

```text
HOLD
ENVIRONMENT_CHANGE
GAP_DETECTED
EVIDENCE_READY
```

The expected four-step episode is:

```text
HOLD                -> MANIFEST
ENVIRONMENT_CHANGE  -> ADAPT
GAP_DETECTED        -> ACQUIRE
EVIDENCE_READY      -> MANIFEST
```

The measured recovery time from the environment-change tick back to Manifest is two ticks.

## Python semantic benchmark

50,000 episodes.

### Python 3.11 runner

```text
fixed Manifest:
  wrong_mode_ticks=100000

conventional equal-information FSM:
  wrong_mode_ticks=0
  recovered_episodes=50000
  mean_recovery_ticks=2.000
  seconds=0.156982

Bardo/Tao capability transition algebra:
  wrong_mode_ticks=0
  recovered_episodes=50000
  mean_recovery_ticks=2.000
  seconds=0.161819

semantic_equivalence_to_conventional=True
flow_vs_conventional_time=1.031x
```

### Python 3.12 runner

```text
fixed Manifest:
  wrong_mode_ticks=100000

conventional equal-information FSM:
  wrong_mode_ticks=0
  recovered_episodes=50000
  mean_recovery_ticks=2.000
  seconds=0.089375

Bardo/Tao capability transition algebra:
  wrong_mode_ticks=0
  recovered_episodes=50000
  mean_recovery_ticks=2.000
  seconds=0.087278

semantic_equivalence_to_conventional=True
flow_vs_conventional_time=0.977x
```

## Semantic conclusion

A fixed Manifest-only system is deliberately wrong during the Adapt and Acquire portions of every episode: two wrong mode ticks per episode.

Both stateful implementations follow the required trajectory exactly and recover in the same two ticks.

Therefore:

> The value of Capability3 here is making the adaptation/acquisition trajectory explicit. The transition semantics are not more powerful than an equal-information conventional finite-state machine.

## Native execution control

The transition graph has only:

```text
3 modes × 4 signals = 12 state/signal combinations
```

So we tested two equal-information implementations over 3,000,000 episodes / 12,000,000 transitions:

1. conventional branch FSM;
2. 12-entry / 12-byte transition lookup table.

### Runner A — Python 3.11 CI job / native C

```text
fixed_manifest_wrong_ticks=6000000
branch_fsm_wrong_ticks=0
lut_fsm_wrong_ticks=0
mean_recovery_ticks=2
transition_lut_entries=12
transition_lut_bytes=12

branch FSM:
  seconds_avg=0.011249
  mtransitions_s=1066.765

12-entry LUT:
  seconds_avg=0.025077
  mtransitions_s=478.525

lut_vs_branch_time=2.229x
semantic_equivalence=true
```

### Runner B — Python 3.12 CI job / native C

```text
fixed_manifest_wrong_ticks=6000000
branch_fsm_wrong_ticks=0
lut_fsm_wrong_ticks=0
mean_recovery_ticks=2
transition_lut_entries=12
transition_lut_bytes=12

branch FSM:
  seconds_avg=0.011260
  mtransitions_s=1065.693

12-entry LUT:
  seconds_avg=0.025048
  mtransitions_s=479.072

lut_vs_branch_time=2.224x
semantic_equivalence=true
```

## Reproduced negative result

The tiny transition LUT is about **2.22x slower** than the conventional branch FSM on both runners even though it is only 12 bytes and semantically identical.

This is an important negative result. The regular four-signal workload is highly predictable, so a modern CPU can execute the small branch graph very efficiently. Replacing it with dependent table lookup adds overhead rather than removing it.

## Execution rule emerging from the evidence

BardoCompute now has two very different control shapes:

### High-dimensional temporal policy

A verdict depends jointly on multiple fields such as:

- current orientation;
- current phase;
- previous phase;
- dwell-time bucket;
- regression/discontinuity history;
- decision state;
- active capability mode.

For this shape, the 16-bit state-indexed 64 KB LUT was much faster than repeatedly decoding and evaluating all predicates in the measured native workload.

### Low-cardinality capability transition graph

Only three modes and four regular signals are involved.

For this shape, the ordinary branch FSM wins decisively over a tiny LUT.

Therefore the current evidence argues against a universal lookup-machine architecture.

A more defensible execution model is:

```text
complex/high-dimensional state predicate
        -> state-indexed LUT

small/predictable transition graph
        -> branch FSM
```

or, combined:

```text
16-bit temporal-capability state
        |
        +-- complex policy/verdict --> 64 KB indexed policy
        |
        +-- simple capability flow --> branch FSM
```

## Relation to Tao

Under the current engineering abstraction, Tao-as-flow-law can describe why the system changes its active capability mode, but the efficient low-level execution of that flow is simply a small predictable finite-state machine.

This distinction is useful:

- **semantic layer:** Manifest / Acquire / Adapt and their trajectory;
- **execution layer:** choose the cheapest implementation for the actual state graph.

## Next falsification

The regular recovery pattern is intentionally easy to predict. The next benchmark should disturb it with:

- delayed gap detection;
- repeated HOLD periods;
- missing or late EVIDENCE_READY;
- a second environment change while already acquiring;
- out-of-order signals;
- discontinuity/restart during adaptation.

Then measure:

- wrong-mode ticks;
- unsafe Manifest ticks after a shock;
- time to correct mode;
- time to recover to Manifest;
- branch FSM vs indexed execution under increasingly unpredictable signal entropy.

This can identify the point where a branch-based capability flow stops being the best execution path.