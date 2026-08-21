# Calibration-Aware Payback v0.1 — Hosted Results

## Question

When does paying to update knowledge become cheaper than continuing to trust a historical calibration?

The experiment follows the negative result from Observation Payback v0.1: a context-conditioned payback policy can win under matched calibration and then lose under distribution shift.

The new hypothesis is:

```text
knowledge has a useful lifetime
```

and therefore calibration trust should depend on measurable provenance rather than being treated as permanently valid.

## Trust kernel

`src/bardocompute/calibration_trust.py`

```text
sample_trust      = n / (n + prior_strength)
age_trust         = exp(-ln(2) * age / half_life)
drift_trust       = 1 - drift_score
calibration_trust = 1 - brier_score

trust = sample_trust
      * age_trust
      * drift_trust
      * calibration_trust
```

This multiplicative form is intentionally conservative and is a falsifiable engineering heuristic, not a universal statistical law.

When trust falls, historical correction probabilities are shrunk toward another prior:

```text
p_adjusted = trust * p_historical + (1 - trust) * p_prior
```

For the static uncertainty control, the prior is the global calibration distribution. For the online drift-aware control, the prior is a recent estimate updated from paid/revealed outcomes.

## Benchmark

`benchmarks/calibration_aware_payback.py`

Hosted GitHub Actions CI #382, Python 3.11:

```text
107 passed
calibration_samples=6480
deployment_steps=90000
shift_at=45000
trained_global_threshold=6/8
probe_every=64
probe_cost=2.00
```

The same benchmark step completed successfully in the Python 3.12 matrix as well.

The deployment stream has 27 context cells (`3 phases x 9 sentinel-hit counts`). The first half follows calibration. The second half applies a controlled shift whose severity is swept from `0.00` to `0.40`. The shift makes historically attractive positive-sentinel cells more deceptive: beneficial-correction probability falls while harmful-correction probability rises.

Four strategies are compared:

1. **global threshold** — one calibration-trained hit threshold (`6/8`);
2. **static payback** — context-conditioned payback using frozen historical probabilities;
3. **uncertainty-shrunk** — frozen calibration whose influence decays toward a global prior;
4. **drift-aware** — paid sparse probes plus outcomes naturally revealed by revisits update a recent estimate; historical trust falls with age, drift, and Brier error.

A probe is not free. A skipped decision is sampled only every 64 opportunities and pays an explicit cost of `2.00`.

## Hosted result

```text
severity,global,static,shrunk,drift-aware,drift/static,drift/global
0.00,54.031,52.301,54.496,54.226,1.037,1.004
0.08,56.426,53.110,53.400,53.776,1.013,0.953
0.16,58.811,54.551,51.811,51.983,0.953,0.884
0.24,60.578,54.845,50.403,50.629,0.923,0.836
0.32,62.470,56.390,49.204,48.951,0.868,0.784
0.40,64.807,57.374,47.996,47.649,0.831,0.735
```

The first tested severity where paid drift-aware recalibration beats frozen static payback is:

```text
0.16
```

At zero drift, drift-aware recalibration is about **3.7% worse** than static payback:

```text
54.226 / 52.301 = 1.037x
```

The probe/update machinery is therefore not free and should not run merely because it exists.

At severity `0.16`, the ordering changes:

```text
static      = 54.551
shrunk      = 51.811
drift-aware = 51.983
```

Both uncertainty-aware approaches beat static calibration, but simple shrinkage is still slightly cheaper than online recalibration.

At severity `0.32`, online recalibration finally beats both static payback and simple uncertainty shrinkage:

```text
static      = 56.390
shrunk      = 49.204
drift-aware = 48.951
```

At severity `0.40`:

```text
static      = 57.374
drift-aware = 47.649
```

or:

```text
drift-aware / static = 0.831x
```

about **16.9% lower economic loss** in this constructed workload, after charging sparse probe cost.

## Main result: three calibration regimes

The experiment exposes three qualitatively different regions:

```text
low drift
    -> keep historical calibration

moderate drift
    -> uncertainty shrinkage is enough

strong drift
    -> paid online recalibration repays its cost
```

This is more useful than a claim that one adaptive method is universally best.

A rough observed phase map for this particular setup is:

```text
severity 0.00-0.08 : STATIC preferred over drift-aware
severity 0.16-0.24 : SHRINK preferred
severity 0.32-0.40 : DRIFT-AWARE preferred
```

These numerical boundaries are workload-specific and must not be treated as universal constants.

## Living Process implication

The center of orientation now has three coupled questions:

```text
T*(t): how much should I trust the model used to interpret evidence?
S*(t): where/how deeply should I observe?
O*(t): KEEP / HOLD / ADAPT?
```

A current working chain is:

```text
calibration provenance
        ↓
TRUST / STALENESS
        ↓
observation payback
SKIP / HOLD / REVISIT
        ↓
new evidence / zoom
        ↓
living-process payback
KEEP / HOLD / ADAPT
        ↓
outcome
        └────→ recalibration evidence
```

This suggests a stronger but still testable principle:

> An adaptive process should not only keep actions revisable; it should keep the **authority of its own calibration** revisable, and pay for recalibration only when expected drift-regret exceeds the cost of learning again.

## Negative results retained

- Drift-aware recalibration loses to static payback when there is little or no drift.
- At moderate drift, a simpler uncertainty-shrinkage control is slightly cheaper than paid online updating.
- Therefore `online learning everywhere` is rejected by this workload in the same way earlier experiments rejected `LUT everywhere`.

## Next falsification

1. Remove the externally supplied `severity` from all decision logic (it is currently only a benchmark generator parameter, not policy input) and estimate drift onset/crossover from stream evidence alone.
2. Sweep probe frequency and probe cost to find whether observation cadence itself should be payback-selected.
3. Add abrupt, gradual, reversible, and recurring drift with equal final aggregate statistics.
4. Measure time-to-distrust and time-to-retrust after the environment returns.
5. Compare rolling-window, EWMA, Bayesian change-point, and simple fixed-control detectors with equal information/cost accounting.
6. Transfer the unchanged trust/observe/action stack to recovery-state and agent-evidence workloads.

## Scientific boundary

This result is a decision-theoretic engineering finding in a constructed benchmark. It does not establish a universal law of cognition, economics, finance, biology, relationships, or physics. The useful research target is the measurable crossover between the cost of stale knowledge and the cost of updating it.
