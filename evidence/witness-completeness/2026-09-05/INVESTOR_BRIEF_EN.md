# Decision-preserving trace compression — research brief

**Stage: reproducible synthetic finding; not a validated product.**

We found an exact information-loss boundary in the pinned BARDO HYBRID encoder. When four earlier ordinary faults occupy its four witness slots, a critical fault and a non-critical fault can produce identical learner inputs despite requiring opposite escalation labels.

The stress lab covers 6,912 synthetic frames. In the overloaded paired family, an input-only predictor is limited to 50% expected accuracy. A conventional validity bitmap preserves exact answers for one defined family of subset queries: 9 serialized bytes rather than 205 bytes of complete TX1 semantic records. The 95.61% payload reduction is task-specific, not full-information compression or measured end-to-end savings.

The source is pinned and unchanged. Five original tests, eight lab tests and the full experiment pass locally and in GitHub on Python 3.11 and 3.13. Input frames and aggregate results match; floating feature fingerprints are not cross-version identical. Full evidence is included.

**What is potentially interesting:** a demonstrable failure mode and a route to deciding whether a compact trace still contains enough information for a particular action. **What is not claimed:** a novel bitmap algorithm, CPU/GPU/FPGA superiority, production safety, commercial traction, or investor demand.

**Proposed product direction:** decision-specific completeness checks for agent traces, with explicit fallback or HOLD when the retained evidence is insufficient. The next validation target is a real external workflow with independently defined outcomes and an equally correct conventional baseline, counting all metadata, computation and fallback traffic.

**Current discussion ask:** technical reproduction and a bounded design-partner experiment, not a claim that this result alone justifies an investment.

Repository draft: https://github.com/safal207/BardoCompute/pull/44
Experiment/CI commit: 6d004a20ae23fca9ad525693607ab8cbd7d903dd
CI: https://github.com/safal207/BardoCompute/actions/runs/33943876410
