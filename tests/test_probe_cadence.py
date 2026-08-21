import pytest

from bardocompute.probe_cadence import (
    ProbeCadenceEvidence,
    evaluate_probe_cadence,
)


def test_more_drift_shortens_probe_interval() -> None:
    calm = evaluate_probe_cadence(
        ProbeCadenceEvidence(
            trust=0.95,
            drift_score=0.05,
            miss_loss=120.0,
            false_action_loss=500.0,
            probe_cost=2.0,
        )
    )
    shifted = evaluate_probe_cadence(
        ProbeCadenceEvidence(
            trust=0.70,
            drift_score=0.60,
            miss_loss=120.0,
            false_action_loss=500.0,
            probe_cost=2.0,
        )
    )
    assert shifted.interval < calm.interval


def test_more_expensive_probe_lengthens_interval() -> None:
    cheap = evaluate_probe_cadence(
        ProbeCadenceEvidence(
            trust=0.8,
            drift_score=0.25,
            miss_loss=120.0,
            false_action_loss=500.0,
            probe_cost=1.0,
        )
    )
    expensive = evaluate_probe_cadence(
        ProbeCadenceEvidence(
            trust=0.8,
            drift_score=0.25,
            miss_loss=120.0,
            false_action_loss=500.0,
            probe_cost=16.0,
        )
    )
    assert expensive.interval > cheap.interval


def test_interval_is_clipped_to_bounds() -> None:
    minimum = evaluate_probe_cadence(
        ProbeCadenceEvidence(
            trust=0.0,
            drift_score=1.0,
            miss_loss=1000.0,
            false_action_loss=1000.0,
            probe_cost=0.01,
            min_interval=12,
            max_interval=200,
        )
    )
    maximum = evaluate_probe_cadence(
        ProbeCadenceEvidence(
            trust=1.0,
            drift_score=0.0,
            miss_loss=1.0,
            false_action_loss=1.0,
            probe_cost=1000.0,
            min_interval=12,
            max_interval=200,
        )
    )
    assert minimum.interval == 12
    assert maximum.interval == 200


def test_zero_probe_cost_selects_minimum_interval() -> None:
    result = evaluate_probe_cadence(
        ProbeCadenceEvidence(
            trust=0.9,
            drift_score=0.1,
            miss_loss=120.0,
            false_action_loss=500.0,
            probe_cost=0.0,
            min_interval=8,
            max_interval=256,
        )
    )
    assert result.interval == 8


@pytest.mark.parametrize(
    "field,value",
    [
        ("trust", -0.1),
        ("trust", 1.1),
        ("drift_score", -0.1),
        ("drift_score", 1.1),
        ("miss_loss", -1.0),
        ("false_action_loss", -1.0),
        ("probe_cost", -1.0),
        ("regret_floor", -1.0),
    ],
)
def test_invalid_values_are_rejected(field: str, value: float) -> None:
    kwargs = dict(
        trust=0.8,
        drift_score=0.2,
        miss_loss=120.0,
        false_action_loss=500.0,
        probe_cost=2.0,
    )
    kwargs[field] = value
    with pytest.raises(ValueError):
        ProbeCadenceEvidence(**kwargs)


def test_invalid_interval_bounds_are_rejected() -> None:
    with pytest.raises(ValueError):
        ProbeCadenceEvidence(
            trust=0.8,
            drift_score=0.2,
            miss_loss=120.0,
            false_action_loss=500.0,
            probe_cost=2.0,
            min_interval=0,
        )
    with pytest.raises(ValueError):
        ProbeCadenceEvidence(
            trust=0.8,
            drift_score=0.2,
            miss_loss=120.0,
            false_action_loss=500.0,
            probe_cost=2.0,
            min_interval=32,
            max_interval=16,
        )
