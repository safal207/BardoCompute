# Trajectory-Aware Computational Homeostasis v0.15

## Status

Pre-registered before evaluation on a new held-out family.

## Why v0.15 exists

The v0.14 level-only controller uses current internal stress but no trajectory information. Its first frozen-family sanity result reduced critical exposure but did not eliminate it: the controller often reacted after internal stress had already acquired enough upward momentum to cross the critical boundary.

The v0.14 validation family is therefore treated as spent evidence and will not be used to tune v0.15.

## Hypothesis

Current internal state is insufficient when the same state can belong to different trajectories.

Working form:

```text
same stress level + falling trajectory
    !=
same stress level + rapidly rising trajectory
```

A homeostatic exchange controller should therefore use both level and recent direction/rate of change.

## Frozen trajectory estimate

The controller observes only stress values that have already occurred.

```text
stress_slope_ema[t]
  = 0.20 * (stress[t] - stress[t-1])
  + 0.80 * stress_slope_ema[t-1]
```

Only positive slope is projected:

```text
projection_horizon = 16 ticks
projected_stress
  = stress[t] + max(0, stress_slope_ema[t]) * 16

effective_stress
  = max(stress[t], projected_stress)
```

The v0.14 dynamic release-cap function is then applied unchanged to `effective_stress`:

```text
effective_stress <= 70:
    no additional cap

70 < effective_stress < 100:
    cap decreases linearly from 96 to 32

effective_stress >= 100:
    cap = 32
```

No current/future hidden relief, regime label, route capacity, or arrival is supplied to the policy.

The constants `alpha=0.20` and `projection_horizon=16` are frozen before the new validation family is evaluated. They are engineering choices, not universal laws.

## Fresh validation family

```text
12 seeds
seed_i = 1310033 + i * 19001
16000 exchange steps / seed
```

The exchange generator and hidden-relief generator remain structurally unchanged from v0.14. Only the seed family changes.

## Comparators

Run on the same fresh family:

```text
v0.13 flow-preserving membrane, no internal-state feedback
v0.14 level-only homeostasis
best post-hoc zero-critical static release cap
v0.15 trajectory-aware homeostasis
```

Static caps remain:

```text
24 / 32 / 40 / 48 / 56 / 64 / 80 / 96 / 112 / 128
```

All policies use the same v0.13 routing logic and forbid discretionary admission shedding.

## Predeclared acceptance criteria

Promote v0.15 only if all conditions hold:

1. v0.13 has non-zero critical-stress ticks on at least 75% of seeds;
2. v0.15 has zero critical-stress ticks on every seed;
3. at least one zero-critical static cap exists for every seed;
4. median v0.15 delivered work is at least `1.08x` strongest static-safe service;
5. median v0.15 delivered work is at least `0.95x` v0.13 service;
6. median v0.15 lost-work ratio versus v0.13 is at most `1.10x`;
7. median v0.15 exchange-cost ratio versus v0.13 is at most `1.25x`;
8. admission shedding remains disabled;
9. no future hidden information is used.

The v0.14 level-only comparator is reported as an ablation. v0.15 does not require an arbitrary percentage win over v0.14; zero critical ticks plus the service/economic guardrails are the primary falsification.

## Narrow interpretation of a pass

> trajectory information can make internal-state exchange regulation anticipatory enough to preserve a predefined viability boundary while retaining materially more service than a static safe cap.

This would connect the earlier temporal-state result to exchange regulation: state plus direction can carry actionable information that the endpoint alone lacks.

## Failure interpretation

If trajectory awareness still crosses the critical boundary, then either the release actuator is too weak/slow, the projection model is inadequate, or the chosen viability/service requirements conflict on this workload.

Do not retune `alpha` or horizon on this validation family. A subsequent experiment would need a fresh family and a new causal hypothesis.