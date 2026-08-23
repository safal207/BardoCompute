from __future__ import annotations

import random
from dataclasses import dataclass

from bardocompute.calibration_trust import (
    CalibrationTrustEvidence,
    evaluate_calibration_trust,
    shrink_correction_probabilities,
)
from bardocompute.observation_payback import (
    ObservationAction,
    ObservationPaybackEvidence,
    evaluate_observation_payback,
)

PHASES = 3
HITS = 9
CALIBRATION_PER_CELL = 240
DEPLOYMENT = 90_000
SHIFT_AT = DEPLOYMENT // 2
SEVERITIES = (0.00, 0.08, 0.16, 0.24, 0.32, 0.40)

MISS_COST = 120.0
FALSE_ACTION_COST = 500.0
ACTION_COST = 20.0
OBSERVATION_COST = 12.0
PROBE_COST = 2.0
PROBE_EVERY = 64


@dataclass(frozen=True, slots=True)
class CellRates:
    beneficial: float
    harmful: float


@dataclass(slots=True)
class Counts:
    total: int = 0
    beneficial: int = 0
    harmful: int = 0


@dataclass(slots=True)
class StrategyStats:
    loss: float = 0.0
    revisits: int = 0
    false_actions: int = 0
    misses: int = 0
    probes: int = 0


@dataclass(slots=True)
class OnlineCell:
    recent_beneficial: float
    recent_harmful: float
    observed: int = 0
    last_observed_step: int = 0
    brier_ema: float = 0.15


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def base_rates(phase: int, hits: int) -> CellRates:
    strength = hits / 8.0
    phase_bonus = (0.00, 0.08, 0.16)[phase]
    beneficial = clamp(0.015 + 0.72 * strength + phase_bonus, 0.01, 0.86)
    harmful = clamp(0.22 * (1.0 - strength) + (0.10, 0.05, 0.02)[phase], 0.01, 0.32)
    if beneficial + harmful > 0.94:
        harmful = 0.94 - beneficial
    return CellRates(beneficial, harmful)


def shifted_rates(base: CellRates, phase: int, hits: int, severity: float) -> CellRates:
    # Shift attacks the historically attractive middle/high-hit cells: the
    # environment creates more deceptive positive sentinels and fewer truly
    # beneficial corrections without changing the context label itself.
    exposure = (hits / 8.0) * (1.0 - 0.18 * phase)
    beneficial = clamp(base.beneficial - severity * 0.75 * exposure, 0.005, 0.90)
    harmful = clamp(base.harmful + severity * 0.85 * exposure, 0.005, 0.90)
    if beneficial + harmful > 0.97:
        scale = 0.97 / (beneficial + harmful)
        beneficial *= scale
        harmful *= scale
    return CellRates(beneficial, harmful)


def draw_outcome(rates: CellRates, rng: random.Random) -> int:
    value = rng.random()
    if value < rates.beneficial:
        return 1
    if value < rates.beneficial + rates.harmful:
        return -1
    return 0


def estimate(counts: Counts) -> CellRates:
    # Three-outcome Laplace smoothing.
    denominator = counts.total + 3
    return CellRates(
        (counts.beneficial + 1) / denominator,
        (counts.harmful + 1) / denominator,
    )


def payback_action(rates: CellRates) -> ObservationAction:
    return evaluate_observation_payback(
        ObservationPaybackEvidence(
            beneficial_correction_probability=rates.beneficial,
            harmful_correction_probability=rates.harmful,
            recoverable_miss_loss=MISS_COST,
            false_action_loss=FALSE_ACTION_COST,
            action_cost=ACTION_COST,
            observation_cost=OBSERVATION_COST,
        )
    ).action


def outcome_loss(action: ObservationAction, outcome: int) -> float:
    if action is ObservationAction.REVISIT:
        loss = OBSERVATION_COST
        if outcome == 1:
            return loss + ACTION_COST
        if outcome == -1:
            return loss + ACTION_COST + FALSE_ACTION_COST
        return loss
    if outcome == 1:
        return MISS_COST
    return 0.0


def record(stats: StrategyStats, action: ObservationAction, outcome: int) -> None:
    stats.loss += outcome_loss(action, outcome)
    if action is ObservationAction.REVISIT:
        stats.revisits += 1
        if outcome == -1:
            stats.false_actions += 1
    elif outcome == 1:
        stats.misses += 1


def build_calibration(seed: int = 0xCA11B4A) -> tuple[dict[tuple[int, int], Counts], list[tuple[int, int, int]]]:
    rng = random.Random(seed)
    table = {(phase, hits): Counts() for phase in range(PHASES) for hits in range(HITS)}
    samples: list[tuple[int, int, int]] = []
    for phase in range(PHASES):
        for hits in range(HITS):
            rates = base_rates(phase, hits)
            for _ in range(CALIBRATION_PER_CELL):
                outcome = draw_outcome(rates, rng)
                cell = table[phase, hits]
                cell.total += 1
                cell.beneficial += outcome == 1
                cell.harmful += outcome == -1
                samples.append((phase, hits, outcome))
    return table, samples


def train_global_threshold(samples: list[tuple[int, int, int]]) -> int:
    candidates: list[tuple[float, int]] = []
    for threshold in range(1, 9):
        loss = 0.0
        for _, hits, outcome in samples:
            action = ObservationAction.REVISIT if hits >= threshold else ObservationAction.SKIP
            loss += outcome_loss(action, outcome)
        candidates.append((loss / len(samples), threshold))
    return min(candidates)[1]


def global_prior(table: dict[tuple[int, int], Counts]) -> CellRates:
    total = Counts()
    for cell in table.values():
        total.total += cell.total
        total.beneficial += cell.beneficial
        total.harmful += cell.harmful
    return estimate(total)


def brier_two(probabilities: CellRates, outcome: int) -> float:
    target_b = 1.0 if outcome == 1 else 0.0
    target_h = 1.0 if outcome == -1 else 0.0
    return ((probabilities.beneficial - target_b) ** 2 + (probabilities.harmful - target_h) ** 2) / 2.0


def deployment_stream(severity: float, seed: int) -> list[tuple[int, int, int]]:
    rng = random.Random(seed)
    stream: list[tuple[int, int, int]] = []
    for step in range(DEPLOYMENT):
        phase = rng.randrange(PHASES)
        # Middle hit counts are common; extremes still occur.
        hits = min(8, max(0, int(round(rng.gauss(4.2, 2.0)))))
        rates = base_rates(phase, hits)
        if step >= SHIFT_AT:
            rates = shifted_rates(rates, phase, hits, severity)
        stream.append((phase, hits, draw_outcome(rates, rng)))
    return stream


def run(severity: float, table: dict[tuple[int, int], Counts], threshold: int) -> dict[str, StrategyStats]:
    estimates = {key: estimate(value) for key, value in table.items()}
    prior = global_prior(table)
    online = {
        key: OnlineCell(rate.beneficial, rate.harmful)
        for key, rate in estimates.items()
    }
    stats = {
        "global_threshold": StrategyStats(),
        "static_payback": StrategyStats(),
        "uncertainty_shrunk": StrategyStats(),
        "drift_aware": StrategyStats(),
    }
    stream = deployment_stream(severity, 0xB4A2D0 + int(severity * 1000))

    for step, (phase, hits, outcome) in enumerate(stream):
        key = (phase, hits)
        base = estimates[key]

        global_action = ObservationAction.REVISIT if hits >= threshold else ObservationAction.SKIP
        record(stats["global_threshold"], global_action, outcome)

        static_action = payback_action(base)
        record(stats["static_payback"], static_action, outcome)

        age = float(step)
        shrunk_trust = evaluate_calibration_trust(
            CalibrationTrustEvidence(
                sample_count=table[key].total,
                age_steps=age,
                drift_score=0.0,
                brier_score=0.15,
                prior_strength=32.0,
                age_half_life=120_000.0,
            )
        ).trust
        shrunk_b, shrunk_h = shrink_correction_probabilities(
            base.beneficial,
            base.harmful,
            trust=shrunk_trust,
            prior_beneficial=prior.beneficial,
            prior_harmful=prior.harmful,
        )
        shrunk_action = payback_action(CellRates(shrunk_b, shrunk_h))
        record(stats["uncertainty_shrunk"], shrunk_action, outcome)

        state = online[key]
        recent = CellRates(state.recent_beneficial, state.recent_harmful)
        drift = clamp(
            1.6
            * (
                abs(recent.beneficial - base.beneficial)
                + abs(recent.harmful - base.harmful)
            ),
            0.0,
            1.0,
        )
        old_trust = evaluate_calibration_trust(
            CalibrationTrustEvidence(
                sample_count=table[key].total,
                age_steps=float(step),
                drift_score=drift,
                brier_score=state.brier_ema,
                prior_strength=32.0,
                age_half_life=120_000.0,
            )
        ).trust
        aware_b, aware_h = shrink_correction_probabilities(
            base.beneficial,
            base.harmful,
            trust=old_trust,
            prior_beneficial=recent.beneficial,
            prior_harmful=recent.harmful,
        )
        aware_rates = CellRates(aware_b, aware_h)
        aware_action = payback_action(aware_rates)
        record(stats["drift_aware"], aware_action, outcome)

        # Revisit reveals the outcome naturally. A sparse probe reveals skipped
        # outcomes and is charged explicitly, preventing free drift detection.
        probed = step % PROBE_EVERY == 0
        revealed = aware_action is ObservationAction.REVISIT or probed
        if probed and aware_action is not ObservationAction.REVISIT:
            stats["drift_aware"].loss += PROBE_COST
            stats["drift_aware"].probes += 1
        if revealed:
            alpha = 0.06
            target_b = 1.0 if outcome == 1 else 0.0
            target_h = 1.0 if outcome == -1 else 0.0
            state.recent_beneficial = (1.0 - alpha) * state.recent_beneficial + alpha * target_b
            state.recent_harmful = (1.0 - alpha) * state.recent_harmful + alpha * target_h
            total = state.recent_beneficial + state.recent_harmful
            if total > 0.98:
                scale = 0.98 / total
                state.recent_beneficial *= scale
                state.recent_harmful *= scale
            state.brier_ema = 0.94 * state.brier_ema + 0.06 * brier_two(aware_rates, outcome)
            state.observed += 1
            state.last_observed_step = step

    return stats


def main() -> None:
    table, calibration_samples = build_calibration()
    threshold = train_global_threshold(calibration_samples)
    print(f"calibration_samples={len(calibration_samples)}")
    print(f"deployment_steps={DEPLOYMENT}")
    print(f"shift_at={SHIFT_AT}")
    print(f"trained_global_threshold={threshold}/8")
    print(f"probe_every={PROBE_EVERY}")
    print(f"probe_cost={PROBE_COST:.2f}")
    print("severity,global_loss,static_loss,shrunk_loss,drift_aware_loss,drift_vs_static,drift_vs_global,probes")

    first_drift_win: float | None = None
    first_static_loss: float | None = None
    for severity in SEVERITIES:
        stats = run(severity, table, threshold)
        global_loss = stats["global_threshold"].loss / DEPLOYMENT
        static_loss = stats["static_payback"].loss / DEPLOYMENT
        shrunk_loss = stats["uncertainty_shrunk"].loss / DEPLOYMENT
        aware_loss = stats["drift_aware"].loss / DEPLOYMENT
        if first_static_loss is None:
            first_static_loss = static_loss
        if first_drift_win is None and aware_loss < static_loss:
            first_drift_win = severity
        print(
            f"{severity:.2f},{global_loss:.3f},{static_loss:.3f},{shrunk_loss:.3f},"
            f"{aware_loss:.3f},{aware_loss/static_loss:.3f},{aware_loss/global_loss:.3f},"
            f"{stats['drift_aware'].probes}"
        )

    print(f"first_severity_where_drift_aware_beats_static={first_drift_win}")
    print(
        "interpretation=Calibration trust is treated as a decaying, testable resource. "
        "Static payback, uncertainty shrinkage, and paid online recalibration are not "
        "assumed to dominate each other; the sweep searches for the drift/cost region "
        "where updating knowledge repays its own observation cost."
    )


if __name__ == "__main__":
    main()
