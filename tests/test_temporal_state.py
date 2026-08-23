import pytest

from bardocompute.phase_age import PhaseAgeBucket, PhaseAgeSignature
from bardocompute.phase_edge import PhaseEdgeSignature
from bardocompute.tao import EvidenceKind, TaoDecision
from bardocompute.temporal_state import TemporalState16
from bardocompute.trajectory import TrajectoryPhase


def test_temporal_state16_round_trip_and_reserved_budget() -> None:
    state = TemporalState16.encode(
        current_missing=EvidenceKind.OUTCOME,
        previous_phase=TrajectoryPhase.REGRESSING,
        current_phase=TrajectoryPhase.CONVERGING,
        phase_age_ticks=17,
        had_regression=True,
        had_discontinuity=True,
        decision=TaoDecision.DEFER,
    )

    assert state.current_missing is EvidenceKind.OUTCOME
    assert state.previous_phase is TrajectoryPhase.REGRESSING
    assert state.current_phase is TrajectoryPhase.CONVERGING
    assert state.age_bucket is PhaseAgeBucket.STALE
    assert state.had_regression
    assert state.had_discontinuity
    assert state.phase_edge_valid
    assert state.decision is TaoDecision.DEFER
    assert state.reserved_bits == 0
    assert state.code <= 0xFFFF


def test_temporal_state16_composes_edge_and_age() -> None:
    edge = PhaseEdgeSignature._encode(
        EvidenceKind.OUTCOME,
        TrajectoryPhase.REGRESSING,
        TrajectoryPhase.CONVERGING,
    )
    age = PhaseAgeSignature.encode(
        EvidenceKind.OUTCOME,
        TrajectoryPhase.CONVERGING,
        8,
    )
    state = TemporalState16.from_components(
        edge,
        age,
        had_regression=True,
        decision=TaoDecision.DEFER,
    )

    assert state.previous_phase is TrajectoryPhase.REGRESSING
    assert state.current_phase is TrajectoryPhase.CONVERGING
    assert state.age_bucket is PhaseAgeBucket.WARM
    assert state.had_regression


def test_temporal_state16_rejects_mismatched_components() -> None:
    edge = PhaseEdgeSignature._encode(
        EvidenceKind.OUTCOME,
        TrajectoryPhase.STALLED,
        TrajectoryPhase.CONVERGING,
    )
    wrong_center = PhaseAgeSignature.encode(
        EvidenceKind.AUTHORITY,
        TrajectoryPhase.CONVERGING,
        2,
    )
    with pytest.raises(ValueError, match="share current orientation"):
        TemporalState16.from_components(edge, wrong_center)

    wrong_phase = PhaseAgeSignature.encode(
        EvidenceKind.OUTCOME,
        TrajectoryPhase.STALLED,
        2,
    )
    with pytest.raises(ValueError, match="share current phase"):
        TemporalState16.from_components(edge, wrong_phase)


def test_reference_temporal_policy_uses_multiple_layers() -> None:
    safe = TemporalState16.encode(
        current_missing=EvidenceKind.OUTCOME,
        previous_phase=TrajectoryPhase.CONVERGING,
        current_phase=TrajectoryPhase.CONVERGING,
        phase_age_ticks=2,
    )
    current_regression = TemporalState16.encode(
        current_missing=EvidenceKind.OUTCOME,
        previous_phase=TrajectoryPhase.CONVERGING,
        current_phase=TrajectoryPhase.REGRESSING,
        phase_age_ticks=2,
        had_regression=True,
    )
    recent_recovery = TemporalState16.encode(
        current_missing=EvidenceKind.OUTCOME,
        previous_phase=TrajectoryPhase.REGRESSING,
        current_phase=TrajectoryPhase.CONVERGING,
        phase_age_ticks=2,
        had_regression=True,
    )
    stale_stall = TemporalState16.encode(
        current_missing=EvidenceKind.OUTCOME,
        previous_phase=TrajectoryPhase.STALLED,
        current_phase=TrajectoryPhase.STALLED,
        phase_age_ticks=32,
    )
    discontinuity = TemporalState16.encode(
        current_missing=EvidenceKind.OUTCOME,
        previous_phase=TrajectoryPhase.CONVERGING,
        current_phase=TrajectoryPhase.CONVERGING,
        phase_age_ticks=2,
        had_discontinuity=True,
    )
    denied = TemporalState16.encode(
        current_missing=EvidenceKind.NONE,
        previous_phase=TrajectoryPhase.CONVERGING,
        current_phase=TrajectoryPhase.CONVERGING,
        phase_age_ticks=2,
        decision=TaoDecision.DENY,
    )

    assert not safe.should_temporal_alert
    assert current_regression.should_temporal_alert
    assert recent_recovery.should_temporal_alert
    assert stale_stall.should_temporal_alert
    assert discontinuity.should_temporal_alert
    assert denied.should_temporal_alert


def test_reserved_decision_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="decision code 3 is reserved"):
        TemporalState16(3 << 12)
