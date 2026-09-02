from __future__ import annotations

from bardocompute.hardware_contract import (
    evaluate_trigram,
    pack_tx1_result,
    unpack_trigram_lines,
)
from bardocompute.hardware_oracle import ORACLE_SIZE, exhaustive_oracle, render_c_header


def test_exhaustive_oracle_covers_all_sparse_addresses() -> None:
    oracle = exhaustive_oracle()

    assert len(oracle) == ORACLE_SIZE == 512
    assert oracle == tuple(
        pack_tx1_result(evaluate_trigram(unpack_trigram_lines(bundle)))
        for bundle in range(512)
    )
    assert sum(value != 0 for value in oracle) == 216


def test_reserved_codes_are_fail_closed_in_oracle() -> None:
    oracle = exhaustive_oracle()

    for bundle in range(512):
        lower, middle, upper = unpack_trigram_lines(bundle)
        if 0b001 in (lower, middle, upper) or 0b111 in (lower, middle, upper):
            assert oracle[bundle] == 0


def test_c_header_is_deterministic_and_bounded() -> None:
    header = render_c_header()

    assert header == render_c_header()
    assert "#define BARDO_TX1_ORACLE_SIZE 512u" in header
    assert header.count("UINT32_C(") == 512
    assert "static const uint32_t BARDO_TX1_ORACLE" in header
