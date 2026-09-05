# BardoCompute — research index

Snapshot: 2026-09-05. [Start](README.md) · [Full branch heads](BRANCH_SNAPSHOT_2026-09-05.tsv)

## Reference and active tracks

| Track | Exact source | Readiness / route |
|---|---|---|
| Original executable algebra | `58333ce20493ab33b6e433df7389bdfefe2771b6` | Historical research starting point; inspect the source before reuse |
| BARDO-TX1 software/native/RTL reference | `f50490e8194f0e5c7aeeba251f2575eb8155ed54` | Reproduction reference; [PR #40](https://github.com/safal207/BardoCompute/pull/40) |
| Consolidated research branch after #40 | `db781884d0761e532f886a5c9433a526ced45f56` | Merge target was `research/v0.42-same-host-dual-interpreter`; not main |
| LOGOS tree benchmark | `58dbf365235d03b0e78abe54551546d220f8c0f8` | Separate research source; not promoted by this documentation change |
| LOGOS learning / HYBRID | `0b9da9e61eed562797473c8a841902247a2aa946` | [Draft PR #42](https://github.com/safal207/BardoCompute/pull/42), based on the LOGOS-tree branch; synthetic evidence only |

Source browser: replace `<SHA>` with the full SHA above in `https://github.com/safal207/BardoCompute/tree/<SHA>`. Use the pinned README/protocol at that source, not an unrelated branch's instructions.

## Verified organization facts

Before this change, main was `0eca048870cf36217e1d8f9dc4f5de30fbe58169` and contained only README.md and LICENSE. The branch listing returned 34 branches (33 distinct head SHAs) on the first page with `per_page=100`. The attached TSV records all 34 returned entries, before the documentation branch was created.

The two names `research/v0.24-staged-withdrawal` and `research/v0.25-factorial-support` both pointed to `4ee7166656366c4d3200c5561e6709574a23b886`. They are duplicate pointers at this snapshot, not declared obsolete. All branch names are retained.

## How to read the many research branches

The v0.22-v0.42 branches cover different resolution, recovery, withdrawal, load, cost and handoff experiments. The snapshot preserves exact heads; this pass does not invent a linear dependency chain or relabel every result as successful. Start from the selected reference or a named research question rather than sorting lexicographically and choosing the largest version.

Before retirement of any branch, inspect its unique commits, PR head/base dependencies, source references and evidence. No branch deletion, archival tag, ref rewrite or PR retargeting was performed in this pass.

## Claim boundary

PR #40's evidence supports its exact configured RTL/simulation/synthesis/place-and-route profile. `CORE_ROOFLINE_ONLY` is not measured host-fed throughput, energy or physical-board execution. LOGOS learning results are frozen synthetic-task observations, not general real-world learning superiority. The publication of this index reruns neither experiment.

## Next promotion gate

A separate code-consolidation PR must specify the chosen baseline, preserve its source ancestry/evidence, run the applicable software/native/RTL checks, resolve review findings, and state which research tracks remain outside main. This index is the navigation fix, not that code promotion.
