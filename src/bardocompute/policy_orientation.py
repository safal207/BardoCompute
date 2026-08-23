from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass(slots=True)
class PolicyOrientation:
    """Small partial-feedback selector for competing adaptive policies.

    The selector is an EXP3-style bandit with a fixed-share step so an old
    winner does not keep permanent authority after the environment changes.
    It receives loss only for the policy that actually controlled the system.

    This is an engineering falsification kernel, not a claim of a novel or
    theoretically optimal bandit algorithm.
    """

    policy_count: int
    exploration: float = 0.08
    learning_rate: float = 0.04
    share: float = 0.03
    weights: list[float] = field(init=False)

    def __post_init__(self) -> None:
        if self.policy_count < 2:
            raise ValueError("policy_count must be >= 2")
        if not 0.0 < self.exploration <= 1.0:
            raise ValueError("exploration must be in (0, 1]")
        if self.learning_rate <= 0.0:
            raise ValueError("learning_rate must be positive")
        if not 0.0 <= self.share < 1.0:
            raise ValueError("share must be in [0, 1)")
        self.weights = [1.0] * self.policy_count

    def probabilities(self) -> tuple[float, ...]:
        total = sum(self.weights)
        if not math.isfinite(total) or total <= 0.0:
            self.weights = [1.0] * self.policy_count
            total = float(self.policy_count)
        uniform = self.exploration / self.policy_count
        exploit = 1.0 - self.exploration
        return tuple(exploit * (weight / total) + uniform for weight in self.weights)

    def choose(self, rng: random.Random) -> tuple[int, float]:
        probabilities = self.probabilities()
        draw = rng.random()
        cumulative = 0.0
        for index, probability in enumerate(probabilities):
            cumulative += probability
            if draw <= cumulative:
                return index, probability
        return self.policy_count - 1, probabilities[-1]

    def observe(self, policy: int, normalized_loss: float, selection_probability: float) -> None:
        """Update only the selected policy from its realized normalized loss."""

        if not 0 <= policy < self.policy_count:
            raise ValueError("policy index out of range")
        if not 0.0 <= normalized_loss <= 1.0:
            raise ValueError("normalized_loss must be in [0, 1]")
        if not 0.0 < selection_probability <= 1.0:
            raise ValueError("selection_probability must be in (0, 1]")

        estimated_loss = normalized_loss / selection_probability
        exponent = max(-60.0, -self.learning_rate * estimated_loss)
        self.weights[policy] *= math.exp(exponent)

        # Fixed-share style forgetting: preserve policy plurality so a policy
        # that was weak in an old regime can regain authority after a shift.
        mean_weight = sum(self.weights) / self.policy_count
        self.weights = [
            (1.0 - self.share) * weight + self.share * mean_weight
            for weight in self.weights
        ]

        # Scale invariance lets us renormalize defensively without changing
        # selection probabilities.
        maximum = max(self.weights)
        if maximum <= 0.0 or not math.isfinite(maximum):
            self.weights = [1.0] * self.policy_count
        elif maximum < 1e-100 or maximum > 1e100:
            self.weights = [weight / maximum for weight in self.weights]
