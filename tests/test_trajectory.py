import pytest

from bardocompute.line import BardoLine, TransitionMode
from bardocompute.tao import EvidenceKind, OrientedTao, TaoDecision
from bardocompute.trajectory import (
    KineticSignature,
    PhasePoint,
    PhaseTrajectory,
    TrajectoryPhase,
    orientation_vector,
)


def defer(mask: EvidenceKind) -> OrientedTao:
    return OrientedTao(TaoDecision.DEFER, mask)


def test_orientation_vector_is_three_axis_missing_evidence_coordinate() -> None:
    mask = EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME
    assert orientation_vector(mask) == (1, 0, 1)


def test_monotone_trajectory_measures_convergence_and_rates() -> None:
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
    assert trajectory.phase_sequence == (
        TrajectoryPhase.CONVERGING,
        TrajectoryPhase.CONVERGING,
    )
    assert trajectory.steps[0].delta == (-1, 0, 0)
    assert trajectory.steps[0].movement_rate == pytest.approx(0.5)
    assert trajectory.steps[0].convergence_rate == pytest.approx(0.5)
    assert trajectory.net_convergence_rate == pytest.approx(0.4)
    assert trajectory.orientation_velocity == pytest.approx(0.4)
    assert trajectory.peak_movement_rate == pytest.approx(0.5)
    assert not trajectory.signature.had_regression
    assert not trajectory.signature.had_discontinuity
    assert trajectory.signature.current_missing == EvidenceKind.NONE
    assert trajectory.kinetic_signature.current_phase is TrajectoryPhase.CONVERGING
    assert trajectory.kinetic_signature.current_missing == EvidenceKind.NONE
    assert trajectory.kinetic_signature.code <= 0xFF


def test_regression_and_discontinuity_are_visible_in_path_and_signatures() -> None:
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
    assert trajectory.orientation_path_length == 5
    assert trajectory.regressions == 2
    assert trajectory.discontinuities == 1
    assert not trajectory.is_monotone_convergent
    assert trajectory.phase_sequence == (
        TrajectoryPhase.CONVERGING,
        TrajectoryPhase.REGRESSING,
        TrajectoryPhase.CONVERGING,
    )
    assert trajectory.convergence_rates == pytest.approx((1.0, -2.0, 1.0))
    assert trajectory.convergence_rate_changes == pytest.approx((-3.0, 3.0))
    assert trajectory.net_convergence_rate == pytest.approx(0.25)
    assert trajectory.peak_movement_rate == pytest.approx(2.0)
    assert trajectory.signature.had_regression
    assert trajectory.signature.had_discontinuity
    assert trajectory.signature.ever_deferred
    assert trajectory.signature.current_missing == EvidenceKind.NONE
    assert trajectory.signature.code <= 0xFF

    kinetic = trajectory.kinetic_signature
    assert kinetic.had_regression
    assert kinetic.had_discontinuity
    assert kinetic.current_phase is TrajectoryPhase.CONVERGING
    assert kinetic.current_missing == EvidenceKind.NONE
    assert kinetic.code <= 0xFF


def test_reorientation_and_stall_are_distinct_from_net_zero_motion() -> None:
    trajectory = PhaseTrajectory(
        (
            PhasePoint(0, BardoLine.stable(0), defer(EvidenceKind.AUTHORITY)),
            PhasePoint(1, BardoLine.stable(0), defer(EvidenceKind.OUTCOME)),
            PhasePoint(3, BardoLine.stable(0), defer(EvidenceKind.OUTCOME)),
        )
    )

    first, second = trajectory.steps
    assert first.phase is TrajectoryPhase.REORIENTING
    assert first.delta == (-1, 0, 1)
    assert first.movement == 2
    assert first.convergence_rate == 0.0

    assert second.phase is TrajectoryPhase.STALLED
    assert second.delta == (0, 0, 0)
    assert second.movement == 0
    assert second.convergence_rate == 0.0

    kinetic = trajectory.kinetic_signature
    assert kinetic.current_phase is TrajectoryPhase.STALLED
    assert kinetic.had_regression


def test_kinetic_signature_has_no_phase_until_first_step() -> None:
    point = PhasePoint(0, BardoLine.stable(0), defer(EvidenceKind.OUTCOME))
    signature = KineticSignature.initial(point)
    assert not signature.has_phase
    assert signature.current_phase is None
    assert signature.current_missing is EvidenceKind.OUTCOME


def test_kinetic_signature_encodes_all_four_current_phases() -> None:
    current = PhasePoint(2, BardoLine.stable(0), defer(EvidenceKind.OUTCOME))
    fixtures = (
        (
            PhasePoint(
                0,
                BardoLine.stable(0),
                defer(EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME),
            ),
            TrajectoryPhase.CONVERGING,
        ),
        (
            PhasePoint(0, BardoLine.stable(0), defer(EvidenceKind.OUTCOME)),
            TrajectoryPhase.STALLED,
        ),
        (
            PhasePoint(0, BardoLine.stable(0), OrientedTao(TaoDecision.ALLOW)),
            TrajectoryPhase.REGRESSING,
        ),
        (
            PhasePoint(0, BardoLine.stable(0), defer(EvidenceKind.AUTHORITY)),
            TrajectoryPhase.REORIENTING,
        ),
    )

    for previous, expected_phase in fixtures:
        signature = KineticSignature.initial(previous).advance(current)
        assert signature.has_phase
        assert signature.current_phase is expected_phase
        assert signature.current_missing is EvidenceKind.OUTCOME
        assert signature.had_regression is (
            expected_phase in (TrajectoryPhase.REGRESSING, TrajectoryPhase.REORIENTING)
        )
        assert signature.code <= 0xFF


def test_ticks_must_be_strictly_increasing() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        PhaseTrajectory(
            (
                PhasePoint(1, BardoLine.stable(0), defer(EvidenceKind.OUTCOME)),
                PhasePoint(1, BardoLine.stable(0), OrientedTao(TaoDecision.ALLOW)),
            )
        )
