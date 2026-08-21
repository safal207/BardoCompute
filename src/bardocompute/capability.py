from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum, IntFlag

from .phase_age import PhaseAgeBucket
from .tao import EvidenceKind
from .temporal_state import TemporalState16
from .trajectory import TrajectoryPhase


class Carrier(str, Enum):
    """Symbolic carrier label for the engineering experiment.

    Yin, Yang, and Tao are project-level labels here. The model deliberately
    does not assign a unique capability to any one carrier: each carrier can
    manifest, acquire, and adapt.
    """

    YIN = "yin"
    YANG = "yang"
    TAO = "tao"


class CapabilityMode(IntEnum):
    """Current way a carrier is using its capability potential."""

    MANIFEST = 0
    ACQUIRE = 1
    ADAPT = 2


class Capability(IntFlag):
    NONE = 0
    MANIFEST = 1
    ACQUIRE = 2
    ADAPT = 4
    ALL = MANIFEST | ACQUIRE | ADAPT


def capability_bit(mode: CapabilityMode) -> Capability:
    return Capability(1 << int(mode))


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """A carrier with innate capability potential and one active mode.

    v0.1 intentionally gives Yin, Yang, and Tao the same default potential.
    Any future carrier-specific asymmetry must be introduced as a separate,
    measurable hypothesis rather than assumed from symbolism.
    """

    carrier: Carrier
    innate: Capability = Capability.ALL
    active: CapabilityMode = CapabilityMode.MANIFEST

    def __post_init__(self) -> None:
        if not self.innate & capability_bit(self.active):
            raise ValueError("active capability mode must be present in innate potential")

    def supports(self, mode: CapabilityMode) -> bool:
        return bool(self.innate & capability_bit(mode))

    def with_mode(self, mode: CapabilityMode) -> "CapabilityProfile":
        if not self.supports(mode):
            raise ValueError("carrier does not support requested capability mode")
        return CapabilityProfile(self.carrier, self.innate, mode)


def choose_capability_mode(
    *,
    current_phase: TrajectoryPhase,
    current_missing: EvidenceKind,
    age_bucket: PhaseAgeBucket,
    had_discontinuity: bool = False,
) -> CapabilityMode:
    """Reference flow law for Manifest / Acquire / Adapt.

    ADAPT has priority when the trajectory is broken, regressing, or being
    reoriented. ACQUIRE is selected when required evidence/knowledge is still
    missing or a stalled phase has become stale. Otherwise the system can
    MANIFEST what it already has.

    This rule is an engineering hypothesis, not a historical Daoist claim.
    A conventional if/else policy with the same inputs is the equal-information
    control and must be semantically equivalent.
    """

    if had_discontinuity or current_phase in (
        TrajectoryPhase.REGRESSING,
        TrajectoryPhase.REORIENTING,
    ):
        return CapabilityMode.ADAPT

    if current_missing != EvidenceKind.NONE or (
        current_phase is TrajectoryPhase.STALLED
        and age_bucket >= PhaseAgeBucket.STALE
    ):
        return CapabilityMode.ACQUIRE

    return CapabilityMode.MANIFEST


def flow_profile(
    profile: CapabilityProfile,
    *,
    current_phase: TrajectoryPhase,
    current_missing: EvidenceKind,
    age_bucket: PhaseAgeBucket,
    had_discontinuity: bool = False,
) -> CapabilityProfile:
    """Move a carrier between capability modes without changing its identity."""

    next_mode = choose_capability_mode(
        current_phase=current_phase,
        current_missing=current_missing,
        age_bucket=age_bucket,
        had_discontinuity=had_discontinuity,
    )
    return profile.with_mode(next_mode)


@dataclass(frozen=True, slots=True)
class CapabilityTemporalState16:
    """TemporalState16 plus active capability mode in its two reserved bits.

    Layout is identical to TemporalState16 in bits 0..13. Bits 14..15 become:
      00 MANIFEST
      01 ACQUIRE
      10 ADAPT
      11 reserved

    Therefore the v0.1 capability layer adds no storage width: the complete
    temporal + active-capability hot state still fits in one uint16_t.
    """

    code: int

    def __post_init__(self) -> None:
        if not 0 <= self.code <= 0xFFFF:
            raise ValueError("capability temporal state must fit in 16 bits")
        if self.mode_code == 3:
            raise ValueError("capability mode code 3 is reserved")
        # Validate the inherited temporal portion as well.
        TemporalState16(self.code & 0x3FFF)

    @classmethod
    def from_temporal(
        cls,
        temporal: TemporalState16,
        mode: CapabilityMode,
    ) -> "CapabilityTemporalState16":
        return cls((temporal.code & 0x3FFF) | ((int(mode) & 0x3) << 14))

    @property
    def temporal(self) -> TemporalState16:
        return TemporalState16(self.code & 0x3FFF)

    @property
    def mode_code(self) -> int:
        return (self.code >> 14) & 0x3

    @property
    def mode(self) -> CapabilityMode:
        return CapabilityMode(self.mode_code)
