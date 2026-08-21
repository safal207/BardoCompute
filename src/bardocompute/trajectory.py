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
    """Map the missing-evidence mask to a 3D orientation coordinate.

    A coordinate is 1 while that evidence dimension is still required and 0
    once it is settled. The result is a computational coordinate, not a claim
    about a physical or philosophical geometry.
    """

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
        """Current center of orientation in evidence-coordinate space."""

        return orientation_vector(self.orientation.missing)


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
        """Total movement of the orientation center through evidence space."""

        return sum(
            orientation_distance(previous.orientation.missing, current.orientation.missing)
            for previous, current in zip(self.points, self.points[1:])
        )

    @property
    def resolved_dimensions(self) -> int:
        """Count evidence dimensions that move from missing to settled."""

        total = 0
        for previous, current in zip(self.points, self.points[1:]):
            cleared = int(previous.orientation.missing) & ~int(current.orientation.missing)
            total += (cleared & 0x7).bit_count()
        return total

    @property
    def regressions(self) -> int:
        """Count dimensions that become missing again after being settled."""

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
        """Orientation-space movement per time tick."""

        if self.duration == 0:
            return 0.0
        return self.orientation_path_length / self.duration

    @property
    def is_monotone_convergent(self) -> bool:
        """True when no settled evidence dimension becomes missing again."""

        return self.regressions == 0
