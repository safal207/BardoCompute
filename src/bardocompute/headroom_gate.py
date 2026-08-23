from __future__ import annotations

import math
from dataclasses import dataclass

from bardocompute.hazard_cadence import (
    HazardCadenceEvidence,
    HazardCadenceResult,
    evaluate_hazard_cadence,
)


@dataclass(frozen=True, slots=True)
class HeadroomGateEvidence:
    """Evidence for deciding whether adaptive cadence has safe headroom.

    ``point_hazard`` selects the ordinary adaptive cadence. ``recent_events``
    and ``recent_exposure`` come only from paid past/present probes and are used
    to form a conservative Wilson upper bound on the recent change rate.

    If that upper bound implies that the unconstrained economic optimum is at
    or below ``min_interval``, cadence adaptation has no safe downward headroom:
    the gate falls back to the minimum interval instead of trusting a lagging
    point estimate to schedule a later check.
    """

    point_hazard: float
    recent_events: int
    recent_exposure: int
    regret_given_change: float
    probe_cost: float
    min_interval: int = 8
    max_interval: int = 256
    z_score: float = 1.96

    def __post_init__(self) -> None:
        if not 0.0 <= self.point_hazard <= 1.0:
            raise ValueError("point_hazard must be in [0, 1]")
        if self.recent_events < 0:
            raise ValueError("recent_events must be non-negative")
        if self.recent_exposure <= 0:
            raise ValueError("recent_exposure must be positive")
        if self.recent_events > self.recent_exposure:
            raise ValueError("recent_events must be <= recent_exposure")
        if self.regret_given_change < 0.0:
            raise ValueError("regret_given_change must be non-negative")
        if self.probe_cost < 0.0:
            raise ValueError("probe_cost must be non-negative")
        if self.min_interval <= 0:
            raise ValueError("min_interval must be positive")
        if self.max_interval < self.min_interval:
            raise ValueError("max_interval must be >= min_interval")
        if self.z_score < 0.0:
            raise ValueError("z_score must be non-negative")


@dataclass(frozen=True, slots=True)
class HeadroomGateResult:
    interval: int
    gated_to_minimum: bool
    point: HazardCadenceResult
    upper_hazard: float
    saturation_hazard: float


def wilson_upper(events: int, exposure: int, z_score: float = 1.96) -> float:
    """Wilson upper confidence bound for a Bernoulli change rate."""

    n = float(exposure)
    p = events / n
    z2 = z_score * z_score
    denominator = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denominator
    radius = (
        z_score
        * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
        / denominator
    )
    return min(1.0, max(0.0, center + radius))


def evaluate_headroom_gate(evidence: HeadroomGateEvidence) -> HeadroomGateResult:
    point = evaluate_hazard_cadence(
        HazardCadenceEvidence(
            change_hazard=evidence.point_hazard,
            regret_given_change=evidence.regret_given_change,
            probe_cost=evidence.probe_cost,
            min_interval=evidence.min_interval,
            max_interval=evidence.max_interval,
        )
    )

    if evidence.probe_cost == 0.0 or evidence.regret_given_change == 0.0:
        saturation_hazard = 0.0 if evidence.probe_cost == 0.0 else math.inf
    else:
        saturation_hazard = (
            2.0
            * evidence.probe_cost
            / (evidence.regret_given_change * evidence.min_interval**2)
        )

    upper_hazard = wilson_upper(
        evidence.recent_events,
        evidence.recent_exposure,
        evidence.z_score,
    )
    gated = evidence.probe_cost == 0.0 or upper_hazard >= saturation_hazard
    interval = evidence.min_interval if gated else point.interval

    return HeadroomGateResult(
        interval=interval,
        gated_to_minimum=gated,
        point=point,
        upper_hazard=upper_hazard,
        saturation_hazard=saturation_hazard,
    )
