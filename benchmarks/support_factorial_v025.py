from __future__ import annotations

from statistics import median

from bardocompute.exchange import MembraneCommand
from bidirectional_homeostasis import BOOST_AMOUNT, BOOSTED_SAFE_CAP
from exchange_conservation import FlowPreservingMembrane
from real_work_queue_outcome_audit_r3 import OutcomeStats, run_outcome_policy, safe_ratio
from real_work_queue_transfer import build_epochs, calibrate_rounds
from storage_reserve import ELASTIC_BUFFER_LIMIT

SEEDS = (
    13_100_401,
    13_200_409,
    13_300_419,
    13_400_421,
    13_500_431,
    13_600_433,
)

MIN_COMPLETED_PRESERVATION = 0.98
MAX_LOST_RATIO = 1.10
MAX_SECONDS_RATIO = 1.15
MAX_MISS_RATIO = 1.25
MAX_SEVERE_RATIO = 1.25


class FixedSupportMembrane:
    """Fixed support configuration for the v0.25 2x2 causal audit."""

    def __init__(self, *, relief: bool, rate_cap: bool) -> None:
        self.base = FlowPreservingMembrane(route_enabled=True)
        self.relief = relief
        self.rate_cap = rate_cap
        self.current_boost = BOOST_AMOUNT if relief else 0.0

    def command(self) -> MembraneCommand:
        base = self.base.command()
        if base.admission_limit is not None:
            raise AssertionError("v0.25 forbids voluntary admission shedding")
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

    def observe(self, result) -> None:
        self.base.observe(result)


def ratios(candidate: OutcomeStats, reference: OutcomeStats) -> dict[str, float]:
    return {
        "completed": safe_ratio(candidate.completed, reference.completed),
        "lost": safe_ratio(candidate.lost, reference.lost),
        "seconds": safe_ratio(
            candidate.seconds_per_completion(), reference.seconds_per_completion()
        ),
        "miss": safe_ratio(
            candidate.deadline_miss_epochs, reference.deadline_miss_epochs
        ),
        "severe": safe_ratio(
            candidate.severe_miss_epochs, reference.severe_miss_epochs
        ),
    }


def eligible(rows: list[dict[str, float]], stats: list[OutcomeStats]) -> bool:
    return (
        median(row["completed"] for row in rows) >= MIN_COMPLETED_PRESERVATION
        and median(row["lost"] for row in rows) <= MAX_LOST_RATIO
        and median(row["seconds"] for row in rows) <= MAX_SECONDS_RATIO
        and median(row["miss"] for row in rows) <= MAX_MISS_RATIO
        and median(row["severe"] for row in rows) <= MAX_SEVERE_RATIO
        and median(row.terminal_backlog for row in stats) == 0
        and sum(row.digest_mismatches for row in stats) == 0
    )


def summarize(name: str, stats: list[OutcomeStats], baseline: list[OutcomeStats]) -> None:
    rows = [ratios(candidate, ref) for candidate, ref in zip(stats, baseline, strict=True)]
    print(f"\n[{name}]")
    print(
        f"median_completed_vs_baseline={median(row['completed'] for row in rows):.3f} "
        f"median_lost_vs_baseline={median(row['lost'] for row in rows):.3f} "
        f"median_seconds_vs_baseline={median(row['seconds'] for row in rows):.3f}"
    )
    print(
        f"median_miss_vs_baseline={median(row['miss'] for row in rows):.3f} "
        f"median_severe_vs_baseline={median(row['severe'] for row in rows):.3f}"
    )
    print(
        f"median_relief_occupancy={median(row.relief_occupancy() for row in stats):.3f} "
        f"median_storage_occupancy={median(row.storage_occupancy() for row in stats):.3f} "
        f"median_peak_backlog={median(row.peak_backlog for row in stats):.1f} "
        f"median_terminal_backlog={median(row.terminal_backlog for row in stats):.1f}"
    )
    print(f"digest_mismatches={sum(row.digest_mismatches for row in stats)}")


def main() -> None:
    rounds, calibrated_task_seconds = calibrate_rounds()
    deadline_seconds = max(0.025, calibrated_task_seconds * 48.0)

    print("benchmark=support_component_factorial_v0.25")
    print(f"seeds={len(SEEDS)}")
    print(f"calibrated_rounds={rounds}")
    print(f"calibrated_task_seconds={calibrated_task_seconds:.6f}")
    print(f"epoch_deadline_seconds={deadline_seconds:.6f}")
    print("design=2x2_RELIEF_x_RATE_CAP")
    print("storage=constant_ELASTIC_BUFFER_LIMIT")
    print("route=existing_FlowPreservingMembrane")
    print("new_actuator_magnitudes=false")
    print("future_phase_information=false")
    print("admission_shedding=false")
    print("external_outcome_judge=R3_independent_vector")

    names = ("full_support", "rate_cap_only", "relief_only", "storage_only")
    stats_by_name: dict[str, list[OutcomeStats]] = {name: [] for name in names}
    baseline_stats: list[OutcomeStats] = []

    for seed in SEEDS:
        epochs = build_epochs(seed)
        baseline = run_outcome_policy(
            epochs,
            controller=FlowPreservingMembrane(route_enabled=True),
            sensor_mode=None,
            rounds=rounds,
            deadline_seconds=deadline_seconds,
        )
        baseline_stats.append(baseline)

        controllers = {
            "full_support": FixedSupportMembrane(relief=True, rate_cap=True),
            "rate_cap_only": FixedSupportMembrane(relief=False, rate_cap=True),
            "relief_only": FixedSupportMembrane(relief=True, rate_cap=False),
            "storage_only": FixedSupportMembrane(relief=False, rate_cap=False),
        }
        current: dict[str, OutcomeStats] = {}
        for name, controller in controllers.items():
            current[name] = run_outcome_policy(
                epochs,
                controller=controller,
                sensor_mode=None,
                rounds=rounds,
                deadline_seconds=deadline_seconds,
            )
            stats_by_name[name].append(current[name])

        a = current["full_support"]
        b = current["rate_cap_only"]
        c = current["relief_only"]
        d = current["storage_only"]
        print(
            f"seed={seed} "
            f"A_miss={a.deadline_miss_epochs} A_severe={a.severe_miss_epochs} "
            f"B_miss={b.deadline_miss_epochs} B_severe={b.severe_miss_epochs} "
            f"C_miss={c.deadline_miss_epochs} C_severe={c.severe_miss_epochs} "
            f"D_miss={d.deadline_miss_epochs} D_severe={d.severe_miss_epochs} "
            f"B_vs_A_miss={safe_ratio(b.deadline_miss_epochs, a.deadline_miss_epochs):.3f} "
            f"C_vs_A_miss={safe_ratio(c.deadline_miss_epochs, a.deadline_miss_epochs):.3f} "
            f"D_vs_B_miss={safe_ratio(d.deadline_miss_epochs, b.deadline_miss_epochs):.3f} "
            f"D_vs_C_miss={safe_ratio(d.deadline_miss_epochs, c.deadline_miss_epochs):.3f}"
        )

    for name in names:
        summarize(name, stats_by_name[name], baseline_stats)

    full = stats_by_name["full_support"]
    comparisons: dict[str, list[dict[str, float]]] = {}
    for name in ("rate_cap_only", "relief_only", "storage_only"):
        comparisons[name] = [
            ratios(candidate, ref)
            for candidate, ref in zip(stats_by_name[name], full, strict=True)
        ]

    eligible_b = eligible(comparisons["rate_cap_only"], stats_by_name["rate_cap_only"])
    eligible_c = eligible(comparisons["relief_only"], stats_by_name["relief_only"])
    eligible_d = eligible(comparisons["storage_only"], stats_by_name["storage_only"])

    # Independent value means removing the component materially worsens miss or
    # severe-miss behavior while preserving the other support component.
    b_rows = comparisons["rate_cap_only"]  # RELIEF removed, CAP retained
    c_rows = comparisons["relief_only"]    # CAP removed, RELIEF retained

    relief_has_independent_value = (
        median(row["miss"] for row in b_rows) > MAX_MISS_RATIO
        or median(row["severe"] for row in b_rows) > MAX_SEVERE_RATIO
    )
    rate_cap_has_independent_value = (
        median(row["miss"] for row in c_rows) > MAX_MISS_RATIO
        or median(row["severe"] for row in c_rows) > MAX_SEVERE_RATIO
    )

    # Interaction is present when neither single-component arm preserves full
    # support quality but the combined arm does by definition.
    support_interaction_present = not eligible_b and not eligible_c

    print("\n[causal_factorial]")
    print(
        f"rate_cap_only_vs_full_completed={median(row['completed'] for row in b_rows):.3f} "
        f"rate_cap_only_vs_full_miss={median(row['miss'] for row in b_rows):.3f} "
        f"rate_cap_only_vs_full_severe={median(row['severe'] for row in b_rows):.3f}"
    )
    print(
        f"relief_only_vs_full_completed={median(row['completed'] for row in c_rows):.3f} "
        f"relief_only_vs_full_miss={median(row['miss'] for row in c_rows):.3f} "
        f"relief_only_vs_full_severe={median(row['severe'] for row in c_rows):.3f}"
    )
    print(f"rate_cap_only_eligible={str(eligible_b).lower()}")
    print(f"relief_only_eligible={str(eligible_c).lower()}")
    print(f"storage_only_eligible={str(eligible_d).lower()}")
    print(f"rate_cap_has_independent_value={str(rate_cap_has_independent_value).lower()}")
    print(f"relief_has_independent_value={str(relief_has_independent_value).lower()}")
    print(f"support_interaction_present={str(support_interaction_present).lower()}")
    print("factorial_complete=true")
    print(
        "interpretation=v0.25 holds ROUTE and STORAGE constant while factorially "
        "ablating the existing RELIEF and RATE-cap support components. It is a "
        "causal component-value audit, not promotion of a new adaptive controller."
    )


if __name__ == "__main__":
    main()
