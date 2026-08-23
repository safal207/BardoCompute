from __future__ import annotations

from dataclasses import dataclass
from random import Random
from time import perf_counter

from bardocompute.capability import (
    CapabilityMode,
    CapabilitySignal,
    step_capability_mode,
)
from bardocompute.stochastic import (
    StochasticCapabilityState,
    TaggedCapabilitySignal,
    step_stochastic_capability,
)


EPISODES = 50_000
SEED = 0xBADA55


@dataclass(frozen=True, slots=True)
class WorkloadCounts:
    second_shocks: int = 0
    premature_evidence: int = 0
    stale_evidence: int = 0
    duplicate_events: int = 0
    missing_final_evidence: int = 0


@dataclass(frozen=True, slots=True)
class Metrics:
    ticks: int
    wrong_mode_ticks: int
    unsafe_manifest_ticks: int
    final_false_recoveries: int
    unresolved_episodes: int
    seconds: float

    @property
    def correct_mode_rate(self) -> float:
        return 1.0 - self.wrong_mode_ticks / self.ticks

    @property
    def unsafe_manifest_rate(self) -> float:
        return self.unsafe_manifest_ticks / self.ticks


def event(signal: CapabilitySignal, epoch: int) -> TaggedCapabilitySignal:
    return TaggedCapabilitySignal(signal, epoch)


def build_workload() -> tuple[list[list[TaggedCapabilitySignal]], WorkloadCounts]:
    rng = Random(SEED)
    episodes: list[list[TaggedCapabilitySignal]] = []
    second_shocks = 0
    premature_evidence = 0
    stale_evidence = 0
    duplicate_events = 0
    missing_final_evidence = 0

    for _ in range(EPISODES):
        epoch = 1
        seq = [event(CapabilitySignal.ENVIRONMENT_CHANGE, epoch)]

        for _ in range(rng.randrange(3)):
            seq.append(event(CapabilitySignal.HOLD, epoch))

        if rng.random() < 0.30:
            seq.append(event(CapabilitySignal.EVIDENCE_READY, epoch))
            premature_evidence += 1

        seq.append(event(CapabilitySignal.GAP_DETECTED, epoch))
        if rng.random() < 0.25:
            seq.append(event(CapabilitySignal.GAP_DETECTED, epoch))
            duplicate_events += 1

        if rng.random() < 0.30:
            second_shocks += 1
            previous_epoch = epoch
            epoch += 1
            seq.append(event(CapabilitySignal.ENVIRONMENT_CHANGE, epoch))

            if rng.random() < 0.55:
                seq.append(event(CapabilitySignal.EVIDENCE_READY, previous_epoch))
                stale_evidence += 1

            for _ in range(rng.randrange(3)):
                seq.append(event(CapabilitySignal.HOLD, epoch))

            if rng.random() < 0.25:
                seq.append(event(CapabilitySignal.EVIDENCE_READY, epoch))
                premature_evidence += 1

            seq.append(event(CapabilitySignal.GAP_DETECTED, epoch))
            if rng.random() < 0.20:
                seq.append(event(CapabilitySignal.GAP_DETECTED, epoch))
                duplicate_events += 1

        for _ in range(rng.randrange(4)):
            seq.append(event(CapabilitySignal.HOLD, epoch))

        if rng.random() < 0.15:
            missing_final_evidence += 1
        else:
            seq.append(event(CapabilitySignal.EVIDENCE_READY, epoch))
            if rng.random() < 0.20:
                seq.append(event(CapabilitySignal.EVIDENCE_READY, epoch))
                duplicate_events += 1

        episodes.append(seq)

    return episodes, WorkloadCounts(
        second_shocks=second_shocks,
        premature_evidence=premature_evidence,
        stale_evidence=stale_evidence,
        duplicate_events=duplicate_events,
        missing_final_evidence=missing_final_evidence,
    )


def conventional_guard(
    state: StochasticCapabilityState,
    ev: TaggedCapabilitySignal,
) -> StochasticCapabilityState:
    # Intentionally independent implementation of the equal-information control.
    if ev.signal is CapabilitySignal.HOLD or ev.epoch < state.epoch:
        return state
    if ev.signal is CapabilitySignal.ENVIRONMENT_CHANGE:
        if ev.epoch == state.epoch:
            return state
        return StochasticCapabilityState(CapabilityMode.ADAPT, ev.epoch, True, False)
    if ev.epoch > state.epoch or not state.active_shock:
        return state
    if ev.signal is CapabilitySignal.GAP_DETECTED:
        return StochasticCapabilityState(CapabilityMode.ACQUIRE, state.epoch, True, True)
    if ev.signal is CapabilitySignal.EVIDENCE_READY:
        if not state.gap_seen:
            return state
        return StochasticCapabilityState(CapabilityMode.MANIFEST, state.epoch, False, False)
    raise ValueError(ev.signal)


def reference_states(
    episodes: list[list[TaggedCapabilitySignal]],
) -> list[list[StochasticCapabilityState]]:
    all_states: list[list[StochasticCapabilityState]] = []
    for seq in episodes:
        state = StochasticCapabilityState()
        states = []
        for ev in seq:
            state = step_stochastic_capability(state, ev)
            states.append(state)
        all_states.append(states)
    return all_states


def run_fixed(
    episodes: list[list[TaggedCapabilitySignal]],
    expected: list[list[StochasticCapabilityState]],
) -> Metrics:
    started = perf_counter()
    ticks = wrong = unsafe = false_recovery = unresolved = 0
    for seq, truth in zip(episodes, expected, strict=True):
        for _, reference in zip(seq, truth, strict=True):
            ticks += 1
            wrong += CapabilityMode.MANIFEST is not reference.mode
            unsafe += reference.active_shock
        final = truth[-1]
        false_recovery += final.active_shock
        unresolved += final.active_shock
    return Metrics(ticks, wrong, unsafe, false_recovery, unresolved, perf_counter() - started)


def run_naive(
    episodes: list[list[TaggedCapabilitySignal]],
    expected: list[list[StochasticCapabilityState]],
) -> Metrics:
    started = perf_counter()
    ticks = wrong = unsafe = false_recovery = unresolved = 0
    for seq, truth in zip(episodes, expected, strict=True):
        mode = CapabilityMode.MANIFEST
        for ev, reference in zip(seq, truth, strict=True):
            mode = step_capability_mode(mode, ev.signal)
            ticks += 1
            wrong += mode is not reference.mode
            unsafe += mode is CapabilityMode.MANIFEST and reference.active_shock
        final = truth[-1]
        false_recovery += mode is CapabilityMode.MANIFEST and final.active_shock
        unresolved += mode is not CapabilityMode.MANIFEST
    return Metrics(ticks, wrong, unsafe, false_recovery, unresolved, perf_counter() - started)


def run_guarded(
    episodes: list[list[TaggedCapabilitySignal]],
    expected: list[list[StochasticCapabilityState]],
    stepper,
) -> Metrics:
    started = perf_counter()
    ticks = wrong = unsafe = false_recovery = unresolved = 0
    for seq, truth in zip(episodes, expected, strict=True):
        state = StochasticCapabilityState()
        for ev, reference in zip(seq, truth, strict=True):
            state = stepper(state, ev)
            ticks += 1
            wrong += state != reference
            unsafe += state.mode is CapabilityMode.MANIFEST and reference.active_shock
        final = truth[-1]
        false_recovery += state.mode is CapabilityMode.MANIFEST and final.active_shock
        unresolved += state.active_shock
    return Metrics(ticks, wrong, unsafe, false_recovery, unresolved, perf_counter() - started)


def print_metrics(name: str, metrics: Metrics) -> None:
    print(f"[{name}]")
    print(f"ticks={metrics.ticks}")
    print(f"wrong_mode_ticks={metrics.wrong_mode_ticks}")
    print(f"unsafe_manifest_ticks={metrics.unsafe_manifest_ticks}")
    print(f"final_false_recoveries={metrics.final_false_recoveries}")
    print(f"unresolved_episodes={metrics.unresolved_episodes}")
    print(f"correct_mode_rate={metrics.correct_mode_rate:.6f}")
    print(f"unsafe_manifest_rate={metrics.unsafe_manifest_rate:.6f}")
    print(f"seconds={metrics.seconds:.6f}")
    print()


def main() -> None:
    episodes, counts = build_workload()
    expected = reference_states(episodes)

    fixed = run_fixed(episodes, expected)
    naive = run_naive(episodes, expected)
    conventional = run_guarded(episodes, expected, conventional_guard)
    guarded = run_guarded(episodes, expected, step_stochastic_capability)

    semantic_equivalence = (
        conventional.wrong_mode_ticks == guarded.wrong_mode_ticks == 0
        and conventional.unsafe_manifest_ticks == guarded.unsafe_manifest_ticks == 0
        and conventional.final_false_recoveries == guarded.final_false_recoveries == 0
        and conventional.unresolved_episodes == guarded.unresolved_episodes
    )

    print(f"episodes={EPISODES}")
    print(f"seed={SEED}")
    print(f"second_shocks={counts.second_shocks}")
    print(f"premature_evidence={counts.premature_evidence}")
    print(f"stale_evidence={counts.stale_evidence}")
    print(f"duplicate_events={counts.duplicate_events}")
    print(f"missing_final_evidence={counts.missing_final_evidence}")
    print()
    print_metrics("fixed Manifest", fixed)
    print_metrics("naive three-mode FSM / no epoch-order guard", naive)
    print_metrics("conventional equal-information epoch-aware FSM", conventional)
    print_metrics("Bardo/Tao stochastic capability guard", guarded)
    print(f"semantic_equivalence_to_conventional={semantic_equivalence}")
    print(f"guard_vs_conventional_time={guarded.seconds / conventional.seconds:.3f}x")
    print()
    print(
        "stochastic_adaptability_axis=(correct_mode_rate, unsafe_manifest_rate, "
        "false_recoveries, unresolved_episodes, execution_cost)"
    )
    print(
        "interpretation=Stochastic adaptability is treated as a vector, not a "
        "magic scalar. Epoch/order state prevents stale or premature evidence "
        "from collapsing adaptation too early. An equally informed conventional "
        "FSM is the semantic control; any future advantage must come from a "
        "more compact or cheaper execution representation."
    )


if __name__ == "__main__":
    main()
