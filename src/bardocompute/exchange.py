from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MembraneCommand:
    """One step of exchange regulation.

    `admission_limit=None` means the gate is fully open.  Otherwise no more
    than that many new units may enter this step.  `release_limit` controls
    how much buffered + newly admitted work may be offered downstream.
    `secondary_fraction` controls routing between two exchange paths.
    """

    release_limit: int
    buffer_limit: int
    secondary_fraction: float = 0.0
    admission_limit: int | None = None

    def __post_init__(self) -> None:
        if self.release_limit < 0:
            raise ValueError("release_limit must be >= 0")
        if self.buffer_limit < 0:
            raise ValueError("buffer_limit must be >= 0")
        if not 0.0 <= self.secondary_fraction <= 1.0:
            raise ValueError("secondary_fraction must be in [0, 1]")
        if self.admission_limit is not None and self.admission_limit < 0:
            raise ValueError("admission_limit must be >= 0 or None")


@dataclass(frozen=True, slots=True)
class ExchangeStep:
    incoming: int
    primary_capacity: int
    secondary_capacity: int

    def __post_init__(self) -> None:
        if self.incoming < 0:
            raise ValueError("incoming must be >= 0")
        if self.primary_capacity < 0 or self.secondary_capacity < 0:
            raise ValueError("capacities must be >= 0")


@dataclass(frozen=True, slots=True)
class ExchangeResult:
    admitted: int
    gate_rejected: int
    released: int
    primary_requested: int
    secondary_requested: int
    primary_delivered: int
    secondary_delivered: int
    delivered: int
    congestion: int
    buffered: int
    overflow_dropped: int

    @property
    def lost(self) -> int:
        return self.gate_rejected + self.overflow_dropped


@dataclass(slots=True)
class ExchangeState:
    buffered: int = 0

    def __post_init__(self) -> None:
        if self.buffered < 0:
            raise ValueError("buffered must be >= 0")


def regulate_exchange(
    state: ExchangeState,
    step: ExchangeStep,
    command: MembraneCommand,
) -> ExchangeResult:
    """Apply one gate/rate/buffer/route decision.

    Failed downstream delivery is retained in the buffer when capacity exists;
    it is not silently counted as completed work.  The function contains no
    policy and no future information: it is only the exchange mechanism.
    """

    admission_limit = step.incoming
    if command.admission_limit is not None:
        admission_limit = min(admission_limit, command.admission_limit)

    admitted = admission_limit
    gate_rejected = step.incoming - admitted
    available = state.buffered + admitted
    released = min(available, command.release_limit)

    secondary_requested = int(round(released * command.secondary_fraction))
    secondary_requested = min(released, max(0, secondary_requested))
    primary_requested = released - secondary_requested

    primary_delivered = min(primary_requested, step.primary_capacity)
    secondary_delivered = min(secondary_requested, step.secondary_capacity)
    delivered = primary_delivered + secondary_delivered
    congestion = (
        primary_requested - primary_delivered
        + secondary_requested - secondary_delivered
    )

    remaining = available - delivered
    buffered = min(remaining, command.buffer_limit)
    overflow_dropped = remaining - buffered
    state.buffered = buffered

    return ExchangeResult(
        admitted=admitted,
        gate_rejected=gate_rejected,
        released=released,
        primary_requested=primary_requested,
        secondary_requested=secondary_requested,
        primary_delivered=primary_delivered,
        secondary_delivered=secondary_delivered,
        delivered=delivered,
        congestion=congestion,
        buffered=buffered,
        overflow_dropped=overflow_dropped,
    )
