from bardocompute.tao import (
    DecisionEvidence,
    EvidenceKind,
    OrientedEvidence,
    TaoDecision,
    decide_tao,
    orient_tao,
)


def test_allows_only_with_positive_resolved_outcome() -> None:
    decision = decide_tao(
        DecisionEvidence(
            authority_valid=True,
            continuity_preserved=True,
            outcome=True,
        )
    )
    assert decision is TaoDecision.ALLOW


def test_denies_resolved_failure() -> None:
    decision = decide_tao(
        DecisionEvidence(
            authority_valid=True,
            continuity_preserved=True,
            outcome=False,
        )
    )
    assert decision is TaoDecision.DENY


def test_defers_when_outcome_is_unresolved() -> None:
    decision = decide_tao(
        DecisionEvidence(
            authority_valid=True,
            continuity_preserved=True,
            outcome=None,
        )
    )
    assert decision is TaoDecision.DEFER


def test_broken_continuity_denies_even_if_outcome_unknown() -> None:
    decision = decide_tao(
        DecisionEvidence(
            authority_valid=True,
            continuity_preserved=False,
            outcome=None,
        )
    )
    assert decision is TaoDecision.DENY


def test_stale_authority_denies_even_if_outcome_unknown() -> None:
    decision = decide_tao(
        DecisionEvidence(
            authority_valid=False,
            continuity_preserved=True,
            outcome=None,
        )
    )
    assert decision is TaoDecision.DENY


def test_oriented_tao_identifies_exact_missing_evidence() -> None:
    oriented = orient_tao(
        OrientedEvidence(
            authority_valid=None,
            continuity_preserved=True,
            outcome=None,
        )
    )
    assert oriented.decision is TaoDecision.DEFER
    assert oriented.missing == EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME
    assert oriented.waits_for(EvidenceKind.AUTHORITY)
    assert oriented.waits_for(EvidenceKind.OUTCOME)
    assert not oriented.waits_for(EvidenceKind.CONTINUITY)


def test_oriented_tao_denies_on_known_failure_without_waiting() -> None:
    oriented = orient_tao(
        OrientedEvidence(
            authority_valid=None,
            continuity_preserved=False,
            outcome=None,
        )
    )
    assert oriented.decision is TaoDecision.DENY
    assert oriented.missing == EvidenceKind.NONE


def test_oriented_tao_allows_when_all_required_evidence_is_positive() -> None:
    oriented = orient_tao(
        OrientedEvidence(
            authority_valid=True,
            continuity_preserved=True,
            outcome=True,
        )
    )
    assert oriented.decision is TaoDecision.ALLOW
    assert oriented.missing == EvidenceKind.NONE
