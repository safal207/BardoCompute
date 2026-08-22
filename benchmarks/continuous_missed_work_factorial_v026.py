from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from math import ceil
from statistics import mean, median

from bardocompute.exchange import ExchangeResult
from real_work_queue_outcome_audit_r3 import MISS_THRESHOLD, SEVERE_MISS_THRESHOLD
from real_work_queue_transfer import (
    BASE_BUFFER,
    RELIEF_TASK_FRACTION,
    EpochSpec,
    _execute_batch,
    _work,
    build_epochs,
    calibrate_rounds,
)
from support_factorial_v025 import FixedSupportMembrane

# Fresh held-out family frozen in issue #12 before implementation/results.
SEEDS = (
    14_100_439,
    14_200_443,
    14_300_449,
    14_400_457,
    14_500_461,
    14_600_467,
)

ARM_CONFIGS = {
    "A_full_support": (True, True),
    "B_rate_cap_only": (False, True),
    "C_relief_only": (True, False),
    "D_storage_only": (False, False),
}
ARM_NAMES = tuple(ARM_CONFIGS)


@dataclass(slots=True)
class ContinuousStats:
    incoming: int = 0
    completed: int = 0
    lost: int = 0
    wall_seconds: float = 0.0
    digest_mismatches: int = 0
    released_work: int = 0
    missed_work: int = 0
    deadline_miss_epochs: int = 0
    severe_miss_epochs: int = 0
    terminal_backlog: int = 0
    epoch_miss_fractions: list[float] = field(default_factory=list)

    def missed_work_burden(self) -> float:
        return self.missed_work / max(1, self.released_work)

    def mean_epoch_miss_fraction(self) -> float:
        return mean(self.epoch_miss_fractions) if self.epoch_miss_fractions else 0.0

    def p90_epoch_miss_fraction(self) -> float:
        if not self.epoch_miss_fractions:
            return 0.0
        ordered = sorted(self.epoch_miss_fractions)
        index = max(0, ceil(0.90 * len(ordered)) - 1)
        return ordered[index]

    def seconds_per_completion(self) -> float:
        return self.wall_seconds / max(1, self.completed)


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

            on_time = p_on + s_on + r_on
            missed = max(0, released - on_time)
            miss_fraction = missed / max(1, released)

            stats.wall_seconds += elapsed
            stats.completed += released
            stats.digest_mismatches += mismatches
            stats.released_work += released
            stats.missed_work += missed
            if released > 0:
                stats.epoch_miss_fractions.append(miss_fraction)
                stats.deadline_miss_epochs += int(miss_fraction >= MISS_THRESHOLD)
                stats.severe_miss_epochs += int(miss_fraction >= SEVERE_MISS_THRESHOLD)

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


def rotated_order(seed_index: int) -> tuple[str, ...]:
    # Deterministic preregistered order-bias control: rotate which arm is first.
    shift = seed_index % len(ARM_NAMES)
    return ARM_NAMES[shift:] + ARM_NAMES[:shift]


def positive_count(values: list[float]) -> int:
    return sum(value > 0.0 for value in values)


def sign_label(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "zero"


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=continuous_missed_work_factorial_v0.26")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("design=existing_v0.25_2x2_RELIEF_x_RATE_CAP")
    print("primary_metric=missed_work_burden")
    print("contrast=paired_absolute_difference")
    print("arm_order=deterministically_rotated_by_seed")
    print("new_actuator_magnitudes=false")
    print("future_phase_information=false")
    print("admission_shedding=false")

    stats_by_arm: dict[str, list[ContinuousStats]] = {name: [] for name in ARM_NAMES}
    delta_relief: list[float] = []
    delta_rate: list[float] = []
    delta_both: list[float] = []
    interaction: list[float] = []

    for seed_index, seed in enumerate(SEEDS):
        epochs = build_epochs(seed)
        current: dict[str, ContinuousStats] = {}
        order = rotated_order(seed_index)

        for name in order:
            relief, rate_cap = ARM_CONFIGS[name]
            current[name] = run_continuous_policy(
                epochs,
                controller=FixedSupportMembrane(relief=relief, rate_cap=rate_cap),
                rounds=rounds,
                deadline_seconds=deadline_seconds,
            )

        for name in ARM_NAMES:
            stats_by_arm[name].append(current[name])

        a = current["A_full_support"].missed_work_burden()
        b = current["B_rate_cap_only"].missed_work_burden()
        c = current["C_relief_only"].missed_work_burden()
        d = current["D_storage_only"].missed_work_burden()

        dr = b - a
        dc = c - a
        db = d - a
        inter = (d - c) - (b - a)
        delta_relief.append(dr)
        delta_rate.append(dc)
        delta_both.append(db)
        interaction.append(inter)

        print(
            f"seed={seed} order={','.join(order)} "
            f"A_burden={a:.6f} B_burden={b:.6f} "
            f"C_burden={c:.6f} D_burden={d:.6f} "
            f"delta_relief={dr:+.6f} delta_rate={dc:+.6f} "
            f"delta_both={db:+.6f} interaction={inter:+.6f}"
        )

    for name in ARM_NAMES:
        rows = stats_by_arm[name]
        print(f"\n[{name}]")
        print(
            f"median_missed_work_burden={median(row.missed_work_burden() for row in rows):.6f} "
            f"median_mean_epoch_miss={median(row.mean_epoch_miss_fraction() for row in rows):.6f} "
            f"median_p90_epoch_miss={median(row.p90_epoch_miss_fraction() for row in rows):.6f}"
        )
        print(
            f"median_seconds_per_completion={median(row.seconds_per_completion() for row in rows):.9f} "
            f"median_completed={median(row.completed for row in rows):.1f} "
            f"median_lost={median(row.lost for row in rows):.1f}"
        )
        print(
            f"median_deadline_miss_epochs={median(row.deadline_miss_epochs for row in rows):.1f} "
            f"median_severe_miss_epochs={median(row.severe_miss_epochs for row in rows):.1f} "
            f"median_terminal_backlog={median(row.terminal_backlog for row in rows):.1f} "
            f"digest_mismatches={sum(row.digest_mismatches for row in rows)}"
        )

    print("\n[continuous_factorial]")
    print(
        f"median_delta_relief={median(delta_relief):+.6f} "
        f"positive_relief_seeds={positive_count(delta_relief)}/6 "
        f"relief_runtime_candidate={str(median(delta_relief) > 0 and positive_count(delta_relief) >= 5).lower()}"
    )
    print(
        f"median_delta_rate={median(delta_rate):+.6f} "
        f"positive_rate_seeds={positive_count(delta_rate)}/6 "
        f"rate_runtime_candidate={str(median(delta_rate) > 0 and positive_count(delta_rate) >= 5).lower()}"
    )
    print(
        f"median_delta_both={median(delta_both):+.6f} "
        f"positive_both_seeds={positive_count(delta_both)}/6"
    )
    median_interaction = median(interaction)
    same_sign_count = sum(
        (value > 0 and median_interaction > 0) or (value < 0 and median_interaction < 0)
        for value in interaction
    )
    print(
        f"median_interaction={median_interaction:+.6f} "
        f"interaction_sign={sign_label(median_interaction)} "
        f"interaction_same_sign_seeds={same_sign_count}/6 "
        f"interaction_runtime_candidate={str(median_interaction != 0 and same_sign_count >= 5).lower()}"
    )
    print("factorial_complete=true")
    print(
        "interpretation=v0.26 keeps the v0.25 support matrix fixed and replaces "
        "ratios of sparse threshold-crossing counts with continuous missed-work "
        "burden plus paired held-out contrasts. Cross-runtime robustness is judged "
        "only after both Python 3.11 and 3.12 results are available."
    )


if __name__ == "__main__":
    main()
