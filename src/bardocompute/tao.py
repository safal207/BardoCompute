from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntFlag


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


class EvidenceKind(IntFlag):
    """Evidence dimensions that may still be required to settle a decision."""

    NONE = 0
    AUTHORITY = 1
    CONTINUITY = 2
    OUTCOME = 4


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    """Minimal evidence needed by the v0.1 Tao decision rule."""

    authority_valid: bool
    continuity_preserved: bool
    outcome: bool | None


@dataclass(frozen=True, slots=True)
class OrientedEvidence:
    """Evidence where each dimension may itself still be unresolved."""

    authority_valid: bool | None
    continuity_preserved: bool | None
    outcome: bool | None


@dataclass(frozen=True, slots=True)
class OrientedTao:
    """A terminal decision or a defer state carrying its missing-evidence mask."""

    decision: TaoDecision
    missing: EvidenceKind = EvidenceKind.NONE

    def __post_init__(self) -> None:
        if self.decision is TaoDecision.DEFER and self.missing is EvidenceKind.NONE:
            raise ValueError("deferred Tao state must identify missing evidence")
        if self.decision is not TaoDecision.DEFER and self.missing is not EvidenceKind.NONE:
            raise ValueError("terminal Tao state cannot carry missing evidence")

    def waits_for(self, kind: EvidenceKind) -> bool:
        return bool(self.missing & kind)


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


def orient_tao(evidence: OrientedEvidence) -> OrientedTao:
    """Return a decision plus the exact evidence still needed to settle it.

    Known failure is terminal. Otherwise unresolved evidence is represented as
    a bit mask so an event-driven runtime can route only relevant updates back
    to this decision instead of treating every pending item identically.
    """

    if evidence.authority_valid is False:
        return OrientedTao(TaoDecision.DENY)
    if evidence.continuity_preserved is False:
        return OrientedTao(TaoDecision.DENY)
    if evidence.outcome is False:
        return OrientedTao(TaoDecision.DENY)

    missing = EvidenceKind.NONE
    if evidence.authority_valid is None:
        missing |= EvidenceKind.AUTHORITY
    if evidence.continuity_preserved is None:
        missing |= EvidenceKind.CONTINUITY
    if evidence.outcome is None:
        missing |= EvidenceKind.OUTCOME

    if missing is not EvidenceKind.NONE:
        return OrientedTao(TaoDecision.DEFER, missing)
    return OrientedTao(TaoDecision.ALLOW)
