import pytest

from bardocompute.calibration_trust import (
    CalibrationTrustEvidence,
    evaluate_calibration_trust,
    shrink_correction_probabilities,
)


def test_trust_decreases_with_age_drift_and_error() -> None:
    fresh = evaluate_calibration_trust(
        CalibrationTrustEvidence(
            sample_count=1000,
            age_steps=0.0,
            drift_score=0.0,
            brier_score=0.05,
        )
    )
    stale = evaluate_calibration_trust(
        CalibrationTrustEvidence(
            sample_count=1000,
            age_steps=1024.0,
            drift_score=0.40,
            brier_score=0.25,
        )
    )
    assert 0.0 <= stale.trust < fresh.trust <= 1.0


def test_zero_samples_have_zero_trust() -> None:
    result = evaluate_calibration_trust(
        CalibrationTrustEvidence(
            sample_count=0,
            age_steps=0.0,
            drift_score=0.0,
            brier_score=0.0,
        )
    )
    assert result.trust == 0.0


def test_shrinkage_moves_probabilities_toward_prior() -> None:
    beneficial, harmful = shrink_correction_probabilities(
        0.80,
        0.05,
        trust=0.25,
        prior_beneficial=0.20,
        prior_harmful=0.20,
    )
    assert beneficial == pytest.approx(0.35)
    assert harmful == pytest.approx(0.1625)


def test_full_trust_preserves_probabilities() -> None:
    assert shrink_correction_probabilities(0.7, 0.1, trust=1.0) == pytest.approx(
        (0.7, 0.1)
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_count": -1},
        {"age_steps": -1.0},
        {"drift_score": -0.1},
        {"drift_score": 1.1},
        {"brier_score": -0.1},
        {"brier_score": 1.1},
        {"prior_strength": 0.0},
        {"age_half_life": 0.0},
    ],
)
def test_invalid_trust_evidence_is_rejected(kwargs: dict) -> None:
    base = dict(
        sample_count=10,
        age_steps=0.0,
        drift_score=0.0,
        brier_score=0.0,
        prior_strength=32.0,
        age_half_life=512.0,
    )
    base.update(kwargs)
    with pytest.raises(ValueError):
        CalibrationTrustEvidence(**base)


def test_invalid_probability_sums_are_rejected() -> None:
    with pytest.raises(ValueError):
        shrink_correction_probabilities(0.8, 0.3, trust=0.5)
