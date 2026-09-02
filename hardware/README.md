# BARDO-TX1 hardware slice

BARDO-TX1 is the first synthesizable BardoCompute execution boundary. It is a
streaming accelerator, not a general-purpose CPU replacement.

Each lane accepts three ordered packed Bardo lines (`lower`, `middle`, `upper`)
and produces, with one registered stage:

- semantic validity;
- dense radix-6 trigram index `0..215`;
- settled target states;
- transition, discontinuity, and target-count features;
- the existing joint reference-policy result.

The default top has eight lanes, so one accepted bundle represents eight
trigrams / twenty-four line states. Throughput claims require post-synthesis
clock data and end-to-end memory/interface measurements; `LANES * f_clock` is
only the core roofline.

## Local verification

```bash
python -m pytest -q tests/test_hardware_contract.py
make -C hardware sim
make -C hardware synth
make -C hardware cpu-smoke
```

The RTL testbench exhausts every one of the `8^3 = 512` sparse input bundles,
checks the `216` valid-state bijection, verifies fail-closed behavior for
reserved codes, and tests output stability under backpressure.

`cpu-smoke` runs both a direct optimized C evaluator and a fair 512-entry lookup-table path over the same sparse 9-bit inputs. Future FPGA claims must beat the faster measured CPU path after interface costs.

## Evidence boundary

The hardware workflow checks out and rechecks one exact source SHA at the start
and end of every job. FPGA artifacts are named with that SHA plus the workflow
run and attempt, and every listed pre-gate checksum entry is verified before
its claim gate runs. The checksum manifest is self-produced: it proves only the
byte consistency of its listed pre-gate files. It is not a signature, a
source-provenance attestation, or evidence that a board executed the bitstream;
source provenance depends on retaining the artifact with its exact GitHub
Actions run.

Ordinary CI is intentionally limited to `CORE_ROOFLINE_ONLY` with
`claim_allowed=false`. No physical execution, end-to-end CPU speedup, power, or
latency claim is made until independently collected physical inputs are bound
and the separate competitive gate passes.
