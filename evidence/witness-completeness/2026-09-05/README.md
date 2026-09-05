# Witness-completeness v1 — saved research results

Research snapshot: 2026-09-05. Branch: `research/witness-completeness-v1`.
Draft PR: https://github.com/safal207/BardoCompute/pull/44
Publishing evidence is not merging the experiment into `main` or approving it
for production.

## Start here

| File | Purpose |
|---|---|
| [REPORT_RU.md](REPORT_RU.md) | Original Russian research report |
| [INVESTOR_BRIEF_EN.md](INVESTOR_BRIEF_EN.md) | Original English technical-investor brief |
| [result.json](result.json) | Original local aggregate result |
| [minimal_fixture.json](minimal_fixture.json) | Minimal counterexample |
| [VERIFICATION.json](VERIFICATION.json) | Cross-environment verification |
| [RUN_LOGS.json](RUN_LOGS.json) | Historical local and CI test logs |
| [MANIFEST.json](MANIFEST.json) | Publication checksums and provenance |

Reports and the local result preserve the original bundle bytes. The earlier
repository result had different formatting but the same values. RUN_LOGS.json
is a lossless container for 12 original UTF-8 texts: local test logs and the
Python 3.11/3.13 CI test logs, interpreter versions, package lists and tested
commit records. Each embedded text has its own byte count and SHA-256.

**This is archival publication, not a fresh experiment run.** Executable source
and experiment code are unchanged by this publication.

## Archive scope

The source bundle is `Bardo_Evidence_Completeness_v1.zip`; its checksum is in
MANIFEST.json. Full representative frame JSON files, complete per-run experiment
outputs, the reproduction source copy and original CI ZIP containers remain in
that downloadable bundle and the referenced CI artifacts. They have **not all
been copied into this directory**. CI artifacts are subject to retention limits.
The repository experiment regenerates the frame records.

The archived report's `cd reproduction` and archive-manifest references refer
to the ZIP layout, not this directory. Use the pinned repository commands below.

## Reproduce from the repository

From a full clone, not a shallow checkout:

```bash
git worktree add --detach ../bardo-witness-replay 6d004a20ae23fca9ad525693607ab8cbd7d903dd
cd ../bardo-witness-replay
python -m pip install -e . pytest
python -m pytest -q tests/test_logos_learning.py
python -m unittest discover -s experiments/witness_completeness_v1 -p test_lab.py -v
python experiments/witness_completeness_v1/run_lab.py --output evidence/reproduced
```

Original encoder: `0b9da9e61eed562797473c8a841902247a2aa946`.
Historical CI: https://github.com/safal207/BardoCompute/actions/runs/33943876410

## Verify publication integrity

From the repository root:

```bash
python - <<'PY'
import hashlib
import json
from pathlib import Path

root = Path("evidence/witness-completeness/2026-09-05")
manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
for item in manifest["files"]:
    data = (root / item["path"]).read_bytes()
    if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise SystemExit("File mismatch: " + item["path"])
logs = json.loads((root / "RUN_LOGS.json").read_text(encoding="utf-8"))
for name, item in logs["files"].items():
    data = item["text"].encode("utf-8")
    if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise SystemExit("Log mismatch: " + name)
print("PASS: archived files and embedded logs")
PY
```

## Claim boundary

Synthetic input-feature collisions and a conventional exact bitmap control.
No production traces, FPGA execution, CPU/GPU superiority, measured savings,
source completeness/freshness proof or demonstrated investor demand.
Floating feature fingerprints are environment-specific. Historical test success
is not independent review or production approval.
