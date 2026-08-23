# Headroom Gate v0.4 — negative result retained

## Question

Can a conservative uncertainty-aware gate reduce the downside tail of EWMA hazard-aware probe scheduling without destroying its median advantage?

The gate was added only after the v0.3 robustness sweep exposed a real failure mode: EWMA had the best median performance across the frozen 32-seed × 9-cost family, but its worst seed/profile ratio reached `1.239x` the strongest fixed cadence.

The intended rule was deliberately minimal:

1. use the ordinary EWMA point hazard to select an adaptive cadence;
2. compute a Wilson upper confidence bound on recent change frequency using only already-paid probes;
3. compute the hazard at which the economic optimum reaches the configured minimum interval;
4. if the conservative upper hazard crosses that saturation point, force the safe minimum cadence.

No true phase label, hidden boundary, future hazard, or generator state is supplied to the policy.

## Executable pieces

- `src/bardocompute/headroom_gate.py`
- `tests/test_headroom_gate.py`
- `benchmarks/headroom_gate_robustness.py`

The robustness benchmark reuses the exact frozen v0.3 family:

- 32 predeclared seeds;
- probe costs `2 / 8 / 32`;
- stale regrets `2 / 10 / 50`;
- randomized order of six hazard levels;
- randomized regime duration;
- best fixed cadence selected after the fact for every seed/profile.

The gate therefore does not receive a friendlier workload than the baseline it is supposed to improve.

## Hosted result

Python 3.12, CI run #436:

```text
[overall_288_seed_profiles]
ewma:       win_rate=0.788 ties=0  median_ratio=0.950 p90_ratio=1.026 worst_ratio=1.239 median_oracle_gap_closed=0.537
rolling:    win_rate=0.729 ties=64 median_ratio=0.953 p90_ratio=1.000 worst_ratio=1.031 median_oracle_gap_closed=0.425
gated_ewma: win_rate=0.410 ties=96 median_ratio=1.000 p90_ratio=1.232 worst_ratio=1.338 median_oracle_gap_closed=0.000

gated_ewma_overall_median_gate_fraction=1.000
gated_vs_ewma_median_delta=+0.050
gated_vs_ewma_worst_delta=+0.099
```

The gate therefore fails its predeclared acceptance criterion on both axes:

- median performance worsens from `0.950` to `1.000`;
- worst-case performance worsens from `1.239` to `1.338`.

It does not merely trade average performance for safety. It loses both the median advantage and the downside-tail objective.

## Representative failures

### Probe cost 8, stale regret 10

```text
ewma:       median=0.923 p90=0.961 worst=0.997
gated_ewma: median=1.252 p90=1.325 worst=1.338
gate_fraction=1.000
```

The raw adaptive policy beats the strongest fixed cadence on every seed, while the hard gate forces the minimum cadence and loses on every seed.

### Probe cost 32, stale regret 50

```text
ewma:       median=0.925 p90=0.968 worst=0.995
gated_ewma: median=1.172 p90=1.243 worst=1.256
gate_fraction=1.000
```

Again, uncertainty-aware forcing removes a useful adaptive regime rather than protecting it.

### Probe cost 2, stale regret 50

```text
ewma:       median=1.024 worst=1.239
gated_ewma: median=1.000 worst=1.000
gate_fraction=1.000
```

This is the one type of saturated profile the gate was intended to protect. It does cap the EWMA failure here, but the same hard rule damages other profiles badly enough that the overall result is worse.

## Why the hard gate fails

The failure is causal rather than cosmetic.

A Wilson upper bound answers approximately:

> Could the true recent hazard plausibly be this high?

That is not the same question as:

> Is the minimum cadence the action with minimum expected regret now?

The hard gate converts epistemic uncertainty into control authority. When the saturation threshold is low, the conservative upper bound remains above it for long periods and the policy becomes stuck at the minimum interval. More probing does not automatically release the gate because the decision rule remains pessimistic.

This gives a useful negative principle:

```text
uncertainty != hazard
hazard != intervention authority
lack of confidence != command to maximize observation
```

In Living Process terms, `HOLD` must preserve revisability without becoming compulsive action.

## Decision

**Reject the hard Wilson-UCB-to-minimum headroom gate as a core mechanism.**

Do not retune the z-score on the same frozen 32 × 9 family. That would turn a falsification set into a tuning set and risk overfitting away the negative evidence.

The implementation remains in the research branch as executable negative evidence, not as a promoted mechanism.

## What the failure suggests next

The v0.3 and v0.4 results together show that no single policy dominates:

- EWMA has the strongest median behavior but a wider tail;
- rolling is slightly weaker at the median but much tighter in the tail;
- fixed minimum cadence is correct in saturated high-consequence/cheap-probe regions;
- other fixed cadences can be better when probing is expensive.

The next falsification should therefore stop asking one estimator to be universally correct.

### Regret-Aware Policy Orientation v0.5

Maintain a small set of already-established candidate policies and choose among them from paid evidence:

```text
fixed-safe candidates
EWMA hazard cadence
rolling hazard cadence
        ↓
realized / estimated regret + switching cost
        ↓
POLICY KEEP / HOLD / SWITCH
```

Candidate selection must not receive free counterfactual outcomes. If an unchosen policy cannot be scored from legitimately common observed evidence, its value must remain uncertain rather than being updated from hidden truth.

Suggested state for the next experiment:

```text
policy identity
policy dwell age
recent realized regret
regret uncertainty
switch cost
```

Acceptance criteria should be predeclared on a held-out seed family:

- retain most of EWMA's median advantage;
- approach rolling's downside tail;
- explicitly account for policy-switch cost;
- retain every losing seed/profile;
- compare against best fixed, EWMA, rolling, and an oracle policy selector.

## Narrow conclusion

> **A system that knows its estimate is uncertain should not automatically choose the most aggressive intervention. The adaptation rule itself is a revisable model whose usefulness depends on regime and cost surface.**

This is negative evidence in favor of policy-level orientation, not evidence for a universal meta-controller.