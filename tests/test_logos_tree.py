from __future__ import annotations

import itertools
import math

import pytest

from bardocompute.logos_tree import (
    LOGOS_WORD_BITS,
    TX1_RESULT_BITS,
    LogosError,
    architecture_comparison,
    balanced_logos,
    deterministic_frame,
    flat_xor_signature,
    linear_logos,
    make_leaves,
    merge_words,
    run_software_benchmark,
)


def _aggregate_tuple(word):
    return (
        word.span_length,
        word.valid_count,
        word.invalid_count,
        word.transition_count,
        word.discontinuity_count,
        word.target_count,
        word.policy_allow_count,
        word.consequential_count,
    )


def test_balanced_and_linear_reducers_preserve_same_bounded_facts() -> None:
    for frame_index in range(64):
        leaves = make_leaves(deterministic_frame(frame_index, 71))
        linear = linear_logos(leaves)
        balanced = balanced_logos(leaves)

        assert _aggregate_tuple(linear) == _aggregate_tuple(balanced)
        assert linear.encode_128().bit_length() <= LOGOS_WORD_BITS
        assert balanced.encode_128().bit_length() <= LOGOS_WORD_BITS
        assert balanced.span_length == 71
        assert balanced.valid_count + balanced.invalid_count == 71


def test_ordered_tree_detects_every_pairwise_lane_swap_for_71_lanes() -> None:
    bundles = list(range(71))
    baseline = balanced_logos(make_leaves(bundles)).ordered_root

    for left in range(71):
        for right in range(left + 1, 71):
            swapped = bundles.copy()
            swapped[left], swapped[right] = swapped[right], swapped[left]
            assert balanced_logos(make_leaves(swapped)).ordered_root != baseline


def test_commutative_xor_collides_but_ordered_tree_separates_all_7_lane_permutations() -> None:
    bundles = deterministic_frame(7, 7)
    xor_values = set()
    roots = set()

    for permutation in itertools.permutations(bundles):
        leaves = make_leaves(permutation)
        xor_values.add(flat_xor_signature(leaves))
        roots.add(balanced_logos(leaves).ordered_root)

    assert len(xor_values) == 1
    assert len(roots) == math.factorial(7)


def test_ordered_root_detects_each_single_input_bit_change() -> None:
    baseline_bundles = list(deterministic_frame(0, 71))
    baseline_root = balanced_logos(make_leaves(baseline_bundles)).ordered_root

    for lane in range(71):
        for bit in range(9):
            mutated = baseline_bundles.copy()
            mutated[lane] ^= 1 << bit
            assert balanced_logos(make_leaves(mutated)).ordered_root != baseline_root


def test_fail_closed_invalid_lanes_propagate_to_root() -> None:
    bundles = [0] * 8
    bundles[3] = 0b001_000_000
    root = balanced_logos(make_leaves(bundles))

    assert root.invalid_count == 1
    assert root.valid_count == 7
    assert root.fail_closed is True


def test_tree_merge_rejects_noncontiguous_spans() -> None:
    left = make_leaves([0])[0].word
    right = make_leaves([0, 2])[1].word

    with pytest.raises(LogosError, match="contiguous"):
        merge_words(right, left)


def test_71_lane_architecture_reduces_output_and_dependency_depth() -> None:
    report = architecture_comparison(71)

    assert report["full_result_bits_per_frame"] == 71 * TX1_RESULT_BITS == 1633
    assert report["logos_result_bits_per_frame"] == 128
    assert report["output_reduction_ratio"] == pytest.approx(12.7578125)
    assert report["output_bits_saved_fraction"] == pytest.approx(
        1.0 - 128 / 1633
    )
    assert report["flat_sequential_dependency_depth"] == 71
    assert report["balanced_tree_dependency_depth"] == 7
    assert report["tree_merge_nodes"] == 70


def test_benchmark_is_explicitly_software_only_and_reports_all_reducers() -> None:
    report = run_software_benchmark(lane_count=8, frames=8, repeats=2)

    assert "not FPGA evidence" in report["boundary"]
    assert [entry["name"] for entry in report["measurements"]] == [
        "full_materialization",
        "flat_xor",
        "linear_ordered_logos",
        "balanced_ordered_logos",
    ]
    assert all(entry["lanes_per_second"] > 0 for entry in report["measurements"])
