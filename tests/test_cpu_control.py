from __future__ import annotations

from pathlib import Path

import pytest

from bardocompute.cpu_control import (
    CpuControlError,
    build_cpu_control_report,
    main,
    parse_key_values,
)


def fpga() -> dict[str, str]:
    return {
        "lanes": "71",
        "clock_mhz": "25",
        "core_mtrigrams_s": "1775",
    }


def cpu() -> dict[str, str]:
    return {
        "correct": "true",
        "cpu_baseline_model": "materialize_and_reduction",
        "threads": "1",
        "best_materialized_cpu_mtrigrams_s": "1800.000",
        "best_reduced_cpu_mtrigrams_s": "3600.000",
        "best_cpu_mtrigrams_s": "3600.000",
    }


def test_reports_both_fair_boundaries_without_promoting_claim() -> None:
    report = build_cpu_control_report(fpga=fpga(), cpu=cpu())

    assert report["cpu_control_gate"] is True
    assert report["core_vs_materialized_cpu_ratio"] == pytest.approx(1775 / 1800)
    assert report["core_vs_reduced_cpu_ratio"] == pytest.approx(1775 / 3600)
    assert report["cpu_competition_status"] == "unresolved"


def test_rejects_legacy_serial_checksum_baseline() -> None:
    evidence = cpu()
    evidence.pop("cpu_baseline_model")
    evidence["best_cpu_mtrigrams_s"] = "799.527"

    with pytest.raises(CpuControlError, match="cpu_baseline_model"):
        build_cpu_control_report(fpga=fpga(), cpu=evidence)


def test_rejects_weaker_compatibility_alias() -> None:
    evidence = cpu()
    evidence["best_cpu_mtrigrams_s"] = "1800.000"

    with pytest.raises(CpuControlError, match="stronger fair path"):
        build_cpu_control_report(fpga=fpga(), cpu=evidence)


def test_parser_rejects_duplicate_keys() -> None:
    with pytest.raises(CpuControlError, match="duplicate key"):
        parse_key_values("threads=1\nthreads=2\n", source="fixture")


def test_cli_writes_checked_report(tmp_path: Path) -> None:
    fpga_path = tmp_path / "fpga.txt"
    cpu_path = tmp_path / "cpu.txt"
    output = tmp_path / "comparison.txt"
    fpga_path.write_text(
        "\n".join(f"{key}={value}" for key, value in fpga().items()) + "\n",
        encoding="utf-8",
    )
    cpu_path.write_text(
        "\n".join(f"{key}={value}" for key, value in cpu().items()) + "\n",
        encoding="utf-8",
    )

    assert main(
        [
            "--fpga-evidence",
            str(fpga_path),
            "--cpu-evidence",
            str(cpu_path),
            "--output",
            str(output),
        ]
    ) == 0
    written = output.read_text(encoding="utf-8")
    assert "cpu_control_gate=pass" in written
    assert "core_vs_strongest_cpu_ratio=" in written
    assert "cpu_competition_status=unresolved" in written
