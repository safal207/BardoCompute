# Witness completeness v1 — an overload boundary, not a CPU breakthrough

Research snapshot: 2026-09-05. Synthetic falsification reproduced locally and on GitHub Actions. No production or physical-hardware claim.

## Result

The unchanged BARDO HYBRID learning encoder can map opposite-label frames to **exactly the same learner feature vector** once its four witness slots are occupied by earlier ordinary invalid lanes. This is an information-loss boundary, not a failure to train a sufficiently large model.

A conventional 71-bit validity bitmap answers the tested family of subset-validity queries exactly, using 9 serialized bytes versus 205 bytes for all 71 packed TX1 semantic records: **95.61% less task-specific payload**. This is not an end-to-end speed, memory, energy, or financial saving. Bitmap indexing is established prior art; no novelty is claimed for the bitmap.

## Minimal counterexample

Start with 71 neutral TX1 lanes. Make lanes 18, 19, 20, 21 invalid in both frames. The negative frame also has invalid ordinary lane 50; the positive frame instead has invalid critical lane 60. The original task's critical region is 0–17 and 53–70. Indices are zero-based.

The global counters and four selected witnesses match. `encode_hybrid` returns equal feature vectors despite different escalation labels. `encode_raw` and the validity bitmap distinguish the frames.

**This is equality of the semantic features supplied to the learner, not equality of complete HYBRID wire records or ordered integrity roots.** The upstream encoder excludes the ordered root from learning features.

On balanced opposite-label identical-feature pairs, a deterministic input-only classifier gets exactly one member of each pair right; a randomized predictor has at most 50% expected accuracy. More training cannot recover omitted information. This is a consequence of the constructed pairs, not measured trained-model accuracy or a statement about all real workloads. External context would change the information boundary.

## Experiments

Three seeds (11, 29, 47), 128 matched pairs per seed per load: 384 pairs / 768 frames per row. Backgrounds vary over all 216 valid trigrams. A direct scan independently checks the escalation labels.

| Earlier ordinary invalid distractors | Opposite-label HYBRID collisions | RAW feature collisions | Bitmap errors |
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

Total: 3,456 pairs / 6,912 frames. The overloaded portion has 1,920 colliding pairs / 3,840 frames. Zero collisions at lower loads does not establish 100% learned accuracy.

A separate finite control covers all 720 permutations of six physical positions, with the query remapped consistently: 48 layouts collide. This is not a deployment failure-rate estimate.

The bitmap agrees with a direct boolean scan on all 65,536 eight-lane state/query combinations and on 100,000 randomized 71-lane cases, including empty, singleton, sparse and dense queries. Eight lab tests include serialization round-trips for all 512 three-line input codes. Five original learning unit tests also pass. The full original training benchmark was not rerun; no training occurs in this lab.

## Sufficiency and negative controls

Let `x` be the 71-bit invalid-lane vector. A query supplies any subset `C`; the exact answer is `bool(x & C)`. Two different vectors differ at some lane `i`, so singleton query `{i}` distinguishes them. Supporting every future subset query therefore requires distinguishing all `2^71` vectors: at least 71 fixed bits in the worst case. The bitmap attains this bound; byte alignment adds one bit. This elementary counting argument is not claimed as a new theorem.

One fixed query known before encoding may need only a one-bit answer. Conversely, the validity bitmap cannot answer arbitrary other predicates. Negative controls retain both boundaries: scope changes can invalidate a cached one-bit answer, and identical validity bitmaps can correspond to different `policy_allow` results.

The full record preserves more facts. Source scanning, metadata, authentication, freshness and fallback traffic are not included in the payload comparison. A bitmap is not a certificate of source truth or completeness.

## Pinned source and reproduction

Original implementation: `0b9da9e61eed562797473c8a841902247a2aa946` (PR #42).
Experiment code / successful CI: `6d004a20ae23fca9ad525693607ab8cbd7d903dd`.
The original `src/bardocompute/` code is unchanged. The harness checks two exact Git blob hashes; CI also compares the complete original source directory.

```bash
git clone https://github.com/safal207/BardoCompute.git
cd BardoCompute
git checkout 6d004a20ae23fca9ad525693607ab8cbd7d903dd
python -m pip install -e . pytest
python -m pytest -q tests/test_logos_learning.py
python -m unittest discover -s experiments/witness_completeness_v1 -p test_lab.py -v
python experiments/witness_completeness_v1/run_lab.py --output evidence/reproduced
python -c "import json; r=json.load(open('evidence/reproduced/result.json')); assert r['source_mode']=='FULL_PINNED_UPSTREAM'; assert all(x['bitmap_errors']==0 for x in r['overload'])"
```

Local Python 3.13.5 and GitHub Python 3.11.16 / 3.13.15 agree on input frames and aggregate outcomes. Some floating-point feature SHA-256 fingerprints differ between Python 3.11 and 3.13; within-environment pair equalities agree. Fingerprints are environment-specific, not cross-version semantic identities.

Successful dedicated matrix run: https://github.com/safal207/BardoCompute/actions/runs/33943876410 . No claim is made about every unrelated inherited workflow. Initial run 33943738219 failed before tests because shallow checkout omitted the source ancestor. `fetch-depth: 0` fixed the setup; the failed attempt is not experimental evidence.

Permanent branch evidence: `evidence/witness-completeness/2026-09-05/` contains the complete local aggregate JSON (formatting changed), minimal fixture, verification and test index. Full nine representative frame pairs and raw logs are in CI artifacts and the downloadable research bundle; the pinned harness regenerates them. CI artifacts have 30-day retention.

## Technical investor discussion boundary

Demonstrated: a reproducible failure boundary, a strong conventional exact control, and an explicit distinction between task-specific sufficiency and unsupported generality. Not demonstrated: a production integration, a novel compression algorithm, CPU/GPU/FPGA superiority, commercial traction or investor demand.

Suggested wording: "We found a concrete way that a bounded trace summary can erase the distinction between a critical event and ordinary noise. We reproduced the failure on pinned code and built an exact compact baseline for one decision family. Our next validation target is a real agent workflow with independently defined outcomes."

Proposed product direction, not implemented here: decision-specific completeness checks for compressed agent traces, requesting additional evidence or returning HOLD when insufficient. ATMAN/CaPU might consume explicit completeness and policy-version information; this lab does not implement that connection.

The next validation should compare equally correct implementations on external traces, including source scanning, metadata, authentication, fallback traffic, tail latency, abstention and unsafe decisions. External reproduction or a bounded customer pilot is needed before a performance or commercial claim. This result alone does not establish market demand, patentability or investment merit.
