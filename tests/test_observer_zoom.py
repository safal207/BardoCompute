import pytest

from bardocompute.observer_zoom import (
    ObserverAction,
    ObserverLevel,
    ScaleObservation,
    assess_observer,
)


def test_single_scale_is_position_and_must_zoom_out() -> None:
    result = assess_observer((ScaleObservation(32, 0.9),))
    assert result.level is ObserverLevel.POSITION
    assert result.action is ObserverAction.ZOOM_OUT


def test_two_agreeing_scales_form_knowledge() -> None:
    result = assess_observer(
        (ScaleObservation(32, 0.10), ScaleObservation(128, 0.12))
    )
    assert result.level is ObserverLevel.KNOWLEDGE
    assert result.action is ObserverAction.STAY


def test_three_tightly_agreeing_scales_form_vision() -> None:
    result = assess_observer(
        (
            ScaleObservation(32, 0.72),
            ScaleObservation(128, 0.76),
            ScaleObservation(512, 0.80),
        )
    )
    assert result.level is ObserverLevel.VISION
    assert result.action is ObserverAction.STAY


def test_cross_scale_conflict_becomes_presence_not_reaction() -> None:
    result = assess_observer(
        (
            ScaleObservation(32, 0.92),
            ScaleObservation(128, 0.25),
            ScaleObservation(512, 0.08),
        )
    )
    assert result.level is ObserverLevel.PRESENCE
    assert result.action is ObserverAction.HOLD


def test_two_scale_conflict_escalates_to_wider_view() -> None:
    result = assess_observer(
        (ScaleObservation(32, 0.90), ScaleObservation(128, 0.20))
    )
    assert result.level is ObserverLevel.PRESENCE
    assert result.action is ObserverAction.ZOOM_OUT


def test_open_requires_repeated_strong_cross_scale_conflict() -> None:
    observations = (
        ScaleObservation(32, 0.91),
        ScaleObservation(128, 0.93),
        ScaleObservation(512, 0.95),
    )
    before = assess_observer(observations, conflict_streak=1)
    after = assess_observer(observations, conflict_streak=2)
    assert before.level is ObserverLevel.VISION
    assert before.action is ObserverAction.STAY
    assert after.level is ObserverLevel.OPEN
    assert after.action is ObserverAction.RELEASE_MODEL


def test_open_is_not_a_reset_of_observation_history() -> None:
    result = assess_observer(
        (
            ScaleObservation(32, 0.90),
            ScaleObservation(128, 0.92),
            ScaleObservation(512, 0.94),
        ),
        conflict_streak=3,
    )
    assert result.level is ObserverLevel.OPEN
    assert result.largest_scale == 512
    assert result.change_belief > 0.9


def test_invalid_scale_and_score_fail_closed() -> None:
    with pytest.raises(ValueError):
        ScaleObservation(0, 0.5)
    with pytest.raises(ValueError):
        ScaleObservation(32, 1.1)
    with pytest.raises(ValueError):
        assess_observer(())
