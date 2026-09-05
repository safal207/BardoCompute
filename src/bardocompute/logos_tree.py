"""Bounded LOGOS reduction model for BARDO-TX1.

The module turns a frame of ordered BARDO-TX1 lane results into a fixed 128-bit
summary. Aggregate counters are associative; the 64-bit root is deliberately
ordered and lane-bound, so exchanging two lane values changes the root.

This is a software falsification model, not an FPGA or CPU-speedup claim.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .hardware_contract import Tx1Result, evaluate_trigram, unpack_trigram_lines

MASK64 = (1 << 64) - 1
LOGOS_WORD_BITS = 128
LOGOS_MAX_LANES = 71
TX1_RESULT_BITS = 23
LEAF_DOMAIN = 0x4C4F474F534C4541  # "LOGOSLEA"
NODE_DOMAIN = 0x4C4F474F534E4F44  # "LOGOSNOD"
BENCHMARK_SCHEMA_VERSION = 1


class LogosError(ValueError):
    """Raised when a LOGOS frame or merge violates its bounded contract."""


@dataclass(frozen=True, slots=True)
class LogosWord:
    """Fixed-width logical state for one contiguous lane span.

    ``span_start`` is internal routing metadata and is not exported in the
    128-bit word. The exported fields are one 64-bit ordered root plus eight
    unsigned 8-bit counters.
    """

    span_start: int
    span_length: int
    valid_count: int
    invalid_count: int
    transition_count: int
    discontinuity_count: int
    target_count: int
    policy_allow_count: int
    consequential_count: int
    ordered_root: int

    def __post_init__(self) -> None:
        if self.span_start < 0:
            raise LogosError("span_start must be >= 0")
        if not 1 <= self.span_length <= LOGOS_MAX_LANES:
            raise LogosError(
                f"span_length must be in [1, {LOGOS_MAX_LANES}], got {self.span_length}"
            )
        for field_name in (
            "valid_count",
            "invalid_count",
            "transition_count",
            "discontinuity_count",
            "target_count",
            "policy_allow_count",
            "consequential_count",
        ):
            value = getattr(self, field_name)
            if not 0 <= value <= 0xFF:
                raise LogosError(f"{field_name} must fit in 8 bits, got {value}")
        if self.valid_count + self.invalid_count != self.span_length:
            raise LogosError("valid_count + invalid_count must equal span_length")
        if not 0 <= self.ordered_root <= MASK64:
            raise LogosError("ordered_root must fit in 64 bits")

    @property
    def all_valid(self) -> bool:
        return self.invalid_count == 0

    @property
    def fail_closed(self) -> bool:
        return self.invalid_count > 0

    def encode_128(self) -> int:
        """Pack the bounded summary into exactly 128 logical bits."""

        lower_fields = (
            self.span_length,
            self.valid_count,
            self.invalid_count,
            self.transition_count,
            self.discontinuity_count,
            self.target_count,
            self.policy_allow_count,
            self.consequential_count,
        )
        lower = 0
        for value in lower_fields:
            lower = (lower << 8) | value
        encoded = (self.ordered_root << 64) | lower
        if encoded.bit_length() > LOGOS_WORD_BITS:
            raise AssertionError("LOGOS word exceeded 128 bits")
        return encoded


@dataclass(frozen=True, slots=True)
class LogosLeaf:
    lane_index: int
    input_bundle: int
    payload: int
    word: LogosWord


def _rotl64(value: int, shift: int) -> int:
    shift &= 63
    value &= MASK64
    if shift == 0:
        return value
    return ((value << shift) & MASK64) | (value >> (64 - shift))


def _mix64(value: int) -> int:
    """SplitMix64 finalizer; deterministic and inexpensive in hardware models."""

    value &= MASK64
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & MASK64
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & MASK64
    value ^= value >> 31
    return value & MASK64


def pack_tx1_result(result: Tx1Result) -> int:
    """Pack the BARDO-TX1 semantic result into the existing 23-bit layout."""

    lower, middle, upper = result.settled_lines
    settled = lower | (middle << 3) | (upper << 6)
    payload = (
        result.trigram_index
        | (int(result.policy_allow) << 8)
        | (settled << 9)
        | (int(result.any_discontinuous) << 18)
        | (int(result.any_transition) << 19)
        | (result.target_count << 20)
        | (int(result.valid) << 22)
    )
    if not 0 <= payload < (1 << TX1_RESULT_BITS):
        raise LogosError(f"TX1 payload exceeded {TX1_RESULT_BITS} bits")
    return payload


def _leaf_root(*, lane_index: int, input_bundle: int, payload: int) -> int:
    return _mix64(
        LEAF_DOMAIN
        ^ _mix64(lane_index + 1)
        ^ _rotl64(_mix64(input_bundle), 17)
        ^ _rotl64(_mix64(payload), 41)
    )


def make_leaf(lane_index: int, input_bundle: int) -> LogosLeaf:
    if not 0 <= lane_index < LOGOS_MAX_LANES:
        raise LogosError(
            f"lane_index must be in [0, {LOGOS_MAX_LANES - 1}], got {lane_index}"
        )
    if not 0 <= input_bundle <= 0x1FF:
        raise LogosError(f"input_bundle must be a 9-bit integer, got {input_bundle}")

    result = evaluate_trigram(unpack_trigram_lines(input_bundle))
    payload = pack_tx1_result(result)
    consequential = int(
        (not result.valid)
        or result.any_transition
        or result.any_discontinuous
        or result.policy_allow
    )
    word = LogosWord(
        span_start=lane_index,
        span_length=1,
        valid_count=int(result.valid),
        invalid_count=int(not result.valid),
        transition_count=int(result.any_transition),
        discontinuity_count=int(result.any_discontinuous),
        target_count=result.target_count,
        policy_allow_count=int(result.policy_allow),
        consequential_count=consequential,
        ordered_root=_leaf_root(
            lane_index=lane_index,
            input_bundle=input_bundle,
            payload=payload,
        ),
    )
    return LogosLeaf(
        lane_index=lane_index,
        input_bundle=input_bundle,
        payload=payload,
        word=word,
    )


def make_leaves(bundles: Sequence[int]) -> tuple[LogosLeaf, ...]:
    if not bundles:
        raise LogosError("at least one lane is required")
    if len(bundles) > LOGOS_MAX_LANES:
        raise LogosError(
            f"at most {LOGOS_MAX_LANES} lanes are supported by the 128-bit word"
        )
    return tuple(make_leaf(index, bundle) for index, bundle in enumerate(bundles))


def merge_words(left: LogosWord, right: LogosWord) -> LogosWord:
    """Merge two adjacent spans with an ordered, non-commutative root."""

    expected_right_start = left.span_start + left.span_length
    if right.span_start != expected_right_start:
        raise LogosError(
            "LOGOS merge requires contiguous ordered spans: "
            f"left ends at {expected_right_start}, right starts at {right.span_start}"
        )

    span_length = left.span_length + right.span_length
    if span_length > LOGOS_MAX_LANES:
        raise LogosError(
            f"merged span exceeds {LOGOS_MAX_LANES} lanes: {span_length}"
        )

    root = _mix64(
        NODE_DOMAIN
        ^ _rotl64(left.ordered_root, 7)
        ^ _rotl64(right.ordered_root, 37)
        ^ _mix64(left.span_start)
        ^ _rotl64(_mix64(left.span_length), 13)
        ^ _rotl64(_mix64(right.span_length), 29)
    )
    return LogosWord(
        span_start=left.span_start,
        span_length=span_length,
        valid_count=left.valid_count + right.valid_count,
        invalid_count=left.invalid_count + right.invalid_count,
        transition_count=left.transition_count + right.transition_count,
        discontinuity_count=left.discontinuity_count + right.discontinuity_count,
        target_count=left.target_count + right.target_count,
        policy_allow_count=left.policy_allow_count + right.policy_allow_count,
        consequential_count=left.consequential_count + right.consequential_count,
        ordered_root=root,
    )


def linear_logos(leaves: Sequence[LogosLeaf]) -> LogosWord:
    """Sequential left fold: order-sensitive, but O(n) dependency depth."""

    if not leaves:
        raise LogosError("at least one leaf is required")
    root = leaves[0].word
    for leaf in leaves[1:]:
        root = merge_words(root, leaf.word)
    return root


def balanced_logos(leaves: Sequence[LogosLeaf]) -> LogosWord:
    """Canonical adjacent-pair tree: O(log n) parallel dependency depth."""

    if not leaves:
        raise LogosError("at least one leaf is required")
    level = [leaf.word for leaf in leaves]
    while len(level) > 1:
        next_level: list[LogosWord] = []
        pair_limit = len(level) - (len(level) % 2)
        for index in range(0, pair_limit, 2):
            next_level.append(merge_words(level[index], level[index + 1]))
        if len(level) % 2:
            next_level.append(level[-1])
        level = next_level
    return level[0]


def flat_xor_signature(leaves: Iterable[LogosLeaf]) -> int:
    """Current commutative blind-spot baseline: lane permutations collide."""

    signature = 0
    found = False
    for leaf in leaves:
        signature ^= leaf.payload
        found = True
    if not found:
        raise LogosError("at least one leaf is required")
    return signature


def materialized_payloads(leaves: Iterable[LogosLeaf]) -> tuple[int, ...]:
    return tuple(leaf.payload for leaf in leaves)


def tree_depth(lane_count: int) -> int:
    if lane_count <= 0:
        raise LogosError("lane_count must be > 0")
    return math.ceil(math.log2(lane_count)) if lane_count > 1 else 0


def architecture_comparison(lane_count: int = LOGOS_MAX_LANES) -> dict[str, Any]:
    if not 1 <= lane_count <= LOGOS_MAX_LANES:
        raise LogosError(
            f"lane_count must be in [1, {LOGOS_MAX_LANES}], got {lane_count}"
        )
    full_result_bits = lane_count * TX1_RESULT_BITS
    return {
        "lane_count": lane_count,
        "full_result_bits_per_frame": full_result_bits,
        "logos_result_bits_per_frame": LOGOS_WORD_BITS,
        "output_reduction_ratio": full_result_bits / LOGOS_WORD_BITS,
        "output_bits_saved_fraction": 1.0 - LOGOS_WORD_BITS / full_result_bits,
        "flat_sequential_dependency_depth": lane_count,
        "balanced_tree_dependency_depth": tree_depth(lane_count),
        "tree_merge_nodes": lane_count - 1,
    }


def deterministic_frame(frame_index: int, lane_count: int) -> tuple[int, ...]:
    if frame_index < 0:
        raise LogosError("frame_index must be >= 0")
    if not 1 <= lane_count <= LOGOS_MAX_LANES:
        raise LogosError(
            f"lane_count must be in [1, {LOGOS_MAX_LANES}], got {lane_count}"
        )
    return tuple(
        (
            frame_index * 131
            + lane * 197
            + (frame_index >> 2) * 29
            + lane * lane * 3
            + 17
        )
        & 0x1FF
        for lane in range(lane_count)
    )


def _time_reducer(
    name: str,
    frames: Sequence[tuple[LogosLeaf, ...]],
    reducer: Any,
    *,
    repeats: int,
) -> dict[str, Any]:
    samples: list[float] = []
    sink = 0
    lane_count = len(frames[0])
    total_lanes = len(frames) * lane_count

    for _ in range(repeats):
        started = time.perf_counter_ns()
        local_sink = 0
        for leaves in frames:
            value = reducer(leaves)
            if isinstance(value, LogosWord):
                local_sink ^= value.encode_128()
            elif isinstance(value, tuple):
                local_sink ^= value[0] if value else 0
                local_sink ^= value[-1] if value else 0
            else:
                local_sink ^= int(value)
        elapsed_seconds = (time.perf_counter_ns() - started) / 1_000_000_000.0
        samples.append(elapsed_seconds)
        sink ^= local_sink

    median_seconds = statistics.median(samples)
    return {
        "name": name,
        "frames": len(frames),
        "lanes_per_frame": lane_count,
        "repeats": repeats,
        "median_seconds": median_seconds,
        "frames_per_second": len(frames) / median_seconds,
        "lanes_per_second": total_lanes / median_seconds,
        "sample_seconds": samples,
        "sink": sink,
    }


def run_software_benchmark(
    *,
    lane_count: int = LOGOS_MAX_LANES,
    frames: int = 256,
    repeats: int = 5,
) -> dict[str, Any]:
    """Compare reducers over identical pre-evaluated leaves.

    Pre-evaluation deliberately isolates reduction-network overhead. The
    figures are Python software measurements and cannot support a hardware or
    CPU-competition claim.
    """

    if frames <= 0:
        raise LogosError("frames must be > 0")
    if repeats <= 0:
        raise LogosError("repeats must be > 0")

    prepared = tuple(
        make_leaves(deterministic_frame(frame_index, lane_count))
        for frame_index in range(frames)
    )

    reducers = (
        ("full_materialization", materialized_payloads),
        ("flat_xor", flat_xor_signature),
        ("linear_ordered_logos", linear_logos),
        ("balanced_ordered_logos", balanced_logos),
    )
    measurements = [
        _time_reducer(name, prepared, reducer, repeats=repeats)
        for name, reducer in reducers
    ]

    by_name = {entry["name"]: entry for entry in measurements}
    balanced = by_name["balanced_ordered_logos"]["lanes_per_second"]
    flat_xor = by_name["flat_xor"]["lanes_per_second"]
    materialized = by_name["full_materialization"]["lanes_per_second"]

    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "boundary": (
            "Python reduction-only benchmark over identical pre-evaluated BARDO-TX1 "
            "leaves; not FPGA evidence and not a CPU-competition claim"
        ),
        "architecture": architecture_comparison(lane_count),
        "measurements": measurements,
        "relative": {
            "balanced_vs_flat_xor": balanced / flat_xor,
            "balanced_vs_full_materialization": balanced / materialized,
        },
    }


def render_benchmark_markdown(report: Mapping[str, Any]) -> str:
    architecture = report["architecture"]
    rows = [
        "# BARDO LOGOS tree comparison",
        "",
        f"**Boundary:** {report['boundary']}",
        "",
        "## Architectural comparison",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Lanes | {architecture['lane_count']} |",
        f"| Full TX1 output | {architecture['full_result_bits_per_frame']} bits/frame |",
        f"| LOGOS root | {architecture['logos_result_bits_per_frame']} bits/frame |",
        f"| Output reduction | {architecture['output_reduction_ratio']:.3f}× |",
        f"| Output bits removed | {architecture['output_bits_saved_fraction']:.2%} |",
        f"| Flat dependency depth | {architecture['flat_sequential_dependency_depth']} |",
        f"| Balanced-tree depth | {architecture['balanced_tree_dependency_depth']} |",
        f"| Tree merge nodes | {architecture['tree_merge_nodes']} |",
        "",
        "## Python reduction-only measurements",
        "",
        "| Reducer | Median s | Mlanes/s |",
        "| --- | ---: | ---: |",
    ]
    for entry in report["measurements"]:
        rows.append(
            f"| {entry['name']} | {entry['median_seconds']:.6f} | "
            f"{entry['lanes_per_second'] / 1_000_000.0:.3f} |"
        )
    rows.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `flat_xor` is a speed baseline but is permutation-blind.",
            "- ordered LOGOS variants bind lane identity and input identity.",
            "- the balanced tree reduces parallel dependency depth; Python object "
            "overhead is expected to make it slower in software.",
            "- only RTL synthesis and a physical host-fed benchmark may establish "
            "a hardware efficiency claim.",
            "",
        ]
    )
    return "\n".join(rows)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark flat and hierarchical BARDO LOGOS reducers."
    )
    parser.add_argument("--lanes", type=int, default=LOGOS_MAX_LANES)
    parser.add_argument("--frames", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = run_software_benchmark(
            lane_count=args.lanes,
            frames=args.frames,
            repeats=args.repeats,
        )
    except LogosError as exc:
        print(f"logos_benchmark=fail reason={exc}")
        return 1

    if args.json_output is not None:
        _write_text(
            args.json_output,
            json.dumps(report, indent=2, sort_keys=True) + "\n",
        )
    if args.markdown_output is not None:
        _write_text(args.markdown_output, render_benchmark_markdown(report))

    architecture = report["architecture"]
    print("logos_benchmark=pass")
    print(f"lanes={architecture['lane_count']}")
    print(f"output_reduction_ratio={architecture['output_reduction_ratio']:.6f}")
    print(f"balanced_tree_depth={architecture['balanced_tree_dependency_depth']}")
    for entry in report["measurements"]:
        print(
            f"{entry['name']}_mlanes_s="
            f"{entry['lanes_per_second'] / 1_000_000.0:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
