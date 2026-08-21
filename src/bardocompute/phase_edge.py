from __future__ import annotations

from dataclasses import dataclass

from .tao import EvidenceKind
from .trajectory import PhasePoint, PhaseStep, TrajectoryPhase, classify_orientation_phase


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


@dataclass(frozen=True, slots=True)
class PhaseEdgeSignature:
    """One-byte ordered transition between two consecutive motion phases.

    Layout:
    bits 0..2: current orientation mask
    bits 3..4: previous phase
    bits 5..6: current phase
    bit 7: valid phase edge

    A phase edge needs two observed phase steps (three points) to bootstrap.
    After that, the byte can be advanced online from each new orientation.

    This representation keeps phase order but does not keep `dt`; dwell-time
    and physical-time semantics require a separate temporal quantity.
    """

    code: int

    def __post_init__(self) -> None:
        if not 0 <= self.code <= 0xFF:
            raise ValueError("phase edge signature must fit in one byte")
        if not self.is_valid:
            raise ValueError("phase edge signature requires two observed steps")

    @classmethod
    def from_points(
        cls,
        first: PhasePoint,
        middle: PhasePoint,
        current: PhasePoint,
    ) -> "PhaseEdgeSignature":
        previous_step = PhaseStep(first, middle)
        current_step = PhaseStep(middle, current)
        return cls._encode(
            current.orientation.missing,
            previous_step.phase,
            current_step.phase,
        )

    @classmethod
    def _encode(
        cls,
        current_missing: EvidenceKind,
        previous_phase: TrajectoryPhase,
        current_phase: TrajectoryPhase,
    ) -> "PhaseEdgeSignature":
        code = int(current_missing) & 0x7
        code |= (_PHASE_TO_CODE[previous_phase] & 0x3) << 3
        code |= (_PHASE_TO_CODE[current_phase] & 0x3) << 5
        code |= 1 << 7
        return cls(code)

    @property
    def is_valid(self) -> bool:
        return bool(self.code & 0x80)

    @property
    def current_missing(self) -> EvidenceKind:
        return EvidenceKind(self.code & 0x7)

    @property
    def previous_phase(self) -> TrajectoryPhase:
        return _CODE_TO_PHASE[(self.code >> 3) & 0x3]

    @property
    def current_phase(self) -> TrajectoryPhase:
        return _CODE_TO_PHASE[(self.code >> 5) & 0x3]

    @property
    def edge_code(self) -> int:
        """Dense 0..15 code for previous_phase -> current_phase."""

        return (_PHASE_TO_CODE[self.previous_phase] << 2) | _PHASE_TO_CODE[
            self.current_phase
        ]

    def advance(self, next_missing: EvidenceKind) -> "PhaseEdgeSignature":
        """Advance one ordered phase step using the next orientation mask."""

        next_phase = classify_orientation_phase(self.current_missing, next_missing)
        return self._encode(next_missing, self.current_phase, next_phase)
