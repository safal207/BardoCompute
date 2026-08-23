from bardocompute.capability import CapabilityMode, CapabilitySignal
from bardocompute.stochastic import (
    StochasticCapabilityState,
    TaggedCapabilitySignal,
    step_stochastic_capability,
)


def ev(signal: CapabilitySignal, epoch: int) -> TaggedCapabilitySignal:
    return TaggedCapabilitySignal(signal, epoch)


def test_nominal_stochastic_recovery_path() -> None:
    state = StochasticCapabilityState()
    state = step_stochastic_capability(state, ev(CapabilitySignal.ENVIRONMENT_CHANGE, 1))
    assert state.mode is CapabilityMode.ADAPT
    state = step_stochastic_capability(state, ev(CapabilitySignal.GAP_DETECTED, 1))
    assert state.mode is CapabilityMode.ACQUIRE
    state = step_stochastic_capability(state, ev(CapabilitySignal.EVIDENCE_READY, 1))
    assert state.mode is CapabilityMode.MANIFEST
    assert not state.active_shock


def test_out_of_order_evidence_does_not_manifest() -> None:
    state = StochasticCapabilityState()
    state = step_stochastic_capability(state, ev(CapabilitySignal.ENVIRONMENT_CHANGE, 1))
    state = step_stochastic_capability(state, ev(CapabilitySignal.EVIDENCE_READY, 1))
    assert state.mode is CapabilityMode.ADAPT
    assert state.active_shock


def test_stale_evidence_from_previous_epoch_is_ignored() -> None:
    state = StochasticCapabilityState()
    state = step_stochastic_capability(state, ev(CapabilitySignal.ENVIRONMENT_CHANGE, 1))
    state = step_stochastic_capability(state, ev(CapabilitySignal.GAP_DETECTED, 1))
    state = step_stochastic_capability(state, ev(CapabilitySignal.ENVIRONMENT_CHANGE, 2))
    state = step_stochastic_capability(state, ev(CapabilitySignal.EVIDENCE_READY, 1))
    assert state.epoch == 2
    assert state.mode is CapabilityMode.ADAPT
    assert state.active_shock


def test_second_shock_resets_acquisition_progress() -> None:
    state = StochasticCapabilityState()
    state = step_stochastic_capability(state, ev(CapabilitySignal.ENVIRONMENT_CHANGE, 1))
    state = step_stochastic_capability(state, ev(CapabilitySignal.GAP_DETECTED, 1))
    assert state.mode is CapabilityMode.ACQUIRE
    state = step_stochastic_capability(state, ev(CapabilitySignal.ENVIRONMENT_CHANGE, 2))
    assert state.mode is CapabilityMode.ADAPT
    assert state.epoch == 2
    assert not state.gap_seen


def test_duplicate_current_epoch_shock_is_idempotent() -> None:
    state = StochasticCapabilityState()
    state = step_stochastic_capability(state, ev(CapabilitySignal.ENVIRONMENT_CHANGE, 1))
    duplicate = step_stochastic_capability(state, ev(CapabilitySignal.ENVIRONMENT_CHANGE, 1))
    assert duplicate == state


def test_future_non_shock_event_cannot_create_epoch() -> None:
    state = StochasticCapabilityState()
    future_gap = step_stochastic_capability(state, ev(CapabilitySignal.GAP_DETECTED, 9))
    assert future_gap == state
