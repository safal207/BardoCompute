from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LineState(str, Enum):
    """Minimal four-state line model.

    ZERO and ONE are stable states. RISING and FALLING are directed
    transitions. The names are computational labels; they are not claims
    about historical terminology in the Book of Changes.
    """

    ZERO = "0"
    ONE = "1"
    RISING = "0->1"
    FALLING = "1->0"

    @property
    def source(self) -> int:
        return 1 if self in (LineState.ONE, LineState.FALLING) else 0

    @property
    def target(self) -> int:
        return 1 if self in (LineState.ONE, LineState.RISING) else 0

    @property
    def is_transition(self) -> bool:
        return self in (LineState.RISING, LineState.FALLING)


class TransitionMode(str, Enum):
    """How a state transition is related to its predecessor.

    STABLE means no transition is occurring.
    CONTINUOUS means the target is treated as causally continuous with the
    source under the current computation.
    DISCONTINUOUS means an interruption, reset, external event, exception, or
    other boundary breaks that continuity.

    These are engineering semantics introduced by BardoCompute.
    """

    STABLE = "stable"
    CONTINUOUS = "continuous"
    DISCONTINUOUS = "discontinuous"


@dataclass(frozen=True, slots=True)
class BardoLine:
    """A line carrying value, direction, and transition continuity."""

    state: LineState
    mode: TransitionMode = TransitionMode.STABLE

    def __post_init__(self) -> None:
        if self.state.is_transition and self.mode is TransitionMode.STABLE:
            raise ValueError("transition states require a transition mode")
        if not self.state.is_transition and self.mode is not TransitionMode.STABLE:
            raise ValueError("stable states cannot carry a transition mode")

    @classmethod
    def stable(cls, value: int) -> "BardoLine":
        if value not in (0, 1):
            raise ValueError("stable value must be 0 or 1")
        return cls(
            LineState.ONE if value == 1 else LineState.ZERO,
            TransitionMode.STABLE,
        )

    @classmethod
    def between(
        cls,
        source: int,
        target: int,
        mode: TransitionMode = TransitionMode.CONTINUOUS,
    ) -> "BardoLine":
        if source not in (0, 1) or target not in (0, 1):
            raise ValueError("source and target must be 0 or 1")
        if source == target:
            if mode is not TransitionMode.CONTINUOUS:
                raise ValueError("equal endpoints are stable in v0.2")
            return cls.stable(source)
        if mode is TransitionMode.STABLE:
            raise ValueError("changing endpoints require a transition mode")
        return cls(
            LineState.RISING if source == 0 else LineState.FALLING,
            mode,
        )

    @property
    def source(self) -> int:
        return self.state.source

    @property
    def target(self) -> int:
        return self.state.target

    @property
    def is_transition(self) -> bool:
        return self.state.is_transition

    @property
    def preserves_continuity(self) -> bool:
        return self.mode is not TransitionMode.DISCONTINUOUS

    def settle(self) -> "BardoLine":
        """Resolve a transition to its target stable state."""
        return BardoLine.stable(self.target)
