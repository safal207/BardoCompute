from __future__ import annotations

from enum import IntEnum
from time import perf_counter

from bardocompute.tao import DecisionEvidence, TaoDecision, decide_tao
from tao_defer import Case, build_cases, ground_truth


class ConventionalDecision(IntEnum):
    DENY = 0
    PENDING = 1
    ALLOW = 2


def decide_conventional(case: Case, outcome: bool | None) -> ConventionalDecision:
    if not case.authority_valid or not case.continuity_preserved:
        return ConventionalDecision.DENY
    if outcome is None:
        return ConventionalDecision.PENDING
    return ConventionalDecision.ALLOW if outcome else ConventionalDecision.DENY


def run_conventional(cases: list[Case]) -> tuple[int, int, int, float]:
    pending = 0
    errors = 0
    resolved_correctly = 0
    started = perf_counter()
    for case in cases:
        initial = decide_conventional(case, case.observed_outcome)
        truth = ground_truth(case)
        if initial is ConventionalDecision.PENDING:
            pending += 1
            final = decide_conventional(case, case.eventual_outcome)
            predicted = final is ConventionalDecision.ALLOW
            resolved_correctly += int(predicted == truth)
        else:
            predicted = initial is ConventionalDecision.ALLOW
            errors += int(predicted != truth)
    return pending, errors, resolved_correctly, perf_counter() - started


def run_tao(cases: list[Case]) -> tuple[int, int, int, float]:
    deferred = 0
    errors = 0
    resolved_correctly = 0
    started = perf_counter()
    for case in cases:
        initial = decide_tao(
            DecisionEvidence(
                authority_valid=case.authority_valid,
                continuity_preserved=case.continuity_preserved,
                outcome=case.observed_outcome,
            )
        )
        truth = ground_truth(case)
        if initial is TaoDecision.DEFER:
            deferred += 1
            final = decide_tao(
                DecisionEvidence(
                    authority_valid=case.authority_valid,
                    continuity_preserved=case.continuity_preserved,
                    outcome=case.eventual_outcome,
                )
            )
            predicted = final is TaoDecision.ALLOW
            resolved_correctly += int(predicted == truth)
        else:
            predicted = initial is TaoDecision.ALLOW
            errors += int(predicted != truth)
    return deferred, errors, resolved_correctly, perf_counter() - started


def main() -> None:
    cases = build_cases()
    c_pending, c_errors, c_resolved, c_time = run_conventional(cases)
    t_defer, t_errors, t_resolved, t_time = run_tao(cases)

    assert c_pending == t_defer == 40_000
    assert c_errors == t_errors == 0
    assert c_resolved == t_resolved == 40_000

    print(f"cases={len(cases)}")
    print("semantic_equivalence=true")
    print()
    print("[conventional ALLOW/PENDING/DENY]")
    print(f"pending={c_pending}")
    print(f"errors={c_errors}")
    print(f"resolved_correctly={c_resolved}")
    print(f"seconds={c_time:.6f}")
    print()
    print("[Tao ALLOW/DEFER/DENY]")
    print(f"deferred={t_defer}")
    print(f"errors={t_errors}")
    print(f"resolved_correctly={t_resolved}")
    print(f"seconds={t_time:.6f}")
    print()
    print(f"tao_vs_conventional_time={t_time / c_time:.3f}x")
    print(
        "interpretation=If semantics are identical, Tao is currently an ontology/API "
        "for explicit non-terminal decisions, not a proven performance advantage over "
        "a conventional pending-state machine."
    )


if __name__ == "__main__":
    main()
