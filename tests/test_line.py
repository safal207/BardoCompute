import pytest

from bardocompute import BardoLine, LineState


def test_stable_line() -> None:
    zero = BardoLine.stable(0)
    one = BardoLine.stable(1)

    assert zero.state is LineState.ZERO
    assert zero.source == zero.target == 0
    assert not zero.is_transition

    assert one.state is LineState.ONE
    assert one.source == one.target == 1
    assert not one.is_transition


def test_rising_transition_retains_source_and_target() -> None:
    line = BardoLine.between(0, 1)

    assert line.state is LineState.RISING
    assert line.source == 0
    assert line.target == 1
    assert line.is_transition
    assert line.settle() == BardoLine.stable(1)


def test_falling_transition_retains_source_and_target() -> None:
    line = BardoLine.between(1, 0)

    assert line.state is LineState.FALLING
    assert line.source == 1
    assert line.target == 0
    assert line.is_transition
    assert line.settle() == BardoLine.stable(0)


def test_invalid_value_rejected() -> None:
    with pytest.raises(ValueError):
        BardoLine.stable(2)
