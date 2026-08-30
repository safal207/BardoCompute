"""Validate BARDO-TX1 CPU controls and emit bounded core-only ratios."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Mapping, Sequence

CPU_MODEL = "materialize_and_reduction"


class CpuControlError(ValueError):
    """Raised when a CPU comparison is weak, malformed, or ambiguous."""


def parse_key_values(text: str, *, source: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not separator or not key or not value:
            raise CpuControlError(
                f"{source}:{line_number}: expected non-empty key=value"
            )
        if key in values:
            raise CpuControlError(f"{source}:{line_number}: duplicate key {key}")
        values[key] = value
    if not values:
        raise CpuControlError(f"{source}: no evidence records found")
    return values


def _required(values: Mapping[str, str], key: str, *, source: str) -> str:
    try:
        return values[key]
    except KeyError as exc:
        raise CpuControlError(f"{source}: missing {key}") from exc


def _positive_float(values: Mapping[str, str], key: str, *, source: str) -> float:
    raw = _required(values, key, source=source)
    try:
        value = float(raw)
    except ValueError as exc:
        raise CpuControlError(f"{source}: {key} must be numeric") from exc
    if not math.isfinite(value) or value <= 0.0:
        raise CpuControlError(f"{source}: {key} must be finite and > 0")
    return value


def _positive_int(values: Mapping[str, str], key: str, *, source: str) -> int:
    raw = _required(values, key, source=source)
    try:
        value = int(raw)
    except ValueError as exc:
        raise CpuControlError(f"{source}: {key} must be an integer") from exc
    if value <= 0 or str(value) != raw:
        raise CpuControlError(f"{source}: {key} must be a canonical positive integer")
    return value


def build_cpu_control_report(
    *, fpga: Mapping[str, str], cpu: Mapping[str, str]
) -> dict[str, float | int | str | bool]:
    if _required(cpu, "correct", source="CPU evidence") != "true":
        raise CpuControlError("CPU evidence: correct=true is required")
    model = _required(cpu, "cpu_baseline_model", source="CPU evidence")
    if model != CPU_MODEL:
        raise CpuControlError(
            "CPU evidence: serial in-loop checksum baselines are inadmissible; "
            f"expected cpu_baseline_model={CPU_MODEL}"
        )
    threads = _positive_int(cpu, "threads", source="CPU evidence")
    materialized = _positive_float(
        cpu, "best_materialized_cpu_mtrigrams_s", source="CPU evidence"
    )
    reduced = _positive_float(
        cpu, "best_reduced_cpu_mtrigrams_s", source="CPU evidence"
    )
    strongest = _positive_float(cpu, "best_cpu_mtrigrams_s", source="CPU evidence")
    expected_strongest = max(materialized, reduced)
    if not math.isclose(strongest, expected_strongest, rel_tol=5e-4, abs_tol=1e-3):
        raise CpuControlError(
            "CPU evidence: best_cpu_mtrigrams_s must equal the stronger fair path"
        )

    lanes = _positive_int(fpga, "lanes", source="FPGA evidence")
    clock_mhz = _positive_float(fpga, "clock_mhz", source="FPGA evidence")
    core = _positive_float(fpga, "core_mtrigrams_s", source="FPGA evidence")
    expected_core = lanes * clock_mhz
    if not math.isclose(core, expected_core, rel_tol=1e-9, abs_tol=1e-6):
        raise CpuControlError(
            "FPGA evidence: core_mtrigrams_s must equal lanes * clock_mhz"
        )

    return {
        "cpu_control_gate": True,
        "cpu_model": model,
        "cpu_threads": threads,
        "fpga_core_mtrigrams_s": core,
        "cpu_materialized_mtrigrams_s": materialized,
        "cpu_reduced_mtrigrams_s": reduced,
        "cpu_strongest_mtrigrams_s": strongest,
        "core_vs_materialized_cpu_ratio": core / materialized,
        "core_vs_reduced_cpu_ratio": core / reduced,
        "core_vs_strongest_cpu_ratio": core / strongest,
        "cpu_competition_status": "unresolved",
    }


def render_key_values(report: Mapping[str, float | int | str | bool]) -> str:
    lines: list[str] = []
    for key, value in report.items():
        if isinstance(value, bool):
            rendered = "pass" if value else "fail"
        elif isinstance(value, float):
            rendered = f"{value:.6f}"
        else:
            rendered = str(value)
        lines.append(f"{key}={rendered}")
    lines.append(
        "claim_boundary=core-only diagnostics; no physical execution, host transport, "
        "power, temperature, or end-to-end latency"
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate fair CPU controls for BARDO-TX1."
    )
    parser.add_argument("--fpga-evidence", type=Path, required=True)
    parser.add_argument("--cpu-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        fpga = parse_key_values(
            args.fpga_evidence.read_text(encoding="utf-8"),
            source=str(args.fpga_evidence),
        )
        cpu = parse_key_values(
            args.cpu_evidence.read_text(encoding="utf-8"),
            source=str(args.cpu_evidence),
        )
        report = build_cpu_control_report(fpga=fpga, cpu=cpu)
        rendered = render_key_values(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    except (OSError, CpuControlError) as exc:
        print(f"cpu_control_gate=fail reason={exc}")
        return 1

    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
