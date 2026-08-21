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
from bardocompute.probe_cadence import ProbeCadenceEvidence, evaluate_probe_cadence

SEGMENT = 30_000
DEPLOYMENT = SEGMENT * 4
FIXED_INTERVALS = (8, 16, 32, 64, 128, 256)
PROBE_COSTS = (2.0, 8.0, 32.0)
MISS_COST = 120.0
FALSE_ACTION_COST = 500.0
ACTION_COST = 20.0
OBSERVATION_COST = 12.0


@dataclass(frozen=True, slots=True)
class Rates:
    beneficial: float
    harmful: float


@dataclass(slots=True)
class State:
    recent_beneficial: float
    recent_harmful: float
    brier_ema: float = 0.10
    last_revealed_step: int = 0
    last_probe_step: int = 0


@dataclass(slots=True)
class Stats:
    loss: float = 0.0
    probes: int = 0
    revisits: int = 0
    misses: int = 0
    false_actions: int = 0
    selected_interval_sum: int = 0
    selected_interval_count: int = 0
    first_probe_after_moderate: int | None = None
    first_probe_after_return: int | None = None


BASE = Rates(0.18, 0.10)
MODERATE = Rates(0.50, 0.05)
STRONG = Rates(0.70, 0.04)


def draw_outcome(rates: Rates, rng: random.Random) -> int:
    value = rng.random()
    if value < rates.beneficial:
        return 1
    if value < rates.beneficial + rates.harmful:
        return -1
    return 0


def stream(seed: int = 0xCADA11CE) -> list[int]:
    rng = random.Random(seed)
    values: list[int] = []
    for step in range(DEPLOYMENT):
        if step < SEGMENT:
            rates = BASE
        elif step < 2 * SEGMENT:
            rates = MODERATE
        elif step < 3 * SEGMENT:
            rates = STRONG
        else:
            rates = BASE
        values.append(draw_outcome(rates, rng))
    return values


def action_for(rates: Rates) -> ObservationAction:
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


def brier(rates: Rates, outcome: int) -> float:
    target_b = 1.0 if outcome == 1 else 0.0
    target_h = 1.0 if outcome == -1 else 0.0
    return ((rates.beneficial - target_b) ** 2 + (rates.harmful - target_h) ** 2) / 2.0


def inferred_rates(state: State, step: int) -> tuple[Rates, float, float]:
    recent = Rates(state.recent_beneficial, state.recent_harmful)
    drift = min(
        1.0,
        1.8
        * (
            abs(recent.beneficial - BASE.beneficial)
            + abs(recent.harmful - BASE.harmful)
        ),
    )
    age = max(0, step - state.last_revealed_step)
    trust = evaluate_calibration_trust(
        CalibrationTrustEvidence(
            sample_count=240,
            age_steps=float(age),
            drift_score=drift,
            brier_score=state.brier_ema,
            prior_strength=32.0,
            age_half_life=384.0,
        )
    ).trust
    adjusted_b, adjusted_h = shrink_correction_probabilities(
        BASE.beneficial,
        BASE.harmful,
        trust=trust,
        prior_beneficial=recent.beneficial,
        prior_harmful=recent.harmful,
    )
    return Rates(adjusted_b, adjusted_h), trust, drift


def update(state: State, rates_used: Rates, outcome: int, step: int) -> None:
    alpha = 0.08
    target_b = 1.0 if outcome == 1 else 0.0
    target_h = 1.0 if outcome == -1 else 0.0
    state.recent_beneficial = (1.0 - alpha) * state.recent_beneficial + alpha * target_b
    state.recent_harmful = (1.0 - alpha) * state.recent_harmful + alpha * target_h
    total = state.recent_beneficial + state.recent_harmful
    if total > 0.98:
        scale = 0.98 / total
        state.recent_beneficial *= scale
        state.recent_harmful *= scale
    state.brier_ema = 0.92 * state.brier_ema + 0.08 * brier(rates_used, outcome)
    state.last_revealed_step = step


def action_loss(action: ObservationAction, outcome: int) -> float:
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


def run_policy(
    outcomes: list[int],
    *,
    probe_cost: float,
    fixed_interval: int | None,
) -> Stats:
    state = State(BASE.beneficial, BASE.harmful)
    stats = Stats()

    for step, outcome in enumerate(outcomes):
        rates, trust, drift = inferred_rates(state, step)
        action = action_for(rates)
        stats.loss += action_loss(action, outcome)
        if action is ObservationAction.REVISIT:
            stats.revisits += 1
            if outcome == -1:
                stats.false_actions += 1
        elif outcome == 1:
            stats.misses += 1

        if fixed_interval is None:
            cadence = evaluate_probe_cadence(
                ProbeCadenceEvidence(
                    trust=trust,
                    drift_score=drift,
                    miss_loss=MISS_COST,
                    false_action_loss=FALSE_ACTION_COST,
                    probe_cost=probe_cost,
                    min_interval=8,
                    max_interval=256,
                )
            ).interval
        else:
            cadence = fixed_interval

        stats.selected_interval_sum += cadence
        stats.selected_interval_count += 1

        due = step - state.last_probe_step >= cadence
        probed = due and action is not ObservationAction.REVISIT
        revealed = action is ObservationAction.REVISIT or probed
        if probed:
            stats.loss += probe_cost
            stats.probes += 1
            state.last_probe_step = step
            if step >= SEGMENT and stats.first_probe_after_moderate is None:
                stats.first_probe_after_moderate = step - SEGMENT
            if step >= 3 * SEGMENT and stats.first_probe_after_return is None:
                stats.first_probe_after_return = step - 3 * SEGMENT
        if revealed:
            update(state, rates, outcome, step)

    return stats


def mean_loss(stats: Stats) -> float:
    return stats.loss / DEPLOYMENT


def main() -> None:
    outcomes = stream()
    print(f"deployment_steps={DEPLOYMENT}")
    print(f"segments=stable:{SEGMENT},moderate:{SEGMENT},strong:{SEGMENT},return:{SEGMENT}")
    print("policy_input=future regime boundaries and labels are hidden")
    print("probe_cost,best_fixed_interval,best_fixed_loss,adaptive_loss,adaptive_vs_best_fixed,adaptive_probes,adaptive_mean_interval,first_probe_after_moderate,first_probe_after_return")

    for probe_cost in PROBE_COSTS:
        fixed_results = [
            (interval, run_policy(outcomes, probe_cost=probe_cost, fixed_interval=interval))
            for interval in FIXED_INTERVALS
        ]
        best_interval, best_stats = min(fixed_results, key=lambda item: mean_loss(item[1]))
        adaptive = run_policy(outcomes, probe_cost=probe_cost, fixed_interval=None)
        mean_interval = adaptive.selected_interval_sum / adaptive.selected_interval_count
        print(
            f"{probe_cost:.2f},{best_interval},{mean_loss(best_stats):.3f},"
            f"{mean_loss(adaptive):.3f},{mean_loss(adaptive)/mean_loss(best_stats):.3f},"
            f"{adaptive.probes},{mean_interval:.2f},"
            f"{adaptive.first_probe_after_moderate},{adaptive.first_probe_after_return}"
        )
        for interval, fixed in fixed_results:
            print(
                f"  fixed_{interval}: loss={mean_loss(fixed):.3f} probes={fixed.probes} "
                f"revisits={fixed.revisits} misses={fixed.misses} false_actions={fixed.false_actions}"
            )
        print(
            f"  adaptive: loss={mean_loss(adaptive):.3f} probes={adaptive.probes} "
            f"revisits={adaptive.revisits} misses={adaptive.misses} "
            f"false_actions={adaptive.false_actions}"
        )

    print(
        "interpretation=Probe cadence is treated as an economic control variable. "
        "A shorter cadence buys faster distrust at higher observation cost; a longer "
        "cadence saves probes but risks stale decisions. The adaptive square-root "
        "inspection rule must earn its place against the best fixed cadence rather "
        "than being assumed optimal."
    )


if __name__ == "__main__":
    main()
