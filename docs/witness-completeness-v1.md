# Witness completeness v1 — an overload boundary, not a CPU breakthrough

Research snapshot: 2026-09-05. Status: synthetic falsification reproduced locally and on GitHub Actions. No production or physical-hardware claim.

## Result first

The unchanged BARDO HYBRID learning encoder can map opposite-label frames to **exactly the same learner feature vector** once its four witness slots are occupied by earlier ordinary invalid lanes. This demonstrates an information-loss boundary of this encoder, not a failure to train a sufficiently large model.

A conventional 71-bit validity bitmap preserves the exact answer to the tested family of subset-validity queries, using 9 serialized bytes versus 205 bytes for all 71 packed TX1 semantic records. This is **95.61% less task-specific payload**, not an end-to-end speed, memory, energy, or financial saving. Bitmap indexing is established prior art; no novelty is claimed for the bitmap.

## Pinned implementation and reproducibility

Original implementation: `0b9da9e61eed562797473c8a841902247a2aa946` (PR #42). Experiment code / successful CI: `6d004a20ae23fca9ad525693607ab8cbd7d903dd`.

The original `src/bardocompute/` implementation is unchanged. The harness checks the Git blob hashes of `logos_learning.py` and `hardware_contract.py`; CI additionally compares the complete source directory against the original commit.

```bash
git clone https://github.com/safal207/BardoCompute.git
cd BardoCompute
git checkout 6d004a20ae23fca9ad525693607ab8cbd7d903dd
python -m pip install -e . pytest
python -m pytest -q tests/test_logos_learning.py
PYTHONPATH=src python -m unittest discover -s experiments/witness_completeness_v1 -p test_lab.py -v
PYTHONPATH=src python experiments/witness_completeness_v1/run_lab.py --output evidence/reproduced
python -c "import json; r=json.load(open('evidence/reproduced/result.json')); assert r['source_mode']=='FULL_PINNED_UPSTREAM'; assert all(x['bitmap_errors']==0 for x in r['overload'])"
```

Shell commands above use POSIX environment-variable syntax. On Windows, install with `pip install -e .` and run the Python commands without the `PYTHONPATH=src` prefix.

## Minimal counterexample

Use 71 neutral TX1 lanes. Make lanes 18, 19, 20, 21 invalid in both frames. In the negative frame, make ordinary lane 50 invalid. In the positive frame, make critical lane 60 invalid instead. The critical region is the original task's outer region: 0–17 and 53–70. Indices are zero-based.

Both frames have the same global counters and the same four selected witnesses. Therefore `encode_hybrid` returns equal feature vectors, although the correct escalation decisions differ. `encode_raw` and the validity bitmap distinguish them.

**The collision concerns the semantic features actually supplied to the learner. It is not a claim that complete HYBRID wire records or ordered integrity roots are identical.** The upstream encoder deliberately excludes the ordered root from its learning features.

On a balanced dataset of these opposite-label identical-feature pairs, a deterministic classifier depending only on the features gets exactly one member of each pair right; a randomized predictor has at most 50% expected accuracy. More training cannot recover omitted information. This is a mathematical consequence of the constructed pairs, not a measured accuracy for a trained model and not a statement about all real workloads.

## Experiments and all tested loads

Three seeds (11, 29, 47), 128 matched pairs per seed per load. Each load contains 384 pairs / 768 frames. Valid backgrounds are randomized over all 216 valid trigrams. Labels are independently checked by a direct scan of the critical region.

| Earlier ordinary invalid distractors | Opposite-label HYBRID collisions | RAW feature collisions | Bitmap decision errors |
|---:|---:|---:|---:|
| 0 | 0 / 384 | 0 | 0 |
| 1 | 0 / 384 | 0 | 0 |
| 2 | 0 / 384 | 0 | 0 |
| 3 | 0 / 384 | 0 | 0 |
| 4 | 384 / 384 | 0 | 0 |
| 5 | 384 / 384 | 0 | 0 |
| 8 | 384 / 384 | 0 | 0 |
| 16 | 384 / 384 | 0 | 0 |
| 32 | 384 / 384 | 0 | 0 |

Total: 3,456 matched pairs / 6,912 frames. The overloaded portion has 1,920 colliding pairs / 3,840 frames. Zero collisions at lower loads is not proof that a learner achieves 100% accuracy there.

Separate layout control: all 720 permutations of six physical positions, with the query remapped along with them. 48 layouts collide. This is a complete finite layout experiment, **not** an estimate of fault frequency in deployed systems.

Bitmap checks: all 65,536 combinations of eight-lane validity vectors and query subsets, followed by 100,000 randomized 71-lane state/query cases (including empty, singleton, sparse, and dense queries). No disagreements with the direct boolean-scan reference.

Self-tests: eight tests, including all 512 three-line input combinations for full-record serialization. The five original learning unit tests also pass. These are test cases and finite subcases, not 165,536 independent system-level safety guarantees. The original full training benchmark was not rerun in this lab.

## Why 71 bits are enough — and necessary for this query family

Let `x` be the 71-bit invalid-lane vector. A query supplies any subset `C` and asks whether any invalid lane belongs to it. The answer is `bool(x & C)`.

Any two different vectors differ at some lane `i`; querying the singleton `{i}` distinguishes them. Therefore an exact fixed encoding that supports every future subset query must distinguish all `2^71` possible vectors, requiring at least 71 bits in the worst case. A bitmap attains this bound; byte alignment adds one padding bit. This elementary counting argument is not claimed as a new theorem.

For one fixed query known before encoding, a one-bit precomputed answer can suffice. For different predicates, the validity bitmap need not suffice at all. Both limitations are covered by negative controls: changing scope can change a cached answer, and two frames with the same validity bitmap can have different `policy_allow` results.

## Reproduction evidence and discrepancies retained

Local Python 3.13.5, GitHub Python 3.11.16 and 3.13.15 agree on every aggregate result and every generated input frame. Some SHA-256 fingerprints of floating-point feature vectors differ between Python 3.11 and 3.13. Within each environment, the paired equality tests agree. Those feature fingerprints are therefore environment-specific, not cross-version semantic identities.

Successful run: https://github.com/safal207/BardoCompute/actions/runs/33943876410 . Both dedicated matrix jobs passed. This statement does not assert that every unrelated inherited repository workflow is green.

The first CI run, 33943738219, failed before tests because shallow checkout omitted the pinned ancestor needed for `git diff`. `fetch-depth: 0` fixed the setup; the failed attempt is not counted as experimental evidence.

Permanent evidence in this branch: `evidence/witness-completeness/2026-09-05/` contains the complete local aggregate result, minimal fixture, cross-environment verification and test counts. The harness regenerates the full nine representative frame pairs; original full records and logs are also preserved in CI artifacts and the downloadable research bundle. GitHub artifacts have 30-day retention; they are not the only record of the experiment.

## What this can support in a technical investor conversation

Demonstrated: a reproducible failure boundary in a specific compressed decision representation; a strong conventional exact baseline; and a precise boundary between task-specific sufficiency and unsupported generality.

Proposed product direction, not yet validated: a layer that states which decisions a compressed agent trace can safely support, detects insufficient evidence, and requests additional evidence or returns HOLD rather than inventing certainty. BARDO could represent transitions; an ATMAN/CaPU integration could consume explicit completeness and policy-version information. This experiment does not implement that integration.

Suggested pitch: "We found a concrete way that a bounded trace summary can erase the distinction between a critical event and ordinary noise. We reproduced the failure on pinned code, and built an exact compact baseline for one decision family. We are now testing whether decision-specific completeness checks can reduce trace traffic without unsafe decisions in a real agent workflow."

Before a performance or commercial claim: use externally sourced traces with independently defined labels, compare against an equally correct ordinary implementation, include source scanning, metadata, authentication and fallback traffic, measure tail latency and abstention, and obtain external reproduction or a customer pilot. No investor interest, market demand, patentability or investment outcome has been measured.
