from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaoDecision(str, Enum):
    """Three-way decision used when evidence may be incomplete.

    ALLOW and DENY are terminal decisions. DEFER is explicitly non-terminal:
    the current evidence is insufficient, but the computation retains the
    conditions needed to resolve later.

    "Tao" is project terminology for this orientation/decision layer. It is
    not a claim that historical Daoist texts define a ternary computer state.
    """

    ALLOW = "allow"
    DEFER = "defer"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    """Minimal evidence needed by the v0.1 Tao decision rule."""

    authority_valid: bool
    continuity_preserved: bool
    outcome: bool | None


def decide_tao(evidence: DecisionEvidence) -> TaoDecision:
    """Return a safe terminal decision or explicitly defer.

    Invalid authority or broken continuity is enough to deny immediately.
    When those guards hold but the external outcome is not yet known, the
    decision stays non-terminal instead of guessing success or failure.
    """

    if not evidence.authority_valid or not evidence.continuity_preserved:
        return TaoDecision.DENY
    if evidence.outcome is None:
        return TaoDecision.DEFER
    return TaoDecision.ALLOW if evidence.outcome else TaoDecision.DENY
