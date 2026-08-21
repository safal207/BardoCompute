from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import inf


class OrientationAction(str, Enum):
    """High-level adaptation action for the living-process hypothesis."""

    KEEP = "keep"
    HOLD = "hold"
    ADAPT = "adapt"


@dataclass(frozen=True, slots=True)
class OrientationEvidence:
    """Evidence used to decide whether changing the execution model can repay itself.

    The model is intentionally small. It does not claim a universal law; it is
    an executable hypothesis that can be falsified across workloads.
    """

    confidence: float
    expected_remaining_steps: float
    saving_per_step: float
    observation_cost: float
    switch_cost: float
    error_cost: float
    hold_margin: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        for name in (
            "expected_remaining_steps",
            "saving_per_step",
            "observation_cost",
            "switch_cost",
            "error_cost",
            "hold_margin",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class OrientationResult:
    action: OrientationAction
    expected_benefit: float
    expected_cost: float
    score: float
    break_even_steps: float


def evaluate_orientation(evidence: OrientationEvidence) -> OrientationResult:
    """Evaluate the Orientation-Persistence payback hypothesis.

    Expected benefit is the confidence-weighted remaining lifetime of the new
    regime multiplied by the per-step saving from using the better execution
    path. Costs include observing, switching, and the current estimate of
    decision error. HOLD is a hysteresis band around the break-even boundary.
    """

    expected_benefit = (
        evidence.confidence
        * evidence.expected_remaining_steps
        * evidence.saving_per_step
    )
    expected_cost = (
        evidence.observation_cost + evidence.switch_cost + evidence.error_cost
    )
    score = expected_benefit - expected_cost

    denominator = evidence.confidence * evidence.saving_per_step
    break_even_steps = expected_cost / denominator if denominator > 0.0 else inf

    if score > evidence.hold_margin:
        action = OrientationAction.ADAPT
    elif score < -evidence.hold_margin:
        action = OrientationAction.KEEP
    else:
        action = OrientationAction.HOLD

    return OrientationResult(
        action=action,
        expected_benefit=expected_benefit,
        expected_cost=expected_cost,
        score=score,
        break_even_steps=break_even_steps,
    )
