from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .tao import EvidenceKind
from .trajectory import TrajectoryPhase


class PhaseAgeBucket(IntEnum):
    """Quantized dwell-time bucket for the current motion phase.

    v0.1 uses event-time ticks rather than wall-clock time:
    FRESH: age 0..3
    WARM: age 4..15
    STALE: age 16..63
    EXPIRED: age >=64

    Thresholds are benchmark parameters, not universal constants.
    """

    FRESH = 0
    WARM = 1
    STALE = 2
    EXPIRED = 3


def phase_age_bucket(age_ticks: int) -> PhaseAgeBucket:
    if age_ticks < 0:
        raise ValueError("phase age must be non-negative")
    if age_ticks <= 3:
        return PhaseAgeBucket.FRESH
    if age_ticks <= 15:
        return PhaseAgeBucket.WARM
    if age_ticks <= 63:
        return PhaseAgeBucket.STALE
    return PhaseAgeBucket.EXPIRED


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
class PhaseAgeSignature:
    """One-byte current phase + quantized dwell-time state.

    Layout:
    bits 0..2: current orientation mask
    bits 3..4: current phase
    bits 5..6: phase-age bucket
    bit 7: valid phase/age observation

    This signature is orthogonal to PhaseEdgeSignature: one retains ordered
    phase history, the other spends the byte budget on how long the current
    phase has persisted.
    """

    code: int

    def __post_init__(self) -> None:
        if not 0 <= self.code <= 0xFF:
            raise ValueError("phase age signature must fit in one byte")
        if not self.is_valid:
            raise ValueError("phase age signature requires a valid phase observation")

    @classmethod
    def encode(
        cls,
        current_missing: EvidenceKind,
        phase: TrajectoryPhase,
        age_ticks: int,
    ) -> "PhaseAgeSignature":
        bucket = phase_age_bucket(age_ticks)
        code = int(current_missing) & 0x7
        code |= (_PHASE_TO_CODE[phase] & 0x3) << 3
        code |= (int(bucket) & 0x3) << 5
        code |= 1 << 7
        return cls(code)

    @property
    def is_valid(self) -> bool:
        return bool(self.code & 0x80)

    @property
    def current_missing(self) -> EvidenceKind:
        return EvidenceKind(self.code & 0x7)

    @property
    def current_phase(self) -> TrajectoryPhase:
        return _CODE_TO_PHASE[(self.code >> 3) & 0x3]

    @property
    def age_bucket(self) -> PhaseAgeBucket:
        return PhaseAgeBucket((self.code >> 5) & 0x3)

    @property
    def is_stale_or_expired(self) -> bool:
        return self.age_bucket >= PhaseAgeBucket.STALE
