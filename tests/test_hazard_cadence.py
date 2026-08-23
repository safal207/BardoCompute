import pytest

from bardocompute.hazard_cadence import (
    HazardCadenceEvidence,
    evaluate_hazard_cadence,
)


def test_higher_change_hazard_shortens_interval() -> None:
    calm = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=0.001,
            regret_given_change=10.0,
            probe_cost=8.0,
            min_interval=1,
        )
    )
    volatile = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=0.02,
            regret_given_change=10.0,
            probe_cost=8.0,
            min_interval=1,
        )
    )
    assert volatile.interval < calm.interval


def test_higher_probe_cost_lengthens_interval() -> None:
    cheap = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=0.005,
            regret_given_change=10.0,
            probe_cost=2.0,
            min_interval=1,
        )
    )
    expensive = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=0.005,
            regret_given_change=10.0,
            probe_cost=32.0,
            min_interval=1,
        )
    )
    assert expensive.interval > cheap.interval


def test_higher_stale_regret_shortens_interval() -> None:
    low = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=0.005,
            regret_given_change=2.0,
            probe_cost=8.0,
            min_interval=1,
        )
    )
    high = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=0.005,
            regret_given_change=50.0,
            probe_cost=8.0,
            min_interval=1,
        )
    )
    assert high.interval < low.interval


def test_zero_probe_cost_selects_minimum() -> None:
    result = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=0.01,
            regret_given_change=10.0,
            probe_cost=0.0,
            min_interval=8,
        )
    )
    assert result.interval == 8


def test_interval_is_clipped() -> None:
    minimum = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=1.0,
            regret_given_change=1000.0,
            probe_cost=0.01,
            min_interval=12,
            max_interval=200,
        )
    )
    maximum = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=0.0,
            regret_given_change=1.0,
            probe_cost=1000.0,
            min_interval=12,
            max_interval=200,
        )
    )
    assert minimum.interval == 12
    assert maximum.interval == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("change_hazard", -0.1),
        ("change_hazard", 1.1),
        ("regret_given_change", -1.0),
        ("probe_cost", -1.0),
        ("hazard_floor", -1.0),
    ],
)
def test_invalid_values_are_rejected(field: str, value: float) -> None:
    kwargs = dict(
        change_hazard=0.01,
        regret_given_change=10.0,
        probe_cost=8.0,
    )
    kwargs[field] = value
    with pytest.raises(ValueError):
        HazardCadenceEvidence(**kwargs)
