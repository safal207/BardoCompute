from __future__ import annotations

from collections import Counter
from time import perf_counter

from bardocompute.capability import (
    CapabilityMode,
    CapabilityProfile,
    Carrier,
    choose_capability_mode,
    flow_profile,
)
from bardocompute.phase_age import PhaseAgeBucket
from bardocompute.tao import EvidenceKind
from bardocompute.trajectory import TrajectoryPhase


CASES = 120_000


def conventional_mode(
    phase: TrajectoryPhase,
    missing: EvidenceKind,
    age: PhaseAgeBucket,
    discontinuity: bool,
) -> CapabilityMode:
    """Equal-information conventional control with no Tao terminology."""

    if discontinuity or phase in (
        TrajectoryPhase.REGRESSING,
        TrajectoryPhase.REORIENTING,
    ):
        return CapabilityMode.ADAPT
    if missing != EvidenceKind.NONE or (
        phase is TrajectoryPhase.STALLED and age >= PhaseAgeBucket.STALE
    ):
        return CapabilityMode.ACQUIRE
    return CapabilityMode.MANIFEST


def main() -> None:
    patterns = (
        (
            TrajectoryPhase.CONVERGING,
            EvidenceKind.NONE,
            PhaseAgeBucket.FRESH,
            False,
            CapabilityMode.MANIFEST,
        ),
        (
            TrajectoryPhase.STALLED,
            EvidenceKind.OUTCOME,
            PhaseAgeBucket.WARM,
            False,
            CapabilityMode.ACQUIRE,
        ),
        (
            TrajectoryPhase.REGRESSING,
            EvidenceKind.NONE,
            PhaseAgeBucket.FRESH,
            False,
            CapabilityMode.ADAPT,
        ),
        (
            TrajectoryPhase.REORIENTING,
            EvidenceKind.AUTHORITY,
            PhaseAgeBucket.STALE,
            True,
            CapabilityMode.ADAPT,
        ),
    )
    signals = [patterns[i & 3] for i in range(CASES)]

    started = perf_counter()
    fixed_errors = sum(
        1 for *_, expected in signals if expected is not CapabilityMode.MANIFEST
    )
    fixed_seconds = perf_counter() - started

    started = perf_counter()
    conventional = [
        conventional_mode(phase, missing, age, discontinuity)
        for phase, missing, age, discontinuity, _ in signals
    ]
    conventional_seconds = perf_counter() - started

    started = perf_counter()
    flowed = [
        choose_capability_mode(
            current_phase=phase,
            current_missing=missing,
            age_bucket=age,
            had_discontinuity=discontinuity,
        )
        for phase, missing, age, discontinuity, _ in signals
    ]
    flow_seconds = perf_counter() - started

    expected = [case[-1] for case in signals]
    semantic_equivalence = conventional == flowed == expected

    carrier_sequences: dict[Carrier, tuple[CapabilityMode, ...]] = {}
    probe = patterns[:3]
    for carrier in Carrier:
        profile = CapabilityProfile(carrier)
        modes: list[CapabilityMode] = []
        for phase, missing, age, discontinuity, _ in probe:
            profile = flow_profile(
                profile,
                current_phase=phase,
                current_missing=missing,
                age_bucket=age,
                had_discontinuity=discontinuity,
            )
            modes.append(profile.active)
        carrier_sequences[carrier] = tuple(modes)

    carrier_invariant = len(set(carrier_sequences.values())) == 1
    counts = Counter(flowed)

    print(f"cases={CASES}")
    print("carrier_count=3")
    print("capability_modes=3")
    print(f"fixed_manifest_errors={fixed_errors}")
    print(f"fixed_seconds={fixed_seconds:.6f}")
    print()
    print("[conventional equal-information flow law]")
    print(f"seconds={conventional_seconds:.6f}")
    print()
    print("[Bardo/Tao capability flow law]")
    print(f"seconds={flow_seconds:.6f}")
    print(f"manifest={counts[CapabilityMode.MANIFEST]}")
    print(f"acquire={counts[CapabilityMode.ACQUIRE]}")
    print(f"adapt={counts[CapabilityMode.ADAPT]}")
    print(f"semantic_equivalence_to_conventional={semantic_equivalence}")
    print(f"carrier_invariant_flow={carrier_invariant}")
    print(f"tao_carrier_adds_unique_behavior={not carrier_invariant}")
    print(f"flow_vs_conventional_time={flow_seconds / conventional_seconds:.3f}x")
    print()
    print(
        "interpretation=All three carriers can hold Manifest/Acquire/Adapt. "
        "The v0.1 flow law moves between modes from temporal context. Tao as "
        "a third carrier adds no unique behavior under equal capability "
        "potential; Tao-as-flow-law remains a separate hypothesis. A "
        "conventional policy with the same inputs is semantically equivalent."
    )


if __name__ == "__main__":
    main()
