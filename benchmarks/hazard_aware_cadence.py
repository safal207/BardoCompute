from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

from bardocompute.hazard_cadence import (
    HazardCadenceEvidence,
    evaluate_hazard_cadence,
)

FIXED_INTERVALS = (8, 16, 32, 64, 128, 256)
PROBE_COSTS = (2.0, 8.0, 32.0)
STALE_REGRET_PER_STEP = 10.0
PHASES = (
    ("calm", 0.001),
    ("volatile", 0.020),
    ("calm_return", 0.001),
    ("moderate", 0.005),
)


@dataclass(frozen=True, slots=True)
class Environment:
    changes: tuple[bool, ...]
    hazards: tuple[float, ...]
    phase_index: tuple[int, ...]
    phase_starts: tuple[int, ...]
    phase_lengths: tuple[int, ...]


@dataclass(slots=True)
class HazardEstimator:
    mode: str
    cumulative_events: float = 1.0
    cumulative_exposure: float = 128.0
    ewma: float = 1.0 / 128.0
    rolling: deque[tuple[int, int]] = field(default_factory=lambda: deque(maxlen=8))

    def update(self, events: int, exposure: int) -> None:
        if exposure <= 0:
            return
        self.cumulative_events += events
        self.cumulative_exposure += exposure

        observed_rate = events / exposure
        # Exposure-aware EWMA: roughly half of the prior estimate survives
        # after 512 newly observed steps.
        weight = 1.0 - math.exp(-math.log(2.0) * exposure / 512.0)
        self.ewma = (1.0 - weight) * self.ewma + weight * observed_rate
        self.rolling.append((events, exposure))

    def value(self) -> float:
        if self.mode == "cumulative":
            return min(1.0, self.cumulative_events / self.cumulative_exposure)
        if self.mode == "ewma":
            return min(1.0, max(0.0, self.ewma))
        if self.mode == "rolling":
            events = 1 + sum(item[0] for item in self.rolling)
            exposure = 128 + sum(item[1] for item in self.rolling)
            return min(1.0, events / exposure)
        raise ValueError(self.mode)


@dataclass(slots=True)
class Stats:
    total_loss: float = 0.0
    probes: int = 0
    stale_steps: int = 0
    selected_interval_sum: int = 0
    selected_interval_count: int = 0
    phase_interval_sum: list[int] = field(default_factory=lambda: [0] * len(PHASES))
    phase_interval_count: list[int] = field(default_factory=lambda: [0] * len(PHASES))
    volatile_contract_lag: int | None = None
    return_expand_lag: int | None = None


def build_environment(seed: int = 0xA2A2D) -> Environment:
    rng = random.Random(seed)
    phase_lengths = tuple(rng.randint(28_000, 42_000) for _ in PHASES)
    changes: list[bool] = []
    hazards: list[float] = []
    phase_index: list[int] = []
    phase_starts: list[int] = []
    cursor = 0

    for index, ((_, hazard), length) in enumerate(zip(PHASES, phase_lengths)):
        phase_starts.append(cursor)
        for _ in range(length):
            hazards.append(hazard)
            phase_index.append(index)
            changes.append(rng.random() < hazard)
        cursor += length

    return Environment(
        changes=tuple(changes),
        hazards=tuple(hazards),
        phase_index=tuple(phase_index),
        phase_starts=tuple(phase_starts),
        phase_lengths=phase_lengths,
    )


def cadence(hazard: float, probe_cost: float) -> int:
    return evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=hazard,
            regret_given_change=STALE_REGRET_PER_STEP,
            probe_cost=probe_cost,
            min_interval=8,
            max_interval=256,
        )
    ).interval


def run_policy(
    environment: Environment,
    *,
    probe_cost: float,
    mode: str,
    fixed_interval: int | None = None,
) -> Stats:
    stats = Stats()
    estimator = HazardEstimator(mode=mode if mode in {"cumulative", "ewma", "rolling"} else "ewma")
    current_epoch = 0
    calibrated_epoch = 0
    last_probe_epoch = 0
    last_probe_step = 0

    if fixed_interval is not None:
        next_interval = fixed_interval
    elif mode == "oracle":
        next_interval = cadence(environment.hazards[0], probe_cost)
    else:
        next_interval = cadence(estimator.value(), probe_cost)
    next_probe = next_interval

    volatile_start = environment.phase_starts[1]
    return_start = environment.phase_starts[2]

    for step, changed in enumerate(environment.changes):
        if changed:
            current_epoch += 1

        if current_epoch != calibrated_epoch:
            stats.total_loss += STALE_REGRET_PER_STEP
            stats.stale_steps += 1

        if step < next_probe:
            continue

        stats.total_loss += probe_cost
        stats.probes += 1
        exposure = max(1, step - last_probe_step)
        events = current_epoch - last_probe_epoch

        if mode in {"cumulative", "ewma", "rolling"}:
            estimator.update(events, exposure)

        calibrated_epoch = current_epoch
        last_probe_epoch = current_epoch
        last_probe_step = step

        if fixed_interval is not None:
            next_interval = fixed_interval
        elif mode == "oracle":
            next_interval = cadence(environment.hazards[step], probe_cost)
        else:
            next_interval = cadence(estimator.value(), probe_cost)

        stats.selected_interval_sum += next_interval
        stats.selected_interval_count += 1
        phase = environment.phase_index[step]
        stats.phase_interval_sum[phase] += next_interval
        stats.phase_interval_count[phase] += 1

        if (
            step >= volatile_start
            and stats.volatile_contract_lag is None
            and next_interval <= 16
        ):
            stats.volatile_contract_lag = step - volatile_start
        if (
            step >= return_start
            and stats.return_expand_lag is None
            and next_interval >= 32
        ):
            stats.return_expand_lag = step - return_start

        next_probe = step + next_interval

    return stats


def mean_loss(stats: Stats, steps: int) -> float:
    return stats.total_loss / steps


def mean_interval(stats: Stats) -> float:
    if stats.selected_interval_count == 0:
        return float("nan")
    return stats.selected_interval_sum / stats.selected_interval_count


def phase_intervals(stats: Stats) -> str:
    values: list[str] = []
    for total, count in zip(stats.phase_interval_sum, stats.phase_interval_count):
        values.append(f"{total / count:.1f}" if count else "nan")
    return "/".join(values)


def main() -> None:
    environment = build_environment()
    steps = len(environment.changes)
    print(f"deployment_steps={steps}")
    print("phases=" + ",".join(
        f"{name}:{length}@hazard={hazard:.3f}"
        for (name, hazard), length in zip(PHASES, environment.phase_lengths)
    ))
    print("policy_input=phase labels, boundaries, future hazards hidden")
    print("probe_reveals=current epoch and event count since previous probe")
    print("phase_interval_order=calm/volatile/calm_return/moderate")

    for probe_cost in PROBE_COSTS:
        fixed = [
            (
                interval,
                run_policy(
                    environment,
                    probe_cost=probe_cost,
                    mode="fixed",
                    fixed_interval=interval,
                ),
            )
            for interval in FIXED_INTERVALS
        ]
        best_interval, best_fixed = min(
            fixed, key=lambda item: mean_loss(item[1], steps)
        )
        cumulative = run_policy(environment, probe_cost=probe_cost, mode="cumulative")
        ewma = run_policy(environment, probe_cost=probe_cost, mode="ewma")
        rolling = run_policy(environment, probe_cost=probe_cost, mode="rolling")
        oracle = run_policy(environment, probe_cost=probe_cost, mode="oracle")

        print(f"\n[probe_cost={probe_cost:.2f}]")
        print(
            "strategy,mean_loss,vs_best_fixed,probes,stale_steps,mean_interval,"
            "phase_mean_intervals,volatile_contract_lag,return_expand_lag"
        )
        rows = [
            (f"fixed_{best_interval}", best_fixed),
            ("cumulative_hazard", cumulative),
            ("ewma_hazard", ewma),
            ("rolling_hazard", rolling),
            ("oracle_current_hazard", oracle),
        ]
        base = mean_loss(best_fixed, steps)
        for name, stats in rows:
            loss = mean_loss(stats, steps)
            print(
                f"{name},{loss:.4f},{loss / base:.3f},{stats.probes},"
                f"{stats.stale_steps},{mean_interval(stats):.2f},"
                f"{phase_intervals(stats)},{stats.volatile_contract_lag},"
                f"{stats.return_expand_lag}"
            )

    print(
        "\ninterpretation=Hazard-aware cadence separates the probability of a "
        "future environment change from the consequence of being stale. The "
        "online estimators receive no hidden phase boundaries. Any adaptive win "
        "must come from estimating change frequency from paid probe history; the "
        "oracle-current-hazard row is an upper control, not a deployable policy."
    )


if __name__ == "__main__":
    main()
