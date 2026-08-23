from __future__ import annotations

import sys
from time import perf_counter

from bardocompute import BardoLine, TransitionMode


def endpoint_only(iterations: int) -> tuple[float, int, int]:
    """Cheapest baseline: retain only the current binary endpoint."""
    observed: set[int] = set()
    last = 0
    started = perf_counter()
    for i in range(iterations):
        source = i & 1
        last = 1 - source
        observed.add(last)
    elapsed = perf_counter() - started
    return elapsed, sys.getsizeof(last), len(observed)


def binary_with_metadata(iterations: int) -> tuple[float, int, int]:
    """Equivalent-information baseline using an ordinary Python tuple."""
    observed: set[tuple[int, int, bool]] = set()
    last = (0, 1, False)
    started = perf_counter()
    for i in range(iterations):
        source = i & 1
        target = 1 - source
        discontinuous = (i % 4) >= 2
        last = (source, target, discontinuous)
        observed.add(last)
    elapsed = perf_counter() - started
    return elapsed, sys.getsizeof(last), len(observed)


def bardo_with_mode(iterations: int) -> tuple[float, int, int]:
    """Bardo v0.2: direction and continuity are first-class semantics."""
    observed: set[tuple[int, int, str]] = set()
    last = BardoLine.between(0, 1)
    started = perf_counter()
    for i in range(iterations):
        source = i & 1
        target = 1 - source
        mode = (
            TransitionMode.DISCONTINUOUS
            if (i % 4) >= 2
            else TransitionMode.CONTINUOUS
        )
        last = BardoLine.between(source, target, mode)
        observed.add((last.source, last.target, last.mode.value))
    elapsed = perf_counter() - started
    return elapsed, sys.getsizeof(last), len(observed)


def main(iterations: int = 100_000) -> None:
    endpoint_time, endpoint_bytes, endpoint_classes = endpoint_only(iterations)
    metadata_time, metadata_bytes, metadata_classes = binary_with_metadata(iterations)
    bardo_time, bardo_bytes, bardo_classes = bardo_with_mode(iterations)

    print(f"iterations={iterations}")
    print()
    print("[endpoint-only binary]")
    print(f"seconds={endpoint_time:.6f}")
    print(f"object_bytes={endpoint_bytes}")
    print(f"distinguishable_classes={endpoint_classes}")
    print()
    print("[binary + explicit metadata]")
    print(f"seconds={metadata_time:.6f}")
    print(f"object_bytes={metadata_bytes}")
    print(f"distinguishable_classes={metadata_classes}")
    print()
    print("[Bardo v0.2]")
    print(f"seconds={bardo_time:.6f}")
    print(f"object_bytes={bardo_bytes}")
    print(f"distinguishable_classes={bardo_classes}")
    print()
    print(
        "utility_gain_vs_endpoint="
        f"{bardo_classes / endpoint_classes:.3f}x distinguishable histories"
    )
    print(
        "speed_cost_vs_equivalent_metadata="
        f"{bardo_time / metadata_time:.3f}x"
    )
    print(
        "object_size_vs_equivalent_metadata="
        f"{bardo_bytes / metadata_bytes:.3f}x"
    )


if __name__ == "__main__":
    main()
