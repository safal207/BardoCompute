from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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


class TrajectoryPhase(str, Enum):
    """Discrete motion class for one orientation step.

    CONVERGING clears at least one missing evidence dimension and adds none.
    REGRESSING adds at least one missing dimension and clears none.
    REORIENTING clears and adds dimensions in the same step.
    STALLED changes no orientation dimension.

    These are engineering labels for the BardoCompute trajectory model.
    """

    CONVERGING = "converging"
    STALLED = "stalled"
    REGRESSING = "regressing"
    REORIENTING = "reorienting"


_PHASE_TO_CODE = {
    TrajectoryPhase.STALLED: 0,
    TrajectoryPhase.CONVERGING: 1,
    TrajectoryPhase.REGRESSING: 2,
    TrajectoryPhase.REORIENTING: 3,
}
_CODE_TO_PHASE = (
    TrajectoryPhase.STALLED,
    TrajectoryPhase.CONVERGING,
    TrajectoryPhase.REGRESSING,
    TrajectoryPhase.REORIENTING,
)


def classify_orientation_phase(
    previous: EvidenceKind,
    current: EvidenceKind,
) -> TrajectoryPhase:
    """Classify one orientation step from two consecutive masks."""

    previous_code = int(previous) & 0x7
    current_code = int(current) & 0x7
    cleared = ((previous_code & ~current_code) & 0x7).bit_count()
    added = ((~previous_code & current_code) & 0x7).bit_count()
    if cleared and added:
        return TrajectoryPhase.REORIENTING
    if cleared:
        return TrajectoryPhase.CONVERGING
    if added:
        return TrajectoryPhase.REGRESSING
    return TrajectoryPhase.STALLED


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
class PhaseStep:
    """One time-bounded movement of the center of orientation."""

    previous: PhasePoint
    current: PhasePoint

    def __post_init__(self) -> None:
        if self.current.tick <= self.previous.tick:
            raise ValueError("phase step requires increasing ticks")

    @property
    def dt(self) -> int:
        return self.current.tick - self.previous.tick

    @property
    def delta(self) -> tuple[int, int, int]:
        """Signed coordinate movement; -1 resolves, +1 becomes missing."""

        return tuple(
            current - previous
            for previous, current in zip(self.previous.center, self.current.center)
        )  # type: ignore[return-value]

    @property
    def cleared_dimensions(self) -> int:
        previous = int(self.previous.orientation.missing)
        current = int(self.current.orientation.missing)
        return ((previous & ~current) & 0x7).bit_count()

    @property
    def added_dimensions(self) -> int:
        previous = int(self.previous.orientation.missing)
        current = int(self.current.orientation.missing)
        return ((~previous & current) & 0x7).bit_count()

    @property
    def movement(self) -> int:
        return orientation_distance(
            self.previous.orientation.missing,
            self.current.orientation.missing,
        )

    @property
    def movement_rate(self) -> float:
        """Orientation-space distance travelled per tick."""

        return self.movement / self.dt

    @property
    def convergence_rate(self) -> float:
        """Signed evidence convergence per tick.

        Positive means the center moves toward fewer missing dimensions.
        Negative means evidence requirements regressed. Zero can mean either
        a stall or a reorientation with equal dimensions cleared and added.
        """

        return (self.cleared_dimensions - self.added_dimensions) / self.dt

    @property
    def phase(self) -> TrajectoryPhase:
        return classify_orientation_phase(
            self.previous.orientation.missing,
            self.current.orientation.missing,
        )

    @property
    def is_discontinuous(self) -> bool:
        return self.current.line.mode is TransitionMode.DISCONTINUOUS


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
class KineticSignature:
    """One-byte hot state retaining current orientation and current motion.

    Logical layout:
    bits 0..2: current missing-evidence mask
    bit 3: a regression has occurred at any prior/current step
    bit 4: a discontinuity has occurred at any prior/current point
    bits 5..6: current four-way TrajectoryPhase code
    bit 7: phase is valid (at least one step has been observed)

    Unlike TemporalSignature, this specialized layout does not retain the
    separate `ever_deferred` flag. It spends that budget on current kinetics.
    """

    code: int

    def __post_init__(self) -> None:
        if not 0 <= self.code <= 0xFF:
            raise ValueError("kinetic signature must fit in one byte")

    @classmethod
    def initial(cls, point: PhasePoint) -> "KineticSignature":
        code = int(point.orientation.missing) & 0x7
        if point.line.mode is TransitionMode.DISCONTINUOUS:
            code |= 1 << 4
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
    def has_phase(self) -> bool:
        return bool(self.code & (1 << 7))

    @property
    def current_phase(self) -> TrajectoryPhase | None:
        if not self.has_phase:
            return None
        return _CODE_TO_PHASE[(self.code >> 5) & 0x3]

    def advance(self, point: PhasePoint) -> "KineticSignature":
        previous_missing = self.current_missing
        next_missing = EvidenceKind(int(point.orientation.missing) & 0x7)
        phase = classify_orientation_phase(previous_missing, next_missing)

        # Preserve history flags, replace current orientation + current phase.
        code = self.code & ((1 << 3) | (1 << 4))
        code |= int(next_missing) & 0x7
        code |= _PHASE_TO_CODE[phase] << 5
        code |= 1 << 7

        if phase in (TrajectoryPhase.REGRESSING, TrajectoryPhase.REORIENTING):
            # A reorientation also reintroduces at least one missing dimension.
            code |= 1 << 3
        if point.line.mode is TransitionMode.DISCONTINUOUS:
            code |= 1 << 4
        return KineticSignature(code)


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
    def steps(self) -> tuple[PhaseStep, ...]:
        return tuple(
            PhaseStep(previous, current)
            for previous, current in zip(self.points, self.points[1:])
        )

    @property
    def phase_sequence(self) -> tuple[TrajectoryPhase, ...]:
        return tuple(step.phase for step in self.steps)

    @property
    def duration(self) -> int:
        return self.points[-1].tick - self.points[0].tick

    @property
    def orientation_path_length(self) -> int:
        return sum(step.movement for step in self.steps)

    @property
    def resolved_dimensions(self) -> int:
        return sum(step.cleared_dimensions for step in self.steps)

    @property
    def regressions(self) -> int:
        return sum(step.added_dimensions for step in self.steps)

    @property
    def discontinuities(self) -> int:
        return sum(point.line.mode is TransitionMode.DISCONTINUOUS for point in self.points)

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
        """Total orientation-space movement per time tick."""

        if self.duration == 0:
            return 0.0
        return self.orientation_path_length / self.duration

    @property
    def net_convergence_rate(self) -> float:
        """Net reduction in missing dimensions per time tick."""

        if self.duration == 0:
            return 0.0
        start = int(self.points[0].orientation.missing).bit_count()
        end = int(self.points[-1].orientation.missing).bit_count()
        return (start - end) / self.duration

    @property
    def convergence_rates(self) -> tuple[float, ...]:
        return tuple(step.convergence_rate for step in self.steps)

    @property
    def convergence_rate_changes(self) -> tuple[float, ...]:
        """Discrete changes in convergence rate between adjacent steps."""

        rates = self.convergence_rates
        return tuple(current - previous for previous, current in zip(rates, rates[1:]))

    @property
    def peak_movement_rate(self) -> float:
        return max((step.movement_rate for step in self.steps), default=0.0)

    @property
    def is_monotone_convergent(self) -> bool:
        return self.regressions == 0

    @property
    def signature(self) -> TemporalSignature:
        signature = TemporalSignature.initial(self.points[0])
        for point in self.points[1:]:
            signature = signature.advance(point)
        return signature

    @property
    def kinetic_signature(self) -> KineticSignature:
        signature = KineticSignature.initial(self.points[0])
        for point in self.points[1:]:
            signature = signature.advance(point)
        return signature
