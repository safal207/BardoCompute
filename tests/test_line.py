import pytest

from bardocompute import BardoLine, LineState, TransitionMode


def test_stable_line() -> None:
    zero = BardoLine.stable(0)
    one = BardoLine.stable(1)

    assert zero.state is LineState.ZERO
    assert zero.mode is TransitionMode.STABLE
    assert zero.source == zero.target == 0
    assert not zero.is_transition

    assert one.state is LineState.ONE
    assert one.mode is TransitionMode.STABLE
    assert one.source == one.target == 1
    assert not one.is_transition


def test_rising_transition_retains_source_and_target() -> None:
    line = BardoLine.between(0, 1)

    assert line.state is LineState.RISING
    assert line.mode is TransitionMode.CONTINUOUS
    assert line.source == 0
    assert line.target == 1
    assert line.is_transition
    assert line.preserves_continuity
    assert line.settle() == BardoLine.stable(1)


def test_falling_transition_retains_source_and_target() -> None:
    line = BardoLine.between(1, 0)

    assert line.state is LineState.FALLING
    assert line.mode is TransitionMode.CONTINUOUS
    assert line.source == 1
    assert line.target == 0
    assert line.is_transition
    assert line.preserves_continuity
    assert line.settle() == BardoLine.stable(0)


def test_same_endpoints_can_have_different_transition_semantics() -> None:
    continuous = BardoLine.between(0, 1, TransitionMode.CONTINUOUS)
    discontinuous = BardoLine.between(0, 1, TransitionMode.DISCONTINUOUS)

    assert continuous.source == discontinuous.source == 0
    assert continuous.target == discontinuous.target == 1
    assert continuous != discontinuous
    assert continuous.preserves_continuity
    assert not discontinuous.preserves_continuity


def test_discontinuous_transition_still_settles_to_target() -> None:
    line = BardoLine.between(1, 0, TransitionMode.DISCONTINUOUS)

    assert line.state is LineState.FALLING
    assert line.mode is TransitionMode.DISCONTINUOUS
    assert line.settle() == BardoLine.stable(0)


def test_equal_endpoints_are_stable_only_in_v02() -> None:
    assert BardoLine.between(1, 1) == BardoLine.stable(1)

    with pytest.raises(ValueError):
        BardoLine.between(1, 1, TransitionMode.DISCONTINUOUS)


def test_invalid_value_rejected() -> None:
    with pytest.raises(ValueError):
        BardoLine.stable(2)


def test_transition_cannot_use_stable_mode() -> None:
    with pytest.raises(ValueError):
        BardoLine.between(0, 1, TransitionMode.STABLE)
