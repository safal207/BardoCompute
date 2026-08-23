from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProbeCadenceEvidence:
    """Evidence for choosing when to buy the next calibration probe.

    The model balances probe cost against an estimated per-step regret rate
    from continuing to trust stale calibration. ``trust`` and ``drift_score``
    must be derived from past/present evidence only.
    """

    trust: float
    drift_score: float
    miss_loss: float
    false_action_loss: float
    probe_cost: float
    min_interval: int = 8
    max_interval: int = 256
    regret_floor: float = 1e-6

    def __post_init__(self) -> None:
        if not 0.0 <= self.trust <= 1.0:
            raise ValueError("trust must be in [0, 1]")
        if not 0.0 <= self.drift_score <= 1.0:
            raise ValueError("drift_score must be in [0, 1]")
        for name in ("miss_loss", "false_action_loss", "probe_cost", "regret_floor"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if self.min_interval <= 0:
            raise ValueError("min_interval must be positive")
        if self.max_interval < self.min_interval:
            raise ValueError("max_interval must be >= min_interval")


@dataclass(frozen=True, slots=True)
class ProbeCadenceResult:
    interval: int
    stale_regret_rate: float
    unconstrained_interval: float


def evaluate_probe_cadence(evidence: ProbeCadenceEvidence) -> ProbeCadenceResult:
    """Choose a probe interval from estimated stale-knowledge regret.

    A simple inspection-cost approximation is used:

        cost_rate(interval) ~= probe_cost / interval
                            + stale_regret_rate * interval / 2

    whose continuous minimum is:

        sqrt(2 * probe_cost / stale_regret_rate)

    The result is clipped to the configured interval range. This is an
    engineering heuristic to falsify, not a universal optimality claim.
    """

    consequence_scale = 0.5 * (evidence.miss_loss + evidence.false_action_loss)
    stale_regret_rate = max(
        evidence.regret_floor,
        consequence_scale
        * (1.0 - evidence.trust)
        * max(evidence.drift_score, 1e-3),
    )

    if evidence.probe_cost == 0.0:
        unconstrained = float(evidence.min_interval)
    else:
        unconstrained = math.sqrt(2.0 * evidence.probe_cost / stale_regret_rate)

    interval = int(round(unconstrained))
    interval = max(evidence.min_interval, min(evidence.max_interval, interval))
    return ProbeCadenceResult(
        interval=interval,
        stale_regret_rate=stale_regret_rate,
        unconstrained_interval=unconstrained,
    )
