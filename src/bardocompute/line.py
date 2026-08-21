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


@dataclass(frozen=True, slots=True)
class BardoLine:
    """A line carrying stable value or directed transition information."""

    state: LineState

    @classmethod
    def stable(cls, value: int) -> "BardoLine":
        if value not in (0, 1):
            raise ValueError("stable value must be 0 or 1")
        return cls(LineState.ONE if value == 1 else LineState.ZERO)

    @classmethod
    def between(cls, source: int, target: int) -> "BardoLine":
        if source not in (0, 1) or target not in (0, 1):
            raise ValueError("source and target must be 0 or 1")
        if source == target:
            return cls.stable(source)
        return cls(LineState.RISING if source == 0 else LineState.FALLING)

    @property
    def source(self) -> int:
        return self.state.source

    @property
    def target(self) -> int:
        return self.state.target

    @property
    def is_transition(self) -> bool:
        return self.state.is_transition

    def settle(self) -> "BardoLine":
        """Resolve a transition to its target stable state."""
        return BardoLine.stable(self.target)
