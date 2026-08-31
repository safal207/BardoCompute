"""Controlled learning-efficiency benchmark for BARDO LOGOS representations.

The benchmark compares three fixed encoders over identical pre-evaluated
BARDO-TX1 lane results:

* RAW: all 71 per-lane semantic results (1,633 logical bits);
* LOGOS: one 128-bit global semantic summary;
* HYBRID: the LOGOS summary plus four bounded witness records (256 bits).

Every learner is the same 128-feature averaged passive-aggressive linear model
with 129 trainable parameters including bias. The data are synthetic and the
result is a representation/sample-efficiency experiment, not evidence of
physical FPGA performance or general learning superiority.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .hardware_contract import Tx1Result, evaluate_trigram, unpack_trigram_lines
from .logos_tree import LOGOS_MAX_LANES, LOGOS_WORD_BITS, TX1_RESULT_BITS

SCHEMA_VERSION = 1
LANES = LOGOS_MAX_LANES
FEATURE_DIM = 128
TRAINABLE_PARAMETERS = FEATURE_DIM + 1
WITNESS_COUNT = 4
WITNESS_RECORD_BITS = 32
TARGET_BALANCED_ACCURACY = 0.80
DEFAULT_TRAIN_SIZES = (64, 128, 256, 512, 1024)
DEFAULT_SEEDS = (11, 29, 47)
DEFAULT_TEST_SIZE = 1536
DEFAULT_EPOCHS = 10
RAW_LOGICAL_BITS = LANES * TX1_RESULT_BITS
LOGOS_LOGICAL_BITS = LOGOS_WORD_BITS
HYBRID_LOGICAL_BITS = LOGOS_WORD_BITS + WITNESS_COUNT * WITNESS_RECORD_BITS
MASK64 = (1 << 64) - 1

FeatureVector = tuple[tuple[int, float], ...]


class LearningError(ValueError):
    """Raised when a benchmark input or report violates its contract."""


class SplitMix64Rng:
    """Small cross-version deterministic PRNG used by datasets and shuffles."""

    def __init__(self, seed: int) -> None:
        self.state = seed & MASK64

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
        return (value ^ (value >> 31)) & MASK64

    def random(self) -> float:
        return (self.next_u64() >> 11) * (1.0 / (1 << 53))

    def uniform(self, lower: float, upper: float) -> float:
        return lower + (upper - lower) * self.random()

    def randbelow(self, upper: int) -> int:
        if upper <= 0:
            raise LearningError("randbelow upper bound must be > 0")
        limit = ((1 << 64) // upper) * upper
        while True:
            value = self.next_u64()
            if value < limit:
                return value % upper

    def choice(self, values: Sequence[int]) -> int:
        if not values:
            raise LearningError("cannot choose from an empty sequence")
        return values[self.randbelow(len(values))]

    def shuffle(self, values: list[Any]) -> None:
        for index in range(len(values) - 1, 0, -1):
            other = self.randbelow(index + 1)
            values[index], values[other] = values[other], values[index]


@dataclass(frozen=True, slots=True)
class FrameStats:
    valid_count: int
    invalid_count: int
    transition_count: int
    discontinuity_count: int
    target_count: int
    policy_allow_count: int
    consequential_count: int


@dataclass(frozen=True, slots=True)
class LearningSample:
    results: tuple[Tx1Result, ...]
    label: int
    focus_lane: int | None = None

    def __post_init__(self) -> None:
        if len(self.results) != LANES:
            raise LearningError(f"expected {LANES} lane results")
        if self.label not in {0, 1}:
            raise LearningError("binary label must be 0 or 1")
        if self.focus_lane is not None and not 0 <= self.focus_lane < LANES:
            raise LearningError("focus_lane is outside the frame")


@dataclass(frozen=True, slots=True)
class LinearModel:
    weights: tuple[float, ...]
    bias: float

    def __post_init__(self) -> None:
        if len(self.weights) != FEATURE_DIM:
            raise LearningError("linear model has the wrong feature width")


def _line_code(
    rng: SplitMix64Rng,
    *,
    target_bias: float,
    transition_rate: float,
    discontinuity_rate: float,
) -> int:
    target = int(rng.random() < target_bias)
    transition = rng.random() < transition_rate
    source = 1 - target if transition else target
    discontinuity = int(transition and rng.random() < discontinuity_rate)
    return (source << 2) | (target << 1) | discontinuity


def _generate_bundles(
    rng: SplitMix64Rng,
    *,
    target_bias: float,
    transition_rate: float,
    discontinuity_rate: float,
    invalid_rate: float = 0.0,
) -> list[int]:
    bundles: list[int] = []
    for _lane in range(LANES):
        lines = [
            _line_code(
                rng,
                target_bias=target_bias,
                transition_rate=transition_rate,
                discontinuity_rate=discontinuity_rate,
            )
            for _ in range(3)
        ]
        if rng.random() < invalid_rate:
            lines[rng.randbelow(3)] = rng.choice((0b001, 0b111))
        bundles.append(lines[0] | (lines[1] << 3) | (lines[2] << 6))
    return bundles


def _evaluate_bundles(bundles: Sequence[int]) -> tuple[Tx1Result, ...]:
    if len(bundles) != LANES:
        raise LearningError(f"expected {LANES} bundles")
    return tuple(evaluate_trigram(unpack_trigram_lines(bundle)) for bundle in bundles)


def frame_stats(results: Sequence[Tx1Result]) -> FrameStats:
    if len(results) != LANES:
        raise LearningError(f"expected {LANES} lane results")
    return FrameStats(
        valid_count=sum(result.valid for result in results),
        invalid_count=sum(not result.valid for result in results),
        transition_count=sum(result.any_transition for result in results),
        discontinuity_count=sum(result.any_discontinuous for result in results),
        target_count=sum(result.target_count for result in results),
        policy_allow_count=sum(result.policy_allow for result in results),
        consequential_count=sum(
            (not result.valid)
            or result.any_transition
            or result.any_discontinuous
            or result.policy_allow
            for result in results
        ),
    )


def _global_teacher_score(stats: FrameStats, noise: float) -> float:
    """Controlled downstream outcome using bounded semantic sufficient statistics."""

    return (
        1.3
        - 0.9 * stats.invalid_count
        - 0.055 * stats.discontinuity_count
        + 0.045 * stats.policy_allow_count
        + 0.012 * stats.transition_count
        - 0.012 * abs(stats.target_count - 106)
        + noise
    )


def generate_global_dataset(size: int, seed: int) -> tuple[LearningSample, ...]:
    """Balanced synthetic recovery-outcome data with no stored label feature."""

    if size <= 0 or size % 2:
        raise LearningError("dataset size must be a positive even integer")
    rng = SplitMix64Rng(seed)
    positive: list[LearningSample] = []
    negative: list[LearningSample] = []
    quota = size // 2
    attempts = 0
    while len(positive) < quota or len(negative) < quota:
        attempts += 1
        if attempts > size * 1000:
            raise LearningError("could not balance the global dataset")
        invalid_rate = 0.0 if rng.random() < 0.72 else rng.uniform(0.0, 0.05)
        bundles = _generate_bundles(
            rng,
            target_bias=rng.uniform(0.2, 0.8),
            transition_rate=rng.uniform(0.05, 0.8),
            discontinuity_rate=rng.uniform(0.0, 0.5),
            invalid_rate=invalid_rate,
        )
        results = _evaluate_bundles(bundles)
        stats = frame_stats(results)
        score = _global_teacher_score(stats, (rng.random() - 0.5) * 0.3)
        label = int(score > 1.0)
        sample = LearningSample(results=results, label=label)
        if label and len(positive) < quota:
            positive.append(sample)
        elif not label and len(negative) < quota:
            negative.append(sample)

    dataset = [*positive, *negative]
    rng.shuffle(dataset)
    return tuple(dataset)


def generate_local_pair(rng: SplitMix64Rng) -> tuple[LearningSample, LearningSample]:
    """Return paired samples with identical global facts but different fault location."""

    bundles = _generate_bundles(
        rng,
        target_bias=rng.uniform(0.35, 0.65),
        transition_rate=rng.uniform(0.05, 0.25),
        discontinuity_rate=rng.uniform(0.0, 0.08),
    )
    critical_lanes = tuple(range(0, 18)) + tuple(range(53, LANES))
    ordinary_lanes = tuple(range(18, 53))
    critical_lane = rng.choice(critical_lanes)
    ordinary_lane = rng.choice(ordinary_lanes)

    # Equalize the two candidate positions, then move the same invalid witness
    # between them. The pair has the same multiset of results and exactly the
    # same global LOGOS semantic counters; only ordered location differs.
    bundles[critical_lane] = 0
    bundles[ordinary_lane] = 0
    invalid_lines = [0b010, 0b110, 0b000]
    invalid_lines[rng.randbelow(3)] = rng.choice((0b001, 0b111))
    invalid_bundle = (
        invalid_lines[0] | (invalid_lines[1] << 3) | (invalid_lines[2] << 6)
    )

    positive_bundles = bundles.copy()
    negative_bundles = bundles.copy()
    positive_bundles[critical_lane] = invalid_bundle
    negative_bundles[ordinary_lane] = invalid_bundle
    return (
        LearningSample(
            results=_evaluate_bundles(positive_bundles),
            label=1,
            focus_lane=critical_lane,
        ),
        LearningSample(
            results=_evaluate_bundles(negative_bundles),
            label=0,
            focus_lane=ordinary_lane,
        ),
    )


def generate_local_dataset(size: int, seed: int) -> tuple[LearningSample, ...]:
    """Balanced location-sensitive escalation task with paired global summaries."""

    if size <= 0 or size % 2:
        raise LearningError("dataset size must be a positive even integer")
    rng = SplitMix64Rng(seed)
    dataset: list[LearningSample] = []
    for _ in range(size // 2):
        dataset.extend(generate_local_pair(rng))
    rng.shuffle(dataset)
    return tuple(dataset)


def _fnv1a64(text: str) -> int:
    value = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * 0x100000001B3) & MASK64
    return value


def _add_hashed(
    values: list[float],
    token: str,
    weight: float,
    *,
    start: int,
    width: int,
) -> None:
    digest = _fnv1a64(token)
    sign = 1.0 if ((digest >> 63) & 1) == 0 else -1.0
    values[start + digest % width] += sign * weight


def _normalize_dense(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        return [0.0 for _ in values]
    return [value / norm for value in values]


def _sparsify(values: Sequence[float]) -> FeatureVector:
    return tuple((index, value) for index, value in enumerate(values) if value != 0.0)


def encode_raw(sample: LearningSample) -> FeatureVector:
    """Fixed 128-feature projection of all 71 per-lane semantic results."""

    values = [0.0] * FEATURE_DIM
    for lane, result in enumerate(sample.results):
        # Preserve the lane-validity axis directly; hash the remaining full
        # result categories into the remaining fixed model budget.
        values[lane] = 1.0 if result.valid else -1.0
        _add_hashed(
            values,
            f"lane:{lane}:transition:{int(result.any_transition)}",
            0.7,
            start=71,
            width=57,
        )
        _add_hashed(
            values,
            f"lane:{lane}:discontinuity:{int(result.any_discontinuous)}",
            0.7,
            start=71,
            width=57,
        )
        _add_hashed(
            values,
            f"lane:{lane}:policy:{int(result.policy_allow)}",
            0.7,
            start=71,
            width=57,
        )
        _add_hashed(
            values,
            f"lane:{lane}:targets:{result.target_count}",
            0.5,
            start=71,
            width=57,
        )
        _add_hashed(
            values,
            f"lane:{lane}:index_bin:{result.trigram_index // 18}",
            0.35,
            start=71,
            width=57,
        )
    return _sparsify(_normalize_dense(values))


def _global_block(sample: LearningSample) -> list[float]:
    stats = frame_stats(sample.results)
    values = [0.0] * 48
    numeric = (
        stats.valid_count / LANES,
        stats.invalid_count / LANES,
        stats.transition_count / LANES,
        stats.discontinuity_count / LANES,
        stats.target_count / (3 * LANES),
        stats.policy_allow_count / LANES,
        stats.consequential_count / LANES,
        stats.policy_allow_count / max(1, stats.transition_count),
        stats.discontinuity_count / max(1, stats.transition_count),
        abs(stats.target_count - 106) / (3 * LANES),
    )
    for index, value in enumerate(numeric):
        values[index] = value

    for name, value, maximum in (
        ("invalid", stats.invalid_count, 8),
        ("discontinuity", stats.discontinuity_count, LANES),
        ("policy", stats.policy_allow_count, LANES),
        ("transition", stats.transition_count, LANES),
        ("targets", stats.target_count, 3 * LANES),
    ):
        bucket = int(8 * value / (maximum + 1))
        _add_hashed(
            values,
            f"{name}:bucket:{bucket}",
            0.5,
            start=16,
            width=32,
        )
    return _normalize_dense(values)


def encode_logos(sample: LearningSample) -> FeatureVector:
    """Learn from semantic counters; the ordered root remains integrity-only."""

    global_values = _global_block(sample)
    return _sparsify([*global_values, *([0.0] * 80)])


def _severity(result: Tx1Result) -> int:
    return (
        100 * int(not result.valid)
        + 20 * int(result.any_discontinuous)
        + 10 * int(result.any_transition)
        + 5 * int(result.policy_allow)
        + result.target_count
    )


def _settled_value(result: Tx1Result) -> int:
    lower, middle, upper = result.settled_lines
    return lower | (middle << 3) | (upper << 6)


def _witness_block(sample: LearningSample) -> list[float]:
    values = [0.0] * 80
    witness_lanes = sorted(
        range(LANES),
        key=lambda lane: (_severity(sample.results[lane]), -lane),
        reverse=True,
    )[:WITNESS_COUNT]

    for slot, lane in enumerate(witness_lanes):
        result = sample.results[lane]
        base = slot * 10
        lane_position = lane / (LANES - 1)
        witness_values = (
            lane_position,
            abs(lane - (LANES - 1) / 2) / ((LANES - 1) / 2),
            float(not result.valid),
            float(result.any_transition),
            float(result.any_discontinuous),
            float(result.policy_allow),
            result.target_count / 3,
            result.trigram_index / 215 if result.valid else 0.0,
            _settled_value(result) / 511,
            _severity(result) / 100,
        )
        for offset, value in enumerate(witness_values):
            values[base + offset] = value
        _add_hashed(
            values,
            (
                f"slot:{slot}:lane:{lane}:valid:{int(result.valid)}:"
                f"targets:{result.target_count}"
            ),
            0.25,
            start=40,
            width=40,
        )
    return _normalize_dense(values)


def encode_hybrid(sample: LearningSample) -> FeatureVector:
    global_values = _global_block(sample)
    witness_values = _witness_block(sample)
    global_weight = 0.9
    witness_weight = math.sqrt(1.0 - global_weight * global_weight)
    return _sparsify(
        [
            *(global_weight * value for value in global_values),
            *(witness_weight * value for value in witness_values),
        ]
    )


ENCODERS: Mapping[str, Callable[[LearningSample], FeatureVector]] = {
    "raw": encode_raw,
    "logos": encode_logos,
    "hybrid": encode_hybrid,
}

REPRESENTATIONS: Mapping[str, Mapping[str, Any]] = {
    "raw": {
        "logical_bits_per_example": RAW_LOGICAL_BITS,
        "description": "all 71 BARDO-TX1 semantic lane results",
    },
    "logos": {
        "logical_bits_per_example": LOGOS_LOGICAL_BITS,
        "description": "one global bounded semantic summary; root used for integrity only",
    },
    "hybrid": {
        "logical_bits_per_example": HYBRID_LOGICAL_BITS,
        "description": "global LOGOS summary plus four 32-bit witness records",
    },
}


def _featurize(
    dataset: Sequence[LearningSample], representation: str
) -> tuple[tuple[FeatureVector, ...], tuple[int, ...], float]:
    encoder = ENCODERS.get(representation)
    if encoder is None:
        raise LearningError(f"unknown representation {representation!r}")
    started = time.perf_counter()
    features = tuple(encoder(sample) for sample in dataset)
    elapsed = time.perf_counter() - started
    labels = tuple(sample.label for sample in dataset)
    return features, labels, elapsed


def train_model(
    features: Sequence[FeatureVector],
    labels: Sequence[int],
    *,
    seed: int,
    epochs: int = DEFAULT_EPOCHS,
    aggressiveness: float = 1.0,
) -> LinearModel:
    """Train an exactly averaged passive-aggressive linear classifier."""

    if len(features) != len(labels) or not features:
        raise LearningError("features and labels must be non-empty and aligned")
    if epochs <= 0 or aggressiveness <= 0.0:
        raise LearningError("epochs and aggressiveness must be positive")

    weights = [0.0] * FEATURE_DIM
    bias = 0.0
    totals = [0.0] * FEATURE_DIM
    timestamps = [0] * FEATURE_DIM
    total_bias = 0.0
    bias_timestamp = 0
    step = 0
    order = list(range(len(features)))
    rng = SplitMix64Rng(seed)

    for _epoch in range(epochs):
        rng.shuffle(order)
        for sample_index in order:
            step += 1
            expected = 1.0 if labels[sample_index] else -1.0
            vector = features[sample_index]
            score = bias + sum(weights[index] * value for index, value in vector)
            loss = max(0.0, 1.0 - expected * score)
            if loss == 0.0:
                continue
            squared_norm = 1.0 + sum(value * value for _index, value in vector)
            update = min(aggressiveness, loss / squared_norm)
            for index, value in vector:
                totals[index] += (step - timestamps[index]) * weights[index]
                timestamps[index] = step
                weights[index] += update * expected * value
            total_bias += (step - bias_timestamp) * bias
            bias_timestamp = step
            bias += update * expected

    for index in range(FEATURE_DIM):
        totals[index] += (step + 1 - timestamps[index]) * weights[index]
    total_bias += (step + 1 - bias_timestamp) * bias
    return LinearModel(
        weights=tuple(total / step for total in totals),
        bias=total_bias / step,
    )


def evaluate_model(
    model: LinearModel,
    features: Sequence[FeatureVector],
    labels: Sequence[int],
) -> dict[str, float]:
    if len(features) != len(labels) or not features:
        raise LearningError("evaluation features and labels must be aligned")
    predictions = [
        int(
            model.bias
            + sum(model.weights[index] * value for index, value in vector)
            >= 0.0
        )
        for vector in features
    ]
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        raise LearningError("evaluation data must contain both labels")
    true_positive_rate = sum(
        prediction == 1 and label == 1
        for prediction, label in zip(predictions, labels, strict=True)
    ) / positives
    true_negative_rate = sum(
        prediction == 0 and label == 0
        for prediction, label in zip(predictions, labels, strict=True)
    ) / negatives
    accuracy = sum(
        prediction == label
        for prediction, label in zip(predictions, labels, strict=True)
    ) / len(labels)
    return {
        "accuracy": accuracy,
        "balanced_accuracy": (true_positive_rate + true_negative_rate) / 2,
        "true_positive_rate": true_positive_rate,
        "true_negative_rate": true_negative_rate,
        "false_negative_rate": 1.0 - true_positive_rate,
    }


def _median(values: Sequence[float]) -> float:
    return float(statistics.median(values))


def _curve_point(
    *,
    train_examples: int,
    runs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    balanced = [float(run["metrics"]["balanced_accuracy"]) for run in runs]
    accuracy = [float(run["metrics"]["accuracy"]) for run in runs]
    training_seconds = [float(run["training_seconds"]) for run in runs]
    encoding_seconds = [float(run["encoding_seconds"]) for run in runs]
    return {
        "train_examples": train_examples,
        "median_balanced_accuracy": _median(balanced),
        "minimum_balanced_accuracy": min(balanced),
        "maximum_balanced_accuracy": max(balanced),
        "median_accuracy": _median(accuracy),
        "median_training_seconds": _median(training_seconds),
        "median_encoding_seconds": _median(encoding_seconds),
        "runs": list(runs),
    }


def _examples_to_target(curve: Sequence[Mapping[str, Any]]) -> int | None:
    for point in curve:
        if float(point["median_balanced_accuracy"]) >= TARGET_BALANCED_ACCURACY:
            return int(point["train_examples"])
    return None


def _point(curve: Sequence[Mapping[str, Any]], train_examples: int) -> Mapping[str, Any]:
    for point in curve:
        if int(point["train_examples"]) == train_examples:
            return point
    raise LearningError(f"curve has no point for {train_examples} examples")


def _task_report(
    *,
    name: str,
    description: str,
    generator: Callable[[int, int], tuple[LearningSample, ...]],
    test_seed: int,
    train_sizes: Sequence[int],
    seeds: Sequence[int],
    test_size: int,
    epochs: int,
) -> dict[str, Any]:
    test_dataset = generator(test_size, test_seed)
    test_features = {
        representation: _featurize(test_dataset, representation)[:2]
        for representation in ENCODERS
    }
    curves: dict[str, list[dict[str, Any]]] = {
        representation: [] for representation in ENCODERS
    }

    for train_examples in train_sizes:
        datasets = {
            seed: generator(train_examples, seed * 10_000 + train_examples)
            for seed in seeds
        }
        encoded = {
            (seed, representation): _featurize(dataset, representation)
            for seed, dataset in datasets.items()
            for representation in ENCODERS
        }
        for representation in ENCODERS:
            runs: list[dict[str, Any]] = []
            evaluation_features, evaluation_labels = test_features[representation]
            for seed in seeds:
                training_features, training_labels, encoding_seconds = encoded[
                    (seed, representation)
                ]
                started = time.perf_counter()
                model = train_model(
                    training_features,
                    training_labels,
                    seed=seed,
                    epochs=epochs,
                )
                training_seconds = time.perf_counter() - started
                runs.append(
                    {
                        "seed": seed,
                        "metrics": evaluate_model(
                            model, evaluation_features, evaluation_labels
                        ),
                        "encoding_seconds": encoding_seconds,
                        "training_seconds": training_seconds,
                    }
                )
            curves[representation].append(
                _curve_point(train_examples=train_examples, runs=runs)
            )

    sample_efficiency: dict[str, Any] = {}
    for representation, curve in curves.items():
        examples = _examples_to_target(curve)
        logical_bits = int(
            REPRESENTATIONS[representation]["logical_bits_per_example"]
        )
        sample_efficiency[representation] = {
            "target_balanced_accuracy": TARGET_BALANCED_ACCURACY,
            "examples_to_target": examples,
            "logical_training_bits_to_target": (
                examples * logical_bits if examples is not None else None
            ),
        }

    return {
        "name": name,
        "description": description,
        "test_examples": test_size,
        "test_positive_fraction": sum(sample.label for sample in test_dataset)
        / test_size,
        "curves": curves,
        "sample_efficiency": sample_efficiency,
    }


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    model = report["model"]
    representations = report["representations"]
    tasks = report["tasks"]
    global_task = tasks["global_recovery"]
    local_task = tasks["localized_escalation"]

    global_raw_64 = float(
        _point(global_task["curves"]["raw"], 64)["median_balanced_accuracy"]
    )
    global_logos_64 = float(
        _point(global_task["curves"]["logos"], 64)["median_balanced_accuracy"]
    )
    global_hybrid_64 = float(
        _point(global_task["curves"]["hybrid"], 64)["median_balanced_accuracy"]
    )
    local_logos_max = max(
        float(point["median_balanced_accuracy"])
        for point in local_task["curves"]["logos"]
    )
    local_raw_examples = local_task["sample_efficiency"]["raw"][
        "examples_to_target"
    ]
    local_hybrid_examples = local_task["sample_efficiency"]["hybrid"][
        "examples_to_target"
    ]
    local_logos_examples = local_task["sample_efficiency"]["logos"][
        "examples_to_target"
    ]
    local_raw_bits = local_task["sample_efficiency"]["raw"][
        "logical_training_bits_to_target"
    ]
    local_hybrid_bits = local_task["sample_efficiency"]["hybrid"][
        "logical_training_bits_to_target"
    ]

    checks = {
        "equal_trainable_parameter_budget": (
            int(model["trainable_parameters"]) == TRAINABLE_PARAMETERS
            and int(model["feature_dimension"]) == FEATURE_DIM
        ),
        "representation_widths_are_explicit": (
            int(representations["raw"]["logical_bits_per_example"])
            == RAW_LOGICAL_BITS
            and int(representations["logos"]["logical_bits_per_example"])
            == LOGOS_LOGICAL_BITS
            and int(representations["hybrid"]["logical_bits_per_example"])
            == HYBRID_LOGICAL_BITS
        ),
        "global_logos_beats_raw_at_64_examples": (
            global_logos_64 - global_raw_64 >= 0.08
        ),
        "global_hybrid_reaches_target_at_64_examples": (
            global_hybrid_64 >= TARGET_BALANCED_ACCURACY
        ),
        "global_logos_reaches_target_at_64_examples": (
            global_logos_64 >= TARGET_BALANCED_ACCURACY
        ),
        "local_global_summary_remains_insufficient": (
            local_logos_examples is None and local_logos_max <= 0.55
        ),
        "local_hybrid_reaches_target": (
            local_hybrid_examples is not None and local_hybrid_examples <= 64
        ),
        "local_raw_reaches_target": (
            local_raw_examples is not None and local_raw_examples <= 256
        ),
        "local_hybrid_uses_at_least_4x_fewer_examples": (
            local_raw_examples is not None
            and local_hybrid_examples is not None
            and local_raw_examples / local_hybrid_examples >= 4.0
        ),
        "local_hybrid_uses_at_least_20x_fewer_logical_training_bits": (
            local_raw_bits is not None
            and local_hybrid_bits is not None
            and local_raw_bits / local_hybrid_bits >= 20.0
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "diagnostics": {
            "global_raw_64_balanced_accuracy": global_raw_64,
            "global_logos_64_balanced_accuracy": global_logos_64,
            "global_hybrid_64_balanced_accuracy": global_hybrid_64,
            "local_logos_max_balanced_accuracy": local_logos_max,
            "local_raw_examples_to_target": local_raw_examples,
            "local_hybrid_examples_to_target": local_hybrid_examples,
            "local_example_efficiency_ratio": (
                local_raw_examples / local_hybrid_examples
                if local_raw_examples is not None
                and local_hybrid_examples is not None
                else None
            ),
            "local_logical_training_bits_ratio": (
                local_raw_bits / local_hybrid_bits
                if local_raw_bits is not None and local_hybrid_bits is not None
                else None
            ),
        },
    }


def run_learning_benchmark(
    *,
    train_sizes: Sequence[int] = DEFAULT_TRAIN_SIZES,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    test_size: int = DEFAULT_TEST_SIZE,
    epochs: int = DEFAULT_EPOCHS,
) -> dict[str, Any]:
    if not train_sizes or any(size <= 0 or size % 2 for size in train_sizes):
        raise LearningError("train sizes must be positive even integers")
    if tuple(sorted(set(train_sizes))) != tuple(train_sizes):
        raise LearningError("train sizes must be strictly increasing")
    if not seeds:
        raise LearningError("at least one training seed is required")
    if test_size <= 0 or test_size % 2:
        raise LearningError("test size must be a positive even integer")

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "boundary": (
            "controlled synthetic learning benchmark over pre-evaluated BARDO-TX1 "
            "results; not real-world model evidence, not FPGA evidence, and not a "
            "general claim that LOGOS always learns better"
        ),
        "model": {
            "type": "averaged passive-aggressive binary linear classifier",
            "feature_dimension": FEATURE_DIM,
            "trainable_parameters": TRAINABLE_PARAMETERS,
            "epochs": epochs,
            "training_seeds": list(seeds),
        },
        "representations": {
            name: dict(metadata) for name, metadata in REPRESENTATIONS.items()
        },
        "train_sizes": list(train_sizes),
        "target_balanced_accuracy": TARGET_BALANCED_ACCURACY,
        "tasks": {
            "global_recovery": _task_report(
                name="global_recovery",
                description=(
                    "controlled downstream outcome generated from global semantic "
                    "sufficient statistics plus bounded noise"
                ),
                generator=generate_global_dataset,
                test_seed=9001,
                train_sizes=train_sizes,
                seeds=seeds,
                test_size=test_size,
                epochs=epochs,
            ),
            "localized_escalation": _task_report(
                name="localized_escalation",
                description=(
                    "paired frames have identical global semantic facts; the label "
                    "depends only on whether the single invalid witness is in a "
                    "critical outer lane region"
                ),
                generator=generate_local_dataset,
                test_seed=9002,
                train_sizes=train_sizes,
                seeds=seeds,
                test_size=test_size,
                epochs=epochs,
            ),
        },
    }
    report["gate"] = validate_report(report)
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# BARDO LOGOS learning-efficiency benchmark v0.3",
        "",
        f"**Boundary:** {report['boundary']}",
        "",
        "## Fixed learner budget",
        "",
        "| Item | Value |",
        "| --- | ---: |",
        f"| Feature dimension | {report['model']['feature_dimension']} |",
        f"| Trainable parameters | {report['model']['trainable_parameters']} |",
        f"| Target balanced accuracy | {report['target_balanced_accuracy']:.2f} |",
        "",
        "## Representation widths",
        "",
        "| Representation | Logical bits/example |",
        "| --- | ---: |",
    ]
    for name, metadata in report["representations"].items():
        lines.append(f"| {name} | {metadata['logical_bits_per_example']} |")

    for task_name, task in report["tasks"].items():
        lines.extend(
            [
                "",
                f"## {task_name}",
                "",
                task["description"],
                "",
                "| Train examples | RAW | LOGOS | HYBRID |",
                "| ---: | ---: | ---: | ---: |",
            ]
        )
        sizes = [point["train_examples"] for point in task["curves"]["raw"]]
        for index, train_examples in enumerate(sizes):
            lines.append(
                f"| {train_examples} | "
                f"{task['curves']['raw'][index]['median_balanced_accuracy']:.3f} | "
                f"{task['curves']['logos'][index]['median_balanced_accuracy']:.3f} | "
                f"{task['curves']['hybrid'][index]['median_balanced_accuracy']:.3f} |"
            )
        lines.extend(
            [
                "",
                "| Representation | Examples to 0.80 | Logical training bits |",
                "| --- | ---: | ---: |",
            ]
        )
        for representation in ("raw", "logos", "hybrid"):
            efficiency = task["sample_efficiency"][representation]
            examples = efficiency["examples_to_target"]
            logical_bits = efficiency["logical_training_bits_to_target"]
            lines.append(
                f"| {representation} | "
                f"{examples if examples is not None else 'not reached'} | "
                f"{logical_bits if logical_bits is not None else 'not reached'} |"
            )

    gate = report["gate"]
    lines.extend(
        [
            "",
            "## Gate",
            "",
            f"**Passed:** `{str(gate['passed']).lower()}`",
            "",
        ]
    )
    lines.extend(
        f"- {name}: `{'pass' if passed else 'fail'}`"
        for name, passed in gate["checks"].items()
    )
    lines.extend(
        [
            "",
            "The ordered root is deliberately excluded from learned semantic "
            "features; it remains an integrity/provenance field. HYBRID restores "
            "bounded local witnesses when a global summary is not sufficient.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare RAW, LOGOS, and HYBRID learning representations."
    )
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--test-size", type=int, default=DEFAULT_TEST_SIZE)
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    args = parser.parse_args(argv)

    try:
        report = run_learning_benchmark(test_size=args.test_size, epochs=args.epochs)
        _write_text(
            args.json_output,
            json.dumps(report, indent=2, sort_keys=True) + "\n",
        )
        _write_text(args.markdown_output, render_markdown(report))
    except (OSError, LearningError) as exc:
        print(f"learning_benchmark=fail reason={exc}")
        return 1

    gate = report["gate"]
    diagnostics = gate["diagnostics"]
    print("learning_benchmark=pass")
    print(f"learning_gate={'pass' if gate['passed'] else 'fail'}")
    print(f"model_parameters={report['model']['trainable_parameters']}")
    print(
        "global_logos_64_balanced_accuracy="
        f"{diagnostics['global_logos_64_balanced_accuracy']:.6f}"
    )
    print(
        "global_hybrid_64_balanced_accuracy="
        f"{diagnostics['global_hybrid_64_balanced_accuracy']:.6f}"
    )
    print(
        "local_raw_examples_to_0_80="
        f"{diagnostics['local_raw_examples_to_target']}"
    )
    print(
        "local_hybrid_examples_to_0_80="
        f"{diagnostics['local_hybrid_examples_to_target']}"
    )
    print(
        "local_example_efficiency_ratio="
        f"{diagnostics['local_example_efficiency_ratio']:.6f}"
    )
    print(
        "local_logical_training_bits_ratio="
        f"{diagnostics['local_logical_training_bits_ratio']:.6f}"
    )
    return 0 if gate["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
