from bardocompute.line import BardoLine
from bardocompute.phase_edge import PhaseEdgeSignature
from bardocompute.tao import EvidenceKind, OrientedTao, TaoDecision
from bardocompute.trajectory import PhasePoint, TrajectoryPhase


def defer(mask: EvidenceKind) -> OrientedTao:
    return OrientedTao(TaoDecision.DEFER, mask)


def point(tick: int, mask: EvidenceKind) -> PhasePoint:
    return PhasePoint(tick, BardoLine.stable(0), defer(mask))


def test_phase_edge_preserves_previous_and_current_phase() -> None:
    signature = PhaseEdgeSignature.from_points(
        point(0, EvidenceKind.AUTHORITY | EvidenceKind.CONTINUITY | EvidenceKind.OUTCOME),
        point(1, EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME),
        point(2, EvidenceKind.OUTCOME),
    )

    assert signature.previous_phase is TrajectoryPhase.CONVERGING
    assert signature.current_phase is TrajectoryPhase.CONVERGING
    assert signature.current_missing is EvidenceKind.OUTCOME
    assert 0 <= signature.edge_code <= 15
    assert signature.code <= 0xFF


def test_phase_edge_distinguishes_same_current_phase_by_previous_phase() -> None:
    middle = point(1, EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME)
    current = point(2, EvidenceKind.OUTCOME)
    first_masks = (
        EvidenceKind.AUTHORITY | EvidenceKind.CONTINUITY | EvidenceKind.OUTCOME,
        EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME,
        EvidenceKind.OUTCOME,
        EvidenceKind.CONTINUITY | EvidenceKind.OUTCOME,
    )
    expected_previous = (
        TrajectoryPhase.CONVERGING,
        TrajectoryPhase.STALLED,
        TrajectoryPhase.REGRESSING,
        TrajectoryPhase.REORIENTING,
    )

    signatures = [
        PhaseEdgeSignature.from_points(point(0, mask), middle, current)
        for mask in first_masks
    ]

    assert {signature.current_phase for signature in signatures} == {
        TrajectoryPhase.CONVERGING
    }
    assert tuple(signature.previous_phase for signature in signatures) == expected_previous
    assert len({signature.edge_code for signature in signatures}) == 4


def test_advance_shifts_current_phase_into_previous_phase() -> None:
    signature = PhaseEdgeSignature.from_points(
        point(0, EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME),
        point(1, EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME),
        point(2, EvidenceKind.OUTCOME),
    )
    assert signature.previous_phase is TrajectoryPhase.STALLED
    assert signature.current_phase is TrajectoryPhase.CONVERGING

    advanced = signature.advance(EvidenceKind.OUTCOME)
    assert advanced.previous_phase is TrajectoryPhase.CONVERGING
    assert advanced.current_phase is TrajectoryPhase.STALLED
    assert advanced.current_missing is EvidenceKind.OUTCOME
    assert advanced.code <= 0xFF
