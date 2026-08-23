from __future__ import annotations

from dataclasses import dataclass

from .phase_age import PhaseAgeBucket, PhaseAgeSignature, phase_age_bucket
from .phase_edge import PhaseEdgeSignature
from .tao import EvidenceKind, TaoDecision
from .trajectory import TrajectoryPhase


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
_DECISION_TO_CODE = {
    TaoDecision.ALLOW: 0,
    TaoDecision.DEFER: 1,
    TaoDecision.DENY: 2,
}
_CODE_TO_DECISION = (
    TaoDecision.ALLOW,
    TaoDecision.DEFER,
    TaoDecision.DENY,
)


@dataclass(frozen=True, slots=True)
class TemporalState16:
    """A compact 16-bit temporal hot-state candidate.

    Logical layout:
      bits 0..2   current orientation / missing-evidence mask
      bits 3..4   previous motion phase
      bits 5..6   current motion phase
      bits 7..8   quantized current phase age
      bit 9       regression has occurred
      bit 10      discontinuity has occurred
      bit 11      ordered phase edge is valid
      bits 12..13 current Tao decision (ALLOW/DEFER/DENY; code 3 reserved)
      bits 14..15 reserved

    This is an engineering representation, not a claim of a new physical
    number system. A conventional uint16_t with identical bits is an equal-
    information control and should have identical low-level behavior.
    """

    code: int

    def __post_init__(self) -> None:
        if not 0 <= self.code <= 0xFFFF:
            raise ValueError("temporal state must fit in 16 bits")
        if self.decision_code == 3:
            raise ValueError("decision code 3 is reserved")

    @classmethod
    def encode(
        cls,
        *,
        current_missing: EvidenceKind,
        previous_phase: TrajectoryPhase,
        current_phase: TrajectoryPhase,
        phase_age_ticks: int,
        had_regression: bool = False,
        had_discontinuity: bool = False,
        phase_edge_valid: bool = True,
        decision: TaoDecision = TaoDecision.DEFER,
    ) -> "TemporalState16":
        age = phase_age_bucket(phase_age_ticks)
        code = int(current_missing) & 0x7
        code |= (_PHASE_TO_CODE[previous_phase] & 0x3) << 3
        code |= (_PHASE_TO_CODE[current_phase] & 0x3) << 5
        code |= (int(age) & 0x3) << 7
        code |= int(had_regression) << 9
        code |= int(had_discontinuity) << 10
        code |= int(phase_edge_valid) << 11
        code |= (_DECISION_TO_CODE[decision] & 0x3) << 12
        return cls(code)

    @classmethod
    def from_components(
        cls,
        edge: PhaseEdgeSignature,
        age: PhaseAgeSignature,
        *,
        had_regression: bool = False,
        had_discontinuity: bool = False,
        decision: TaoDecision = TaoDecision.DEFER,
    ) -> "TemporalState16":
        if edge.current_missing != age.current_missing:
            raise ValueError("phase edge and phase age must share current orientation")
        if edge.current_phase is not age.current_phase:
            raise ValueError("phase edge and phase age must share current phase")

        code = int(edge.current_missing) & 0x7
        code |= (_PHASE_TO_CODE[edge.previous_phase] & 0x3) << 3
        code |= (_PHASE_TO_CODE[edge.current_phase] & 0x3) << 5
        code |= (int(age.age_bucket) & 0x3) << 7
        code |= int(had_regression) << 9
        code |= int(had_discontinuity) << 10
        code |= int(edge.is_valid) << 11
        code |= (_DECISION_TO_CODE[decision] & 0x3) << 12
        return cls(code)

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
    def age_bucket(self) -> PhaseAgeBucket:
        return PhaseAgeBucket((self.code >> 7) & 0x3)

    @property
    def had_regression(self) -> bool:
        return bool(self.code & (1 << 9))

    @property
    def had_discontinuity(self) -> bool:
        return bool(self.code & (1 << 10))

    @property
    def phase_edge_valid(self) -> bool:
        return bool(self.code & (1 << 11))

    @property
    def decision_code(self) -> int:
        return (self.code >> 12) & 0x3

    @property
    def decision(self) -> TaoDecision:
        return _CODE_TO_DECISION[self.decision_code]

    @property
    def reserved_bits(self) -> int:
        return (self.code >> 14) & 0x3

    @property
    def should_temporal_alert(self) -> bool:
        """Reference multi-condition policy used by v0.1 benchmarks.

        Alert on current regression, recent recovery from regression, stale
        stall, any discontinuity history, or terminal DENY.
        """

        current_regression = self.current_phase is TrajectoryPhase.REGRESSING
        recent_regression = (
            self.phase_edge_valid
            and self.previous_phase is TrajectoryPhase.REGRESSING
            and self.current_phase is TrajectoryPhase.CONVERGING
        )
        stale_stall = (
            self.current_phase is TrajectoryPhase.STALLED
            and self.age_bucket >= PhaseAgeBucket.STALE
        )
        return (
            current_regression
            or recent_regression
            or stale_stall
            or self.had_discontinuity
            or self.decision is TaoDecision.DENY
        )
