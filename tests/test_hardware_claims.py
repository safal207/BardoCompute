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
        "profile": "native_25mhz",
        "top": "bardo_tx1_ulx3s_bench",
        "bitstream": "bardo_tx1_ulx3s_bench.bit",
        "expected_self_test_signature": "0xf8cc45c1e3244a5a",
        "clock_mhz": "25",
        "lanes": "71",
        "core_mtrigrams_s": "1775",
        "cpu_competition_status": "unresolved",
        "claim_boundary": "on-chip generator and reducer; not host end-to-end",
    }


def fpga_evidence_75() -> dict[str, str]:
    evidence = fpga_evidence()
    evidence.update(
        {
            "profile": "pll_25_to_75mhz",
            "top": "bardo_tx1_ulx3s_bench_75",
            "bitstream": "bardo_tx1_ulx3s_bench_75.bit",
            "expected_self_test_signature": "0xf8cc45c1e3244a5a",
            "clock_mhz": "75",
            "core_mtrigrams_s": "5325",
        }
    )
    return evidence


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


def _cli_fixture(
    tmp_path: Path,
    *,
    fpga: dict[str, str] | None = None,
    report: dict[str, object] | None = None,
    measurement: dict[str, object] | None = None,
    bind_physical_inputs: bool = False,
) -> tuple[list[str], dict[str, Path]]:
    fpga = fpga or fpga_evidence()
    report = report or nextpnr_report()
    bitstream_name = fpga["bitstream"]

    paths = {
        "fpga": tmp_path / "evidence.txt",
        "cpu": tmp_path / "cpu.log",
        "report": tmp_path / "nextpnr-report.json",
        "sums": tmp_path / "SHA256SUMS",
        "bitstream": tmp_path / bitstream_name,
        "measurement": tmp_path / "measurement.json",
        "json_output": tmp_path / "claim.json",
        "markdown_output": tmp_path / "claim.md",
    }
    paths["fpga"].write_text(
        "\n".join(f"{key}={value}" for key, value in fpga.items()) + "\n",
        encoding="utf-8",
    )
    paths["cpu"].write_text(
        "\n".join(f"{key}={value}" for key, value in cpu_evidence().items()) + "\n",
        encoding="utf-8",
    )
    paths["report"].write_text(json.dumps(report), encoding="utf-8")
    paths["bitstream"].write_bytes(b"BARDO fixture bitstream\x00")

    manifest_lines = [
        f"{_digest(paths['bitstream'])}  build/{bitstream_name}",
        f"{_digest(paths['fpga'])}  build/evidence.txt",
        f"{_digest(paths['report'])}  build/nextpnr-report.json",
    ]
    if measurement is not None:
        measurement = dict(measurement)
        measurement["bitstream_sha256"] = _digest(paths["bitstream"])
        paths["measurement"].write_text(json.dumps(measurement), encoding="utf-8")
        if bind_physical_inputs:
            manifest_lines.extend(
                [
                    f"{_digest(paths['cpu'])}  control/cpu.log",
                    f"{_digest(paths['measurement'])}  physical/measurement.json",
                ]
            )
    paths["sums"].write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    args = [
        "--fpga-evidence",
        str(paths["fpga"]),
        "--cpu-evidence",
        str(paths["cpu"]),
        "--nextpnr-report",
        str(paths["report"]),
        "--sha256s",
        str(paths["sums"]),
        "--bitstream",
        str(paths["bitstream"]),
        "--json-output",
        str(paths["json_output"]),
        "--markdown-output",
        str(paths["markdown_output"]),
    ]
    if measurement is not None:
        args.extend(["--measurement", str(paths["measurement"])])
    return args, paths


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
    assert report["core"]["profile"] == "native_25mhz"
    assert report["core"]["top"] == "bardo_tx1_ulx3s_bench"
    assert report["core"]["bitstream"] == "bardo_tx1_ulx3s_bench.bit"


def test_on_chip_self_test_rejects_contradictory_signature() -> None:
    measurement = measurement_base("on_chip_self_test")
    measurement.update(
        {
            "self_test_signature": "0x0000000000000000",
            "completed_epochs": 1,
        }
    )

    with pytest.raises(EvidenceError, match="does not match the selected FPGA profile"):
        build(measurement)


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
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    common, paths = _cli_fixture(tmp_path)

    assert main(common) == 0
    written = json.loads(paths["json_output"].read_text(encoding="utf-8"))
    assert written["status"] == "CORE_ROOFLINE_ONLY"
    assert written["bitstream_sha256"] == _digest(paths["bitstream"])
    assert "diagnostic" in paths["markdown_output"].read_text(encoding="utf-8")
    assert main([*common, "--require-competitive"]) == 3

    # Rehash the modified report so this is a semantic profile failure, not a
    # manifest-tamper failure. A 75 MHz report cannot back the native profile.
    mixed_report = nextpnr_report()
    mixed_report["fmax"] = {
        "$glbnet$clk_75mhz": {
            "achieved": 90.0,
            "constraint": 75.00187683105469,
        }
    }
    paths["report"].write_text(json.dumps(mixed_report), encoding="utf-8")
    manifest = paths["sums"].read_text(encoding="utf-8")
    manifest = manifest.replace(
        written_digest := parse_sha256_manifest(manifest)["build/nextpnr-report.json"],
        _digest(paths["report"]),
        1,
    )
    assert written_digest != _digest(paths["report"])
    paths["sums"].write_text(manifest, encoding="utf-8")
    assert main(common) == 1
    assert "no clock constraint matches" in capsys.readouterr().out


def test_quantized_nextpnr_constraint_matches_declared_profile() -> None:
    fpga = fpga_evidence_75()
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
    fpga = fpga_evidence_75()
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("top", "bardo_tx1_ulx3s_bench_75"),
        ("bitstream", "bardo_tx1_ulx3s_bench_75.bit"),
        ("clock_mhz", "75"),
        ("expected_self_test_signature", "0x0000000000000000"),
    ],
)
def test_native_profile_rejects_mismatched_contract_fields(
    field: str, value: str
) -> None:
    fpga = fpga_evidence()
    fpga[field] = value

    with pytest.raises(EvidenceError, match="does not match profile"):
        build_claim_report(
            fpga_evidence=fpga,
            cpu_evidence=cpu_evidence(),
            nextpnr_report=nextpnr_report(),
            bitstream_sha256=BITSTREAM_SHA256,
        )


def test_unknown_fpga_profile_fails_closed() -> None:
    fpga = fpga_evidence()
    fpga["profile"] = "native_100mhz"

    with pytest.raises(EvidenceError, match="unsupported profile"):
        build_claim_report(
            fpga_evidence=fpga,
            cpu_evidence=cpu_evidence(),
            nextpnr_report=nextpnr_report(),
            bitstream_sha256=BITSTREAM_SHA256,
        )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../evidence.txt",
        "build/../evidence.txt",
        "/tmp/evidence.txt",
        "./evidence.txt",
        "build/./evidence.txt",
        "build//evidence.txt",
        "C:/build/evidence.txt",
        r"build\evidence.txt",
    ],
)
def test_manifest_rejects_unsafe_paths(unsafe_path: str) -> None:
    with pytest.raises(EvidenceError, match="unsafe manifest path"):
        parse_sha256_manifest(f"{BITSTREAM_SHA256}  {unsafe_path}\n")


def test_profile_selects_exact_bitstream_from_multi_profile_manifest() -> None:
    manifest = (
        f"{'b' * 64}  build/bardo_tx1_ulx3s_bench_75.bit\n"
        f"{BITSTREAM_SHA256}  build/bardo_tx1_ulx3s_bench.bit\n"
    )

    assert (
        parse_sha256s_text(
            manifest, expected_filename="bardo_tx1_ulx3s_bench.bit"
        )
        == BITSTREAM_SHA256
    )


def test_cli_hashes_actual_bitstream_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args, paths = _cli_fixture(tmp_path)
    paths["bitstream"].write_bytes(b"tampered after manifest generation")

    assert main(args) == 1
    assert "SHA-256 mismatch" in capsys.readouterr().out
    assert not paths["json_output"].exists()


def test_cli_rejects_bitstream_with_wrong_profile_basename(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args, paths = _cli_fixture(tmp_path)
    wrong_path = tmp_path / "renamed.bit"
    paths["bitstream"].rename(wrong_path)
    args[args.index("--bitstream") + 1] = str(wrong_path)

    assert main(args) == 1
    assert "does not match selected profile bitstream" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("flag", "path_key"),
    [
        ("--fpga-evidence", "fpga"),
        ("--cpu-evidence", "cpu"),
        ("--nextpnr-report", "report"),
        ("--sha256s", "sums"),
        ("--bitstream", "bitstream"),
        ("--measurement", "measurement"),
    ],
)
def test_cli_rejects_direct_symlink_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    path_key: str,
) -> None:
    measurement = host_measurement() if flag == "--measurement" else None
    args, paths = _cli_fixture(
        tmp_path,
        measurement=measurement,
        bind_physical_inputs=measurement is not None,
    )
    path = paths[path_key]
    backing = path.with_name(f"{path.name}.real")
    path.rename(backing)
    path.symlink_to(backing.name)
    args[args.index(flag) + 1] = str(path)

    assert main(args) == 1
    assert "direct symlink input is not allowed" in capsys.readouterr().out


def test_physical_measurement_requires_cpu_and_measurement_manifest_bindings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args, paths = _cli_fixture(tmp_path, measurement=host_measurement())

    assert main(args) == 1
    assert "manifest entry for 'cpu.log'" in capsys.readouterr().out

    with paths["sums"].open("a", encoding="utf-8") as manifest:
        manifest.write(f"{_digest(paths['cpu'])}  control/cpu.log\n")
    assert main(args) == 1
    assert "manifest entry for 'measurement.json'" in capsys.readouterr().out

    with paths["sums"].open("a", encoding="utf-8") as manifest:
        manifest.write(
            f"{_digest(paths['measurement'])}  physical/measurement.json\n"
        )
    assert main(args) == 0
    written = json.loads(paths["json_output"].read_text(encoding="utf-8"))
    assert written["status"] == "CPU_COMPETITIVE_PASS"
    assert written["claim_allowed"] is True
