from __future__ import annotations

from collections import Counter
from time import perf_counter

from bardocompute.line import BardoLine
from bardocompute.phase_edge import PhaseEdgeSignature
from bardocompute.tao import EvidenceKind, OrientedTao, TaoDecision
from bardocompute.trajectory import PhasePoint, TrajectoryPhase


def defer(mask: EvidenceKind) -> OrientedTao:
    return OrientedTao(TaoDecision.DEFER, mask)


def point(tick: int, mask: EvidenceKind) -> PhasePoint:
    return PhasePoint(tick, BardoLine.stable(0), defer(mask))


def make_signature(kind: int) -> PhaseEdgeSignature:
    # All cases share middle and current points, so current center and current
    # phase are equal. Only the phase immediately before current convergence differs.
    middle = point(1, EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME)
    current = point(2, EvidenceKind.OUTCOME)

    if kind == 0:  # CONVERGING -> CONVERGING
        first_mask = (
            EvidenceKind.AUTHORITY | EvidenceKind.CONTINUITY | EvidenceKind.OUTCOME
        )
    elif kind == 1:  # STALLED -> CONVERGING
        first_mask = EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME
    elif kind == 2:  # REGRESSING -> CONVERGING
        first_mask = EvidenceKind.OUTCOME
    else:  # REORIENTING -> CONVERGING
        first_mask = EvidenceKind.CONTINUITY | EvidenceKind.OUTCOME

    return PhaseEdgeSignature.from_points(point(0, first_mask), middle, current)


def main() -> None:
    n = 100_000
    signatures = [make_signature(i % 4) for i in range(n)]

    started = perf_counter()
    center_classes = {signature.current_missing for signature in signatures}
    center_seconds = perf_counter() - started

    started = perf_counter()
    current_phase_classes = {signature.current_phase for signature in signatures}
    current_phase_seconds = perf_counter() - started

    started = perf_counter()
    edge_counts = Counter(signature.edge_code for signature in signatures)
    edge_seconds = perf_counter() - started

    recent_regressions = sum(
        signature.previous_phase is TrajectoryPhase.REGRESSING
        for signature in signatures
    )

    # A monitor that knows only the current phase sees CONVERGING everywhere,
    # so it cannot tell that 25k records were regressing one step earlier.
    phase_only_recent_regression_alerts = 0
    phase_only_false_negatives = recent_regressions

    edge_recent_regression_alerts = sum(
        signature.previous_phase is TrajectoryPhase.REGRESSING
        for signature in signatures
    )
    edge_false_negatives = recent_regressions - edge_recent_regression_alerts

    conventional_edges = [
        (signature.previous_phase, signature.current_phase) for signature in signatures
    ]
    semantic_equivalence = all(
        signature.edge_code
        == ((
            {
                TrajectoryPhase.STALLED: 0,
                TrajectoryPhase.CONVERGING: 1,
                TrajectoryPhase.REGRESSING: 2,
                TrajectoryPhase.REORIENTING: 3,
            }[previous]
            << 2
        ) | {
            TrajectoryPhase.STALLED: 0,
            TrajectoryPhase.CONVERGING: 1,
            TrajectoryPhase.REGRESSING: 2,
            TrajectoryPhase.REORIENTING: 3,
        }[current])
        for signature, (previous, current) in zip(signatures, conventional_edges)
    )

    assert len(center_classes) == 1
    assert len(current_phase_classes) == 1
    assert current_phase_classes == {TrajectoryPhase.CONVERGING}
    assert len(edge_counts) == 4
    assert sorted(edge_counts.values()) == [25_000] * 4
    assert recent_regressions == 25_000
    assert phase_only_false_negatives == 25_000
    assert edge_false_negatives == 0
    assert semantic_equivalence

    print(f"cases={n}")
    print("all_current_centers_equal=true")
    print("all_current_phases_equal=true")
    print()
    print("[current center only]")
    print(f"distinguishable_classes={len(center_classes)}")
    print(f"seconds={center_seconds:.6f}")
    print()
    print("[current phase only]")
    print(f"distinguishable_classes={len(current_phase_classes)}")
    print(f"recent_regression_false_negatives={phase_only_false_negatives}")
    print(f"seconds={current_phase_seconds:.6f}")
    print()
    print("[ordered phase edge]")
    print(f"distinguishable_classes={len(edge_counts)}")
    print(f"recent_regressions={recent_regressions}")
    print(f"recent_regression_false_negatives={edge_false_negatives}")
    print(f"seconds={edge_seconds:.6f}")
    print(f"semantic_equivalence_to_conventional_phase_pair={semantic_equivalence}")
    print()
    print(
        "interpretation=Equal O(t) and equal current phase can still hide different "
        "phase trajectories. The ordered phase edge preserves one additional order of "
        "temporal context. A conventional previous/current phase pair is semantically "
        "equivalent; the next question is compact online implementation cost."
    )


if __name__ == "__main__":
    main()
