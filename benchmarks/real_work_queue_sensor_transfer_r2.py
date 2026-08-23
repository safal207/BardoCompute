from __future__ import annotations

from statistics import median

from bardocompute.exchange import ExchangeResult
from exchange_conservation import FlowPreservingMembrane
from storage_reserve import ElasticStorageMembrane
from real_work_queue_transfer import (
    BASE_BUFFER,
    CRITICAL_STRESS,
    INITIAL_STRESS,
    MAX_STRESS,
    MAX_ACTUATOR_OCCUPANCY,
    MAX_MEDIAN_CRITICAL_RATIO,
    MAX_MEDIAN_LOST_RATIO,
    MAX_MEDIAN_SECONDS_PER_COMPLETION_RATIO,
    MIN_ACTUATOR_OCCUPANCY,
    MIN_BASELINE_CRITICAL_SEED_FRACTION,
    MIN_MEDIAN_COMPLETED_RATIO,
    STRESS_SMOOTHING,
    TransferStats,
    _execute_batch,
    build_epochs,
    calibrate_rounds,
    run_policy as run_r1_policy,
)

# R2 changes only the observation model used to feed the already-frozen
# v0.18 controller.  No route/rate/relief/storage actuator changes are allowed.
#
# R1 normalized backlog by the *current* buffer limit.  Because elastic storage
# itself changes that limit (256 -> 2048), the actuator could change the sensor
# scale that decides whether protection is needed.  R2 pins backlog pressure to
# the immutable baseline service buffer and adds directly observed deadline-miss
# pressure.  The spent R1 seed family is not reused.

SEEDS = (5_100_121, 5_200_123, 5_300_129, 5_400_131)


def _sensor_independent_stress(
    previous: float,
    *,
    elapsed: float,
    deadline: float,
    backlog: int,
    released: int,
    on_time: int,
) -> float:
    latency_ratio = elapsed / max(1e-9, deadline)
    backlog_ratio = backlog / BASE_BUFFER
    miss_fraction = max(0, released - on_time) / max(1, released)

    # Each component has a stable physical reference independent of actuator
    # state: deadline, baseline retention capacity, or released work.
    instant = min(
        MAX_STRESS,
        max(
            100.0 * latency_ratio,
            100.0 * backlog_ratio,
            100.0 * miss_fraction,
        ),
    )
    alpha = STRESS_SMOOTHING
    return max(0.0, min(MAX_STRESS, (1.0 - alpha) * previous + alpha * instant))


def run_r2_policy(
    epochs,
    *,
    controller,
    rounds: int,
    deadline_seconds: float,
) -> TransferStats:
    from concurrent.futures import ThreadPoolExecutor

    stats = TransferStats()
    backlog = 0
    stress = INITIAL_STRESS

    for phase in (
        "normal",
        "burst",
        "primary_degraded",
        "global_congested",
        "recovery",
        "drain",
    ):
        stats.phase_release[phase] = []
        stats.phase_secondary[phase] = []

    if hasattr(controller, "set_stress"):
        controller.set_stress(stress)

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        from real_work_queue_transfer import _work

        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()

        queue = list(epochs)
        from real_work_queue_transfer import EpochSpec

        queue.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

        for spec in queue:
            if spec.phase == "drain" and backlog == 0:
                break

            if hasattr(controller, "set_stress"):
                controller.set_stress(stress)
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("R2 forbids voluntary admission shedding")

            stats.incoming += spec.incoming
            available_capacity = max(0, command.buffer_limit - backlog)
            admitted = min(spec.incoming, available_capacity)
            overflow = spec.incoming - admitted
            backlog += admitted
            stats.lost += overflow

            released = min(backlog, command.release_limit)
            backlog -= released

            relief_active = bool(getattr(controller, "current_boost", 0.0) > 0.0)
            storage_active = command.buffer_limit > BASE_BUFFER
            stats.relief_epochs += int(relief_active)
            stats.storage_epochs += int(storage_active)

            relief_count = 0
            if relief_active and released:
                from real_work_queue_transfer import RELIEF_TASK_FRACTION

                relief_count = min(
                    released, int(round(released * RELIEF_TASK_FRACTION))
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
            result = ExchangeResult(
                admitted=admitted,
                gate_rejected=0,
                released=released,
                primary_requested=primary_count,
                secondary_requested=secondary_count,
                primary_delivered=p_on,
                secondary_delivered=s_on,
                delivered=on_time,
                congestion=max(0, released - on_time),
                buffered=backlog,
                overflow_dropped=overflow,
            )
            controller.observe(result)

            stress = _sensor_independent_stress(
                stress,
                elapsed=elapsed,
                deadline=deadline_seconds,
                backlog=backlog,
                released=released,
                on_time=on_time,
            )
            stats.max_stress = max(stats.max_stress, stress)
            stats.critical_epochs += int(stress >= CRITICAL_STRESS)
            stats.phase_release[spec.phase].append(command.release_limit)
            stats.phase_secondary[spec.phase].append(command.secondary_fraction)

    stats.terminal_backlog = backlog
    return stats


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=real_work_queue_sensor_independent_transfer_r2")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("actuators=unchanged_v0.18_route_rate_relief_storage")
    print("sensor_denominator=immutable_baseline_buffer")
    print("future_phase_information=false")
    print("admission_shedding=false")

    baseline_critical_seeds = 0
    critical_ratios: list[float] = []
    completed_ratios: list[float] = []
    lost_ratios: list[float] = []
    seconds_ratios: list[float] = []
    relief_occupancies: list[float] = []
    storage_occupancies: list[float] = []
    terminal_backlogs: list[int] = []
    r2_vs_r1_critical: list[float] = []
    total_mismatches = 0

    for seed in SEEDS:
        epochs = build_epochs(seed)
        baseline = run_r2_policy(
            epochs,
            controller=FlowPreservingMembrane(route_enabled=True),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        r1 = run_r1_policy(
            epochs,
            controller=ElasticStorageMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        r2 = run_r2_policy(
            epochs,
            controller=ElasticStorageMembrane(),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )

        baseline_critical_seeds += int(baseline.critical_epochs > 0)
        critical_ratio = r2.critical_epochs / max(1, baseline.critical_epochs)
        completed_ratio = r2.completed / max(1, baseline.completed)
        lost_ratio = r2.lost / max(1, baseline.lost)
        seconds_ratio = r2.seconds_per_completion() / max(
            1e-12, baseline.seconds_per_completion()
        )
        epoch_count = len(epochs) + 24
        relief_occ = r2.relief_epochs / epoch_count
        storage_occ = r2.storage_epochs / epoch_count
        improvement = r2.critical_epochs / max(1, r1.critical_epochs)

        critical_ratios.append(critical_ratio)
        completed_ratios.append(completed_ratio)
        lost_ratios.append(lost_ratio)
        seconds_ratios.append(seconds_ratio)
        relief_occupancies.append(relief_occ)
        storage_occupancies.append(storage_occ)
        terminal_backlogs.append(r2.terminal_backlog)
        r2_vs_r1_critical.append(improvement)
        total_mismatches += (
            baseline.digest_mismatches + r1.digest_mismatches + r2.digest_mismatches
        )

        print(
            f"seed={seed} baseline_critical={baseline.critical_epochs} "
            f"r1_sensor_critical={r1.critical_epochs} r2_critical={r2.critical_epochs} "
            f"critical_ratio={critical_ratio:.3f} r2_vs_r1_critical={improvement:.3f} "
            f"completed_ratio={completed_ratio:.3f} lost_ratio={lost_ratio:.3f} "
            f"seconds_per_completion_ratio={seconds_ratio:.3f} "
            f"relief_occupancy={relief_occ:.3f} storage_occupancy={storage_occ:.3f} "
            f"terminal_backlog={r2.terminal_backlog}"
        )

    informative_fraction = baseline_critical_seeds / len(SEEDS)
    passes = (
        informative_fraction >= MIN_BASELINE_CRITICAL_SEED_FRACTION
        and median(critical_ratios) <= MAX_MEDIAN_CRITICAL_RATIO
        and median(completed_ratios) >= MIN_MEDIAN_COMPLETED_RATIO
        and median(lost_ratios) <= MAX_MEDIAN_LOST_RATIO
        and median(seconds_ratios) <= MAX_MEDIAN_SECONDS_PER_COMPLETION_RATIO
        and MIN_ACTUATOR_OCCUPANCY
        <= median(relief_occupancies)
        <= MAX_ACTUATOR_OCCUPANCY
        and MIN_ACTUATOR_OCCUPANCY
        <= median(storage_occupancies)
        <= MAX_ACTUATOR_OCCUPANCY
        and total_mismatches == 0
        and median(terminal_backlogs) == 0
    )

    print("\n[overall]")
    print(f"baseline_critical_seed_fraction={informative_fraction:.3f}")
    print(f"median_critical_ratio={median(critical_ratios):.3f}")
    print(f"median_r2_vs_r1_critical={median(r2_vs_r1_critical):.3f}")
    print(
        f"median_completed_ratio={median(completed_ratios):.3f} "
        f"median_lost_ratio={median(lost_ratios):.3f} "
        f"median_seconds_per_completion_ratio={median(seconds_ratios):.3f}"
    )
    print(
        f"median_relief_occupancy={median(relief_occupancies):.3f} "
        f"median_storage_occupancy={median(storage_occupancies):.3f} "
        f"median_terminal_backlog={median(terminal_backlogs):.1f}"
    )
    print(f"digest_mismatches={total_mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")
    print(
        "interpretation=R2 tests whether the R1 transfer failure came from an "
        "actuator-dependent sensor scale. The v0.18 actuators are unchanged; "
        "only real-work viability observation is made independent of elastic "
        "storage capacity."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
