from __future__ import annotations

from time import perf_counter

from bardocompute.capability import (
    CapabilityMode,
    CapabilitySignal,
    step_capability_mode,
)


EPISODES = 50_000
SIGNALS = (
    CapabilitySignal.HOLD,
    CapabilitySignal.ENVIRONMENT_CHANGE,
    CapabilitySignal.GAP_DETECTED,
    CapabilitySignal.EVIDENCE_READY,
)
EXPECTED = (
    CapabilityMode.MANIFEST,
    CapabilityMode.ADAPT,
    CapabilityMode.ACQUIRE,
    CapabilityMode.MANIFEST,
)


def conventional_step(
    current: CapabilityMode,
    signal: CapabilitySignal,
) -> CapabilityMode:
    if signal is CapabilitySignal.HOLD:
        return current
    if signal is CapabilitySignal.ENVIRONMENT_CHANGE:
        return CapabilityMode.ADAPT
    if signal is CapabilitySignal.GAP_DETECTED:
        if current in (CapabilityMode.ADAPT, CapabilityMode.ACQUIRE):
            return CapabilityMode.ACQUIRE
        return CapabilityMode.ADAPT
    if signal is CapabilitySignal.EVIDENCE_READY:
        if current in (CapabilityMode.ADAPT, CapabilityMode.ACQUIRE):
            return CapabilityMode.MANIFEST
        return current
    raise ValueError(signal)


def run_fixed_manifest() -> tuple[int, int]:
    errors = 0
    recovered = 0
    for _ in range(EPISODES):
        for expected in EXPECTED:
            mode = CapabilityMode.MANIFEST
            errors += mode is not expected
        recovered += 1
    return errors, recovered


def run_stateful(stepper) -> tuple[int, int, int]:
    errors = 0
    recovered = 0
    total_recovery_ticks = 0
    for _ in range(EPISODES):
        mode = CapabilityMode.MANIFEST
        change_tick = None
        for tick, (signal, expected) in enumerate(zip(SIGNALS, EXPECTED, strict=True)):
            mode = stepper(mode, signal)
            errors += mode is not expected
            if signal is CapabilitySignal.ENVIRONMENT_CHANGE:
                change_tick = tick
            if (
                change_tick is not None
                and tick > change_tick
                and mode is CapabilityMode.MANIFEST
            ):
                recovered += 1
                total_recovery_ticks += tick - change_tick
                change_tick = None
    return errors, recovered, total_recovery_ticks


def main() -> None:
    started = perf_counter()
    fixed_errors, fixed_recovered = run_fixed_manifest()
    fixed_seconds = perf_counter() - started

    started = perf_counter()
    conventional_errors, conventional_recovered, conventional_ticks = run_stateful(
        conventional_step
    )
    conventional_seconds = perf_counter() - started

    started = perf_counter()
    flow_errors, flow_recovered, flow_ticks = run_stateful(step_capability_mode)
    flow_seconds = perf_counter() - started

    semantic_equivalence = (
        conventional_errors == flow_errors == 0
        and conventional_recovered == flow_recovered == EPISODES
        and conventional_ticks == flow_ticks == EPISODES * 2
    )

    print(f"episodes={EPISODES}")
    print("signals_per_episode=4")
    print("expected_path=MANIFEST->ADAPT->ACQUIRE->MANIFEST")
    print()
    print("[fixed Manifest]")
    print(f"wrong_mode_ticks={fixed_errors}")
    print(f"recovered_episodes={fixed_recovered}")
    print(f"seconds={fixed_seconds:.6f}")
    print()
    print("[conventional equal-information state machine]")
    print(f"wrong_mode_ticks={conventional_errors}")
    print(f"recovered_episodes={conventional_recovered}")
    print(f"mean_recovery_ticks={conventional_ticks / EPISODES:.3f}")
    print(f"seconds={conventional_seconds:.6f}")
    print()
    print("[Bardo/Tao capability transition algebra]")
    print(f"wrong_mode_ticks={flow_errors}")
    print(f"recovered_episodes={flow_recovered}")
    print(f"mean_recovery_ticks={flow_ticks / EPISODES:.3f}")
    print(f"seconds={flow_seconds:.6f}")
    print(f"semantic_equivalence_to_conventional={semantic_equivalence}")
    print(f"flow_vs_conventional_time={flow_seconds / conventional_seconds:.3f}x")
    print()
    print(
        "interpretation=The capability model now represents a trajectory of "
        "mode changes rather than a static label. A fixed Manifest policy is "
        "wrong during adaptation/acquisition, while the capability transition "
        "algebra follows the required recovery path. The conventional FSM is "
        "the equal-information control and should recover in exactly the same "
        "number of ticks."
    )


if __name__ == "__main__":
    main()
