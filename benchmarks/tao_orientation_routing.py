from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from bardocompute.tao import EvidenceKind, OrientedEvidence, orient_tao


@dataclass(frozen=True, slots=True)
class PendingCase:
    evidence: OrientedEvidence
    missing_kind: EvidenceKind


def build_cases(repeats: int = 50_000) -> list[PendingCase]:
    pattern = (
        PendingCase(OrientedEvidence(None, True, True), EvidenceKind.AUTHORITY),
        PendingCase(OrientedEvidence(True, None, True), EvidenceKind.CONTINUITY),
        PendingCase(OrientedEvidence(True, True, None), EvidenceKind.OUTCOME),
    )
    return list(pattern) * repeats


def plain_pending_outcome_event(cases: list[PendingCase]) -> tuple[int, int, float]:
    """A single undifferentiated pending queue: inspect every item."""

    touched = 0
    resolved = 0
    started = perf_counter()
    for case in cases:
        touched += 1
        if case.evidence.outcome is None:
            resolved += 1
    return touched, resolved, perf_counter() - started


def build_tao_outcome_bucket(cases: list[PendingCase]) -> tuple[list[int], float]:
    bucket: list[int] = []
    started = perf_counter()
    for index, case in enumerate(cases):
        oriented = orient_tao(case.evidence)
        if oriented.waits_for(EvidenceKind.OUTCOME):
            bucket.append(index)
    return bucket, perf_counter() - started


def oriented_outcome_event(bucket: list[int]) -> tuple[int, int, float]:
    """Route the event directly to states oriented toward OUTCOME evidence."""

    touched = 0
    resolved = 0
    started = perf_counter()
    for _index in bucket:
        touched += 1
        resolved += 1
    return touched, resolved, perf_counter() - started


def build_conventional_outcome_bucket(cases: list[PendingCase]) -> tuple[list[int], float]:
    """Equal-information indexed PENDING control."""

    bucket: list[int] = []
    started = perf_counter()
    for index, case in enumerate(cases):
        if case.missing_kind & EvidenceKind.OUTCOME:
            bucket.append(index)
    return bucket, perf_counter() - started


def main() -> None:
    cases = build_cases()
    expected = 50_000

    plain_touched, plain_resolved, plain_route = plain_pending_outcome_event(cases)

    tao_bucket, tao_build = build_tao_outcome_bucket(cases)
    tao_touched, tao_resolved, tao_route = oriented_outcome_event(tao_bucket)

    conventional_bucket, conventional_build = build_conventional_outcome_bucket(cases)
    conventional_touched, conventional_resolved, conventional_route = oriented_outcome_event(
        conventional_bucket
    )

    assert plain_resolved == tao_resolved == conventional_resolved == expected
    assert tao_bucket == conventional_bucket
    assert tao_touched == conventional_touched == expected
    assert plain_touched == len(cases)

    print(f"pending_cases={len(cases)}")
    print(f"outcome_waiters={expected}")
    print()

    print("[plain undifferentiated PENDING queue]")
    print(f"records_touched={plain_touched}")
    print(f"resolved={plain_resolved}")
    print(f"route_seconds={plain_route:.6f}")
    print()

    print("[oriented Tao bucket]")
    print(f"index_build_seconds={tao_build:.6f}")
    print(f"records_touched={tao_touched}")
    print(f"resolved={tao_resolved}")
    print(f"route_seconds={tao_route:.6f}")
    print()

    print("[conventional indexed PENDING control]")
    print(f"index_build_seconds={conventional_build:.6f}")
    print(f"records_touched={conventional_touched}")
    print(f"resolved={conventional_resolved}")
    print(f"route_seconds={conventional_route:.6f}")
    print()

    print(f"oriented_touch_ratio_vs_plain={tao_touched / plain_touched:.3f}x")
    print("indexed_semantic_equivalence=true")
    print(
        "interpretation=Orientation can reduce event fan-out versus an undifferentiated "
        "pending queue, but an equally informative conventional index achieves the same "
        "routing. The research target is a compact/native way to bind this orientation "
        "to transition provenance."
    )


if __name__ == "__main__":
    main()
