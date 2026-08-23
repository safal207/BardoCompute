from __future__ import annotations

from time import perf_counter

from bardocompute.packed import pack_line


def build_tuple_events(iterations: int) -> tuple[list[tuple[int, bool]], float]:
    """Conventional explicit metadata with the same decision information."""
    started = perf_counter()
    events: list[tuple[int, bool]] = []
    for i in range(iterations):
        source = i & 1
        target = 1 - source
        discontinuous = (i % 4) == 0
        events.append((target, discontinuous))
    return events, perf_counter() - started


def build_generic_packed_events(iterations: int) -> tuple[list[int], float]:
    """Generic three-bit field, deliberately not using BardoCompute helpers."""
    started = perf_counter()
    events: list[int] = []
    for i in range(iterations):
        source = i & 1
        target = 1 - source
        discontinuous = (i % 4) == 0
        code = (source << 2) | (target << 1) | int(discontinuous)
        events.append(code)
    return events, perf_counter() - started


def build_bardo_packed_events(iterations: int) -> tuple[list[int], float]:
    """The same three-bit representation through the validated public helper."""
    started = perf_counter()
    events: list[int] = []
    for i in range(iterations):
        source = i & 1
        target = 1 - source
        discontinuous = (i % 4) == 0
        events.append(pack_line(source, target, discontinuous))
    return events, perf_counter() - started


def scan_tuple_events(events: list[tuple[int, bool]]) -> tuple[int, float]:
    allowed = 0
    started = perf_counter()
    for target, discontinuous in events:
        if target == 1 and not discontinuous:
            allowed += 1
    return allowed, perf_counter() - started


def scan_packed_events(events: list[int]) -> tuple[int, float]:
    allowed = 0
    started = perf_counter()
    for code in events:
        if (code & 0b010) and not (code & 0b001):
            allowed += 1
    return allowed, perf_counter() - started


def streaming_explicit_fields(iterations: int) -> tuple[int, float]:
    """Lower-bound conventional control: decide immediately, store nothing."""
    allowed = 0
    started = perf_counter()
    for i in range(iterations):
        source = i & 1
        target = 1 - source
        discontinuous = (i % 4) == 0
        if target == 1 and not discontinuous:
            allowed += 1
    return allowed, perf_counter() - started


def main(iterations: int = 100_000) -> None:
    expected_allowed = iterations // 4

    tuple_events, tuple_build = build_tuple_events(iterations)
    generic_events, generic_build = build_generic_packed_events(iterations)
    bardo_events, bardo_build = build_bardo_packed_events(iterations)

    tuple_allowed, tuple_scan = scan_tuple_events(tuple_events)
    generic_allowed, generic_scan = scan_packed_events(generic_events)
    bardo_allowed, bardo_scan = scan_packed_events(bardo_events)
    streaming_allowed, streaming_time = streaming_explicit_fields(iterations)

    tuple_total = tuple_build + tuple_scan
    generic_total = generic_build + generic_scan
    bardo_total = bardo_build + bardo_scan

    assert tuple_allowed == expected_allowed
    assert generic_allowed == expected_allowed
    assert bardo_allowed == expected_allowed
    assert streaming_allowed == expected_allowed
    assert generic_events == bardo_events

    print(f"iterations={iterations}")
    print(f"expected_allowed={expected_allowed}")
    print()
    print("[conventional tuple metadata]")
    print(f"build_seconds={tuple_build:.6f}")
    print(f"scan_seconds={tuple_scan:.6f}")
    print(f"total_seconds={tuple_total:.6f}")
    print()
    print("[generic packed 3-bit field]")
    print(f"build_seconds={generic_build:.6f}")
    print(f"scan_seconds={generic_scan:.6f}")
    print(f"total_seconds={generic_total:.6f}")
    print()
    print("[Bardo pack_line API -> same 3-bit field]")
    print(f"build_seconds={bardo_build:.6f}")
    print(f"scan_seconds={bardo_scan:.6f}")
    print(f"total_seconds={bardo_total:.6f}")
    print()
    print("[streaming explicit fields / no retained transition state]")
    print(f"total_seconds={streaming_time:.6f}")
    print()
    print(f"generic_packed_vs_tuple_scan={generic_scan / tuple_scan:.3f}x")
    print(f"generic_packed_vs_tuple_total={generic_total / tuple_total:.3f}x")
    print(f"bardo_api_vs_generic_build={bardo_build / generic_build:.3f}x")
    print(f"bardo_api_vs_generic_total={bardo_total / generic_total:.3f}x")
    print(f"generic_packed_vs_streaming_total={generic_total / streaming_time:.3f}x")
    print("representation_identity=True")
    print(
        "interpretation=If generic packed and Bardo packed scan equally, the speed "
        "property belongs to the inline bitfield representation, not the Bardo name."
    )


if __name__ == "__main__":
    main()
