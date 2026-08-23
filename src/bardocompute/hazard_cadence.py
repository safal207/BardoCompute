from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HazardCadenceEvidence:
    """Evidence for scheduling the next calibration probe.

    ``change_hazard`` is an online estimate of the per-step probability that
    the environment changes before the next probe. It must be inferred from
    past/present evidence, never from a hidden future boundary.
    """

    change_hazard: float
    regret_given_change: float
    probe_cost: float
    min_interval: int = 8
    max_interval: int = 256
    hazard_floor: float = 1e-9

    def __post_init__(self) -> None:
        if not 0.0 <= self.change_hazard <= 1.0:
            raise ValueError("change_hazard must be in [0, 1]")
        for name in ("regret_given_change", "probe_cost", "hazard_floor"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if self.min_interval <= 0:
            raise ValueError("min_interval must be positive")
        if self.max_interval < self.min_interval:
            raise ValueError("max_interval must be >= min_interval")


@dataclass(frozen=True, slots=True)
class HazardCadenceResult:
    interval: int
    hazard_regret_rate: float
    unconstrained_interval: float


def evaluate_hazard_cadence(
    evidence: HazardCadenceEvidence,
) -> HazardCadenceResult:
    """Balance inspection cost against expected stale time after a change.

    For a low-hazard approximation, one probe interval ``d`` has cost rate:

        probe_cost / d + change_hazard * regret_given_change * d / 2

    The continuous minimum is:

        sqrt(2 * probe_cost / (change_hazard * regret_given_change))

    This separates *probability of change* from *cost if stale*. The formula is
    an engineering hypothesis to falsify, not a universal scheduling law.
    """

    hazard_regret_rate = max(
        evidence.hazard_floor,
        evidence.change_hazard * evidence.regret_given_change,
    )
    if evidence.probe_cost == 0.0:
        unconstrained = float(evidence.min_interval)
    else:
        unconstrained = math.sqrt(
            2.0 * evidence.probe_cost / hazard_regret_rate
        )

    interval = int(round(unconstrained))
    interval = max(evidence.min_interval, min(evidence.max_interval, interval))
    return HazardCadenceResult(
        interval=interval,
        hazard_regret_rate=hazard_regret_rate,
        unconstrained_interval=unconstrained,
    )
