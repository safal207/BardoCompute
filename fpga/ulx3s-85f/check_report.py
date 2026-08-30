#!/usr/bin/env python3
"""Fail closed on structural or timing regressions in the ECP5 report."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _used(utilization: dict[str, Any], resource: str) -> int:
    entry = utilization.get(resource)
    if not isinstance(entry, dict) or "used" not in entry:
        raise ValueError(f"nextpnr report is missing utilization.{resource}.used")
    return int(entry["used"])


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} NEXT_PNR_REPORT.json", file=sys.stderr)
        return 2

    report_path = Path(sys.argv[1])
    try:
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
    if dsp_used != 0:
        errors.append(
            f"MULT18X18D used={dsp_used}; BARDO-TX1 radix constants must not consume DSPs"
        )

    for clock_name, timing in fmax.items():
        if not isinstance(timing, dict):
            errors.append(f"clock {clock_name!r} has malformed timing data")
            continue
        achieved = float(timing.get("achieved", 0.0))
        constraint = float(timing.get("constraint", 0.0))
        print(
            f"clock={clock_name} achieved_mhz={achieved:.3f} "
            f"constraint_mhz={constraint:.3f}"
        )
        if achieved + 1e-9 < constraint:
            errors.append(
                f"clock {clock_name} achieved {achieved:.3f} MHz below "
                f"{constraint:.3f} MHz constraint"
            )

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
