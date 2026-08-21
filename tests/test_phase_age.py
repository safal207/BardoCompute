import pytest

from bardocompute.phase_age import PhaseAgeBucket, PhaseAgeSignature, phase_age_bucket
from bardocompute.tao import EvidenceKind
from bardocompute.trajectory import TrajectoryPhase


def test_phase_age_bucket_boundaries() -> None:
    assert phase_age_bucket(0) is PhaseAgeBucket.FRESH
    assert phase_age_bucket(3) is PhaseAgeBucket.FRESH
    assert phase_age_bucket(4) is PhaseAgeBucket.WARM
    assert phase_age_bucket(15) is PhaseAgeBucket.WARM
    assert phase_age_bucket(16) is PhaseAgeBucket.STALE
    assert phase_age_bucket(63) is PhaseAgeBucket.STALE
    assert phase_age_bucket(64) is PhaseAgeBucket.EXPIRED
    assert phase_age_bucket(10_000) is PhaseAgeBucket.EXPIRED


def test_phase_age_rejects_negative_age() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        phase_age_bucket(-1)


def test_phase_age_signature_fits_one_byte() -> None:
    signature = PhaseAgeSignature.encode(
        EvidenceKind.OUTCOME,
        TrajectoryPhase.CONVERGING,
        17,
    )
    assert signature.current_missing is EvidenceKind.OUTCOME
    assert signature.current_phase is TrajectoryPhase.CONVERGING
    assert signature.age_bucket is PhaseAgeBucket.STALE
    assert signature.is_stale_or_expired
    assert signature.code <= 0xFF


def test_same_center_and_phase_can_differ_by_age() -> None:
    fresh = PhaseAgeSignature.encode(
        EvidenceKind.OUTCOME,
        TrajectoryPhase.CONVERGING,
        2,
    )
    expired = PhaseAgeSignature.encode(
        EvidenceKind.OUTCOME,
        TrajectoryPhase.CONVERGING,
        100,
    )

    assert fresh.current_missing == expired.current_missing
    assert fresh.current_phase == expired.current_phase
    assert fresh.age_bucket is PhaseAgeBucket.FRESH
    assert expired.age_bucket is PhaseAgeBucket.EXPIRED
    assert fresh.code != expired.code
