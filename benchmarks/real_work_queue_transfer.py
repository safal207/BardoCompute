from __future__ import annotations

import hashlib
import math
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from statistics import median

from bardocompute.exchange import ExchangeResult
from exchange_conservation import FlowPreservingMembrane
from storage_reserve import AlwaysExpandedMembrane, ElasticStorageMembrane

# Real executed micro-workload transfer R1.
#
# This is intentionally not called a production benchmark.  The payload work is
# real SHA-256 execution and the metrics use wall-clock completion, while route
# degradation is controlled fault injection.  The v0.18 control structure is
# reused unchanged: route/rate feedback, protective relief, and elastic storage.

SEEDS = (4_100_101, 4_200_103, 4_300_107, 4_400_113)
PAYLOAD = bytes((i * 37 + 11) % 256 for i in range(64 * 1024))
EXPECTED_DIGEST = hashlib.sha256(PAYLOAD).digest()
INITIAL_STRESS = 45.0
CRITICAL_STRESS = 100.0
MAX_STRESS = 150.0
BASE_BUFFER = 256
ELASTIC_BUFFER = 2048

# Controller thresholds and actuators are inherited from v0.18.  Only the
# mapping from measured queue/latency pressure to its normalized stress signal
# is new for this transfer.
STRESS_SMOOTHING = 0.40
RELIEF_TASK_FRACTION = 0.50

# Pre-registered acceptance.  Do not retune these values on this seed family.
MIN_BASELINE_CRITICAL_SEED_FRACTION = 0.75
MAX_MEDIAN_CRITICAL_RATIO = 0.25
MIN_MEDIAN_COMPLETED_RATIO = 0.98
MAX_MEDIAN_LOST_RATIO = 0.75
MAX_MEDIAN_SECONDS_PER_COMPLETION_RATIO = 1.15
MIN_ACTUATOR_OCCUPANCY = 0.02
MAX_ACTUATOR_OCCUPANCY = 0.60
MAX_MEDIAN_LOST_VS_ALWAYS_EXPANDED = 1.05


@dataclass(frozen=True, slots=True)
class EpochSpec:
    phase: str
    incoming: int
    primary_multiplier: float
    secondary_multiplier: float


@dataclass(slots=True)
class TransferStats:
    incoming: int = 0
    completed: int = 0
    lost: int = 0
    critical_epochs: int = 0
    max_stress: float = 0.0
    wall_seconds: float = 0.0
    digest_mismatches: int = 0
    relief_epochs: int = 0
    storage_epochs: int = 0
    terminal_backlog: int = 0
    phase_release: dict[str, list[int]] = field(default_factory=dict)
    phase_secondary: dict[str, list[float]] = field(default_factory=dict)

    def seconds_per_completion(self) -> float:
        return self.wall_seconds / max(1, self.completed)


def _work(rounds: int) -> tuple[bytes, float]:
    # The returned service result is route-independent.  Extra rounds are CPU
    # contention only and cannot change task correctness.
    digest = EXPECTED_DIGEST
    junk = 0
    for _ in range(max(1, rounds)):
        junk ^= hashlib.sha256(PAYLOAD).digest()[0]
    if junk == -1:  # impossible, prevents the ballast variable being dead code
        raise AssertionError("unreachable")
    return digest, time.perf_counter()


def calibrate_rounds() -> tuple[int, float]:
    """Choose real work so one task is roughly 0.8-1.6 ms on this runner."""
    rounds = 1
    target = 0.0010
    measured = 0.0
    while rounds <= 4096:
        start = time.perf_counter()
        for _ in range(4):
            _work(rounds)
        measured = (time.perf_counter() - start) / 4.0
        if measured >= target:
            break
        rounds *= 2
    return rounds, measured


def build_epochs(seed: int) -> tuple[EpochSpec, ...]:
    rng = random.Random(seed)
    phases = (
        ("normal", 6, 48, 1.0, 1.15),
        ("burst", 8, 108, 1.0, 1.15),
        ("primary_degraded", 10, 92, 6.0, 1.15),
        ("global_congested", 10, 88, 5.0, 5.0),
        ("recovery", 12, 48, 1.0, 1.15),
    )
    rows: list[EpochSpec] = []
    for phase, count, incoming, primary_mult, secondary_mult in phases:
        for _ in range(count):
            jitter = rng.randint(-5, 5)
            rows.append(
                EpochSpec(
                    phase=phase,
                    incoming=max(0, incoming + jitter),
                    primary_multiplier=primary_mult,
                    secondary_multiplier=secondary_mult,
                )
            )
    return tuple(rows)


def _execute_batch(
    *,
    primary: ThreadPoolExecutor,
    secondary: ThreadPoolExecutor,
    relief: ThreadPoolExecutor,
    primary_count: int,
    secondary_count: int,
    relief_count: int,
    rounds: int,
    primary_multiplier: float,
    secondary_multiplier: float,
    deadline_seconds: float,
) -> tuple[float, int, int, int, int]:
    start = time.perf_counter()
    futures: list[tuple[str, object]] = []

    primary_rounds = max(1, int(round(rounds * primary_multiplier)))
    secondary_rounds = max(1, int(round(rounds * secondary_multiplier)))

    for _ in range(primary_count):
        futures.append(("primary", primary.submit(_work, primary_rounds)))
    for _ in range(secondary_count):
        futures.append(("secondary", secondary.submit(_work, secondary_rounds)))
    for _ in range(relief_count):
        futures.append(("relief", relief.submit(_work, rounds)))

    on_time_primary = 0
    on_time_secondary = 0
    on_time_relief = 0
    mismatches = 0
    last_finish = start
    deadline = start + deadline_seconds

    for route, future in futures:
        digest, finish = future.result()
        last_finish = max(last_finish, finish)
        if digest != EXPECTED_DIGEST:
            mismatches += 1
        if finish <= deadline:
            if route == "primary":
                on_time_primary += 1
            elif route == "secondary":
                on_time_secondary += 1
            else:
                on_time_relief += 1

    return (
        max(0.0, last_finish - start),
        on_time_primary,
        on_time_secondary,
        on_time_relief,
        mismatches,
    )


def _normalize_stress(
    previous: float,
    *,
    elapsed: float,
    deadline: float,
    backlog: int,
    buffer_limit: int,
) -> float:
    latency_ratio = elapsed / max(1e-9, deadline)
    backlog_ratio = backlog / max(1, buffer_limit)
    instant = min(MAX_STRESS, 60.0 * latency_ratio + 70.0 * backlog_ratio)
    alpha = STRESS_SMOOTHING
    return max(0.0, min(MAX_STRESS, (1.0 - alpha) * previous + alpha * instant))


def run_policy(
    epochs: tuple[EpochSpec, ...],
    *,
    controller,
    rounds: int,
    deadline_seconds: float,
) -> TransferStats:
    stats = TransferStats()
    backlog = 0
    stress = INITIAL_STRESS

    for phase in ("normal", "burst", "primary_degraded", "global_congested", "recovery", "drain"):
        stats.phase_release[phase] = []
        stats.phase_secondary[phase] = []

    if hasattr(controller, "set_stress"):
        controller.set_stress(stress)

    with (
        ThreadPoolExecutor(max_workers=1) as primary,
        ThreadPoolExecutor(max_workers=1) as secondary,
        ThreadPoolExecutor(max_workers=1) as relief,
    ):
        # Warm worker creation outside measured epochs.
        primary.submit(_work, 1).result()
        secondary.submit(_work, 1).result()
        relief.submit(_work, 1).result()

        queue = list(epochs)
        # Recovery drain has no new arrivals.  It proves retained work can
        # re-enter service instead of remaining parked indefinitely.
        queue.extend(EpochSpec("drain", 0, 1.0, 1.15) for _ in range(24))

        for spec in queue:
            if spec.phase == "drain" and backlog == 0:
                break

            if hasattr(controller, "set_stress"):
                controller.set_stress(stress)
            command = controller.command()
            if command.admission_limit is not None:
                raise AssertionError("R1 forbids voluntary admission shedding")

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
                relief_count = min(released, int(round(released * RELIEF_TASK_FRACTION)))
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

            stress = _normalize_stress(
                stress,
                elapsed=elapsed,
                deadline=deadline_seconds,
                backlog=backlog,
                buffer_limit=command.buffer_limit,
            )
            stats.max_stress = max(stats.max_stress, stress)
            stats.critical_epochs += int(stress >= CRITICAL_STRESS)
            stats.phase_release[spec.phase].append(command.release_limit)
            stats.phase_secondary[spec.phase].append(command.secondary_fraction)

    stats.terminal_backlog = backlog
    return stats


def nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    # Two normal lanes each handle roughly half of an 80-task release.
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=real_executed_work_queue_transfer_r1")
    print(f"python_threads_cpu_count={os.cpu_count()}")
    print(f"seeds={len(SEEDS)}")
    print(f"payload_bytes={len(PAYLOAD)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("work=real_sha256_execution")
    print("fault_injection=controlled_cpu_ballast_by_route")
    print("controller=v0.18_structure_unchanged")
    print("future_phase_information=false")
    print("admission_shedding=false")

    critical_ratios: list[float] = []
    completed_ratios: list[float] = []
    lost_ratios: list[float] = []
    sec_per_completion_ratios: list[float] = []
    lost_vs_always: list[float] = []
    relief_occupancies: list[float] = []
    storage_occupancies: list[float] = []
    baseline_critical_seeds = 0
    total_mismatches = 0
    elastic_rows: list[TransferStats] = []

    for seed in SEEDS:
        epochs = build_epochs(seed)

        baseline = run_policy(
            epochs,
            controller=FlowPreservingMembrane(route_enabled=True),
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        elastic_controller = ElasticStorageMembrane()
        elastic = run_policy(
            epochs,
            controller=elastic_controller,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        always_controller = AlwaysExpandedMembrane()
        always = run_policy(
            epochs,
            controller=always_controller,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        elastic_rows.append(elastic)

        baseline_critical_seeds += int(baseline.critical_epochs > 0)
        critical_ratio = elastic.critical_epochs / max(1, baseline.critical_epochs)
        completed_ratio = elastic.completed / max(1, baseline.completed)
        lost_ratio = elastic.lost / max(1, baseline.lost)
        sec_ratio = elastic.seconds_per_completion() / max(
            1e-12, baseline.seconds_per_completion()
        )
        always_lost_ratio = elastic.lost / max(1, always.lost)
        epoch_count = len(epochs) + 24
        relief_occ = elastic.relief_epochs / epoch_count
        storage_occ = elastic.storage_epochs / epoch_count

        critical_ratios.append(critical_ratio)
        completed_ratios.append(completed_ratio)
        lost_ratios.append(lost_ratio)
        sec_per_completion_ratios.append(sec_ratio)
        lost_vs_always.append(always_lost_ratio)
        relief_occupancies.append(relief_occ)
        storage_occupancies.append(storage_occ)
        total_mismatches += (
            baseline.digest_mismatches
            + elastic.digest_mismatches
            + always.digest_mismatches
        )

        print(
            f"seed={seed} "
            f"baseline_critical={baseline.critical_epochs} "
            f"elastic_critical={elastic.critical_epochs} "
            f"critical_ratio={critical_ratio:.3f} "
            f"completed_ratio={completed_ratio:.3f} "
            f"lost_ratio={lost_ratio:.3f} "
            f"seconds_per_completion_ratio={sec_ratio:.3f} "
            f"elastic_vs_always_lost={always_lost_ratio:.3f} "
            f"relief_occupancy={relief_occ:.3f} "
            f"storage_occupancy={storage_occ:.3f} "
            f"terminal_backlog={elastic.terminal_backlog}"
        )

    informative_fraction = baseline_critical_seeds / len(SEEDS)
    passes = (
        informative_fraction >= MIN_BASELINE_CRITICAL_SEED_FRACTION
        and median(critical_ratios) <= MAX_MEDIAN_CRITICAL_RATIO
        and median(completed_ratios) >= MIN_MEDIAN_COMPLETED_RATIO
        and median(lost_ratios) <= MAX_MEDIAN_LOST_RATIO
        and median(sec_per_completion_ratios)
        <= MAX_MEDIAN_SECONDS_PER_COMPLETION_RATIO
        and MIN_ACTUATOR_OCCUPANCY <= median(relief_occupancies) <= MAX_ACTUATOR_OCCUPANCY
        and MIN_ACTUATOR_OCCUPANCY <= median(storage_occupancies) <= MAX_ACTUATOR_OCCUPANCY
        and median(lost_vs_always) <= MAX_MEDIAN_LOST_VS_ALWAYS_EXPANDED
        and total_mismatches == 0
        and median(row.terminal_backlog for row in elastic_rows) == 0
    )

    print("\n[overall]")
    print(f"baseline_critical_seed_fraction={informative_fraction:.3f}")
    print(
        f"median_critical_ratio={median(critical_ratios):.3f} "
        f"p90_critical_ratio={nearest_rank(critical_ratios, .90):.3f}"
    )
    print(
        f"median_completed_ratio={median(completed_ratios):.3f} "
        f"median_lost_ratio={median(lost_ratios):.3f} "
        f"median_seconds_per_completion_ratio={median(sec_per_completion_ratios):.3f}"
    )
    print(
        f"median_elastic_vs_always_lost={median(lost_vs_always):.3f} "
        f"median_relief_occupancy={median(relief_occupancies):.3f} "
        f"median_storage_occupancy={median(storage_occupancies):.3f} "
        f"median_terminal_backlog={median(row.terminal_backlog for row in elastic_rows):.1f}"
    )
    print(f"digest_mismatches={total_mismatches}")
    print(f"passes_preregistered_acceptance={str(passes).lower()}")

    print("\n[posthoc_command_morphology]")
    for phase in ("normal", "burst", "primary_degraded", "global_congested", "recovery"):
        releases = [value for row in elastic_rows for value in row.phase_release[phase]]
        shares = [value for row in elastic_rows for value in row.phase_secondary[phase]]
        print(
            f"{phase}: median_release={median(releases):.1f} "
            f"median_secondary_fraction={median(shares):.3f}"
        )

    print(
        "interpretation=R1 transfers the already-frozen route/rate/relief/storage "
        "control structure to real executed SHA-256 work with wall-clock queue "
        "pressure. Controlled CPU ballast is fault injection, not a production "
        "trace. A pass supports transfer of the control pattern only."
    )

    if not passes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
