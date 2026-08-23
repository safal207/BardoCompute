from __future__ import annotations

import sys
from time import perf_counter

from bardocompute import BardoLine


def binary_baseline(iterations: int) -> tuple[int, float, int]:
    state = 0
    started = perf_counter()
    for _ in range(iterations):
        state = 1 - state
    elapsed = perf_counter() - started
    return state, elapsed, sys.getsizeof(state)


def bardo_model(iterations: int) -> tuple[BardoLine, float, int, int]:
    state = BardoLine.stable(0)
    transitions_observed = 0
    started = perf_counter()
    for _ in range(iterations):
        transition = BardoLine.between(state.target, 1 - state.target)
        transitions_observed += int(transition.is_transition)
        state = transition.settle()
    elapsed = perf_counter() - started
    return state, elapsed, sys.getsizeof(state), transitions_observed


def main(iterations: int = 100_000) -> None:
    binary_state, binary_time, binary_size = binary_baseline(iterations)
    bardo_state, bardo_time, bardo_size, transitions = bardo_model(iterations)

    print(f"iterations={iterations}")
    print(f"binary.final={binary_state}")
    print(f"binary.seconds={binary_time:.6f}")
    print(f"binary.object_bytes={binary_size}")
    print(f"bardo.final={bardo_state.target}")
    print(f"bardo.seconds={bardo_time:.6f}")
    print(f"bardo.object_bytes={bardo_size}")
    print(f"bardo.transitions_observed={transitions}")
    print(f"speed_ratio_bardo_over_binary={bardo_time / binary_time:.3f}")
    print(f"size_ratio_bardo_over_binary={bardo_size / binary_size:.3f}")


if __name__ == "__main__":
    main()
