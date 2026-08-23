from __future__ import annotations

from time import perf_counter

from bardocompute.line import BardoLine, TransitionMode
from bardocompute.tao import EvidenceKind, OrientedTao, TaoDecision
from bardocompute.trajectory import PhasePoint, PhaseTrajectory


def defer(mask: EvidenceKind) -> OrientedTao:
    return OrientedTao(TaoDecision.DEFER, mask)


def clean_history() -> PhaseTrajectory:
    return PhaseTrajectory(
        (
            PhasePoint(0, BardoLine.stable(0), defer(EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME)),
            PhasePoint(1, BardoLine.between(0, 1, TransitionMode.CONTINUOUS), defer(EvidenceKind.OUTCOME)),
            PhasePoint(2, BardoLine.stable(1), OrientedTao(TaoDecision.ALLOW)),
        )
    )


def regressed_history() -> PhaseTrajectory:
    return PhaseTrajectory(
        (
            PhasePoint(0, BardoLine.stable(0), defer(EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME)),
            PhasePoint(1, BardoLine.stable(1), OrientedTao(TaoDecision.ALLOW)),
            PhasePoint(2, BardoLine.between(1, 0, TransitionMode.DISCONTINUOUS), defer(EvidenceKind.AUTHORITY | EvidenceKind.OUTCOME)),
            PhasePoint(3, BardoLine.stable(1), OrientedTao(TaoDecision.ALLOW)),
        )
    )


def snapshot_safe(history: PhaseTrajectory) -> bool:
    final = history.points[-1]
    return final.orientation.decision is TaoDecision.ALLOW and final.orientation.missing == EvidenceKind.NONE


def full_history_safe(history: PhaseTrajectory) -> bool:
    return history.regressions == 0 and history.discontinuities == 0 and snapshot_safe(history)


def signature_safe(history: PhaseTrajectory) -> bool:
    signature = history.signature
    return (
        not signature.had_regression
        and not signature.had_discontinuity
        and signature.current_missing == EvidenceKind.NONE
        and snapshot_safe(history)
    )


def main() -> None:
    repeats = 50_000
    histories = [clean_history(), regressed_history()] * repeats
    expected_safe = repeats

    started = perf_counter()
    snapshot_allowed = sum(snapshot_safe(history) for history in histories)
    snapshot_seconds = perf_counter() - started

    started = perf_counter()
    history_allowed = sum(full_history_safe(history) for history in histories)
    history_seconds = perf_counter() - started

    started = perf_counter()
    signature_allowed = sum(signature_safe(history) for history in histories)
    signature_seconds = perf_counter() - started

    assert history_allowed == signature_allowed == expected_safe
    assert snapshot_allowed == repeats * 2

    print(f"histories={len(histories)}")
    print(f"expected_safe={expected_safe}")
    print()
    print("[final snapshot only]")
    print(f"allowed={snapshot_allowed}")
    print(f"false_allows={snapshot_allowed - expected_safe}")
    print(f"seconds={snapshot_seconds:.6f}")
    print()
    print("[full temporal history]")
    print(f"allowed={history_allowed}")
    print("false_allows=0")
    print(f"seconds={history_seconds:.6f}")
    print()
    print("[one-byte temporal signature derived from history]")
    print(f"allowed={signature_allowed}")
    print("false_allows=0")
    print(f"seconds={signature_seconds:.6f}")
    print()
    print(
        "interpretation=Identical final snapshots can hide unsafe trajectories. "
        "A temporal signature can preserve policy-relevant history, but this Python "
        "benchmark derives it after the fact; the processor hypothesis requires "
        "updating the signature online as transitions occur."
    )


if __name__ == "__main__":
    main()
