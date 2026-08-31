# BARDO LOGOS learning-efficiency benchmark v0.3

## Question

Can a system learn more efficiently from bounded BARDO-LOGOS relations than
from all per-lane BARDO-TX1 results?

This experiment does not assume the answer is always yes. It separates two
cases:

1. a task whose downstream outcome depends on global semantic relations;
2. a task where a global summary is provably insufficient because the location
   of one consequential witness matters.

The benchmark is synthetic and controlled. It measures representation and
sample efficiency, not general intelligence, production accuracy, FPGA speed,
or real-world business value.

## Fixed learner boundary

Every representation uses the same learner:

```text
model: averaged passive-aggressive binary linear classifier
feature dimension: 128
trainable weights: 128
bias: 1
total trainable parameters: 129
epochs: 10
training seeds: 11, 29, 47
held-out examples per task: 1,536
target metric: balanced accuracy >= 0.80
```

The fixed encoders are not trained. Each encoder maps its logical record into
the same 128-feature learner budget.

## Compared representations

| Representation | Logical record | Bits/example |
| --- | --- | ---: |
| RAW | all `71 × 23-bit` TX1 semantic results | 1,633 |
| LOGOS | one bounded global semantic word | 128 |
| HYBRID | LOGOS plus four 32-bit witness records | 256 |

The 64-bit ordered root is not used as a numeric learning feature. Its avalanche
behavior makes it useful for integrity and provenance, not as a semantic
embedding. LOGOS learning uses the bounded counters and ratios. HYBRID adds the
four highest-severity witnesses with lane position and local TX1 facts.

## Task A — global recovery outcome

Frames are generated from varied target, transition, discontinuity, and invalid
rates. A controlled downstream teacher computes:

```text
score =
    1.3
    - 0.9   * invalid_count
    - 0.055 * discontinuity_count
    + 0.045 * policy_allow_count
    + 0.012 * transition_count
    - 0.012 * abs(target_count - 106)
    + bounded_noise

label = score > 1.0
```

The dataset is balanced after generation. The teacher score and label are never
included in any representation. This task asks whether known semantic
sufficient statistics reduce the examples required by a fixed small learner.

Expected falsification:

- LOGOS should outperform RAW at small sample sizes;
- HYBRID may match or improve LOGOS but is not required to use its witnesses;
- no conclusion transfers automatically to tasks whose labels need information
  omitted by the global summary.

## Task B — localized escalation

Each positive/negative pair starts from the same frame. Two candidate lanes are
set to the same neutral value. The same invalid witness is then placed either:

- in an outer critical region (`label=1`); or
- in an inner ordinary region (`label=0`).

The pair therefore has:

```text
identical global semantic counters
identical multiset of lane results
one invalid witness in each frame
only ordered location differs
```

Consequences:

- LOGOS without witnesses must remain near chance by construction;
- RAW can learn location from all 71 lane records;
- HYBRID can learn location from the bounded witness record.

This is an explicit information-loss test. A result where LOGOS stays at chance
is a success of the benchmark, not a failure of the implementation.

## Sample-efficiency calculation

For each task and representation, the benchmark records the smallest tested
training set whose median balanced accuracy across all three seeds reaches
`0.80`.

Logical training input is then:

```text
examples_to_target × logical_bits_per_example
```

For localized escalation, the release gate requires:

```text
HYBRID examples <= 64
RAW examples <= 256
RAW / HYBRID examples >= 4×
RAW / HYBRID logical training bits >= 20×
LOGOS does not reach 0.80 and remains <= 0.55
```

## Claim boundary

A positive result supports only this statement:

> On two frozen synthetic BARDO tasks, bounded semantic summaries and witnesses
> can improve the sample and logical-data efficiency of the same 129-parameter
> linear learner.

It does not prove:

- better learning on real payment, agent, or hardware traces;
- lower wall-clock training cost on every implementation;
- lower energy consumption;
- superiority over learned embeddings, transformers, graph networks, or CPUs;
- that one 128-bit global word is sufficient for every decision.

The next valid gate is replaying the same protocol on a real transition-heavy
trace with labels defined independently of the LOGOS feature design.
