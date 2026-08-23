from __future__ import annotations

from collections import Counter
from time import perf_counter

from bardocompute.line import BardoLine
from bardocompute.tao import EvidenceKind, OrientedTao, TaoDecision
from bardocompute.trajectory import PhasePoint, PhaseStep, TrajectoryPhase


def defer(mask: EvidenceKind) -> OrientedTao:
    return OrientedTao(TaoDecision.DEFER, mask)


def make_step(kind: int) -> PhaseStep:
    """Return four different paths that all end at OUTCOME-missing."""

    current = PhasePoint(2, BardoLine.stable(0), defer(EvidenceKind.OUTCOME))

    if kind == 0:  # converging: authority was also missing, then resolved
        previous_orientation = defer(EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME)
    elif kind == 1:  # stalled: nothing changed
        previous_orientation = defer(EvidenceKind.OUTCOME)
    elif kind == 2:  # regressing: outcome had been settled, then became missing
        previous_orientation = OrientedTao(TaoDecision.ALLOW)
    else:  # reorienting: authority settled while outcome became missing
        previous_orientation = defer(EvidenceKind.AUTHORITY)

    previous = PhasePoint(0, BardoLine.stable(0), previous_orientation)
    return PhaseStep(previous, current)


def main() -> None:
    n = 100_000
    steps = [make_step(i % 4) for i in range(n)]

    started = perf_counter()
    snapshot_classes = {step.current.orientation.missing for step in steps}
    snapshot_seconds = perf_counter() - started

    started = perf_counter()
    phases = Counter(step.phase for step in steps)
    kinetics_seconds = perf_counter() - started

    actual_regressions = phases[TrajectoryPhase.REGRESSING]

    # An endpoint-only optimistic monitor sees the same current orientation for
    # every record, so it emits no regression alert and misses all regressions.
    snapshot_regression_alerts = 0
    snapshot_false_negatives = actual_regressions - snapshot_regression_alerts

    kinetics_regression_alerts = phases[TrajectoryPhase.REGRESSING]
    kinetics_false_negatives = actual_regressions - kinetics_regression_alerts

    assert len(snapshot_classes) == 1
    assert phases == {
        TrajectoryPhase.CONVERGING: 25_000,
        TrajectoryPhase.STALLED: 25_000,
        TrajectoryPhase.REGRESSING: 25_000,
        TrajectoryPhase.REORIENTING: 25_000,
    }
    assert snapshot_false_negatives == 25_000
    assert kinetics_false_negatives == 0

    print(f"cases={n}")
    print("all_current_centers_equal=true")
    print()
    print("[current orientation snapshot]")
    print(f"distinguishable_classes={len(snapshot_classes)}")
    print(f"regression_false_negatives={snapshot_false_negatives}")
    print(f"seconds={snapshot_seconds:.6f}")
    print()
    print("[trajectory phase kinetics]")
    print(f"distinguishable_classes={len(phases)}")
    for phase in TrajectoryPhase:
        print(f"{phase.value}={phases[phase]}")
    print(f"regression_false_negatives={kinetics_false_negatives}")
    print(f"seconds={kinetics_seconds:.6f}")
    print()
    print(
        "interpretation=The same center O(t) can have different temporal motion. "
        "A phase step distinguishes convergence, stall, regression, and reorientation; "
        "an equally informative conventional previous-state control can do the same."
    )


if __name__ == "__main__":
    main()
