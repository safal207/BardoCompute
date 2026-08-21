import pytest

from bardocompute.capability import (
    Capability,
    CapabilityMode,
    CapabilityProfile,
    CapabilityTemporalState16,
    Carrier,
    choose_capability_mode,
    flow_profile,
)
from bardocompute.phase_age import PhaseAgeBucket
from bardocompute.tao import EvidenceKind, TaoDecision
from bardocompute.temporal_state import TemporalState16
from bardocompute.trajectory import TrajectoryPhase


def test_all_three_carriers_have_all_three_capabilities_by_default() -> None:
    for carrier in Carrier:
        profile = CapabilityProfile(carrier)
        assert profile.innate == Capability.ALL
        assert profile.supports(CapabilityMode.MANIFEST)
        assert profile.supports(CapabilityMode.ACQUIRE)
        assert profile.supports(CapabilityMode.ADAPT)


def test_flow_law_manifest_acquire_adapt() -> None:
    assert choose_capability_mode(
        current_phase=TrajectoryPhase.CONVERGING,
        current_missing=EvidenceKind.NONE,
        age_bucket=PhaseAgeBucket.FRESH,
    ) is CapabilityMode.MANIFEST

    assert choose_capability_mode(
        current_phase=TrajectoryPhase.STALLED,
        current_missing=EvidenceKind.OUTCOME,
        age_bucket=PhaseAgeBucket.WARM,
    ) is CapabilityMode.ACQUIRE

    assert choose_capability_mode(
        current_phase=TrajectoryPhase.REGRESSING,
        current_missing=EvidenceKind.NONE,
        age_bucket=PhaseAgeBucket.FRESH,
    ) is CapabilityMode.ADAPT

    assert choose_capability_mode(
        current_phase=TrajectoryPhase.CONVERGING,
        current_missing=EvidenceKind.NONE,
        age_bucket=PhaseAgeBucket.FRESH,
        had_discontinuity=True,
    ) is CapabilityMode.ADAPT


def test_capability_modes_can_flow_without_changing_carrier() -> None:
    profile = CapabilityProfile(Carrier.YIN)
    profile = flow_profile(
        profile,
        current_phase=TrajectoryPhase.STALLED,
        current_missing=EvidenceKind.AUTHORITY,
        age_bucket=PhaseAgeBucket.WARM,
    )
    assert profile.carrier is Carrier.YIN
    assert profile.active is CapabilityMode.ACQUIRE

    profile = flow_profile(
        profile,
        current_phase=TrajectoryPhase.REORIENTING,
        current_missing=EvidenceKind.NONE,
        age_bucket=PhaseAgeBucket.FRESH,
    )
    assert profile.carrier is Carrier.YIN
    assert profile.active is CapabilityMode.ADAPT

    profile = flow_profile(
        profile,
        current_phase=TrajectoryPhase.CONVERGING,
        current_missing=EvidenceKind.NONE,
        age_bucket=PhaseAgeBucket.FRESH,
    )
    assert profile.carrier is Carrier.YIN
    assert profile.active is CapabilityMode.MANIFEST


def test_capability_temporal_state_uses_reserved_two_bits_only() -> None:
    temporal = TemporalState16.encode(
        current_missing=EvidenceKind.OUTCOME,
        previous_phase=TrajectoryPhase.STALLED,
        current_phase=TrajectoryPhase.CONVERGING,
        phase_age_ticks=8,
        had_regression=True,
        had_discontinuity=False,
        phase_edge_valid=True,
        decision=TaoDecision.DEFER,
    )

    for mode in CapabilityMode:
        state = CapabilityTemporalState16.from_temporal(temporal, mode)
        assert state.temporal == temporal
        assert state.mode is mode
        assert state.code & 0x3FFF == temporal.code
        assert 0 <= state.code <= 0xFFFF


def test_reserved_capability_code_is_rejected() -> None:
    temporal = TemporalState16.encode(
        current_missing=EvidenceKind.NONE,
        previous_phase=TrajectoryPhase.CONVERGING,
        current_phase=TrajectoryPhase.CONVERGING,
        phase_age_ticks=1,
        decision=TaoDecision.ALLOW,
    )
    with pytest.raises(ValueError, match="reserved"):
        CapabilityTemporalState16(temporal.code | (3 << 14))


def test_profile_rejects_active_mode_not_present_in_potential() -> None:
    with pytest.raises(ValueError, match="innate potential"):
        CapabilityProfile(
            Carrier.TAO,
            innate=Capability.MANIFEST,
            active=CapabilityMode.ADAPT,
        )
