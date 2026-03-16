"""
Bahamut.AI Trust Score Store
Multi-dimensional trust score management with DB persistence.
"""
import structlog
from typing import Optional

logger = structlog.get_logger()

# Initial trust scores (all agents start at 1.0 baseline)
AGENT_IDS = [
    "macro_agent", "flow_agent", "volatility_agent", "options_agent",
    "liquidity_agent", "sentiment_agent", "technical_agent",
    "learning_agent",
]

INITIAL_DIMENSIONS = [
    "global", "regime:risk_on", "regime:risk_off", "regime:high_vol",
    "regime:low_vol", "regime:crisis", "regime:trend_continuation",
    "asset:fx", "asset:indices", "asset:commodities", "asset:crypto", "asset:bonds",
    "tf:1H", "tf:4H", "tf:1D",
]


class TrustScoreStore:
    """In-memory trust score cache. Will be backed by PostgreSQL in production."""

    def __init__(self):
        self._scores: dict[str, dict[str, float]] = {}
        self._samples: dict[str, dict[str, int]] = {}
        self._initialize()

    def _initialize(self):
        for agent_id in AGENT_IDS:
            self._scores[agent_id] = {}
            self._samples[agent_id] = {}
            for dim in INITIAL_DIMENSIONS:
                self._scores[agent_id][dim] = 1.0
                self._samples[agent_id][dim] = 0

    def get(self, agent_id: str, dimension: str) -> tuple[float, int]:
        """Get trust score and sample count for agent+dimension."""
        scores = self._scores.get(agent_id, {})
        samples = self._samples.get(agent_id, {})
        return scores.get(dimension, 1.0), samples.get(dimension, 0)

    def set(self, agent_id: str, dimension: str, score: float, increment_sample: bool = True):
        """Update trust score for agent+dimension."""
        score = max(0.1, min(2.0, score))
        if agent_id not in self._scores:
            self._scores[agent_id] = {}
            self._samples[agent_id] = {}
        self._scores[agent_id][dimension] = round(score, 4)
        if increment_sample:
            self._samples[agent_id][dimension] = self._samples.get(agent_id, {}).get(dimension, 0) + 1

    def resolve(self, agent_id: str, regime: str, asset_class: str, timeframe: str) -> float:
        """Resolve multi-dimensional trust score with weighted blending."""
        global_t, global_n = self.get(agent_id, "global")
        regime_t, regime_n = self.get(agent_id, f"regime:{regime.lower()}")
        asset_t, asset_n = self.get(agent_id, f"asset:{asset_class}")
        tf_t, tf_n = self.get(agent_id, f"tf:{timeframe}")

        MIN_SAMPLES = 10

        weights = {"global": 0.20, "regime": 0.35, "asset": 0.25, "tf": 0.20}
        scores = {
            "global": global_t,
            "regime": regime_t if regime_n >= MIN_SAMPLES else global_t,
            "asset": asset_t if asset_n >= MIN_SAMPLES else global_t,
            "tf": tf_t if tf_n >= MIN_SAMPLES else global_t,
        }

        resolved = sum(weights[d] * scores[d] for d in weights)
        return max(0.1, min(2.0, round(resolved, 4)))

    def get_scores_for_context(
        self, regime: str, asset_class: str, timeframe: str
    ) -> dict[str, float]:
        """Get resolved trust scores for all agents in a specific context."""
        result = {}
        for agent_id in AGENT_IDS:
            result[agent_id] = self.resolve(agent_id, regime, asset_class, timeframe)
        return result

    def update_after_trade(
        self, agent_id: str, outcome_correct: bool, confidence: float,
        regime: str, asset_class: str, timeframe: str
    ):
        """Update trust scores after a trade outcome. Implements asymmetric learning rates."""
        agent_outcome = 1.0 if outcome_correct else 0.0

        if outcome_correct and confidence >= 0.7:
            alpha = 0.05
        elif outcome_correct and confidence < 0.7:
            alpha = 0.03
        elif not outcome_correct and confidence < 0.5:
            alpha = 0.04
        elif not outcome_correct and confidence >= 0.7:
            alpha = 0.10
        else:
            alpha = 0.05

        for dimension in [
            "global",
            f"regime:{regime.lower()}",
            f"asset:{asset_class}",
            f"tf:{timeframe}",
        ]:
            current, _ = self.get(agent_id, dimension)
            normalized = (current - 0.1) / 1.9  # normalize to 0-1
            new_normalized = normalized + alpha * (agent_outcome - normalized)
            new_score = 0.1 + new_normalized * 1.9  # denormalize
            self.set(agent_id, dimension, new_score)

        logger.info(
            "trust_score_updated",
            agent_id=agent_id,
            outcome="correct" if outcome_correct else "wrong",
            confidence=confidence,
            alpha=alpha,
        )

    def apply_daily_decay(self, stale_threshold_days: int = 14, decay_rate: float = 0.005):
        """Decay all scores toward baseline (1.0) for stale dimensions."""
        for agent_id in AGENT_IDS:
            for dim in self._scores.get(agent_id, {}):
                score = self._scores[agent_id][dim]
                if score != 1.0:
                    direction = 1.0 - score
                    self._scores[agent_id][dim] += direction * decay_rate
                    self._scores[agent_id][dim] = round(
                        max(0.1, min(2.0, self._scores[agent_id][dim])), 4
                    )

    def get_all_scores(self) -> dict:
        """Return all scores for dashboard display."""
        result = {}
        for agent_id in AGENT_IDS:
            result[agent_id] = {
                dim: {"score": self._scores[agent_id].get(dim, 1.0),
                      "samples": self._samples[agent_id].get(dim, 0)}
                for dim in self._scores.get(agent_id, {})
            }
        return result


# Singleton
trust_store = TrustScoreStore()
