import random

import pytest

from bardocompute.policy_orientation import PolicyOrientation


def test_probabilities_are_normalized_and_exploratory() -> None:
    selector = PolicyOrientation(policy_count=4, exploration=0.2)
    probabilities = selector.probabilities()
    assert sum(probabilities) == pytest.approx(1.0)
    assert all(probability >= 0.05 for probability in probabilities)


def test_observed_loss_reduces_selected_policy_weight() -> None:
    selector = PolicyOrientation(policy_count=3, exploration=0.1, learning_rate=0.1, share=0.0)
    before = selector.weights[1]
    selector.observe(1, normalized_loss=0.8, selection_probability=0.4)
    assert selector.weights[1] < before
    assert selector.weights[0] == pytest.approx(1.0)
    assert selector.weights[2] == pytest.approx(1.0)


def test_fixed_share_keeps_nonselected_policies_alive() -> None:
    selector = PolicyOrientation(policy_count=3, exploration=0.1, learning_rate=1.0, share=0.1)
    for _ in range(30):
        selector.observe(0, normalized_loss=1.0, selection_probability=0.5)
    assert all(weight > 0.0 for weight in selector.weights)
    assert selector.probabilities()[0] >= selector.exploration / 3


def test_choose_returns_its_actual_probability() -> None:
    selector = PolicyOrientation(policy_count=3)
    rng = random.Random(7)
    policy, probability = selector.choose(rng)
    assert 0 <= policy < 3
    assert probability == pytest.approx(selector.probabilities()[policy])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"policy_count": 1},
        {"policy_count": 3, "exploration": 0.0},
        {"policy_count": 3, "exploration": 1.1},
        {"policy_count": 3, "learning_rate": 0.0},
        {"policy_count": 3, "share": -0.1},
        {"policy_count": 3, "share": 1.0},
    ],
)
def test_invalid_selector_configuration_is_rejected(kwargs: dict[str, float | int]) -> None:
    with pytest.raises(ValueError):
        PolicyOrientation(**kwargs)


def test_invalid_feedback_is_rejected() -> None:
    selector = PolicyOrientation(policy_count=3)
    with pytest.raises(ValueError):
        selector.observe(3, 0.5, 0.5)
    with pytest.raises(ValueError):
        selector.observe(0, -0.1, 0.5)
    with pytest.raises(ValueError):
        selector.observe(0, 1.1, 0.5)
    with pytest.raises(ValueError):
        selector.observe(0, 0.5, 0.0)
