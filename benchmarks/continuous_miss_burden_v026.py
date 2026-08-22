from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

from bardocompute.exchange import ExchangeResult, MembraneCommand
from bidirectional_homeostasis import BOOST_AMOUNT, BOOSTED_SAFE_CAP
from exchange_conservation import FlowPreservingMembrane
from real_work_queue_transfer import (
    BASE_BUFFER,
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)
from storage_reserve import ELASTIC_BUFFER_LIMIT

SEEDS = (
    14_100_439,
    14_200_443,
    14_300_449,
    14_400_457,
    14_500_463,
    14_600_469,
    14_700_473,
    14_800_481,
)

MISS_THRESHOLD = 0.25
SEVERE_MISS_THRESHOLD = 0.50
MIN_COMPLETED_PRESERVATION = 0.98
MIN_SIGN_AGREEMENT = 6


class FixedSupportMembrane:
    """Exact v0.25 support arm; only measurement changes in v0.26."""

    def __init__(self, *, relief: bool, rate_cap: bool) -> None:
        self.base = FlowPreservingMembrane(route_enabled=True)
        self.relief = relief
        self.rate_cap = rate_cap
        self.current_boost = BOOST_AMOUNT if relief else 0.0

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.26 forbids voluntary admission shedding")
        self.current_boost = BOOST_AMOUNT if self.relief else 0.0
        release_limit = (
            min(base.release_limit, BOOSTED_SAFE_CAP)
            if self.rate_cap
            else base.release_limit
        )
        return MembraneCommand(
            admission_limit=None,
            release_limit=release_limit,
            buffer_limit=ELASTIC_BUFFER_LIMIT,
            secondary_fraction=base.secondary_fraction,
        )

    def observe(self, result: ExchangeResult) -> None:
        self.base.observe(result)


@dataclass(slots=True)
class ContinuousStats:
    incoming: int = 0
    completed: int = 0
    lost: int = 0
    deadline_miss_epochs: int = 0
    severe_miss_epochs: int = 0
    wall_seconds: float = 0.0
    digest_mismatches: int = 0
    executed_epochs: int = 0
    terminal_backlog: int = 0
    missed_work_total: int = 0
    released_work_total: int = 0
    severe_excess_total: float = 0.0

    def seconds_per_completion(self) -> float:
        return self.wall_seconds / max(1, self.completed)

    def missed_work_fraction(self) -> float:
        return self.missed_work_total / max(1, self.released_work_total)

    def severe_excess_fraction(self) -> float:
        return self.severe_excess_total / max(1, self.released_work_total)


def run_continuous_policy(
    epochs: tuple[EpochSpec, ...],
    *,
    controller: FixedSupportMembrane,
    rounds: int,
    deadline_seconds: float,
) -> ContinuousStats:
    stats = ContinuousStats()
    backlog = 0

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()

        queue = list(epochs)
        queue.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

        for spec in queue:
            if spec.phase == "drain" and backlog == 0:
                break

            stats.executed_epochs += 1
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("v0.26 forbids voluntary admission shedding")

            stats.incoming += spec.incoming
            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            backlog += admitted
            stats.lost += overflow

            released = min(backlog, command.release_limit)
            backlog -= released

            relief_active = bool(getattr(controller, "current_boost", 0.0) > 0.0)
            relief_count = 0
            if relief_active and released:
                relief_count = min(
                    released,
                    int(round(released * RELIEF_TASK_FRACTION)),
                )
            ordinary = released - relief_count
            secondary_count = min(
                ordinary,
                max(0, int(round(ordinary * command.secondary_fraction))),
            )
            primary_count = ordinary - secondary_count

            elapsed, p_on, s_on, r_on, mismatches = _execute_batch(
                primary=primary,
                secondary=secondary,
                relief=relief,
                primary_count=primary_count,
                secondary_count=secondary_count,
                relief_count=relief_count,
                rounds=rounds,
                primary_multiplier=spec.primary_multiplier,
                secondary_multiplier=spec.secondary_multiplier,
                deadline_seconds=deadline_seconds,
            )
            stats.wall_seconds += elapsed
            stats.completed += released
            stats.digest_mismatches += mismatches

            on_time = p_on + s_on + r_on
            missed = max(0, released - on_time)
            miss_fraction = missed / max(1, released)
            stats.missed_work_total += missed
            stats.released_work_total += released
            stats.severe_excess_total += max(
                0.0, miss_fraction - SEVERE_MISS_THRESHOLD
            ) * released

            if released > 0:
                stats.deadline_miss_epochs += int(miss_fraction >= MISS_THRESHOLD)
                stats.severe_miss_epochs += int(
                    miss_fraction >= SEVERE_MISS_THRESHOLD
                )

            result = ExchangeResult(
                admitted=admitted,
                gate_rejected=0,
                released=released,
                primary_requested=primary_count,
                secondary_requested=secondary_count,
                primary_delivered=p_on,
                secondary_delivered=s_on,
                delivered=on_time,
                congestion=missed,
                buffered=backlog,
                overflow_dropped=overflow,
            )
            controller.observe(result)

    stats.terminal_backlog = backlog
    return stats


def paired_delta(candidate: ContinuousStats, reference: ContinuousStats) -> dict[str, float]:
    return {
        "missed": candidate.missed_work_fraction() - reference.missed_work_fraction(),
        "severe": candidate.severe_excess_fraction() - reference.severe_excess_fraction(),
        "seconds": candidate.seconds_per_completion() - reference.seconds_per_completion(),
        "completed_ratio": candidate.completed / max(1, reference.completed),
    }


def sign_count(values: list[float]) -> int:
    return sum(value > 0.0 for value in values)


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=continuous_miss_burden_support_factorial_v0.26")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("design=2x2_RELIEF_x_RATE_CAP")
    print("measurement=paired_continuous_missed_work_burden")
    print("storage=constant_ELASTIC_BUFFER_LIMIT")
    print("route=existing_FlowPreservingMembrane")
    print("new_actuator_magnitudes=false")
    print("future_phase_information=false")
    print("admission_shedding=false")

    names = ("full_support", "rate_cap_only", "relief_only", "storage_only")
    stats_by_name: dict[str, list[ContinuousStats]] = {name: [] for name in names}

    relief_deltas: list[dict[str, float]] = []
    rate_deltas: list[dict[str, float]] = []
    both_deltas: list[dict[str, float]] = []
    interaction_missed: list[float] = []
    interaction_severe: list[float] = []

    for seed in SEEDS:
        epochs = build_epochs(seed)
        controllers = {
            "full_support": FixedSupportMembrane(relief=True, rate_cap=True),
            "rate_cap_only": FixedSupportMembrane(relief=False, rate_cap=True),
            "relief_only": FixedSupportMembrane(relief=True, rate_cap=False),
            "storage_only": FixedSupportMembrane(relief=False, rate_cap=False),
        }
        current: dict[str, ContinuousStats] = {}
        for name, controller in controllers.items():
            current[name] = run_continuous_policy(
                epochs,
                controller=controller,
                rounds=rounds,
                deadline_seconds=deadline_seconds,
            )
            stats_by_name[name].append(current[name])

        a = current["full_support"]
        b = current["rate_cap_only"]
        c = current["relief_only"]
        d = current["storage_only"]

        relief_delta = paired_delta(b, a)
        rate_delta = paired_delta(c, a)
        both_delta = paired_delta(d, a)
        relief_deltas.append(relief_delta)
        rate_deltas.append(rate_delta)
        both_deltas.append(both_delta)

        interaction_missed.append(
            (d.missed_work_fraction() - c.missed_work_fraction())
            - (b.missed_work_fraction() - a.missed_work_fraction())
        )
        interaction_severe.append(
            (d.severe_excess_fraction() - c.severe_excess_fraction())
            - (b.severe_excess_fraction() - a.severe_excess_fraction())
        )

        print(
            f"seed={seed} "
            f"A_burden={a.missed_work_fraction():.6f} "
            f"B_burden={b.missed_work_fraction():.6f} "
            f"C_burden={c.missed_work_fraction():.6f} "
            f"D_burden={d.missed_work_fraction():.6f} "
            f"relief_delta={relief_delta['missed']:.6f} "
            f"rate_delta={rate_delta['missed']:.6f} "
            f"both_delta={both_delta['missed']:.6f} "
            f"interaction={interaction_missed[-1]:.6f}"
        )

    relief_missed = [row["missed"] for row in relief_deltas]
    rate_missed = [row["missed"] for row in rate_deltas]
    relief_severe = [row["severe"] for row in relief_deltas]
    rate_severe = [row["severe"] for row in rate_deltas]

    relief_completed_ok = median(
        row["completed_ratio"] for row in relief_deltas
    ) >= MIN_COMPLETED_PRESERVATION
    rate_completed_ok = median(
        row["completed_ratio"] for row in rate_deltas
    ) >= MIN_COMPLETED_PRESERVATION

    relief_local_value = (
        median(relief_missed) > 0.0
        and sign_count(relief_missed) >= MIN_SIGN_AGREEMENT
        and relief_completed_ok
        and all(row.terminal_backlog == 0 for row in stats_by_name["rate_cap_only"])
        and sum(row.digest_mismatches for row in stats_by_name["rate_cap_only"]) == 0
    )
    rate_local_value = (
        median(rate_missed) > 0.0
        and sign_count(rate_missed) >= MIN_SIGN_AGREEMENT
        and rate_completed_ok
        and all(row.terminal_backlog == 0 for row in stats_by_name["relief_only"])
        and sum(row.digest_mismatches for row in stats_by_name["relief_only"]) == 0
    )
    interaction_local = (
        median(interaction_missed) > 0.0
        and sign_count(interaction_missed) >= MIN_SIGN_AGREEMENT
    )

    print("\n[causal_continuous]")
    print(
        f"relief_removal_median_missed_delta={median(relief_missed):.6f} "
        f"relief_removal_positive_seeds={sign_count(relief_missed)}/{len(SEEDS)} "
        f"relief_removal_median_severe_delta={median(relief_severe):.6f}"
    )
    print(
        f"rate_cap_removal_median_missed_delta={median(rate_missed):.6f} "
        f"rate_cap_removal_positive_seeds={sign_count(rate_missed)}/{len(SEEDS)} "
        f"rate_cap_removal_median_severe_delta={median(rate_severe):.6f}"
    )
    print(
        f"interaction_median_missed_delta={median(interaction_missed):.6f} "
        f"interaction_positive_seeds={sign_count(interaction_missed)}/{len(SEEDS)} "
        f"interaction_median_severe_delta={median(interaction_severe):.6f}"
    )
    print(f"relief_completed_preservation={str(relief_completed_ok).lower()}")
    print(f"rate_completed_preservation={str(rate_completed_ok).lower()}")
    print(f"relief_local_continuous_value={str(relief_local_value).lower()}")
    print(f"rate_cap_local_continuous_value={str(rate_local_value).lower()}")
    print(f"interaction_local_continuous_value={str(interaction_local).lower()}")
    print("continuous_factorial_complete=true")
    print(
        "interpretation=v0.26 repeats the frozen v0.25 support matrix but uses "
        "paired continuous missed-work burden so zero-reference severe epochs "
        "cannot turn one event into an infinite causal ratio."
    )


if __name__ == "__main__":
    main()
