import math

import pytest

from bardocompute.living_process import (
    OrientationAction,
    OrientationEvidence,
    evaluate_orientation,
)


def test_adapt_when_expected_persistence_repays_cost() -> None:
    result = evaluate_orientation(
        OrientationEvidence(
            confidence=0.9,
            expected_remaining_steps=512,
            saving_per_step=1.0,
            observation_cost=32.0,
            switch_cost=80.0,
            error_cost=16.0,
            hold_margin=8.0,
        )
    )
    assert result.action is OrientationAction.ADAPT
    assert result.score > 0.0


def test_keep_when_regime_is_too_short_to_repay_switch() -> None:
    result = evaluate_orientation(
        OrientationEvidence(
            confidence=0.9,
            expected_remaining_steps=64,
            saving_per_step=1.0,
            observation_cost=32.0,
            switch_cost=80.0,
            error_cost=16.0,
            hold_margin=8.0,
        )
    )
    assert result.action is OrientationAction.KEEP
    assert result.score < 0.0


def test_hold_near_break_even_boundary() -> None:
    result = evaluate_orientation(
        OrientationEvidence(
            confidence=1.0,
            expected_remaining_steps=128,
            saving_per_step=1.0,
            observation_cost=32.0,
            switch_cost=80.0,
            error_cost=16.0,
            hold_margin=4.0,
        )
    )
    assert result.action is OrientationAction.HOLD
    assert result.score == 0.0
    assert result.break_even_steps == 128.0


def test_zero_saving_has_infinite_break_even() -> None:
    result = evaluate_orientation(
        OrientationEvidence(
            confidence=1.0,
            expected_remaining_steps=1024,
            saving_per_step=0.0,
            observation_cost=1.0,
            switch_cost=1.0,
            error_cost=1.0,
        )
    )
    assert result.action is OrientationAction.KEEP
    assert math.isinf(result.break_even_steps)


@pytest.mark.parametrize(
    "field,value",
    [
        ("confidence", 1.1),
        ("expected_remaining_steps", -1.0),
        ("saving_per_step", -1.0),
        ("observation_cost", -1.0),
        ("switch_cost", -1.0),
        ("error_cost", -1.0),
        ("hold_margin", -1.0),
    ],
)
def test_invalid_evidence_is_rejected(field: str, value: float) -> None:
    kwargs = dict(
        confidence=0.8,
        expected_remaining_steps=100.0,
        saving_per_step=1.0,
        observation_cost=1.0,
        switch_cost=1.0,
        error_cost=1.0,
        hold_margin=1.0,
    )
    kwargs[field] = value
    with pytest.raises(ValueError):
        OrientationEvidence(**kwargs)
