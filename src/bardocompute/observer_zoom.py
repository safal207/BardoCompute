from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import fmean


class ObserverLevel(str, Enum):
    """Epistemic levels used by the adaptive-observer hypothesis.

    The names are engineering labels inspired by the research metaphor. They
    are not claims about consciousness or metaphysics.
    """

    POSITION = "position"
    KNOWLEDGE = "knowledge"
    VISION = "vision"
    PRESENCE = "presence"
    OPEN = "open"


class ObserverAction(str, Enum):
    STAY = "stay"
    ZOOM_OUT = "zoom_out"
    HOLD = "hold"
    RELEASE_MODEL = "release_model"


@dataclass(frozen=True, slots=True)
class ScaleObservation:
    scale: int
    change_score: float

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ValueError("scale must be positive")
        if not 0.0 <= self.change_score <= 1.0:
            raise ValueError("change_score must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class ObserverAssessment:
    level: ObserverLevel
    action: ObserverAction
    change_belief: float
    confidence: float
    scale_spread: float
    largest_scale: int


def assess_observer(
    observations: tuple[ScaleObservation, ...],
    *,
    change_threshold: float = 0.5,
    agreement_tolerance: float = 0.15,
    strong_conflict_threshold: float = 0.85,
    conflict_streak: int = 0,
    release_streak: int = 2,
) -> ObserverAssessment:
    """Assess whether evidence survives a change of observation scale.

    Operational interpretation for v0.1:

    - POSITION: only one scale is known; it has no authority to finalize.
    - KNOWLEDGE: at least two scales agree on the same side of the threshold.
    - VISION: three or more scales agree tightly.
    - PRESENCE: scales disagree; preserve non-action and, when possible,
      acquire a wider view rather than reacting to one scale.
    - OPEN: repeated strong, cross-scale change evidence may release the old
      model commitment. History is retained; OPEN is not a reset.

    This function prepares evidence. It does not itself choose KEEP/ADAPT;
    that remains the job of the Living Process orientation layer.
    """

    if not observations:
        raise ValueError("at least one observation is required")
    if not 0.0 < change_threshold < 1.0:
        raise ValueError("change_threshold must be in (0, 1)")
    if agreement_tolerance < 0.0:
        raise ValueError("agreement_tolerance must be non-negative")
    if conflict_streak < 0 or release_streak < 1:
        raise ValueError("invalid conflict streak")

    ordered = tuple(sorted(observations, key=lambda item: item.scale))
    scores = tuple(item.change_score for item in ordered)
    belief = fmean(scores)
    spread = max(scores) - min(scores)
    largest_scale = ordered[-1].scale
    confidence = max(0.0, 1.0 - spread)

    if len(ordered) == 1:
        return ObserverAssessment(
            level=ObserverLevel.POSITION,
            action=ObserverAction.ZOOM_OUT,
            change_belief=belief,
            confidence=confidence,
            scale_spread=spread,
            largest_scale=largest_scale,
        )

    above = tuple(score >= change_threshold for score in scores)
    same_side = all(above) or not any(above)

    if not same_side or spread > max(agreement_tolerance * 2.0, 0.30):
        action = ObserverAction.ZOOM_OUT if len(ordered) < 3 else ObserverAction.HOLD
        return ObserverAssessment(
            level=ObserverLevel.PRESENCE,
            action=action,
            change_belief=belief,
            confidence=confidence,
            scale_spread=spread,
            largest_scale=largest_scale,
        )

    strong_change = min(scores) >= strong_conflict_threshold
    if len(ordered) >= 3 and strong_change and conflict_streak >= release_streak:
        return ObserverAssessment(
            level=ObserverLevel.OPEN,
            action=ObserverAction.RELEASE_MODEL,
            change_belief=belief,
            confidence=confidence,
            scale_spread=spread,
            largest_scale=largest_scale,
        )

    level = (
        ObserverLevel.VISION
        if len(ordered) >= 3 and spread <= agreement_tolerance
        else ObserverLevel.KNOWLEDGE
    )
    return ObserverAssessment(
        level=level,
        action=ObserverAction.STAY,
        change_belief=belief,
        confidence=confidence,
        scale_spread=spread,
        largest_scale=largest_scale,
    )
