from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from bardocompute.hardware_claims import (
    EQUAL_THROUGHPUT_REL_TOLERANCE,
    EvidenceError,
    build_claim_report,
    main,
    parse_key_value_text,
    parse_sha256_manifest,
    parse_sha256s_text,
    verify_manifest_path,
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


def host_measurement() -> dict[str, object]:
    measurement = measurement_base("host_stream")
    measurement.update(
        {
            "workload": "payment recovery transition trace v1",
            "workload_kind": "real",
            "output_mode": "full_results",
            "items": 1_000_000,
            # 500 Mtrigrams/s, exactly the measured CPU throughput.
            "elapsed_seconds": 0.002,
            "input_bytes": math.ceil(1_000_000 * 9 / 8),
            "output_bytes": math.ceil(1_000_000 * 23 / 8),
            "includes_host_device_transfer": True,
            "includes_setup_overhead": True,
            "same_workload_as_cpu": True,
            "same_host_cpu_baseline": True,
            "cpu_mtrigrams_s": 500.0,
            "board_power_w": 10.0,
            "cpu_power_w": 50.0,
            "fpga_p99_ns": 100.0,
            "cpu_p99_ns": 250.0,
            "equal_throughput": True,
        }
    )
    return measurement


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
            "self_test_signature": "0xf8cc45c1e3244a5a",
            "completed_epochs": 1000,
        }
    )

    report = build(measurement)

    assert report["status"] == "PHYSICAL_SELF_TEST_ONLY"
    assert report["claim_allowed"] is False
    assert report["physical_measurement"]["completed_epochs"] == 1000


def test_real_host_stream_requires_and_passes_both_energy_and_p99_gates() -> None:
    report = build(host_measurement())

    assert report["status"] == "CPU_COMPETITIVE_PASS"
    assert report["claim_allowed"] is True
    physical = report["physical_measurement"]
    assert physical["throughput_mtrigrams_s"] == pytest.approx(500.0)
    assert physical["throughput_per_watt_ratio"] == pytest.approx(5.0)
    assert physical["p99_latency_improvement_ratio"] == pytest.approx(2.5)
    assert physical["equal_throughput_verified"] is True
    assert physical["throughput_relative_gap"] == pytest.approx(0.0)
    assert report["claim_threshold"]["requires_all_metrics"] is True


def test_energy_only_measurement_cannot_promote_claim() -> None:
    measurement = host_measurement()
    measurement.pop("fpga_p99_ns")
    measurement.pop("cpu_p99_ns")

    report = build(measurement)

    assert report["status"] == "END_TO_END_NOT_PROVEN"
    assert report["claim_allowed"] is False
    assert any("p99" in reason for reason in report["reasons"])


def test_latency_only_measurement_cannot_promote_claim() -> None:
    measurement = host_measurement()
    measurement.pop("board_power_w")
    measurement.pop("cpu_power_w")

    report = build(measurement)

    assert report["status"] == "END_TO_END_NOT_PROVEN"
    assert report["claim_allowed"] is False
    assert any("throughput-per-watt" in reason for reason in report["reasons"])


def test_equal_throughput_is_derived_not_trusted() -> None:
    measurement = host_measurement()
    measurement["elapsed_seconds"] = 0.001  # FPGA 1000, CPU 500 Mtrigrams/s.

    with pytest.raises(EvidenceError, match="contradicts measured"):
        build(measurement)


def test_unequal_throughput_without_boolean_cannot_promote_latency() -> None:
    measurement = host_measurement()
    measurement.pop("equal_throughput")
    measurement["elapsed_seconds"] = 0.00189  # gap is just over five percent.

    report = build(measurement)

    assert report["claim_allowed"] is False
    physical = report["physical_measurement"]
    assert physical["throughput_relative_gap"] > EQUAL_THROUGHPUT_REL_TOLERANCE
    assert physical["equal_throughput_verified"] is False
    assert physical["p99_latency_improvement_ratio"] is None


def test_synthetic_host_stream_cannot_promote_claim() -> None:
    measurement = host_measurement()
    measurement["workload"] = "counter generator"
    measurement["workload_kind"] = "synthetic"
    measurement["output_mode"] = "reduced_verdicts"
    measurement["output_bytes"] = 64

    report = build(measurement)

    assert report["status"] == "END_TO_END_NOT_PROVEN"
    assert report["claim_allowed"] is False
    assert any("synthetic" in reason for reason in report["reasons"])


def test_measurement_must_match_exact_bitstream() -> None:
    measurement = measurement_base("on_chip_self_test")
    measurement.update(
        {
            "bitstream_sha256": "b" * 64,
            "self_test_signature": "0xf8cc45c1e3244a5a",
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

    with pytest.raises(EvidenceError, match="duplicate filename"):
        parse_sha256_manifest(
            f"{BITSTREAM_SHA256}  build/evidence.txt\n"
            f"{'b' * 64}  build/evidence.txt\n"
        )


def test_manifest_binds_claim_inputs_to_the_bitstream_profile(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.txt"
    report_path = tmp_path / "nextpnr-report.json"
    evidence_path.write_text("clock_mhz=25\n", encoding="utf-8")
    report_path.write_text("{}\n", encoding="utf-8")
    manifest = parse_sha256_manifest(
        f"{BITSTREAM_SHA256}  build/bardo_tx1.bit\n"
        f"{_digest(evidence_path)}  build/evidence.txt\n"
        f"{_digest(report_path)}  build/nextpnr-report.json\n"
    )

    assert verify_manifest_path(manifest, evidence_path, source="fixture") == _digest(
        evidence_path
    )
    assert verify_manifest_path(manifest, report_path, source="fixture") == _digest(
        report_path
    )

    evidence_path.write_text("clock_mhz=75\n", encoding="utf-8")
    with pytest.raises(EvidenceError, match="SHA-256 mismatch"):
        verify_manifest_path(manifest, evidence_path, source="fixture")


def test_cli_writes_unresolved_report_and_rejects_mixed_profile(
    tmp_path: Path,
) -> None:
    fpga_path = tmp_path / "evidence.txt"
    cpu_path = tmp_path / "cpu.log"
    report_path = tmp_path / "nextpnr-report.json"
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
        f"{BITSTREAM_SHA256}  build/bardo_tx1.bit\n"
        f"{_digest(fpga_path)}  build/evidence.txt\n"
        f"{_digest(report_path)}  build/nextpnr-report.json\n",
        encoding="utf-8",
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

    report_path.write_text(json.dumps({**nextpnr_report(), "mixed": True}), encoding="utf-8")
    assert main(common) == 1


def test_quantized_nextpnr_constraint_matches_declared_profile() -> None:
    fpga = fpga_evidence()
    fpga["clock_mhz"] = "75"
    fpga["core_mtrigrams_s"] = "5325"
    report = nextpnr_report()
    report["fmax"] = {
        "$glbnet$clk_75mhz": {
            "achieved": 85.5139389038086,
            "constraint": 75.00187683105469,
        }
    }

    result = build_claim_report(
        fpga_evidence=fpga,
        cpu_evidence=cpu_evidence(),
        nextpnr_report=report,
        bitstream_sha256=BITSTREAM_SHA256,
    )

    assert result["implementation"]["clocks"][0]["constraint_mhz"] == pytest.approx(
        75.00187683105469
    )


def test_distinct_nextpnr_constraint_does_not_match_declared_profile() -> None:
    fpga = fpga_evidence()
    fpga["clock_mhz"] = "75"
    fpga["core_mtrigrams_s"] = "5325"
    report = nextpnr_report()
    report["fmax"] = {
        "$glbnet$clk_wrong_profile": {
            "achieved": 85.5,
            "constraint": 74.99,
        }
    }

    with pytest.raises(EvidenceError, match="no clock constraint matches"):
        build_claim_report(
            fpga_evidence=fpga,
            cpu_evidence=cpu_evidence(),
            nextpnr_report=report,
            bitstream_sha256=BITSTREAM_SHA256,
        )
