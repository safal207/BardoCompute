from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ObservationAction(str, Enum):
    """Whether additional observation is expected to repay its cost."""

    SKIP = "skip"
    HOLD = "hold"
    REVISIT = "revisit"


@dataclass(frozen=True, slots=True)
class ObservationPaybackEvidence:
    """Economic evidence for buying one additional observation step.

    ``beneficial_correction_probability`` and
    ``harmful_correction_probability`` are expected frequencies of mutually
    exclusive outcomes from the proposed follow-up observation. They must be
    estimated from information available before the decision (for example,
    historical calibration plus current sentinel evidence), never from the
    hidden future of the episode being decided.
    """

    beneficial_correction_probability: float
    harmful_correction_probability: float
    recoverable_miss_loss: float
    false_action_loss: float
    action_cost: float
    observation_cost: float
    hold_margin: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "beneficial_correction_probability",
            "harmful_correction_probability",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")

        if (
            self.beneficial_correction_probability
            + self.harmful_correction_probability
            > 1.0 + 1e-12
        ):
            raise ValueError("correction probabilities must sum to <= 1")

        for name in (
            "recoverable_miss_loss",
            "false_action_loss",
            "action_cost",
            "observation_cost",
            "hold_margin",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class ObservationPaybackResult:
    action: ObservationAction
    expected_benefit: float
    expected_harm: float
    expected_observation_cost: float
    score: float


def evaluate_observation_payback(
    evidence: ObservationPaybackEvidence,
) -> ObservationPaybackResult:
    """Estimate whether one deeper/revisited observation is worth buying.

    The proposed observation is useful only when it can correct a costly
    current decision. A beneficial correction avoids a miss but still pays the
    downstream action cost. A harmful correction triggers an unnecessary
    action and therefore pays both false-action loss and action cost.

    This is a decision-theoretic kernel, not an oracle. The quality of the
    result depends on calibration of the two probabilities supplied to it.
    """

    expected_benefit = evidence.beneficial_correction_probability * max(
        0.0, evidence.recoverable_miss_loss - evidence.action_cost
    )
    expected_harm = evidence.harmful_correction_probability * (
        evidence.false_action_loss + evidence.action_cost
    )
    expected_observation_cost = evidence.observation_cost
    score = expected_benefit - expected_harm - expected_observation_cost

    if score > evidence.hold_margin:
        action = ObservationAction.REVISIT
    elif score < -evidence.hold_margin:
        action = ObservationAction.SKIP
    else:
        action = ObservationAction.HOLD

    return ObservationPaybackResult(
        action=action,
        expected_benefit=expected_benefit,
        expected_harm=expected_harm,
        expected_observation_cost=expected_observation_cost,
        score=score,
    )
