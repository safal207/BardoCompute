# Hazard-Aware Cadence Robustness v0.3 — Hosted Results

## Question

Does hazard-aware observation cadence remain useful when regime order, regime duration, random seed, probe cost, and stale consequence all vary?

The benchmark was predeclared to retain losing profiles rather than average them away.

Executable benchmark:

- `benchmarks/hazard_cadence_robustness.py`

Hosted GitHub Actions CI #424, Python 3.11:

```text
130 passed
seeds=32
hazard_levels=0.0005,0.0010,0.0025,0.0050,0.0100,0.0200
regime_order=randomized_per_seed
regime_length=uniform_integer_4000_to_8000
probe_costs=2,8,32
stale_regrets=2,10,50
```

This creates `32 x 3 x 3 = 288` seed/profile comparisons per adaptive estimator. The strongest fixed interval is selected **after the fact** for each seed/profile, making it a deliberately strong control. Online estimators see only paid past/present transition counts; they receive no regime labels, boundaries, future hazards, or future durations.

## Overall result

```text
[overall_288_seed_profiles]
cumulative: win_rate=0.500 ties=32 median_ratio=1.000 p90_ratio=1.042 worst_ratio=1.152 median_oracle_gap_closed=0.002
ewma:       win_rate=0.788 ties=0  median_ratio=0.950 p90_ratio=1.026 worst_ratio=1.239 median_oracle_gap_closed=0.537
rolling:    win_rate=0.729 ties=64 median_ratio=0.953 p90_ratio=1.000 worst_ratio=1.031 median_oracle_gap_closed=0.425
```

Interpretation of the ratio:

```text
adaptive_loss / best_fixed_loss
< 1.0 -> adaptive wins
= 1.0 -> tie
> 1.0 -> adaptive loses
```

### EWMA

EWMA is the strongest broad performer in this sweep:

- wins `78.8%` of the 288 seed/profiles;
- median ratio `0.950`, roughly 5% lower loss than the best hindsight-selected fixed interval;
- closes a median `53.7%` of the available fixed-to-oracle gap;
- but p90 is `1.026` and worst case is `1.239`.

Therefore the broad claim `adaptive cadence always wins` is rejected.

### Rolling

Rolling hazard is slightly weaker on median but has a much tighter downside tail:

- win rate `72.9%`;
- median ratio `0.953`;
- p90 ratio `1.000`;
- worst ratio `1.031`;
- median oracle-gap closure `42.5%`.

This makes rolling interesting as a safer adaptive control when tail regret matters more than median improvement.

### Cumulative

Cumulative hazard is effectively neutral overall:

- win rate `50.0%` plus 32 ties;
- median ratio `1.000`;
- median oracle-gap closure `0.2%`.

It adapts too slowly to changing hazard and should not remain the default candidate.

## Important profile structure

The adaptive methods are not uniformly useful across consequence/cost profiles.

Examples:

```text
probe_cost=8, stale_regret=2
EWMA:    win_rate=1.000 median_ratio=0.912 worst_ratio=0.983
Rolling: win_rate=1.000 median_ratio=0.916 worst_ratio=0.976
```

Both adaptive estimators beat the best fixed cadence on every one of the 32 seeds in this profile.

But:

```text
probe_cost=2, stale_regret=50
EWMA:    win_rate=0.125 median_ratio=1.024 worst_ratio=1.239
Rolling: win_rate=0.000 with 32 ties at ratio=1.000
```

When stale consequence is so large relative to probe cost that the best fixed strategy is already at the minimum practical interval, an adaptive estimator has little room to improve and estimation lag can make it worse.

This exposes a useful saturation boundary:

```text
if the economic optimum is already clipped at min_interval,
there is no adaptation headroom left in cadence.
```

## Main supported conclusion

> **Hazard-aware cadence has reproducible value across many randomized environments, but only where there is genuine interval-selection headroom. When the safe economic optimum is already pinned to the minimum observation interval, adaptive hazard estimation can add regret rather than remove it.**

This is stronger than the one-run v0.2 result because it preserves all losing seeds and compares against the strongest fixed interval selected separately for every seed/profile.

## Center-of-orientation implication

The observation decision now needs a headroom test before adaptive scheduling is useful:

```text
T*(t): trust current knowledge
H*(t): estimate future change hazard
R*(t): estimate stale consequence / regret
B*(t): determine whether cadence has economic headroom
S*(t): choose observation cadence / scale
O*(t): KEEP / HOLD / ADAPT
```

`B*(t)` is not proposed as a new philosophical layer. It is a pruning condition derived from the existing cost boundary:

```text
if optimal cadence is clipped at min_interval:
    adaptive cadence has no useful search space
    -> use safe minimum cadence
else:
    hazard-aware adaptive cadence may repay estimation cost
```

## Negative results retained

- EWMA loses in 21.2% of seed/profiles overall.
- EWMA worst observed ratio is `1.239`.
- Rolling is safer in the tail but has lower overall win rate and can collapse to the minimum interval, producing ties rather than gains.
- Cumulative hazard provides almost no median advantage.
- No estimator is promoted as a universal winner.

## Next falsification

1. Add an explicit **headroom gate** that selects fixed minimum cadence when the cost optimum is already clipped.
2. Compare `EWMA`, `rolling`, and `headroom-gated adaptive` on the same frozen 288-profile family without changing seeds.
3. Measure whether the gate improves p90/worst-case without erasing median gain.
4. If it passes, transfer the unchanged `TRUST -> HAZARD -> OBSERVE -> ACT` logic to a recovery-state workload and an agent-evidence workload.
5. Only after transfer should cadence be integrated into the main execution path.

## Scientific boundary

This is a constructed decision-theoretic benchmark. It does not establish a universal law of cognition, finance, relationships, biology, or economics. The supported result is narrower: in this workload family, the value of adaptive observation cadence depends on both change hazard and whether the cost surface leaves room to choose a cadence above the minimum safe interval.
