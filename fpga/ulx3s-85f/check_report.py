#!/usr/bin/env python3
"""Fail closed on structural or timing regressions in the ECP5 report."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


def _used(utilization: dict[str, Any], resource: str) -> int:
    entry = utilization.get(resource)
    if not isinstance(entry, dict) or "used" not in entry:
        raise ValueError(f"nextpnr report is missing utilization.{resource}.used")
    value = entry["used"]
    if type(value) is not int:
        raise ValueError(
            f"nextpnr report utilization.{resource}.used must be an integer"
        )
    result = int(value)
    if result < 0:
        raise ValueError(
            f"nextpnr report utilization.{resource}.used must be non-negative"
        )
    return result


def _timing_mhz(timing: dict[str, Any], field: str, clock_name: str) -> float:
    if field not in timing:
        raise ValueError(f"clock {clock_name!r} is missing {field!r}")
    value = timing[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"clock {clock_name!r} {field!r} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(
            f"clock {clock_name!r} {field!r} must be finite"
        ) from exc
    if not math.isfinite(result):
        raise ValueError(f"clock {clock_name!r} {field!r} must be finite")
    if result <= 0.0:
        raise ValueError(f"clock {clock_name!r} {field!r} must be positive")
    return result


def main() -> int:
    if len(sys.argv) != 3:
        print(
            f"usage: {Path(sys.argv[0]).name} "
            "NEXT_PNR_REPORT.json EXPECTED_CLOCK_MHZ",
            file=sys.stderr,
        )
        return 2

    report_path = Path(sys.argv[1])
    try:
        expected_clock_mhz = float(sys.argv[2])
        if not math.isfinite(expected_clock_mhz) or expected_clock_mhz <= 0.0:
            raise ValueError("expected clock must be finite and positive")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        utilization = report["utilization"]
        fmax = report["fmax"]
        if not isinstance(utilization, dict) or not isinstance(fmax, dict) or not fmax:
            raise ValueError("nextpnr report has no usable utilization/fmax data")

        dsp_used = _used(utilization, "MULT18X18D")
        comb_used = _used(utilization, "TRELLIS_COMB")
        ff_used = _used(utilization, "TRELLIS_FF")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"resource_check=fail reason={exc}", file=sys.stderr)
        return 1

    errors: list[str] = []
    matching_clock_constraints: list[str] = []
    if dsp_used != 0:
        errors.append(
            f"MULT18X18D used={dsp_used}; "
            "BARDO-TX1 radix constants must not consume DSPs"
        )

    for clock_name, timing in fmax.items():
        if not isinstance(timing, dict):
            errors.append(f"clock {clock_name!r} has malformed timing data")
            continue
        try:
            achieved = _timing_mhz(timing, "achieved", clock_name)
            constraint = _timing_mhz(timing, "constraint", clock_name)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        print(
            f"clock={clock_name} achieved_mhz={achieved:.3f} "
            f"constraint_mhz={constraint:.3f}"
        )
        if achieved + 1e-9 < constraint:
            errors.append(
                f"clock {clock_name} achieved {achieved:.3f} MHz below "
                f"{constraint:.3f} MHz constraint"
            )
        if math.isclose(
            constraint,
            expected_clock_mhz,
            rel_tol=1e-4,
            abs_tol=1e-6,
        ):
            matching_clock_constraints.append(str(clock_name))

    if len(matching_clock_constraints) != 1:
        errors.append(
            "expected exactly one fmax constraint matching "
            f"{expected_clock_mhz:.6g} MHz, found "
            f"{len(matching_clock_constraints)}"
        )

    print(f"expected_clock_mhz={expected_clock_mhz:.6g}")
    print(f"mult18x18d_used={dsp_used}")
    print(f"trellis_comb_used={comb_used}")
    print(f"trellis_ff_used={ff_used}")

    if errors:
        for error in errors:
            print(f"resource_error={error}", file=sys.stderr)
        print("resource_check=fail", file=sys.stderr)
        return 1

    print("resource_check=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
