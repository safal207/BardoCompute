"""Generate an independent exhaustive C oracle for BARDO-TX1."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .hardware_contract import evaluate_trigram, pack_tx1_result, unpack_trigram_lines

ORACLE_SIZE = 512


def exhaustive_oracle() -> tuple[int, ...]:
    """Return the Python-contract result for every nine-bit input address."""

    return tuple(
        pack_tx1_result(evaluate_trigram(unpack_trigram_lines(bundle)))
        for bundle in range(ORACLE_SIZE)
    )


def render_c_header(values: Sequence[int] | None = None) -> str:
    """Render a deterministic C header consumed by the independent baseline."""

    oracle = tuple(exhaustive_oracle() if values is None else values)
    if len(oracle) != ORACLE_SIZE:
        raise ValueError(f"oracle must contain exactly {ORACLE_SIZE} values")
    if any(not isinstance(value, int) or not 0 <= value < (1 << 23) for value in oracle):
        raise ValueError("oracle values must be unsigned 23-bit integers")

    lines = [
        "#ifndef BARDO_TX1_ORACLE_H",
        "#define BARDO_TX1_ORACLE_H",
        "",
        "#include <stdint.h>",
        "",
        f"#define BARDO_TX1_ORACLE_SIZE {ORACLE_SIZE}u",
        "static const uint32_t BARDO_TX1_ORACLE[BARDO_TX1_ORACLE_SIZE] = {",
    ]
    for offset in range(0, ORACLE_SIZE, 8):
        chunk = oracle[offset : offset + 8]
        lines.append("    " + ", ".join(f"UINT32_C(0x{value:06x})" for value in chunk) + ",")
    lines.extend(["};", "", "#endif", ""])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate BARDO-TX1 exhaustive C oracle")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_c_header(), encoding="utf-8")
    print(f"oracle_entries={ORACLE_SIZE}")
    print("oracle_source=python_hardware_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
