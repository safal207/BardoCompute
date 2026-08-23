from __future__ import annotations

import random
from dataclasses import dataclass

from bardocompute.observation_payback import (
    ObservationAction,
    ObservationPaybackEvidence,
    evaluate_observation_payback,
)

LENGTH = 512
KINDS = (
    "stable",
    "transient",
    "persistent",
    "gradual",
    "late_shift",
    "weak_shift",
    "reversal",
)
CALIBRATION_PER_KIND = 1_500
TEST_PER_KIND = 2_000


@dataclass(slots=True)
class Episode:
    values: list[int]
    truth_adapt: bool
    shift_start: int | None
    kind: str


@dataclass(slots=True)
class CalibrationCell:
    total: int = 0
    beneficial: int = 0
    harmful: int = 0


@dataclass(frozen=True, slots=True)
class CostProfile:
    name: str
    sample_cost: float
    miss_cost: float
    false_action_cost: float
    adapt_cost: float


@dataclass(slots=True)
class Stats:
    episodes: int = 0
    observed: int = 0
    adapted: int = 0
    false_adapt: int = 0
    missed_adapt: int = 0
    inspections: int = 0


PROFILES = (
    CostProfile("cheap_observation", 0.10, 120.0, 80.0, 20.0),
    CostProfile("balanced", 0.50, 120.0, 80.0, 20.0),
    CostProfile("false_adapt_sensitive", 0.50, 120.0, 500.0, 20.0),
    CostProfile("expensive_observation", 2.00, 120.0, 80.0, 20.0),
)


def draw(probability: float, rng: random.Random) -> int:
    return 1 if rng.random() < probability else 0


def make_episode(kind: str, rng: random.Random, *, shifted: bool) -> Episode:
    base = 0.12 if shifted else 0.08
    burst_length = (
        rng.randrange(32, 97) if kind == "transient" and shifted else 32
    )
    shift_start = (
        rng.randrange(144, 385)
        if kind in {"late_shift", "weak_shift", "reversal"}
        else None
    )
    reversal_end = (
        min(LENGTH, shift_start + rng.randrange(48, 145))
        if kind == "reversal" and shift_start is not None
        else None
    )

    late_probability = None
    if kind == "late_shift":
        late_probability = (
            rng.uniform(0.58, 0.82) if shifted else rng.uniform(0.68, 0.92)
        )
    elif kind == "weak_shift":
        late_probability = (
            rng.uniform(0.50, 0.62) if shifted else rng.uniform(0.52, 0.68)
        )

    values: list[int] = []
    for index in range(LENGTH):
        if kind == "stable":
            probability = base
        elif kind == "transient":
            probability = (0.76 if shifted else 0.86) if index < burst_length else base
        elif kind == "persistent":
            probability = 0.72 if shifted else 0.84
        elif kind == "gradual":
            if index < 96:
                probability = 0.24
            elif index < 384:
                maximum = 0.68 if shifted else 0.82
                probability = 0.24 + (maximum - 0.24) * (index - 96) / 288
            else:
                probability = 0.68 if shifted else 0.82
        elif kind in {"late_shift", "weak_shift"}:
            assert shift_start is not None
            assert late_probability is not None
            probability = base if index < shift_start else late_probability
        elif kind == "reversal":
            assert shift_start is not None
            assert reversal_end is not None
            amplitude = 0.72 if shifted else 0.84
            probability = (
                amplitude if shift_start <= index < reversal_end else base
            )
        else:
            raise ValueError(kind)
        values.append(draw(probability, rng))

    return Episode(
        values=values,
        truth_adapt=kind in {"persistent", "gradual", "late_shift", "weak_shift"},
        shift_start=shift_start,
        kind=kind,
    )


def make_dataset(
    *, per_kind: int, seed: int, shifted: bool
) -> list[Episode]:
    rng = random.Random(seed)
    return [
        make_episode(kind, rng, shifted=shifted)
        for kind in KINDS
        for _ in range(per_kind)
    ]


def initial_positive(episode: Episode) -> bool:
    return sum(episode.values[:128]) / 128 >= 0.5


def sentinel_hits(episode: Episode, start: int) -> int:
    return sum(episode.values[index] for index in range(start, start + 32, 4))


def full_interval_positive(episode: Episode, start: int) -> bool:
    return sum(episode.values[start : start + 32]) / 32 >= 0.5


def build_calibration(
    episodes: list[Episode],
) -> dict[tuple[int, int], CalibrationCell]:
    table = {
        (interval_index, hits): CalibrationCell()
        for interval_index in range(12)
        for hits in range(9)
    }
    for episode in episodes:
        if initial_positive(episode):
            continue
        for interval_index, start in enumerate(range(128, LENGTH, 32)):
            hits = sentinel_hits(episode, start)
            cell = table[interval_index, hits]
            cell.total += 1
            if not full_interval_positive(episode, start):
                continue
            if episode.truth_adapt:
                cell.beneficial += 1
            else:
                cell.harmful += 1
    return table


def probabilities(cell: CalibrationCell) -> tuple[float, float]:
    # Three-outcome Laplace smoothing: beneficial, harmful, neutral.
    denominator = cell.total + 3
    return (
        (cell.beneficial + 1) / denominator,
        (cell.harmful + 1) / denominator,
    )


def payback_action(
    table: dict[tuple[int, int], CalibrationCell],
    profile: CostProfile,
    interval_index: int,
    hits: int,
) -> ObservationAction:
    beneficial_probability, harmful_probability = probabilities(
        table[interval_index, hits]
    )
    result = evaluate_observation_payback(
        ObservationPaybackEvidence(
            beneficial_correction_probability=beneficial_probability,
            harmful_correction_probability=harmful_probability,
            recoverable_miss_loss=profile.miss_cost,
            false_action_loss=profile.false_action_cost,
            action_cost=profile.adapt_cost,
            observation_cost=24 * profile.sample_cost,
        )
    )
    return result.action


def conventional_payback_action(
    table: dict[tuple[int, int], CalibrationCell],
    profile: CostProfile,
    interval_index: int,
    hits: int,
) -> ObservationAction:
    beneficial_probability, harmful_probability = probabilities(
        table[interval_index, hits]
    )
    score = (
        beneficial_probability * max(0.0, profile.miss_cost - profile.adapt_cost)
        - harmful_probability * (profile.false_action_cost + profile.adapt_cost)
        - 24 * profile.sample_cost
    )
    if score > 0.0:
        return ObservationAction.REVISIT
    if score < 0.0:
        return ObservationAction.SKIP
    return ObservationAction.HOLD


def run_fixed_long(episode: Episode) -> tuple[bool, int, int]:
    if initial_positive(episode):
        return True, 128, 0
    return sum(episode.values) / LENGTH >= 0.5, LENGTH, 1


def run_fixed_threshold(
    episode: Episode, threshold: int
) -> tuple[bool, int, int]:
    observed = 128
    if initial_positive(episode):
        return True, observed, 0

    inspections = 0
    for start in range(128, LENGTH, 32):
        hits = sentinel_hits(episode, start)
        observed += 8
        if hits < threshold:
            continue
        inspections += 1
        observed += 24
        if full_interval_positive(episode, start):
            return True, observed, inspections
    return False, observed, inspections


def run_payback(
    episode: Episode,
    table: dict[tuple[int, int], CalibrationCell],
    profile: CostProfile,
) -> tuple[bool, int, int]:
    observed = 128
    if initial_positive(episode):
        return True, observed, 0

    inspections = 0
    for interval_index, start in enumerate(range(128, LENGTH, 32)):
        hits = sentinel_hits(episode, start)
        observed += 8
        action = payback_action(table, profile, interval_index, hits)
        if action is not ObservationAction.REVISIT:
            continue
        inspections += 1
        observed += 24
        if full_interval_positive(episode, start):
            return True, observed, inspections
    return False, observed, inspections


def collect(
    episodes: list[Episode],
    runner,
) -> Stats:
    stats = Stats()
    for episode in episodes:
        decision, observed, inspections = runner(episode)
        stats.episodes += 1
        stats.observed += observed
        stats.inspections += inspections
        if decision:
            stats.adapted += 1
            if not episode.truth_adapt:
                stats.false_adapt += 1
        elif episode.truth_adapt:
            stats.missed_adapt += 1
    return stats


def mean_loss(stats: Stats, profile: CostProfile) -> float:
    total = (
        stats.observed * profile.sample_cost
        + stats.adapted * profile.adapt_cost
        + stats.false_adapt * profile.false_action_cost
        + stats.missed_adapt * profile.miss_cost
    )
    return total / stats.episodes


def trained_fixed_threshold(
    calibration: list[Episode], profile: CostProfile
) -> int:
    candidates: list[tuple[float, int]] = []
    for threshold in range(1, 9):
        stats = collect(
            calibration,
            lambda episode, threshold=threshold: run_fixed_threshold(
                episode, threshold
            ),
        )
        candidates.append((mean_loss(stats, profile), threshold))
    return min(candidates)[1]


def print_stats(name: str, stats: Stats, profile: CostProfile) -> None:
    print(f"  {name}:")
    print(f"    mean_loss={mean_loss(stats, profile):.3f}")
    print(f"    mean_observed={stats.observed / stats.episodes:.2f}")
    print(f"    false_adapt={stats.false_adapt}")
    print(f"    missed_adapt={stats.missed_adapt}")
    print(f"    mean_deep_inspections={stats.inspections / stats.episodes:.3f}")


def main() -> None:
    calibration = make_dataset(
        per_kind=CALIBRATION_PER_KIND,
        seed=0xCA11B4A,
        shifted=False,
    )
    in_distribution = make_dataset(
        per_kind=TEST_PER_KIND,
        seed=0xB4A2D0,
        shifted=False,
    )
    shifted = make_dataset(
        per_kind=TEST_PER_KIND,
        seed=0xB4A2D1,
        shifted=True,
    )
    table = build_calibration(calibration)

    semantic_equivalence = all(
        payback_action(table, profile, interval_index, hits)
        is conventional_payback_action(table, profile, interval_index, hits)
        for profile in PROFILES
        for interval_index in range(12)
        for hits in range(9)
    )

    print(f"calibration_episodes={len(calibration)}")
    print(f"test_episodes_per_distribution={len(in_distribution)}")
    print("calibration_source=past seeded episodes only")
    print(f"semantic_equivalence_to_conventional={semantic_equivalence}")

    for profile in PROFILES:
        threshold = trained_fixed_threshold(calibration, profile)
        revisit_cells = sum(
            payback_action(table, profile, interval_index, hits)
            is ObservationAction.REVISIT
            for interval_index in range(12)
            for hits in range(9)
        )
        print(f"\n[{profile.name}]")
        print(f"sample_cost={profile.sample_cost:.2f}")
        print(f"miss_cost={profile.miss_cost:.2f}")
        print(f"false_action_cost={profile.false_action_cost:.2f}")
        print(f"adapt_cost={profile.adapt_cost:.2f}")
        print(f"trained_fixed_threshold={threshold}/8")
        print(f"payback_revisit_cells={revisit_cells}/108")

        for label, episodes in (
            ("in_distribution", in_distribution),
            ("distribution_shift", shifted),
        ):
            print(f"\n  [{label}]")
            print_stats(
                "fixed512",
                collect(episodes, run_fixed_long),
                profile,
            )
            print_stats(
                f"trained_fixed_{threshold}/8",
                collect(
                    episodes,
                    lambda episode, threshold=threshold: run_fixed_threshold(
                        episode, threshold
                    ),
                ),
                profile,
            )
            print_stats(
                "adaptive_payback",
                collect(
                    episodes,
                    lambda episode, profile=profile: run_payback(
                        episode, table, profile
                    ),
                ),
                profile,
            )

    print(
        "\ninterpretation=Observation payback changes when deeper inspection is "
        "economically justified using only historical calibration plus current "
        "sentinel evidence. It is not a universal winner: calibration shift can "
        "make a simpler trained fixed threshold cheaper. That failure is part of "
        "the falsification surface, not something to hide."
    )


if __name__ == "__main__":
    main()
