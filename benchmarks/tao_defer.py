from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from bardocompute.tao import DecisionEvidence, TaoDecision, decide_tao


@dataclass(frozen=True, slots=True)
class Case:
    authority_valid: bool
    continuity_preserved: bool
    observed_outcome: bool | None
    eventual_outcome: bool


def build_cases(repeats: int = 20_000) -> list[Case]:
    """Create a balanced workload with resolved, unresolved, and invalid paths."""

    pattern = (
        Case(True, True, True, True),       # resolved success
        Case(True, True, False, False),     # resolved failure
        Case(True, True, None, True),       # pending -> later success
        Case(True, True, None, False),      # pending -> later failure
        Case(False, True, None, True),      # stale authority: deny now
        Case(True, False, None, True),      # broken continuity: deny now
    )
    return list(pattern) * repeats


def ground_truth(case: Case) -> bool:
    if not case.authority_valid or not case.continuity_preserved:
        return False
    return case.eventual_outcome


def binary_optimistic(case: Case) -> bool:
    """A binary engine that maps unresolved to ALLOW."""

    if not case.authority_valid or not case.continuity_preserved:
        return False
    return True if case.observed_outcome is None else case.observed_outcome


def binary_conservative(case: Case) -> bool:
    """A binary engine that maps unresolved to DENY."""

    if not case.authority_valid or not case.continuity_preserved:
        return False
    return False if case.observed_outcome is None else case.observed_outcome


def evaluate_binary(cases: list[Case], policy) -> tuple[int, int, float]:
    false_allows = 0
    false_denies = 0
    started = perf_counter()
    for case in cases:
        predicted = policy(case)
        truth = ground_truth(case)
        false_allows += int(predicted and not truth)
        false_denies += int((not predicted) and truth)
    elapsed = perf_counter() - started
    return false_allows, false_denies, elapsed


def evaluate_tao(cases: list[Case]) -> tuple[int, int, int, int, float]:
    premature_false_allows = 0
    premature_false_denies = 0
    deferred = 0
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
            continue

        predicted = initial is TaoDecision.ALLOW
        premature_false_allows += int(predicted and not truth)
        premature_false_denies += int((not predicted) and truth)

    elapsed = perf_counter() - started
    return (
        premature_false_allows,
        premature_false_denies,
        deferred,
        resolved_correctly,
        elapsed,
    )


def main() -> None:
    cases = build_cases()

    opt_fa, opt_fd, opt_time = evaluate_binary(cases, binary_optimistic)
    con_fa, con_fd, con_time = evaluate_binary(cases, binary_conservative)
    tao_fa, tao_fd, deferred, resolved, tao_time = evaluate_tao(cases)

    expected_deferred = 40_000
    assert deferred == expected_deferred
    assert tao_fa == 0
    assert tao_fd == 0
    assert resolved == expected_deferred

    print(f"cases={len(cases)}")
    print(f"pending_cases={expected_deferred}")
    print()

    print("[binary optimistic: pending -> allow]")
    print(f"false_allows={opt_fa}")
    print(f"false_denies={opt_fd}")
    print(f"seconds={opt_time:.6f}")
    print()

    print("[binary conservative: pending -> deny]")
    print(f"false_allows={con_fa}")
    print(f"false_denies={con_fd}")
    print(f"seconds={con_time:.6f}")
    print()

    print("[Tao: pending -> defer, then resolve]")
    print(f"premature_false_allows={tao_fa}")
    print(f"premature_false_denies={tao_fd}")
    print(f"deferred={deferred}")
    print(f"deferred_resolved_correctly={resolved}")
    print(f"seconds={tao_time:.6f}")
    print()

    print(
        "interpretation=Tao does not predict unknown outcomes; it buys correctness "
        "by keeping an unresolved decision non-terminal until evidence arrives."
    )


if __name__ == "__main__":
    main()
