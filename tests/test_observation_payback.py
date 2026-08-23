import pytest

from bardocompute.observation_payback import (
    ObservationAction,
    ObservationPaybackEvidence,
    evaluate_observation_payback,
)


def test_revisit_when_expected_correction_repays_observation() -> None:
    result = evaluate_observation_payback(
        ObservationPaybackEvidence(
            beneficial_correction_probability=0.70,
            harmful_correction_probability=0.05,
            recoverable_miss_loss=120.0,
            false_action_loss=80.0,
            action_cost=20.0,
            observation_cost=12.0,
        )
    )
    assert result.action is ObservationAction.REVISIT
    assert result.score > 0.0


def test_skip_when_observation_is_too_expensive() -> None:
    result = evaluate_observation_payback(
        ObservationPaybackEvidence(
            beneficial_correction_probability=0.20,
            harmful_correction_probability=0.05,
            recoverable_miss_loss=120.0,
            false_action_loss=80.0,
            action_cost=20.0,
            observation_cost=40.0,
        )
    )
    assert result.action is ObservationAction.SKIP
    assert result.score < 0.0


def test_harmful_correction_probability_can_suppress_revisit() -> None:
    result = evaluate_observation_payback(
        ObservationPaybackEvidence(
            beneficial_correction_probability=0.55,
            harmful_correction_probability=0.40,
            recoverable_miss_loss=120.0,
            false_action_loss=200.0,
            action_cost=20.0,
            observation_cost=4.0,
        )
    )
    assert result.action is ObservationAction.SKIP


def test_hold_is_hysteresis_band_around_observation_break_even() -> None:
    result = evaluate_observation_payback(
        ObservationPaybackEvidence(
            beneficial_correction_probability=0.20,
            harmful_correction_probability=0.10,
            recoverable_miss_loss=120.0,
            false_action_loss=80.0,
            action_cost=20.0,
            observation_cost=10.0,
            hold_margin=1.0,
        )
    )
    # 0.2 * (120 - 20) - 0.1 * (80 + 20) - 10 == 0
    assert result.score == pytest.approx(0.0)
    assert result.action is ObservationAction.HOLD


def test_action_cost_larger_than_recoverable_loss_has_no_benefit() -> None:
    result = evaluate_observation_payback(
        ObservationPaybackEvidence(
            beneficial_correction_probability=1.0,
            harmful_correction_probability=0.0,
            recoverable_miss_loss=10.0,
            false_action_loss=0.0,
            action_cost=20.0,
            observation_cost=1.0,
        )
    )
    assert result.expected_benefit == 0.0
    assert result.action is ObservationAction.SKIP


@pytest.mark.parametrize(
    "field,value",
    [
        ("beneficial_correction_probability", -0.1),
        ("beneficial_correction_probability", 1.1),
        ("harmful_correction_probability", -0.1),
        ("harmful_correction_probability", 1.1),
        ("recoverable_miss_loss", -1.0),
        ("false_action_loss", -1.0),
        ("action_cost", -1.0),
        ("observation_cost", -1.0),
        ("hold_margin", -1.0),
    ],
)
def test_invalid_evidence_is_rejected(field: str, value: float) -> None:
    kwargs = dict(
        beneficial_correction_probability=0.4,
        harmful_correction_probability=0.2,
        recoverable_miss_loss=100.0,
        false_action_loss=100.0,
        action_cost=10.0,
        observation_cost=5.0,
        hold_margin=0.0,
    )
    kwargs[field] = value
    with pytest.raises(ValueError):
        ObservationPaybackEvidence(**kwargs)


def test_correction_probabilities_must_be_mutually_compatible() -> None:
    with pytest.raises(ValueError):
        ObservationPaybackEvidence(
            beneficial_correction_probability=0.7,
            harmful_correction_probability=0.4,
            recoverable_miss_loss=100.0,
            false_action_loss=100.0,
            action_cost=10.0,
            observation_cost=5.0,
        )
