# Regret-Aware Policy Orientation v0.5 — strong negative result

## Question

Can a small partial-feedback meta-controller choose among already-established cadence policies, preserve most of EWMA's median advantage, and approach rolling's safer downside tail after explicit policy-switch cost?

This experiment was motivated by v0.3/v0.4:

- EWMA had the strongest median performance but a wider tail;
- rolling had a slightly weaker median but a much tighter tail;
- a hard uncertainty gate failed catastrophically;
- no single cadence estimator dominated every cost/regime surface.

The hypothesis was therefore deliberately moved one level up: keep multiple candidate policies and learn which one deserves control.

## Executable pieces

- `src/bardocompute/policy_orientation.py`
- `tests/test_policy_orientation.py`
- `benchmarks/regret_aware_policy_orientation.py`

The selector is an EXP3-style partial-feedback learner with fixed-share forgetting. It is an engineering falsification kernel, not a claim of a novel or theoretically optimal bandit algorithm.

Candidate policies:

```text
fixed_8
fixed_16
fixed_32
fixed_64
fixed_128
fixed_256
EWMA hazard cadence
rolling hazard cadence
```

Predeclared selector settings:

```text
block_size=1024
exploration=0.08
learning_rate=0.04
share=0.03
switch_cost=4 probe-cost units
```

The selector receives realized loss only for the policy that actually controlled the block. Unchosen policies do **not** receive free counterfactual outcomes. Probe evidence produced by the actually executed trajectory is common paid evidence and may update the EWMA/rolling hazard views.

No selector parameter was tuned on either reported validation family.

## Acceptance criterion

Relative rather than absolute criteria were frozen before the hosted run:

1. retain at least half of EWMA's median gain over the best fixed cadence;
2. close at least half of the distance from EWMA's worst case toward rolling's worst case.

Both had to pass.

## Frozen v0.3 family

32 original seeds × 9 cost profiles = 288 comparisons.

```text
EWMA:
  win_rate=0.788
  median_ratio=0.950
  p90_ratio=1.026
  worst_ratio=1.239
  median_oracle_gap_closed=0.537

rolling:
  win_rate=0.729
  median_ratio=0.953
  p90_ratio=1.000
  worst_ratio=1.031
  median_oracle_gap_closed=0.425

partial-feedback selector:
  win_rate=0.000
  median_ratio=1.763
  p90_ratio=3.291
  worst_ratio=5.282
  median_oracle_gap_closed=-7.322
  median_switch_rate=0.879
```

The selector lost to the strongest fixed cadence on every reported seed/profile.

Its policy occupancy remained nearly uniform:

```text
fixed_8   0.124
fixed_16  0.122
fixed_32  0.121
fixed_64  0.127
fixed_128 0.118
fixed_256 0.117
EWMA      0.136
rolling   0.136
```

Acceptance thresholds:

```text
median_limit=0.975
worst_limit=1.135
median_pass=false
worst_pass=false
```

## Held-out family

A separate untouched 32-seed family was generated from a disjoint seed sequence and evaluated with the same nine cost profiles.

```text
EWMA:
  win_rate=0.823
  median_ratio=0.951
  p90_ratio=1.021
  worst_ratio=1.203
  median_oracle_gap_closed=0.540

rolling:
  win_rate=0.708
  median_ratio=0.955
  p90_ratio=1.000
  worst_ratio=1.050
  median_oracle_gap_closed=0.377

partial-feedback selector:
  win_rate=0.000
  median_ratio=1.800
  p90_ratio=3.474
  worst_ratio=5.796
  median_oracle_gap_closed=-7.872
  median_switch_rate=0.889
```

Policy occupancy again stayed nearly uniform:

```text
fixed_8   0.122
fixed_16  0.128
fixed_32  0.127
fixed_64  0.124
fixed_128 0.120
fixed_256 0.116
EWMA      0.131
rolling   0.132
```

Acceptance thresholds:

```text
median_limit=0.976
worst_limit=1.126
median_pass=false
worst_pass=false
```

The failure therefore transfers to a held-out family rather than being peculiar to the original robustness seeds.

## Why it fails

The result is not a small miss that should be repaired by immediate parameter tuning.

The deployment trajectories provide only on the order of a few dozen 1024-step policy blocks per environment while the selector is trying to discriminate eight arms under partial feedback. Exploration therefore consumes a material fraction of the entire useful horizon.

Observed evidence is consistent with this mechanism:

- policy share stays close to uniform rather than concentrating on a useful expert;
- median switch rate is about `0.88–0.89`;
- every switch pays explicit cost;
- bad fixed cadences are repeatedly given control long enough to accrue stale/probe regret;
- only the chosen policy receives realized loss, so learning is deliberately slower than a full-information oracle selector.

The meta-controller therefore violates the same payback condition that motivated Living Process at the action layer.

## Recursive payback insight

The important result is not "bandits are bad". It is narrower:

> **Changing the rule used to adapt is itself an adaptation and must repay its own observation, exploration, learning, and switching costs.**

A useful working condition is:

```text
expected lifetime of policy advantage
    > time/cost required to identify and switch to that policy
```

or symbolically:

```text
tau_policy_advantage / tau_policy_learning  >> 1
```

when switching and exploration costs are non-negligible.

This is structurally the same condition already observed for morphology and execution adaptation:

```text
short-lived regime  -> adaptation cannot repay itself
long-lived regime   -> adaptation may become profitable
```

The same principle therefore appears recursively at the meta-policy level, but the current broad eight-arm selector does **not** earn promotion.

## Decision

Reject the v0.5 partial-feedback meta-controller as a core mechanism.

Do not retune EXP3 exploration, learning rate, share, block size, arm set, or switch cost on the frozen or held-out families and then report the same families as independent confirmation.

The implementation remains in the research branch as executable negative evidence.

## Pruning consequence

Do not add another permanent semantic layer for `P*(t)` yet.

The stable center remains:

```text
T*(t): TRUST
H*(t): HAZARD
S*(t): OBSERVATION
O*(t): ORIENTATION / ACTION
```

Policy-level adaptation is now governed by the same payback rule rather than promoted automatically as a fifth core axis.

## Next falsification — cross-domain transfer

Further optimizing cadence on the same synthetic family has declining scientific value. The stronger next test is transfer.

Freeze the supported `TRUST -> HAZARD -> OBSERVE -> ORIENT` concepts and apply them unchanged to an unrelated recovery-state workload where:

- transitions can be normal, interrupted, stale, replayed, or reordered;
- checking authoritative recovery state has a measurable cost;
- staying stale has a measurable unsafe/regret cost;
- the environment's failure/recovery hazard changes over time;
- no hidden future boundary is supplied to the policy.

Test whether the same qualitative regions reappear:

```text
stable / low hazard       -> sparse observation
rising hazard              -> shorter observation cadence
stale calibration          -> shrink / relearn
single detected change     -> not sufficient authority to adapt
persistent profitable shift -> adapt
```

If the phase structure transfers without rewriting the central decision variables, that is much stronger evidence for a general adaptive-process principle than another cadence-specific percentage gain.

## Narrow conclusion

> **Meta-adaptation does not escape the Living Process rule. The mechanism that decides how to adapt must itself persist long enough to repay the cost of learning and changing that mechanism.**

This is a working research principle, not a universal theorem.