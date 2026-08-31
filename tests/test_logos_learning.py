from __future__ import annotations

import pytest

from bardocompute.logos_learning import (
    FEATURE_DIM,
    HYBRID_LOGICAL_BITS,
    LOGOS_LOGICAL_BITS,
    RAW_LOGICAL_BITS,
    TRAINABLE_PARAMETERS,
    SplitMix64Rng,
    encode_hybrid,
    encode_logos,
    encode_raw,
    frame_stats,
    generate_global_dataset,
    generate_local_pair,
    run_learning_benchmark,
    train_model,
)


def test_splitmix64_sequence_is_cross_version_frozen() -> None:
    rng = SplitMix64Rng(123)
    assert [rng.next_u64() for _ in range(4)] == [
        0xB4DC9BD462DE412B,
        0xFA023CE9F06FB77C,
        0xDC12D311D371CBE8,
        0xAFD2040C909881FF,
    ]


def test_global_dataset_is_balanced_and_reproducible() -> None:
    first = generate_global_dataset(32, 77)
    second = generate_global_dataset(32, 77)

    assert sum(sample.label for sample in first) == 16
    assert first == second


def test_local_pair_falsifies_global_summary_sufficiency() -> None:
    positive, negative = generate_local_pair(SplitMix64Rng(91))

    assert positive.label == 1
    assert negative.label == 0
    assert frame_stats(positive.results) == frame_stats(negative.results)
    assert encode_logos(positive) == encode_logos(negative)
    assert encode_raw(positive) != encode_raw(negative)
    assert encode_hybrid(positive) != encode_hybrid(negative)


def test_all_representations_share_one_trainable_budget() -> None:
    assert FEATURE_DIM == 128
    assert TRAINABLE_PARAMETERS == 129
    assert RAW_LOGICAL_BITS == 71 * 23 == 1633
    assert LOGOS_LOGICAL_BITS == 128
    assert HYBRID_LOGICAL_BITS == 256

    dataset = generate_global_dataset(16, 101)
    for encoder in (encode_raw, encode_logos, encode_hybrid):
        features = tuple(encoder(sample) for sample in dataset)
        model = train_model(
            features,
            tuple(sample.label for sample in dataset),
            seed=3,
            epochs=2,
        )
        assert len(model.weights) == FEATURE_DIM


def test_small_benchmark_keeps_claim_boundary_explicit() -> None:
    report = run_learning_benchmark(
        train_sizes=(32, 64),
        seeds=(11,),
        test_size=128,
        epochs=3,
    )

    assert "controlled synthetic" in report["boundary"]
    assert report["model"]["trainable_parameters"] == 129
    assert report["tasks"]["localized_escalation"][
        "test_positive_fraction"
    ] == pytest.approx(0.5)
    # The full release gate is intentionally calibrated to the frozen default
    # benchmark, not this small smoke run.
    assert isinstance(report["gate"]["passed"], bool)
