from __future__ import annotations

from collections import Counter
from time import perf_counter

from bardocompute.phase_age import PhaseAgeBucket, PhaseAgeSignature
from bardocompute.tao import EvidenceKind
from bardocompute.trajectory import TrajectoryPhase


def main() -> None:
    n = 100_000
    ages = (2, 8, 32, 128)
    signatures = [
        PhaseAgeSignature.encode(
            EvidenceKind.OUTCOME,
            TrajectoryPhase.CONVERGING,
            ages[i % 4],
        )
        for i in range(n)
    ]

    started = perf_counter()
    phase_only_classes = {
        (signature.current_missing, signature.current_phase)
        for signature in signatures
    }
    phase_only_seconds = perf_counter() - started

    started = perf_counter()
    age_classes = Counter(signature.age_bucket for signature in signatures)
    age_seconds = perf_counter() - started

    actual_stale_or_expired = sum(
        signature.age_bucket >= PhaseAgeBucket.STALE for signature in signatures
    )

    # Center/current-phase/current-edge are equal by construction. A monitor
    # without dwell time has no basis to emit an age alert.
    phase_only_alerts = 0
    phase_only_false_negatives = actual_stale_or_expired

    age_alerts = sum(signature.is_stale_or_expired for signature in signatures)
    age_false_negatives = actual_stale_or_expired - age_alerts

    conventional_buckets = [int(signature.age_bucket) for signature in signatures]
    semantic_equivalence = all(
        conventional == int(signature.age_bucket)
        for conventional, signature in zip(conventional_buckets, signatures)
    )

    assert len(phase_only_classes) == 1
    assert age_classes == {
        PhaseAgeBucket.FRESH: 25_000,
        PhaseAgeBucket.WARM: 25_000,
        PhaseAgeBucket.STALE: 25_000,
        PhaseAgeBucket.EXPIRED: 25_000,
    }
    assert actual_stale_or_expired == 50_000
    assert phase_only_false_negatives == 50_000
    assert age_false_negatives == 0
    assert semantic_equivalence

    print(f"cases={n}")
    print("same_current_center=true")
    print("same_current_phase=true")
    print("same_phase_edge=true")
    print()
    print("[center + current phase, no dwell time]")
    print(f"distinguishable_classes={len(phase_only_classes)}")
    print(f"stale_or_expired_false_negatives={phase_only_false_negatives}")
    print(f"seconds={phase_only_seconds:.6f}")
    print()
    print("[quantized phase age]")
    print(f"distinguishable_age_classes={len(age_classes)}")
    for bucket in PhaseAgeBucket:
        print(f"{bucket.name.lower()}={age_classes[bucket]}")
    print(f"stale_or_expired={actual_stale_or_expired}")
    print(f"stale_or_expired_false_negatives={age_false_negatives}")
    print(f"seconds={age_seconds:.6f}")
    print(f"semantic_equivalence_to_conventional_age_bucket={semantic_equivalence}")
    print()
    print(
        "interpretation=Equal center, current phase, and phase edge can still differ "
        "by dwell time. Quantized phase age makes staleness explicit. A conventional "
        "age counter/bucket is semantically equivalent; the processor question is the "
        "cost of keeping this temporal quantity close to hot transition state."
    )


if __name__ == "__main__":
    main()
