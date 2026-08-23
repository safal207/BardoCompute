from __future__ import annotations

from collections import Counter
from time import perf_counter

from bardocompute.phase_age import PhaseAgeBucket
from bardocompute.tao import EvidenceKind, TaoDecision
from bardocompute.temporal_state import TemporalState16
from bardocompute.trajectory import TrajectoryPhase


def make_state(kind: int) -> TemporalState16:
    common = dict(current_missing=EvidenceKind.OUTCOME, decision=TaoDecision.DEFER)

    if kind == 0:  # safe convergence
        return TemporalState16.encode(
            **common,
            previous_phase=TrajectoryPhase.CONVERGING,
            current_phase=TrajectoryPhase.CONVERGING,
            phase_age_ticks=2,
        )
    if kind == 1:  # currently regressing
        return TemporalState16.encode(
            **common,
            previous_phase=TrajectoryPhase.CONVERGING,
            current_phase=TrajectoryPhase.REGRESSING,
            phase_age_ticks=2,
            had_regression=True,
        )
    if kind == 2:  # recently regressed, now converging
        return TemporalState16.encode(
            **common,
            previous_phase=TrajectoryPhase.REGRESSING,
            current_phase=TrajectoryPhase.CONVERGING,
            phase_age_ticks=2,
            had_regression=True,
        )
    if kind == 3:  # stalled long enough to be stale
        return TemporalState16.encode(
            **common,
            previous_phase=TrajectoryPhase.STALLED,
            current_phase=TrajectoryPhase.STALLED,
            phase_age_ticks=32,
        )
    return TemporalState16.encode(  # hidden discontinuity on otherwise safe path
        **common,
        previous_phase=TrajectoryPhase.CONVERGING,
        current_phase=TrajectoryPhase.CONVERGING,
        phase_age_ticks=2,
        had_discontinuity=True,
    )


def main() -> None:
    n = 100_000
    states = [make_state(i % 5) for i in range(n)]
    expected_alerts = 80_000

    started = perf_counter()
    current_phase_alerts = sum(
        state.current_phase is TrajectoryPhase.REGRESSING for state in states
    )
    current_phase_seconds = perf_counter() - started

    started = perf_counter()
    edge_alerts = sum(
        state.previous_phase is TrajectoryPhase.REGRESSING
        and state.current_phase is TrajectoryPhase.CONVERGING
        for state in states
    )
    edge_seconds = perf_counter() - started

    started = perf_counter()
    age_alerts = sum(
        state.current_phase is TrajectoryPhase.STALLED
        and state.age_bucket >= PhaseAgeBucket.STALE
        for state in states
    )
    age_seconds = perf_counter() - started

    started = perf_counter()
    combined_alerts = sum(state.should_temporal_alert for state in states)
    combined_seconds = perf_counter() - started

    generic_codes = [state.code for state in states]
    generic_alerts = 0
    for code in generic_codes:
        previous = (code >> 3) & 0x3
        current = (code >> 5) & 0x3
        age = (code >> 7) & 0x3
        discontinuity = bool(code & (1 << 10))
        edge_valid = bool(code & (1 << 11))
        decision = (code >> 12) & 0x3
        generic_alerts += int(
            current == 2
            or (edge_valid and previous == 2 and current == 1)
            or (current == 0 and age >= 2)
            or discontinuity
            or decision == 2
        )

    kind_counts = Counter(i % 5 for i in range(n))

    assert all(state.current_missing is EvidenceKind.OUTCOME for state in states)
    assert kind_counts == {0: 20_000, 1: 20_000, 2: 20_000, 3: 20_000, 4: 20_000}
    assert current_phase_alerts == 20_000
    assert edge_alerts == 20_000
    assert age_alerts == 20_000
    assert combined_alerts == expected_alerts
    assert generic_alerts == expected_alerts
    assert all(state.reserved_bits == 0 for state in states)

    print(f"cases={n}")
    print(f"expected_alerts={expected_alerts}")
    print("all_current_orientation_masks_equal=true")
    print("used_bits=14")
    print("reserved_bits=2")
    print()
    print("[current phase only]")
    print(f"alerts={current_phase_alerts}")
    print(f"false_negatives={expected_alerts - current_phase_alerts}")
    print(f"seconds={current_phase_seconds:.6f}")
    print()
    print("[phase edge only]")
    print(f"alerts={edge_alerts}")
    print(f"false_negatives={expected_alerts - edge_alerts}")
    print(f"seconds={edge_seconds:.6f}")
    print()
    print("[phase age only]")
    print(f"alerts={age_alerts}")
    print(f"false_negatives={expected_alerts - age_alerts}")
    print(f"seconds={age_seconds:.6f}")
    print()
    print("[TemporalState16 combined policy]")
    print(f"alerts={combined_alerts}")
    print(f"false_negatives={expected_alerts - combined_alerts}")
    print(f"seconds={combined_seconds:.6f}")
    print(f"generic_uint16_semantic_equivalence={generic_alerts == combined_alerts}")
    print()
    print(
        "interpretation=No single temporal slice is sufficient for this mixed workload. "
        "A combined temporal word makes current motion, recent phase order, dwell-time "
        "staleness, and discontinuity history simultaneously available. A conventional "
        "uint16_t with identical bits is the equal-information semantic control."
    )


if __name__ == "__main__":
    main()
