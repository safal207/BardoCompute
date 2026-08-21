import pytest

from bardocompute.headroom_gate import (
    HeadroomGateEvidence,
    evaluate_headroom_gate,
    wilson_upper,
)


def test_high_recent_hazard_gates_to_safe_minimum() -> None:
    result = evaluate_headroom_gate(
        HeadroomGateEvidence(
            point_hazard=0.001,
            recent_events=8,
            recent_exposure=256,
            regret_given_change=50.0,
            probe_cost=2.0,
            min_interval=8,
            max_interval=256,
        )
    )
    assert result.gated_to_minimum
    assert result.interval == 8
    assert result.point.interval > 8


def test_calm_well_supported_recent_history_preserves_adaptive_headroom() -> None:
    result = evaluate_headroom_gate(
        HeadroomGateEvidence(
            point_hazard=0.0005,
            recent_events=0,
            recent_exposure=16_000,
            regret_given_change=10.0,
            probe_cost=32.0,
            min_interval=8,
            max_interval=256,
        )
    )
    assert not result.gated_to_minimum
    assert result.interval == result.point.interval
    assert result.interval > 8


def test_more_evidence_tightens_zero_event_upper_bound() -> None:
    assert wilson_upper(0, 10_000) < wilson_upper(0, 100)


def test_zero_probe_cost_uses_minimum() -> None:
    result = evaluate_headroom_gate(
        HeadroomGateEvidence(
            point_hazard=0.0,
            recent_events=0,
            recent_exposure=128,
            regret_given_change=10.0,
            probe_cost=0.0,
        )
    )
    assert result.gated_to_minimum
    assert result.interval == 8


@pytest.mark.parametrize(
    "kwargs",
    [
        {"point_hazard": -0.1},
        {"point_hazard": 1.1},
        {"recent_events": -1},
        {"recent_exposure": 0},
        {"recent_events": 5, "recent_exposure": 4},
        {"regret_given_change": -1.0},
        {"probe_cost": -1.0},
        {"min_interval": 0},
        {"min_interval": 32, "max_interval": 16},
        {"z_score": -1.0},
    ],
)
def test_invalid_evidence_is_rejected(kwargs: dict[str, float | int]) -> None:
    base = dict(
        point_hazard=0.01,
        recent_events=1,
        recent_exposure=128,
        regret_given_change=10.0,
        probe_cost=8.0,
        min_interval=8,
        max_interval=256,
        z_score=1.96,
    )
    base.update(kwargs)
    with pytest.raises(ValueError):
        HeadroomGateEvidence(**base)
