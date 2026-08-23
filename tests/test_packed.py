import pytest

from bardocompute.packed import (
    PACKED_FALLING_CONTINUOUS,
    PACKED_FALLING_DISCONTINUOUS,
    PACKED_ONE,
    PACKED_RISING_CONTINUOUS,
    PACKED_RISING_DISCONTINUOUS,
    PACKED_ZERO,
    RESERVED_PACKED_CODES,
    pack_line,
    packed_is_discontinuous,
    packed_is_transition,
    packed_settle,
    packed_source,
    packed_target,
    validate_packed_line,
)


@pytest.mark.parametrize(
    ("source", "target", "discontinuous", "expected"),
    [
        (0, 0, False, PACKED_ZERO),
        (1, 1, False, PACKED_ONE),
        (0, 1, False, PACKED_RISING_CONTINUOUS),
        (0, 1, True, PACKED_RISING_DISCONTINUOUS),
        (1, 0, False, PACKED_FALLING_CONTINUOUS),
        (1, 0, True, PACKED_FALLING_DISCONTINUOUS),
    ],
)
def test_pack_line_maps_all_v02_states(
    source: int,
    target: int,
    discontinuous: bool,
    expected: int,
) -> None:
    code = pack_line(source, target, discontinuous)

    assert code == expected
    assert packed_source(code) == source
    assert packed_target(code) == target
    assert packed_is_discontinuous(code) is discontinuous
    assert packed_is_transition(code) is (source != target)


def test_reserved_codes_are_rejected() -> None:
    for code in RESERVED_PACKED_CODES:
        with pytest.raises(ValueError):
            validate_packed_line(code)


def test_same_value_discontinuity_is_reserved() -> None:
    with pytest.raises(ValueError):
        pack_line(0, 0, True)

    with pytest.raises(ValueError):
        pack_line(1, 1, True)


def test_packed_settle_uses_target_bit() -> None:
    assert packed_settle(PACKED_RISING_CONTINUOUS) == PACKED_ONE
    assert packed_settle(PACKED_RISING_DISCONTINUOUS) == PACKED_ONE
    assert packed_settle(PACKED_FALLING_CONTINUOUS) == PACKED_ZERO
    assert packed_settle(PACKED_FALLING_DISCONTINUOUS) == PACKED_ZERO
