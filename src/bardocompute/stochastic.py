from __future__ import annotations

from dataclasses import dataclass

from .capability import CapabilityMode, CapabilitySignal


@dataclass(frozen=True, slots=True)
class TaggedCapabilitySignal:
    """Capability signal tagged with the environment epoch that produced it."""

    signal: CapabilitySignal
    epoch: int

    def __post_init__(self) -> None:
        if self.epoch < 0:
            raise ValueError("epoch must be non-negative")


@dataclass(frozen=True, slots=True)
class StochasticCapabilityState:
    """Minimal state for capability flow under delayed/reordered signals.

    The epoch binds observations to the environment shock that produced them.
    `active_shock` says the system has not yet completed adaptation for the
    current epoch. `gap_seen` prevents an out-of-order EVIDENCE_READY event
    from prematurely returning the system to MANIFEST.

    This is an engineering state machine. A conventional epoch-aware FSM with
    the same fields is the equal-information control.
    """

    mode: CapabilityMode = CapabilityMode.MANIFEST
    epoch: int = 0
    active_shock: bool = False
    gap_seen: bool = False


def step_stochastic_capability(
    state: StochasticCapabilityState,
    event: TaggedCapabilitySignal,
) -> StochasticCapabilityState:
    """Advance capability state while rejecting stale or premature evidence.

    Rules:
    - HOLD never changes state.
    - an older epoch is stale and ignored;
    - ENVIRONMENT_CHANGE with a newer epoch starts/restarts adaptation;
    - duplicate ENVIRONMENT_CHANGE for the current epoch is idempotent;
    - GAP_DETECTED is relevant only to the active current epoch;
    - EVIDENCE_READY can close an epoch only after GAP_DETECTED for that epoch.

    These rules deliberately make order/provenance explicit. They are not a
    claim that Bardo/Tao terminology creates behavior unavailable to a normal
    finite-state machine.
    """

    if event.signal is CapabilitySignal.HOLD:
        return state

    if event.epoch < state.epoch:
        return state

    if event.signal is CapabilitySignal.ENVIRONMENT_CHANGE:
        if event.epoch == state.epoch:
            return state
        return StochasticCapabilityState(
            mode=CapabilityMode.ADAPT,
            epoch=event.epoch,
            active_shock=True,
            gap_seen=False,
        )

    if event.epoch > state.epoch:
        # Non-shock observations cannot create a new environment epoch.
        return state

    if not state.active_shock:
        return state

    if event.signal is CapabilitySignal.GAP_DETECTED:
        return StochasticCapabilityState(
            mode=CapabilityMode.ACQUIRE,
            epoch=state.epoch,
            active_shock=True,
            gap_seen=True,
        )

    if event.signal is CapabilitySignal.EVIDENCE_READY:
        if not state.gap_seen:
            return state
        return StochasticCapabilityState(
            mode=CapabilityMode.MANIFEST,
            epoch=state.epoch,
            active_shock=False,
            gap_seen=False,
        )

    raise ValueError(f"unsupported capability signal: {event.signal!r}")
