# BardoCompute

**Transition-state computing — a research reference, not a production processor.**

BardoCompute studies whether retaining the direction and continuity of a state transition is useful for execution, verification and recovery. Symbolic inspiration is not evidence of a computational advantage.

## Start here

| Your goal | Entry point |
|---|---|
| Start in Russian / начать по-русски | [START_HERE.md](START_HERE.md) |
| Run a pinned reference | Reproduction below |
| Find code, experiments and evidence | [RESEARCH_INDEX.md](RESEARCH_INDEX.md) |
| Understand readiness and exact revisions | [PROJECT_STATUS.json](PROJECT_STATUS.json) |
| Add work without losing the research history | [REPOSITORY_GUIDE.md](REPOSITORY_GUIDE.md) |

## What can be used today

| Track | Use it for | Boundary |
|---|---|---|
| Software/native reference at `f50490e…` | Study and reproduce transition semantics and controls | Research use; not a supported production API |
| BARDO-TX1 at the same exact revision | RTL simulation and the documented FPGA implementation experiments | `CORE_ROOFLINE_ONLY`; no physical-board or CPU-competitive claim |
| LOGOS / HYBRID | Reproduce separate synthetic learning experiments | Research branch; not an integrated release |

**`main` is the navigation entry point.** Its historical tip contained only README and LICENSE. Executable work has not disappeared: it lives in the pinned tracks below. This documentation change does not merge or promote their code.

## Reproduce the reference

From a clone of this repository, use a separate worktree so the navigation checkout stays intact:

```sh
git fetch origin
git worktree add --detach ../BardoCompute-reference f50490e8194f0e5c7aeeba251f2575eb8155ed54
cd ../BardoCompute-reference
python -m venv .venv
# Activate .venv for your shell before installing dependencies.
python -m pip install -e . pytest
python -m pytest -q
```

Python >=3.11 is declared by the pinned package. Native and RTL/FPGA tests require the tools described in the [exact hardware guide](https://github.com/safal207/BardoCompute/blob/f50490e8194f0e5c7aeeba251f2575eb8155ed54/docs/hardware-v0.1.md). This organization pass did not rerun those experiments.

## Research and evidence

[PR #40](https://github.com/safal207/BardoCompute/pull/40) was merged into `research/v0.42-same-host-dual-interpreter`, **not into main**. Source evidence stays bound to `f50490e8194f0e5c7aeeba251f2575eb8155ed54`; a branch name or a later documentation commit must not inherit its measured status.

The [research index](RESEARCH_INDEX.md) separates the reference, active experiments and preserved branches. The [34-branch snapshot](BRANCH_SNAPSHOT_2026-09-05.tsv) records exact heads before this organization change. No branch was deleted, renamed or force-pushed.

## Architecture family

[BardoCompute](https://github.com/safal207/BardoCompute): transition representation · [COSMIC-ORGANICS](https://github.com/safal207/COSMIC-ORGANICS): sparse execution · [ATMAN-LATTICE](https://github.com/safal207/ATMAN-LATTICE): authority and governed revision · [CaPU](https://github.com/safal207/CaPU): effect admission and recovery.

These roles are an integration map, not a claim that the four repositories already form a verified end-to-end system.

## History and license

The previous landing page is preserved byte-for-byte at [README.previous.md](README.previous.md). Existing research and Apache-2.0 licensing are unchanged. Readiness snapshot: **2026-09-05**.
