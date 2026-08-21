from __future__ import annotations

from dataclasses import dataclass

from .line import BardoLine, TransitionMode
from .tao import EvidenceKind, OrientedTao, TaoDecision


_EVIDENCE_AXES = (
    EvidenceKind.AUTHORITY,
    EvidenceKind.CONTINUITY,
    EvidenceKind.OUTCOME,
)


def orientation_vector(mask: EvidenceKind) -> tuple[int, int, int]:
    """Map the missing-evidence mask to a 3D orientation coordinate."""

    return tuple(int(bool(mask & axis)) for axis in _EVIDENCE_AXES)  # type: ignore[return-value]


def orientation_distance(left: EvidenceKind, right: EvidenceKind) -> int:
    """Hamming distance between two orientation coordinates."""

    return (int(left) ^ int(right)).bit_count()


@dataclass(frozen=True, slots=True)
class PhasePoint:
    """One observed transition/orientation state at a monotonic time tick."""

    tick: int
    line: BardoLine
    orientation: OrientedTao

    def __post_init__(self) -> None:
        if self.tick < 0:
            raise ValueError("tick must be non-negative")

    @property
    def center(self) -> tuple[int, int, int]:
        return orientation_vector(self.orientation.missing)


@dataclass(frozen=True, slots=True)
class TemporalSignature:
    """Compact online summary of trajectory properties relevant to policy.

    Logical layout in one byte:
    bits 0..2: current missing-evidence mask
    bit 3: a regression has occurred
    bit 4: a discontinuity has occurred
    bit 5: a deferred state has occurred
    bits 6..7: reserved
    """

    code: int

    def __post_init__(self) -> None:
        if not 0 <= self.code <= 0xFF:
            raise ValueError("temporal signature must fit in one byte")

    @classmethod
    def initial(cls, point: PhasePoint) -> "TemporalSignature":
        code = int(point.orientation.missing) & 0x7
        if point.line.mode is TransitionMode.DISCONTINUOUS:
            code |= 1 << 4
        if point.orientation.decision is TaoDecision.DEFER:
            code |= 1 << 5
        return cls(code)

    @property
    def current_missing(self) -> EvidenceKind:
        return EvidenceKind(self.code & 0x7)

    @property
    def had_regression(self) -> bool:
        return bool(self.code & (1 << 3))

    @property
    def had_discontinuity(self) -> bool:
        return bool(self.code & (1 << 4))

    @property
    def ever_deferred(self) -> bool:
        return bool(self.code & (1 << 5))

    def advance(self, point: PhasePoint) -> "TemporalSignature":
        previous_missing = int(self.current_missing)
        next_missing = int(point.orientation.missing) & 0x7
        code = (self.code & ~0x7) | next_missing

        added = (~previous_missing & next_missing) & 0x7
        if added:
            code |= 1 << 3
        if point.line.mode is TransitionMode.DISCONTINUOUS:
            code |= 1 << 4
        if point.orientation.decision is TaoDecision.DEFER:
            code |= 1 << 5
        return TemporalSignature(code)


@dataclass(frozen=True, slots=True)
class PhaseTrajectory:
    """A time-ordered path through transition and orientation states."""

    points: tuple[PhasePoint, ...]

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("trajectory requires at least one point")
        for previous, current in zip(self.points, self.points[1:]):
            if current.tick <= previous.tick:
                raise ValueError("trajectory ticks must be strictly increasing")

    @property
    def duration(self) -> int:
        return self.points[-1].tick - self.points[0].tick

    @property
    def orientation_path_length(self) -> int:
        return sum(
            orientation_distance(previous.orientation.missing, current.orientation.missing)
            for previous, current in zip(self.points, self.points[1:])
        )

    @property
    def resolved_dimensions(self) -> int:
        total = 0
        for previous, current in zip(self.points, self.points[1:]):
            cleared = int(previous.orientation.missing) & ~int(current.orientation.missing)
            total += (cleared & 0x7).bit_count()
        return total

    @property
    def regressions(self) -> int:
        total = 0
        for previous, current in zip(self.points, self.points[1:]):
            added = ~int(previous.orientation.missing) & int(current.orientation.missing)
            total += (added & 0x7).bit_count()
        return total

    @property
    def discontinuities(self) -> int:
        return sum(
            point.line.mode is TransitionMode.DISCONTINUOUS for point in self.points
        )

    @property
    def terminal_tick(self) -> int | None:
        for point in self.points:
            if point.orientation.decision is not TaoDecision.DEFER:
                return point.tick
        return None

    @property
    def convergence_time(self) -> int | None:
        terminal = self.terminal_tick
        if terminal is None:
            return None
        return terminal - self.points[0].tick

    @property
    def orientation_velocity(self) -> float:
        if self.duration == 0:
            return 0.0
        return self.orientation_path_length / self.duration

    @property
    def is_monotone_convergent(self) -> bool:
        return self.regressions == 0

    @property
    def signature(self) -> TemporalSignature:
        signature = TemporalSignature.initial(self.points[0])
        for point in self.points[1:]:
            signature = signature.advance(point)
        return signature
