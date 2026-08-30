from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from bardocompute.hardware_claims import (
    EvidenceError,
    build_claim_report,
    main,
    parse_key_value_text,
    parse_sha256s_text,
)

BITSTREAM_SHA256 = "a" * 64


def fpga_evidence() -> dict[str, str]:
    return {
        "board": "ULX3S-85F",
        "device": "LFE5U-85F",
        "package": "CABGA381",
        "clock_mhz": "25",
        "lanes": "71",
        "core_mtrigrams_s": "1775",
        "cpu_competition_status": "unresolved",
        "claim_boundary": "on-chip generator and reducer; not host end-to-end",
    }


def cpu_evidence() -> dict[str, str]:
    return {
        "correct": "true",
        "best_cpu_mtrigrams_s": "799.527",
        "comparison_boundary": (
            "same 9-bit sparse input, same fail-closed outputs, direct and LUT paths"
        ),
    }


def nextpnr_report() -> dict[str, object]:
    return {
        "fmax": {
            "$glbnet$clk": {
                "achieved": 84.71704864501953,
                "constraint": 25.0,
            }
        },
        "utilization": {
            "TRELLIS_COMB": {"used": 4143, "available": 83640},
            "TRELLIS_FF": {"used": 1327, "available": 83640},
            "DP16KD": {"used": 0, "available": 208},
            "MULT18X18D": {"used": 0, "available": 156},
        },
    }


def build(measurement: dict[str, object] | None = None) -> dict[str, object]:
    return build_claim_report(
        fpga_evidence=fpga_evidence(),
        cpu_evidence=cpu_evidence(),
        nextpnr_report=nextpnr_report(),
        bitstream_sha256=BITSTREAM_SHA256,
        measurement=measurement,
    )


def measurement_base(mode: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": mode,
        "board": "ULX3S-85F",
        "semantic_contract": "bardo-tx1-v0.1",
        "bitstream_sha256": BITSTREAM_SHA256,
        "correct": True,
    }


def test_core_roofline_is_reported_but_not_promoted_to_speedup() -> None:
    report = build()

    assert report["status"] == "CORE_ROOFLINE_ONLY"
    assert report["claim_allowed"] is False
    assert report["core_roofline_vs_cpu_ratio"] == pytest.approx(1775 / 799.527)
    core = report["core"]
    assert core["required_input_gb_s"] == pytest.approx(1.996875)
    assert core["required_full_output_gb_s"] == pytest.approx(5.103125)
    assert core["required_full_roundtrip_gb_s"] == pytest.approx(7.1)


def test_inconsistent_lane_roofline_fails_closed() -> None:
    fpga = fpga_evidence()
    fpga["core_mtrigrams_s"] = "1774"

    with pytest.raises(EvidenceError, match=r"lanes\*clock_mhz"):
        build_claim_report(
            fpga_evidence=fpga,
            cpu_evidence=cpu_evidence(),
            nextpnr_report=nextpnr_report(),
            bitstream_sha256=BITSTREAM_SHA256,
        )


def test_on_chip_self_test_is_physical_correctness_not_cpu_competition() -> None:
    measurement = measurement_base("on_chip_self_test")
    measurement.update(
        {
            "self_test_signature": "0xb0058cd5263c1fc3",
            "completed_epochs": 1000,
        }
    )

    report = build(measurement)

    assert report["status"] == "PHYSICAL_SELF_TEST_ONLY"
    assert report["claim_allowed"] is False
    assert report["physical_measurement"]["completed_epochs"] == 1000


def test_real_host_stream_can_pass_throughput_per_watt_gate() -> None:
    measurement = measurement_base("host_stream")
    measurement.update(
        {
            "workload": "payment recovery transition trace v1",
            "workload_kind": "real",
            "output_mode": "full_results",
            "items": 1_000_000,
            "elapsed_seconds": 0.0005,
            "input_bytes": math.ceil(1_000_000 * 9 / 8),
            "output_bytes": math.ceil(1_000_000 * 23 / 8),
            "includes_host_device_transfer": True,
            "includes_setup_overhead": True,
            "same_workload_as_cpu": True,
            "same_host_cpu_baseline": True,
            "cpu_mtrigrams_s": 500.0,
            "board_power_w": 10.0,
            "cpu_power_w": 50.0,
        }
    )

    report = build(measurement)

    assert report["status"] == "CPU_COMPETITIVE_PASS"
    assert report["claim_allowed"] is True
    physical = report["physical_measurement"]
    assert physical["throughput_mtrigrams_s"] == pytest.approx(2000.0)
    assert physical["throughput_per_watt_ratio"] == pytest.approx(20.0)


def test_synthetic_host_stream_cannot_promote_claim() -> None:
    measurement = measurement_base("host_stream")
    measurement.update(
        {
            "workload": "counter generator",
            "workload_kind": "synthetic",
            "output_mode": "reduced_verdicts",
            "items": 1_000_000,
            "elapsed_seconds": 0.0005,
            "input_bytes": math.ceil(1_000_000 * 9 / 8),
            "output_bytes": 64,
            "includes_host_device_transfer": True,
            "includes_setup_overhead": True,
            "same_workload_as_cpu": True,
            "same_host_cpu_baseline": True,
            "cpu_mtrigrams_s": 500.0,
            "board_power_w": 10.0,
            "cpu_power_w": 50.0,
        }
    )

    report = build(measurement)

    assert report["status"] == "END_TO_END_NOT_PROVEN"
    assert report["claim_allowed"] is False
    assert any("synthetic" in reason for reason in report["reasons"])


def test_measurement_must_match_exact_bitstream() -> None:
    measurement = measurement_base("on_chip_self_test")
    measurement.update(
        {
            "bitstream_sha256": "b" * 64,
            "self_test_signature": "0xb0058cd5263c1fc3",
            "completed_epochs": 1,
        }
    )

    with pytest.raises(EvidenceError, match="does not match"):
        build(measurement)


def test_parsers_reject_ambiguous_evidence() -> None:
    with pytest.raises(EvidenceError, match="duplicate key"):
        parse_key_value_text("lanes=71\nlanes=72\n")

    manifest = (
        f"{BITSTREAM_SHA256}  build/core.bit\n"
        f"{'b' * 64}  build/other.bit\n"
    )
    with pytest.raises(EvidenceError, match="exactly one"):
        parse_sha256s_text(manifest)


def test_cli_writes_unresolved_report_and_require_flag_fails(
    tmp_path: Path,
) -> None:
    fpga_path = tmp_path / "evidence.txt"
    cpu_path = tmp_path / "cpu.log"
    report_path = tmp_path / "nextpnr.json"
    sums_path = tmp_path / "SHA256SUMS"
    json_output = tmp_path / "claim.json"
    markdown_output = tmp_path / "claim.md"

    fpga_path.write_text(
        "\n".join(f"{key}={value}" for key, value in fpga_evidence().items()) + "\n",
        encoding="utf-8",
    )
    cpu_path.write_text(
        "\n".join(f"{key}={value}" for key, value in cpu_evidence().items()) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(json.dumps(nextpnr_report()), encoding="utf-8")
    sums_path.write_text(
        f"{BITSTREAM_SHA256}  build/bardo_tx1.bit\n", encoding="utf-8"
    )

    common = [
        "--fpga-evidence",
        str(fpga_path),
        "--cpu-evidence",
        str(cpu_path),
        "--nextpnr-report",
        str(report_path),
        "--sha256s",
        str(sums_path),
        "--json-output",
        str(json_output),
        "--markdown-output",
        str(markdown_output),
    ]

    assert main(common) == 0
    written = json.loads(json_output.read_text(encoding="utf-8"))
    assert written["status"] == "CORE_ROOFLINE_ONLY"
    assert "diagnostic" in markdown_output.read_text(encoding="utf-8")
    assert main([*common, "--require-competitive"]) == 3
