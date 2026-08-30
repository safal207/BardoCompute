from __future__ import annotations

from itertools import product

import pytest

from bardocompute.hardware_contract import (
    LINE_CODE_FROM_DIGIT,
    decode_trigram_index,
    evaluate_lanes,
    evaluate_trigram,
    pack_trigram_lines,
    unpack_trigram_lines,
)
from bardocompute.packed import VALID_PACKED_CODES, packed_settle


def test_dense_index_is_a_bijection_over_all_216_valid_trigrams() -> None:
    seen: dict[int, tuple[int, int, int]] = {}
    for lines in product(LINE_CODE_FROM_DIGIT, repeat=3):
        result = evaluate_trigram(lines)
        assert result.valid
        assert 0 <= result.trigram_index < 216
        assert result.trigram_index not in seen
        seen[result.trigram_index] = lines
        assert decode_trigram_index(result.trigram_index) == lines

    assert set(seen) == set(range(216))


def test_all_512_sparse_input_bundles_match_fail_closed_contract() -> None:
    for lines in product(range(8), repeat=3):
        result = evaluate_trigram(lines)
        expected_valid = all(code in VALID_PACKED_CODES for code in lines)
        assert result.valid is expected_valid

        if not expected_valid:
            assert result.trigram_index == 0
            assert result.policy_allow is False
            assert result.settled_lines == (0, 0, 0)
            assert result.any_discontinuous is False
            assert result.any_transition is False
            assert result.target_count == 0
            continue

        expected_discontinuous = any(code & 1 for code in lines)
        expected_transition = any(((code >> 2) & 1) != ((code >> 1) & 1) for code in lines)
        expected_target_count = sum((code >> 1) & 1 for code in lines)
        expected_policy = (
            not expected_discontinuous
            and expected_target_count >= 2
            and expected_transition
        )
        assert result.any_discontinuous is expected_discontinuous
        assert result.any_transition is expected_transition
        assert result.target_count == expected_target_count
        assert result.policy_allow is expected_policy
        assert result.settled_lines == tuple(packed_settle(code) for code in lines)


def test_sparse_bundle_wire_order_is_lower_middle_upper() -> None:
    lines = (0b010, 0b101, 0b110)
    bundle = pack_trigram_lines(*lines)
    assert bundle == 0b110_101_010
    assert unpack_trigram_lines(bundle) == lines


def test_parallel_reference_is_lane_independent() -> None:
    lanes = (
        (0b010, 0b110, 0b110),
        (0b011, 0b110, 0b110),
        (0b001, 0b110, 0b110),
    )
    assert evaluate_lanes(lanes) == tuple(evaluate_trigram(lines) for lines in lanes)
    assert [result.policy_allow for result in evaluate_lanes(lanes)] == [True, False, False]


@pytest.mark.parametrize("bad", [-1, 8, 99, 1.5, "010"])
def test_line_inputs_must_be_three_bit_integers(bad: object) -> None:
    with pytest.raises(ValueError):
        evaluate_trigram((0, 0, bad))  # type: ignore[arg-type]
