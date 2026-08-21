from bardocompute.tao import DecisionEvidence, TaoDecision, decide_tao


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
