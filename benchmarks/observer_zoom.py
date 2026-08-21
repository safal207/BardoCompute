from __future__ import annotations

import random
from dataclasses import dataclass

from bardocompute.observer_zoom import (
    ObserverAction,
    ObserverLevel,
    ScaleObservation,
    assess_observer,
)

EPISODES_PER_KIND = 10_000
LENGTH = 512
KINDS = ("stable", "transient", "persistent", "gradual", "late_shift")


@dataclass(slots=True)
class Stats:
    errors: int = 0
    false_adapt: int = 0
    missed_adapt: int = 0
    holds: int = 0
    observed: int = 0


def draw(probability: float, rng: random.Random) -> int:
    return 1 if rng.random() < probability else 0


def make_episode(kind: str, rng: random.Random) -> list[int]:
    values: list[int] = []
    for i in range(LENGTH):
        if kind == "stable":
            p = 0.08
        elif kind == "transient":
            p = 0.86 if i < 32 else 0.08
        elif kind == "persistent":
            p = 0.86
        elif kind == "gradual":
            p = 0.30 if i < 32 else (0.58 if i < 128 else 0.80)
        elif kind == "late_shift":
            p = 0.08 if i < 128 else 0.86
        else:
            raise ValueError(kind)
        values.append(draw(p, rng))
    return values


def score(values: list[int], width: int) -> float:
    return sum(values[:width]) / width


def truth_should_adapt(kind: str) -> bool:
    return kind in {"persistent", "gradual", "late_shift"}


def record(stats: Stats, decision: bool | None, truth: bool, observed: int) -> None:
    stats.observed += observed
    if decision is None:
        stats.holds += 1
        return
    if decision != truth:
        stats.errors += 1
        if decision:
            stats.false_adapt += 1
        else:
            stats.missed_adapt += 1


def fixed32(values: list[int]) -> tuple[bool, int]:
    return score(values, 32) >= 0.5, 32


def fixed512(values: list[int]) -> tuple[bool, int]:
    return score(values, 512) >= 0.5, 512


def conventional_multiscale(values: list[int]) -> tuple[bool, int]:
    s32 = score(values, 32)
    s128 = score(values, 128)
    same_side = (s32 >= 0.5) == (s128 >= 0.5)
    if same_side and abs(s32 - s128) <= 0.30:
        return (s32 + s128) / 2.0 >= 0.5, 128
    s512 = score(values, 512)
    return s512 >= 0.5, 512


def observer_stack(values: list[int]) -> tuple[bool | None, int, ObserverLevel]:
    observations = (ScaleObservation(32, score(values, 32)),)
    first = assess_observer(observations)
    assert first.action is ObserverAction.ZOOM_OUT

    observations += (ScaleObservation(128, score(values, 128)),)
    second = assess_observer(observations)
    if second.level is ObserverLevel.KNOWLEDGE:
        return second.change_belief >= 0.5, 128, second.level

    observations += (ScaleObservation(512, score(values, 512)),)
    third = assess_observer(observations)
    if third.level is ObserverLevel.PRESENCE:
        # PRESENCE means do not let a cross-scale conflict silently become a
        # terminal adaptation. The conventional equal-information control
        # resolves with the longest scale instead, so this is a semantic
        # difference that must be measured rather than assumed superior.
        return None, 512, third.level
    return third.change_belief >= 0.5, 512, third.level


def main() -> None:
    rng = random.Random(0xB4A2D0)
    stats = {
        "fixed32": Stats(),
        "fixed512": Stats(),
        "conventional_multiscale": Stats(),
        "observer_stack": Stats(),
    }
    levels = {level: 0 for level in ObserverLevel}

    for kind in KINDS:
        truth = truth_should_adapt(kind)
        for _ in range(EPISODES_PER_KIND):
            values = make_episode(kind, rng)

            decision, observed = fixed32(values)
            record(stats["fixed32"], decision, truth, observed)

            decision, observed = fixed512(values)
            record(stats["fixed512"], decision, truth, observed)

            decision, observed = conventional_multiscale(values)
            record(stats["conventional_multiscale"], decision, truth, observed)

            decision, observed, level = observer_stack(values)
            record(stats["observer_stack"], decision, truth, observed)
            levels[level] += 1

    total = EPISODES_PER_KIND * len(KINDS)
    print(f"episodes={total}")
    print("kinds=" + ",".join(KINDS))
    for name, item in stats.items():
        print(f"\n[{name}]")
        print(f"errors={item.errors}")
        print(f"false_adapt={item.false_adapt}")
        print(f"missed_adapt={item.missed_adapt}")
        print(f"holds={item.holds}")
        print(f"mean_observed={item.observed / total:.2f}")
    print("\n[observer_levels]")
    for level in ObserverLevel:
        print(f"{level.value}={levels[level]}")

    conventional = stats["conventional_multiscale"]
    fixed_long = stats["fixed512"]
    print(
        "multiscale_observation_vs_fixed512="
        f"{conventional.observed / fixed_long.observed:.3f}x"
    )
    print(
        "interpretation=This benchmark tests whether scale escalation helps "
        "separate transient bursts from persistent change without future-derived "
        "persistence. It deliberately includes a late-shift case that can fool "
        "one-shot early stopping. Observer-level labels receive no oracle data."
    )


if __name__ == "__main__":
    main()
