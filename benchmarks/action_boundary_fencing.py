from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from bardocompute.capability import CapabilityMode
from bardocompute.stochastic import StochasticCapabilityState
from recovery_state_transfer import (
    HAZARDS,
    PROBE_COSTS,
    SEEDS,
    STALE_REGRETS,
    HazardEstimator,
    RecoveryEnvironment,
    build_environment,
    cadence,
    process_authoritative_probe,
)

FIXED_CADENCES = (1, 8, 32, 128)


@dataclass(slots=True)
class ActionStats:
    probes: int = 0
    attempted_actions: int = 0
    accepted_actions: int = 0
    unsafe_accepted_actions: int = 0
    fence_rejections: int = 0
    local_holds: int = 0
    stale_attempts: int = 0
    interval_sum: int = 0
    interval_count: int = 0
    interval_by_hazard_sum: dict[float, int] = field(default_factory=dict)
    interval_by_hazard_count: dict[float, int] = field(default_factory=dict)

    @property
    def acceptance_rate(self) -> float:
        total = self.accepted_actions + self.fence_rejections + self.local_holds
        return self.accepted_actions / total if total else 1.0


@dataclass(slots=True)
class ReceiptCounters:
    stale_receipts: int = 0
    premature_receipts: int = 0
    duplicate_receipts: int = 0


def selected_interval(
    *,
    mode: str,
    estimator: HazardEstimator,
    environment: RecoveryEnvironment,
    step: int,
    probe_cost: float,
    stale_regret: float,
    fixed_interval: int | None,
) -> int:
    if fixed_interval is not None:
        return fixed_interval
    if mode == "oracle":
        return cadence(environment.hazards[step], probe_cost, stale_regret)
    return cadence(estimator.value(), probe_cost, stale_regret)


def run(
    environment: RecoveryEnvironment,
    *,
    seed: int,
    probe_cost: float,
    stale_regret: float,
    mode: str,
    fenced: bool,
    fixed_interval: int | None = None,
) -> ActionStats:
    """Run one observer schedule with or without authoritative action fencing.

    Observation and enforcement are deliberately separated.

    The client only learns a new authority epoch through its paid probe path.
    It attempts a protected action only while its existing local recovery guard
    says MANIFEST. A fenced resource additionally compares the client's epoch
    token with the resource's current authoritative epoch and rejects stale
    operations. The resource therefore prevents a stale effect even if the
    client has not yet observed the authority change.
    """

    stats = ActionStats(
        interval_by_hazard_sum={hazard: 0 for hazard in HAZARDS},
        interval_by_hazard_count={hazard: 0 for hazard in HAZARDS},
    )
    estimator = HazardEstimator(mode=mode if mode in {"ewma", "rolling"} else "ewma")
    state = StochasticCapabilityState()
    authority_epoch = 0
    last_probe_epoch = 0
    last_probe_step = 0
    counters = ReceiptCounters()

    interval = selected_interval(
        mode=mode,
        estimator=estimator,
        environment=environment,
        step=0,
        probe_cost=probe_cost,
        stale_regret=stale_regret,
        fixed_interval=fixed_interval,
    )
    next_probe = 0 if interval == 1 else interval

    for step, restarted in enumerate(environment.restarts):
        if restarted:
            authority_epoch += 1

        # Probe before acting when the cadence says this tick is an observation
        # point. fixed=1 therefore represents an authoritative check before
        # every protected action.
        if step >= next_probe:
            stats.probes += 1
            exposure = max(1, step - last_probe_step)
            events = authority_epoch - last_probe_epoch
            if mode in {"ewma", "rolling"}:
                estimator.update(events, exposure)

            state = process_authoritative_probe(
                state,
                authority_epoch=authority_epoch,
                seed=seed,
                step=step,
                stats=counters,  # compatible receipt counters
            )

            last_probe_epoch = authority_epoch
            last_probe_step = step
            interval = selected_interval(
                mode=mode,
                estimator=estimator,
                environment=environment,
                step=step,
                probe_cost=probe_cost,
                stale_regret=stale_regret,
                fixed_interval=fixed_interval,
            )
            stats.interval_sum += interval
            stats.interval_count += 1
            hazard = environment.hazards[step]
            stats.interval_by_hazard_sum[hazard] += interval
            stats.interval_by_hazard_count[hazard] += 1
            next_probe = step + interval

        local_authorized = (
            state.mode is CapabilityMode.MANIFEST and not state.active_shock
        )
        if not local_authorized:
            stats.local_holds += 1
            continue

        stats.attempted_actions += 1
        stale_token = state.epoch != authority_epoch
        stats.stale_attempts += int(stale_token)

        if fenced and stale_token:
            stats.fence_rejections += 1
            continue

        stats.accepted_actions += 1
        stats.unsafe_accepted_actions += int(stale_token)

    return stats


def adversarial_lower_bound(interval: int) -> tuple[int, int]:
    """Restart one tick after a probe and act until the next probe.

    A pull-only observer cannot distinguish the changed world from the unchanged
    world before its next observation. Therefore it accepts interval-1 stale
    actions. A resource-side epoch fence rejects all of those same attempts.
    """

    if interval <= 1:
        return 0, 0
    pull_unsafe = interval - 1
    fenced_unsafe = 0
    return pull_unsafe, fenced_unsafe


def main() -> None:
    print("domain=authority_epoch_recovery_with_protected_actions")
    print("question=can_observation_cadence_alone_guarantee_zero_stale_effects")
    print("resource_fence=accept_only_if_client_epoch_equals_current_authority_epoch")
    print("future_restart_boundaries=hidden_from_client")
    print()

    print("[adversarial_indistinguishability_control]")
    for interval in FIXED_CADENCES:
        pull, fenced = adversarial_lower_bound(interval)
        print(
            f"interval={interval} pull_unsafe_accepted={pull} "
            f"fenced_unsafe_accepted={fenced}"
        )

    environments = [(seed, build_environment(seed)) for seed in SEEDS]
    print("\n[stochastic_transfer]")
    print(f"seeds={len(environments)}")

    for mode, fixed in (("fixed", 8), ("fixed", 32), ("ewma", None), ("rolling", None)):
        pull_unsafe: list[int] = []
        fenced_unsafe: list[int] = []
        fenced_rejects: list[int] = []
        fenced_acceptance: list[float] = []
        probes: list[int] = []

        # Use the middle cost profile only to instantiate the unchanged adaptive
        # cadence formula. Safety conclusions do not depend on scalar loss here.
        probe_cost = PROBE_COSTS[1]
        stale_regret = STALE_REGRETS[1]

        for seed, environment in environments:
            pull = run(
                environment,
                seed=seed,
                probe_cost=probe_cost,
                stale_regret=stale_regret,
                mode=mode,
                fenced=False,
                fixed_interval=fixed,
            )
            fenced = run(
                environment,
                seed=seed,
                probe_cost=probe_cost,
                stale_regret=stale_regret,
                mode=mode,
                fenced=True,
                fixed_interval=fixed,
            )

            # The action fence must not alter observation scheduling.
            assert pull.probes == fenced.probes
            assert pull.stale_attempts == fenced.stale_attempts
            assert pull.local_holds == fenced.local_holds

            pull_unsafe.append(pull.unsafe_accepted_actions)
            fenced_unsafe.append(fenced.unsafe_accepted_actions)
            fenced_rejects.append(fenced.fence_rejections)
            fenced_acceptance.append(fenced.acceptance_rate)
            probes.append(fenced.probes)

        label = f"fixed{fixed}" if fixed is not None else mode
        print(
            f"{label}: median_probes={median(probes):.1f} "
            f"median_pull_unsafe_accepted={median(pull_unsafe):.1f} "
            f"median_fenced_unsafe_accepted={median(fenced_unsafe):.1f} "
            f"median_fence_rejections={median(fenced_rejects):.1f} "
            f"median_fenced_acceptance_rate={median(fenced_acceptance):.6f}"
        )

    print(
        "interpretation=When authority changes are hidden between observations, "
        "any pull-only cadence greater than one tick has an unavoidable stale-action "
        "window. Tightening cadence shrinks that window but does not remove the "
        "information boundary. Moving monotonic authority enforcement to the protected "
        "resource converts stale effects into explicit rejections without changing "
        "the observer schedule. Observation can then optimize freshness/economics, "
        "while the action boundary owns stale-effect safety. The fence is not claimed "
        "to be free; this benchmark establishes semantics before measuring its runtime "
        "and availability cost."
    )


if __name__ == "__main__":
    main()
