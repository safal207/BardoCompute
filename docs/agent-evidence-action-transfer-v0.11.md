# Agent Evidence → Decision → Action Transfer v0.11

## Status

Pre-registered before hosted results.

## Question

Does the architecture established in the recovery-state domain transfer to an agent-style evidence/decision/action flow without changing the core roles?

Target separation:

```text
evidence provenance / revalidation
  -> is the cached authority state still credible/fresh enough?

decision binding
  -> which exact action was authorized?

decision reference
  -> is this authorization being consumed once or replayed?

action-boundary fence
  -> may the requested action take effect under current authority?

outcome receipt
  -> evidence for later calibration, not proof that earlier state was eternally fresh
```

## Claims explicitly forbidden

```text
proof artifact == dispatch receipt
state hash == live freshness guarantee
decision for action A == authority for action B
old valid decision == permanently valid decision
```

## Workload

Reuse the v0.6 hidden authority-epoch environments:

```text
16 seeded environments
hazard regimes .0005 / .0020 / .0080 / .0250
randomized regime order and duration
future authority changes hidden from the agent
```

At every tick the agent has a requested action and mints a decision from its currently cached authority epoch.

Deterministic adversarial noise injects:

```text
wrong-action binding attempts
replayed decision references
hidden authority changes between revalidations
```

No future restart boundary, true future hazard, or oracle validity label is provided to the policy.

## Policies

```text
artifact-only EWMA
  adaptive evidence revalidation
  no action fence

per-action revalidation + fence
  authoritative refresh before every action
  action/epoch/replay fence

fixed fenced candidates
  1 / 8 / 16 / 32 / 64 / 128

EWMA + fence
rolling + fence
```

The strongest fixed fenced comparator is selected after the fact per seed/cost profile where economics are reported.

## Fence semantics

An action is admissible only if all conditions hold:

```text
decision.authority_epoch == current_resource_epoch
decision.bound_action == requested_action
decision_ref has not already been consumed
```

A successful decision reference is consumed once.

Two independently written equal-information fence functions are evaluated. Their applied/rejected outcomes must match exactly.

## Safety metrics

Count applied effects separately:

```text
stale_authority_effects
wrong_action_effects
replay_effects
unsafe_effects_total
```

Rejected attempts are **availability/backpressure**, not unsafe effects.

## Economics

For fenced policies only:

```text
operational_cost
  = revalidation_count * revalidation_cost
  + rejected_action_count * rejection_cost
```

Frozen cost profiles:

```text
revalidation_cost / rejection_cost
2 / 5
8 / 5
32 / 5
```

No unsafe-action penalty is included in fenced optimization because unsafe applied effects are required to be zero.

## Predeclared acceptance criteria

The transfer is supported only if:

1. artifact-only execution produces non-zero stale-authority applied effects;
2. injected wrong-binding attempts produce non-zero wrong-action effects without a fence;
3. injected replay attempts produce non-zero replay effects without a fence;
4. every fenced policy has `unsafe_effects_total == 0` for every seed;
5. independently written equal-information fences produce identical applied/rejected behavior;
6. adaptive fenced policies use fewer median revalidations than per-action revalidation;
7. no future boundary/hazard information is used;
8. economic results retain negative profiles rather than retuning estimators after validation.

Economic superiority over the strongest fixed policy is **not** required for semantic transfer; it is reported as secondary evidence because v0.9 already established that question in the recovery domain.

## Interpretation guardrail

Passing v0.11 would support:

> evidence freshness, decision binding, replay protection, and action admissibility remain causally distinct in an agent-style execution flow.

It would not prove that a proof service can attest caller-side dispatch, or that a decision artifact proves the action was actually consumed.

## Next step only if v0.11 survives

Add an explicit outcome/dispatch receipt and test the distinction:

```text
decision_ref -> authorization identity
execution receipt -> consumption/effect evidence
```

Then attack crash/retry/idempotency boundaries rather than adding another estimator.
