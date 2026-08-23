from __future__ import annotations

from dataclasses import dataclass

from .line import BardoLine


@dataclass(frozen=True, slots=True)
class BardoTrigram:
    """Three ordered Bardo lines, bottom to top."""

    lower: BardoLine
    middle: BardoLine
    upper: BardoLine

    def __iter__(self):
        yield self.lower
        yield self.middle
        yield self.upper

    @property
    def source_bits(self) -> tuple[int, int, int]:
        return tuple(line.source for line in self)  # type: ignore[return-value]

    @property
    def target_bits(self) -> tuple[int, int, int]:
        return tuple(line.target for line in self)  # type: ignore[return-value]

    @property
    def transition_count(self) -> int:
        return sum(line.is_transition for line in self)

    def settle(self) -> "BardoTrigram":
        return BardoTrigram(*(line.settle() for line in self))
