from __future__ import annotations

from dataclasses import dataclass
from math import exp


@dataclass(frozen=True, slots=True)
class CalibrationTrustEvidence:
    """Evidence for how much a historical calibration should influence a decision."""

    sample_count: int
    age_steps: float
    drift_score: float
    brier_score: float
    prior_strength: float = 32.0
    age_half_life: float = 512.0

    def __post_init__(self) -> None:
        if self.sample_count < 0:
            raise ValueError("sample_count must be non-negative")
        if self.age_steps < 0.0:
            raise ValueError("age_steps must be non-negative")
        if not 0.0 <= self.drift_score <= 1.0:
            raise ValueError("drift_score must be in [0, 1]")
        if not 0.0 <= self.brier_score <= 1.0:
            raise ValueError("brier_score must be in [0, 1]")
        if self.prior_strength <= 0.0:
            raise ValueError("prior_strength must be positive")
        if self.age_half_life <= 0.0:
            raise ValueError("age_half_life must be positive")


@dataclass(frozen=True, slots=True)
class CalibrationTrustResult:
    trust: float
    sample_trust: float
    age_trust: float
    drift_trust: float
    calibration_trust: float


def evaluate_calibration_trust(
    evidence: CalibrationTrustEvidence,
) -> CalibrationTrustResult:
    """Return a bounded trust score from measurable calibration provenance.

    The multiplicative form is intentionally conservative: no single strong
    component can fully compensate for severe drift, extreme age, or poor
    calibration. This is a falsifiable engineering heuristic, not a universal
    statistical law.
    """

    sample_trust = evidence.sample_count / (
        evidence.sample_count + evidence.prior_strength
    )
    age_trust = exp(-0.6931471805599453 * evidence.age_steps / evidence.age_half_life)
    drift_trust = 1.0 - evidence.drift_score
    calibration_trust = 1.0 - evidence.brier_score
    trust = sample_trust * age_trust * drift_trust * calibration_trust
    return CalibrationTrustResult(
        trust=trust,
        sample_trust=sample_trust,
        age_trust=age_trust,
        drift_trust=drift_trust,
        calibration_trust=calibration_trust,
    )


def shrink_correction_probabilities(
    beneficial_probability: float,
    harmful_probability: float,
    *,
    trust: float,
    prior_beneficial: float = 1.0 / 3.0,
    prior_harmful: float = 1.0 / 3.0,
) -> tuple[float, float]:
    """Shrink stale/uncertain correction probabilities toward a neutral prior."""

    for name, value in (
        ("beneficial_probability", beneficial_probability),
        ("harmful_probability", harmful_probability),
        ("trust", trust),
        ("prior_beneficial", prior_beneficial),
        ("prior_harmful", prior_harmful),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in [0, 1]")
    if beneficial_probability + harmful_probability > 1.0 + 1e-12:
        raise ValueError("correction probabilities must sum to <= 1")
    if prior_beneficial + prior_harmful > 1.0 + 1e-12:
        raise ValueError("prior probabilities must sum to <= 1")

    beneficial = trust * beneficial_probability + (1.0 - trust) * prior_beneficial
    harmful = trust * harmful_probability + (1.0 - trust) * prior_harmful
    return beneficial, harmful
