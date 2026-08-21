import pytest

from bardocompute.line import BardoLine, TransitionMode
from bardocompute.tao import EvidenceKind, OrientedTao, TaoDecision
from bardocompute.trajectory import PhasePoint, PhaseTrajectory, orientation_vector


def defer(mask: EvidenceKind) -> OrientedTao:
    return OrientedTao(TaoDecision.DEFER, mask)


def test_orientation_vector_is_three_axis_missing_evidence_coordinate() -> None:
    mask = EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME
    assert orientation_vector(mask) == (1, 0, 1)


def test_monotone_trajectory_measures_convergence() -> None:
    trajectory = PhaseTrajectory(
        (
            PhasePoint(
                0,
                BardoLine.stable(0),
                defer(EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME),
            ),
            PhasePoint(
                2,
                BardoLine.between(0, 1, TransitionMode.CONTINUOUS),
                defer(EvidenceKind.OUTCOME),
            ),
            PhasePoint(5, BardoLine.stable(1), OrientedTao(TaoDecision.ALLOW)),
        )
    )

    assert trajectory.duration == 5
    assert trajectory.orientation_path_length == 2
    assert trajectory.resolved_dimensions == 2
    assert trajectory.regressions == 0
    assert trajectory.discontinuities == 0
    assert trajectory.convergence_time == 5
    assert trajectory.is_monotone_convergent


def test_regression_and_discontinuity_are_visible_in_path() -> None:
    trajectory = PhaseTrajectory(
        (
            PhasePoint(0, BardoLine.stable(0), defer(EvidenceKind.OUTCOME)),
            PhasePoint(1, BardoLine.stable(0), OrientedTao(TaoDecision.ALLOW)),
            PhasePoint(
                2,
                BardoLine.between(0, 1, TransitionMode.DISCONTINUOUS),
                defer(EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME),
            ),
            PhasePoint(4, BardoLine.stable(1), OrientedTao(TaoDecision.ALLOW)),
        )
    )

    assert trajectory.orientation_path_length == 4
    assert trajectory.regressions == 2
    assert trajectory.discontinuities == 1
    assert not trajectory.is_monotone_convergent


def test_ticks_must_be_strictly_increasing() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        PhaseTrajectory(
            (
                PhasePoint(1, BardoLine.stable(0), defer(EvidenceKind.OUTCOME)),
                PhasePoint(1, BardoLine.stable(0), OrientedTao(TaoDecision.ALLOW)),
            )
        )
