import pytest

from bardocompute.exchange import (
    ExchangeState,
    ExchangeStep,
    MembraneCommand,
    regulate_exchange,
)


def test_gate_can_reject_new_exchange_without_erasing_buffer() -> None:
    state = ExchangeState(buffered=7)
    result = regulate_exchange(
        state,
        ExchangeStep(incoming=10, primary_capacity=10, secondary_capacity=0),
        MembraneCommand(
            admission_limit=0,
            release_limit=5,
            buffer_limit=20,
            secondary_fraction=0.0,
        ),
    )
    assert result.admitted == 0
    assert result.gate_rejected == 10
    assert result.delivered == 5
    assert result.buffered == 2


def test_rate_limit_preserves_unsent_work_in_buffer() -> None:
    state = ExchangeState()
    result = regulate_exchange(
        state,
        ExchangeStep(incoming=20, primary_capacity=100, secondary_capacity=100),
        MembraneCommand(release_limit=6, buffer_limit=50),
    )
    assert result.released == 6
    assert result.delivered == 6
    assert state.buffered == 14
    assert result.overflow_dropped == 0


def test_route_fraction_moves_flow_to_secondary_path() -> None:
    state = ExchangeState()
    result = regulate_exchange(
        state,
        ExchangeStep(incoming=20, primary_capacity=100, secondary_capacity=100),
        MembraneCommand(
            release_limit=20,
            buffer_limit=20,
            secondary_fraction=0.25,
        ),
    )
    assert result.primary_requested == 15
    assert result.secondary_requested == 5
    assert result.delivered == 20


def test_downstream_congestion_returns_work_to_buffer() -> None:
    state = ExchangeState()
    result = regulate_exchange(
        state,
        ExchangeStep(incoming=20, primary_capacity=5, secondary_capacity=0),
        MembraneCommand(release_limit=20, buffer_limit=30),
    )
    assert result.congestion == 15
    assert result.delivered == 5
    assert state.buffered == 15


def test_buffer_overflow_is_explicit_loss() -> None:
    state = ExchangeState(buffered=8)
    result = regulate_exchange(
        state,
        ExchangeStep(incoming=10, primary_capacity=0, secondary_capacity=0),
        MembraneCommand(release_limit=18, buffer_limit=12),
    )
    assert result.delivered == 0
    assert result.buffered == 12
    assert result.overflow_dropped == 6
    assert result.lost == 6


@pytest.mark.parametrize(
    "kwargs",
    [
        {"release_limit": -1, "buffer_limit": 10},
        {"release_limit": 1, "buffer_limit": -1},
        {"release_limit": 1, "buffer_limit": 1, "secondary_fraction": -0.1},
        {"release_limit": 1, "buffer_limit": 1, "secondary_fraction": 1.1},
        {"release_limit": 1, "buffer_limit": 1, "admission_limit": -1},
    ],
)
def test_invalid_commands_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MembraneCommand(**kwargs)
