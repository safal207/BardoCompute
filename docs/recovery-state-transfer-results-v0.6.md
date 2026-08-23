# Recovery-State Transfer v0.6 — first cross-domain evidence

## Question

Does the already-supported hazard-aware observation rule transfer without changing its cadence formula from the synthetic hazard benchmark into a recovery-state domain with authoritative epochs, restart/interruption risk, and noisy/reordered recovery evidence?

The transferred cadence rule is unchanged:

```text
cost_rate(d)
  ~= probe_cost / d
   + change_hazard * regret_given_change * d / 2

d* = sqrt(2 * probe_cost / (change_hazard * regret_given_change))
```

The semantics around it are different:

- the environment has an authoritative recovery epoch;
- restart/interruption increments that epoch;
- a local process can continue operating on an older epoch until it buys a check;
- stale operation accrues unsafe/regret cost;
- a paid authoritative check reveals the current epoch and restart count since the previous check;
- recovery receipts may be stale, replayed, duplicated, or premature;
- the existing epoch/order guard handles receipt provenance independently of the cadence policy.

Future restart boundaries, true regime labels, and future hazards are hidden from the policy.

## Executable pieces

- `benchmarks/recovery_state_transfer.py`
- `.github/workflows/recovery-transfer.yml`

The benchmark reuses the existing `evaluate_hazard_cadence` implementation and the existing `step_stochastic_capability` recovery guard. No recovery-specific cadence formula was introduced.

## Workload

```text
seeds=16
hidden hazard levels=0.0005 / 0.0020 / 0.0080 / 0.0250
regime order=randomized per seed
regime duration=7000..11000 steps
probe costs=2 / 8 / 32
stale regrets=5 / 25
fixed controls=8 / 16 / 32 / 64 / 128 / 256
```

The strongest fixed cadence is chosen after the fact for every seed/cost profile.

Two hosted runners reproduced the same deterministic outcome:

- Python 3.11, westcentralus;
- Python 3.12, eastus2.

Dedicated workflow: **Recovery State Transfer Benchmark #2**.

## Hosted result

Across 16 seeds × 6 cost profiles = 96 comparisons per adaptive estimator:

```text
EWMA:
  win_rate=0.875
  median_loss_ratio=0.915
  p90_loss_ratio=1.010
  worst_loss_ratio=1.101
  median_unsafe_ratio=1.098

rolling:
  win_rate=0.812
  median_loss_ratio=0.924
  p90_loss_ratio=1.000
  worst_loss_ratio=1.025
  median_unsafe_ratio=1.059
```

Thus the unchanged hazard-aware cadence rule transfers as an **economic loss** improvement on this recovery workload:

- EWMA median total loss is about 8.5% lower than the strongest fixed cadence;
- rolling median total loss is about 7.6% lower;
- rolling again has the tighter downside tail.

This qualitatively repeats the earlier synthetic result rather than requiring a new recovery-specific rule.

## Hidden-hazard phase behavior

The adaptive policy is not given the true hazard level, but its observed cadence changes monotonically with the hidden environment.

EWMA median selected interval by true hidden hazard:

```text
0.0005 -> 50.3
0.0020 -> 27.2
0.0080 -> 13.8
0.0250 ->  9.0
```

Rolling:

```text
0.0005 -> 21.3
0.0020 -> 18.9
0.0080 -> 15.2
0.0250 -> 11.1
```

This is direct cross-domain support for the qualitative phase relation:

```text
lower inferred change hazard  -> observe less often
higher inferred change hazard -> observe more often
```

without providing phase labels or future boundaries to the policy.

## Provenance result

The recovery stream injects large volumes of misleading receipt traffic across the adaptive runs:

```text
stale receipts     = 270,158
premature receipts = 15,819
duplicate receipts = 412,105
```

The existing epoch/order recovery guard produced:

```text
EWMA post-probe false recoveries    = 0
rolling post-probe false recoveries = 0
```

The metric intentionally counts false recovery **after an authoritative check and receipt processing**. Ordinary stale exposure between checks is tracked separately as unsafe ticks; it is not mislabelled as a provenance failure.

This separation matters:

```text
cadence -> how long local knowledge may remain stale
provenance guard -> whether observed recovery evidence is allowed to close recovery
```

The two correctness mechanisms are not conflated.

## Important safety caveat

The transfer is not a blanket success.

Although adaptive cadence reduces total economic loss, it can tolerate more stale/unsafe exposure than the strongest fixed cadence:

```text
EWMA median_unsafe_ratio    = 1.098
rolling median_unsafe_ratio = 1.059
```

Representative profiles make the tradeoff visible:

```text
probe_cost=8, stale_regret=25
EWMA:    median_loss=0.956x fixed, median_unsafe=1.242x
rolling: median_loss=0.943x fixed, median_unsafe=1.098x

probe_cost=2, stale_regret=5
EWMA:    median_loss=0.910x fixed, median_unsafe=1.236x
rolling: median_loss=0.924x fixed, median_unsafe=1.188x
```

Therefore the statement

> lower scalar loss implies a safer adaptive process

is rejected.

The payback objective can economically prefer fewer checks even when that increases the duration of stale authority exposure.

For recovery, finance, authorization, and agent-execution domains, unsafe exposure may be a hard constraint rather than a fungible cost term.

## New causal distinction

The transfer introduces a critical distinction without adding a new cultural/semantic layer:

```text
UTILITY / REGRET OBJECTIVE
        !=
SAFETY / RISK CONSTRAINT
```

A system may optimize expected utility only inside an admissible safety region.

A working constrained form is:

```text
minimize expected observation + adaptation regret
subject to unsafe_exposure <= risk_budget
```

or, for strict authority boundaries:

```text
if safety constraint is violated:
    economic payback cannot authorize the action
```

This is stronger than merely increasing the numerical penalty for unsafe events: a sufficiently large future reward should not be able to buy permission to violate a non-fungible authority constraint.

## Relation to Recursive Adaptation Payback

The cross-domain result supports the economic part of the working principle:

> observation frequency should increase when the inferred hazard of becoming stale makes delayed knowledge more expensive than checking.

But it also bounds that principle:

> adaptation payback operates **inside** safety/authority constraints; it does not replace them.

The current synthesis is therefore:

```text
1. establish admissibility / authority / safety
2. estimate trust and hazard
3. optimize observation/adaptation payback inside the admissible region
4. keep the resulting decision revisable
```

## Decision

Promote the recovery transfer as evidence that hazard-aware observation has cross-domain economic value.

Do **not** promote the current scalar objective as a safety-preserving controller.

## Next falsification — Risk-Constrained Orientation

Before transferring to a financial or agent-execution domain, test a minimal constraint rather than adding another meta-policy:

1. preserve the same recovery workload and hidden hazard process;
2. define a predeclared unsafe-exposure budget / maximum stale-age constraint;
3. compare:
   - strongest fixed cadence;
   - unconstrained EWMA / rolling;
   - constrained adaptive cadence;
   - oracle constrained control;
4. charge all probes normally;
5. measure both total loss and constraint violations;
6. the constrained adaptive rule earns its place only if it preserves most of the economic gain while never purchasing that gain by exceeding the declared safety budget;
7. only after that, transfer the unchanged constrained `TRUST -> HAZARD -> OBSERVE -> ORIENT` stack to agent-evidence / authorization workloads.

## Narrow conclusion

> **The same hazard-aware observation economics transferred to recovery state, but economic optimality and safety are different causal objectives. Adaptive payback must be subordinate to non-fungible authority/risk constraints when stale operation is unsafe.**
