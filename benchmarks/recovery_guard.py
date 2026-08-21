from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from bardocompute import BardoLine, TransitionMode


@dataclass(frozen=True, slots=True)
class GuardResult:
    seconds: float
    allowed: int
    false_allows: int


def build_workload(iterations: int) -> tuple[list[int], dict[int, bool], list[BardoLine]]:
    """Build equivalent views of one deterministic recovery workload.

    Every transition flips the bit. Rising transitions are eligible for a
    hypothetical dispatch, but only if causal continuity is preserved.
    Every fourth event is discontinuous, which makes half of the rising
    transitions unsafe to dispatch.

    Workload construction is intentionally outside the timed guard loops.
    This benchmark measures decision/reconstruction cost, not object creation.
    """
    targets: list[int] = []
    discontinuous_by_event: dict[int, bool] = {}
    bardo_lines: list[BardoLine] = []

    for i in range(iterations):
        source = i & 1
        target = 1 - source
        discontinuous = (i % 4) == 0
        mode = (
            TransitionMode.DISCONTINUOUS
            if discontinuous
            else TransitionMode.CONTINUOUS
        )

        targets.append(target)
        discontinuous_by_event[i] = discontinuous
        bardo_lines.append(BardoLine.between(source, target, mode))

    return targets, discontinuous_by_event, bardo_lines


def endpoint_only_guard(
    targets: list[int], discontinuous_by_event: dict[int, bool]
) -> GuardResult:
    """Fast but under-informed: terminal state alone cannot detect the break."""
    allowed = 0
    false_allows = 0

    started = perf_counter()
    for i, target in enumerate(targets):
        if target == 1:
            allowed += 1
            false_allows += int(discontinuous_by_event[i])
    elapsed = perf_counter() - started

    return GuardResult(elapsed, allowed, false_allows)


def external_lookup_guard(
    targets: list[int], discontinuous_by_event: dict[int, bool]
) -> GuardResult:
    """Correct baseline: reconstruct continuity through external metadata."""
    allowed = 0

    started = perf_counter()
    for i, target in enumerate(targets):
        if target == 1 and not discontinuous_by_event[i]:
            allowed += 1
    elapsed = perf_counter() - started

    return GuardResult(elapsed, allowed, 0)


def bardo_inline_guard(lines: list[BardoLine]) -> GuardResult:
    """Correct Bardo path: continuity is carried directly by the transition."""
    allowed = 0

    started = perf_counter()
    for line in lines:
        if line.target == 1 and line.preserves_continuity:
            allowed += 1
    elapsed = perf_counter() - started

    return GuardResult(elapsed, allowed, 0)


def main(iterations: int = 100_000) -> None:
    targets, discontinuous_by_event, lines = build_workload(iterations)

    endpoint = endpoint_only_guard(targets, discontinuous_by_event)
    lookup = external_lookup_guard(targets, discontinuous_by_event)
    bardo = bardo_inline_guard(lines)

    expected_allowed = iterations // 4

    print(f"iterations={iterations}")
    print(f"expected_allowed={expected_allowed}")
    print()
    print("[endpoint-only / no provenance]")
    print(f"decision_seconds={endpoint.seconds:.6f}")
    print(f"allowed={endpoint.allowed}")
    print(f"false_allows={endpoint.false_allows}")
    print()
    print("[endpoint + external continuity lookup]")
    print(f"decision_seconds={lookup.seconds:.6f}")
    print(f"allowed={lookup.allowed}")
    print(f"false_allows={lookup.false_allows}")
    print()
    print("[Bardo inline continuity]")
    print(f"decision_seconds={bardo.seconds:.6f}")
    print(f"allowed={bardo.allowed}")
    print(f"false_allows={bardo.false_allows}")
    print()
    print(f"endpoint_correct={endpoint.allowed == expected_allowed}")
    print(f"lookup_correct={lookup.allowed == expected_allowed}")
    print(f"bardo_correct={bardo.allowed == expected_allowed}")
    print(f"bardo_vs_lookup_decision_ratio={bardo.seconds / lookup.seconds:.3f}x")


if __name__ == "__main__":
    main()
