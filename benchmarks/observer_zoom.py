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
    late_detected: int = 0
    late_detection_lag: int = 0


def draw(probability: float, rng: random.Random) -> int:
    return 1 if rng.random() < probability else 0


def make_episode(kind: str, rng: random.Random) -> tuple[list[int], int | None]:
    shift_start = rng.randrange(144, 385) if kind == "late_shift" else None
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
            assert shift_start is not None
            p = 0.08 if i < shift_start else 0.86
        else:
            raise ValueError(kind)
        values.append(draw(p, rng))
    return values, shift_start


def score(values: list[int], width: int) -> float:
    return sum(values[:width]) / width


def truth_should_adapt(kind: str) -> bool:
    return kind in {"persistent", "gradual", "late_shift"}


def record(
    stats: Stats,
    decision: bool | None,
    truth: bool,
    observed: int,
    *,
    detection_tick: int | None = None,
    shift_start: int | None = None,
) -> None:
    stats.observed += observed
    if shift_start is not None and detection_tick is not None:
        stats.late_detected += 1
        stats.late_detection_lag += max(0, detection_tick - shift_start)
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


def early_multiscale(values: list[int]) -> tuple[bool, int]:
    s32 = score(values, 32)
    s128 = score(values, 128)
    same_side = (s32 >= 0.5) == (s128 >= 0.5)
    if same_side and abs(s32 - s128) <= 0.30:
        return (s32 + s128) / 2.0 >= 0.5, 128
    s512 = score(values, 512)
    return s512 >= 0.5, 512


def event_triggered_revisit(values: list[int]) -> tuple[bool, int, int | None]:
    """Re-open zoom after an early KEEP using only past/present samples.

    A quiet two-scale decision at tick 128 is not treated as permanent. Every
    following 32-signal interval, eight evenly spaced sentinel reads test for a
    new change. Five or more changed samples trigger full inspection of that
    already-arrived interval. No future regime length or hidden boundary is
    supplied to the policy.
    """

    s32 = score(values, 32)
    s128 = score(values, 128)
    same_side = (s32 >= 0.5) == (s128 >= 0.5)
    if not (same_side and abs(s32 - s128) <= 0.30):
        return score(values, 512) >= 0.5, 512, None

    decision = (s32 + s128) / 2.0 >= 0.5
    if decision:
        return True, 128, 128

    observed = 128
    for start in range(128, LENGTH, 32):
        end = min(start + 32, LENGTH)
        indices = list(range(start, end, 4))
        sentinel_hits = sum(values[index] for index in indices)
        observed += len(indices)
        if sentinel_hits < 5:
            continue

        # The interval has already arrived. Read the samples not touched by the
        # sentinel, so the accounting counts unique observations rather than
        # charging the same evidence twice.
        observed += (end - start) - len(indices)
        if sum(values[start:end]) / (end - start) >= 0.5:
            return True, observed, end

    return False, observed, None


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
        return None, 512, third.level
    return third.change_belief >= 0.5, 512, third.level


def main() -> None:
    rng = random.Random(0xB4A2D0)
    stats = {
        "fixed32": Stats(),
        "fixed512": Stats(),
        "early_multiscale": Stats(),
        "event_triggered_revisit": Stats(),
        "observer_stack": Stats(),
    }
    levels = {level: 0 for level in ObserverLevel}

    for kind in KINDS:
        truth = truth_should_adapt(kind)
        for _ in range(EPISODES_PER_KIND):
            values, shift_start = make_episode(kind, rng)

            decision, observed = fixed32(values)
            record(stats["fixed32"], decision, truth, observed)

            decision, observed = fixed512(values)
            record(stats["fixed512"], decision, truth, observed)

            decision, observed = early_multiscale(values)
            record(stats["early_multiscale"], decision, truth, observed)

            decision, observed, detection_tick = event_triggered_revisit(values)
            record(
                stats["event_triggered_revisit"],
                decision,
                truth,
                observed,
                detection_tick=detection_tick,
                shift_start=shift_start,
            )

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
        if item.late_detected:
            print(f"late_detected={item.late_detected}")
            print(
                "mean_late_detection_lag="
                f"{item.late_detection_lag / item.late_detected:.2f}"
            )

    print("\n[observer_levels]")
    for level in ObserverLevel:
        print(f"{level.value}={levels[level]}")

    early = stats["early_multiscale"]
    revisit = stats["event_triggered_revisit"]
    fixed_long = stats["fixed512"]
    print(
        "early_multiscale_observation_vs_fixed512="
        f"{early.observed / fixed_long.observed:.3f}x"
    )
    print(
        "revisit_observation_vs_fixed512="
        f"{revisit.observed / fixed_long.observed:.3f}x"
    )
    print(
        "interpretation=Scale escalation can reject transient bursts with less "
        "observation than a fixed long window, but one-shot early stopping can "
        "miss later regime changes. Event-triggered revisit tests whether HOLD/" 
        "KEEP can remain revisable without continuously paying the full long-window cost."
    )


if __name__ == "__main__":
    main()
