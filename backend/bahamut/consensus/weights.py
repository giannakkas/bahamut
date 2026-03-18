"""
Bahamut.AI Dynamic Weight Resolver

effective_weight(agent) = base * trust * regime * timeframe * event_proximity

Replaces static BASE_WEIGHTS dicts with context-aware resolution.
"""
import structlog

logger = structlog.get_logger()

DEFAULT_BASE_WEIGHTS = {
    "fx":          {"macro_agent": 0.25, "volatility_agent": 0.15, "liquidity_agent": 0.15, "sentiment_agent": 0.15, "technical_agent": 0.30},
    "indices":     {"macro_agent": 0.20, "volatility_agent": 0.20, "liquidity_agent": 0.15, "sentiment_agent": 0.15, "technical_agent": 0.30},
    "commodities": {"macro_agent": 0.20, "volatility_agent": 0.15, "liquidity_agent": 0.15, "sentiment_agent": 0.25, "technical_agent": 0.25},
    "crypto":      {"macro_agent": 0.10, "volatility_agent": 0.15, "liquidity_agent": 0.20, "sentiment_agent": 0.25, "technical_agent": 0.30},
    "bonds":       {"macro_agent": 0.30, "volatility_agent": 0.15, "liquidity_agent": 0.10, "sentiment_agent": 0.15, "technical_agent": 0.30},
}

REGIME_FACTORS = {
    "RISK_OFF":            {"macro_agent": 1.0, "volatility_agent": 1.0, "sentiment_agent": 0.9, "technical_agent": 0.5, "liquidity_agent": 0.7},
    "RISK_ON":             {"macro_agent": 0.8, "technical_agent": 1.0, "volatility_agent": 0.6, "sentiment_agent": 0.7, "liquidity_agent": 0.8},
    "HIGH_VOL":            {"volatility_agent": 1.0, "macro_agent": 0.7, "technical_agent": 0.5, "sentiment_agent": 0.8, "liquidity_agent": 0.8},
    "LOW_VOL":             {"technical_agent": 1.0, "liquidity_agent": 1.0, "macro_agent": 0.6, "volatility_agent": 0.5, "sentiment_agent": 0.5},
    "CRISIS":              {"macro_agent": 1.0, "volatility_agent": 1.0, "sentiment_agent": 1.0, "technical_agent": 0.3, "liquidity_agent": 0.6},
    "TREND_CONTINUATION":  {"technical_agent": 1.0, "macro_agent": 0.8, "volatility_agent": 0.6, "sentiment_agent": 0.6, "liquidity_agent": 0.7},
}

TIMEFRAME_FACTORS = {
    "1H": {"technical_agent": 1.1, "sentiment_agent": 1.0, "macro_agent": 0.6, "volatility_agent": 0.9, "liquidity_agent": 1.0},
    "4H": {"technical_agent": 1.0, "macro_agent": 0.9, "sentiment_agent": 0.9, "volatility_agent": 1.0, "liquidity_agent": 0.9},
    "1D": {"technical_agent": 0.9, "macro_agent": 1.1, "sentiment_agent": 0.8, "volatility_agent": 1.0, "liquidity_agent": 0.8},
}

EVENT_PROXIMITY_FACTORS = {
    "imminent": {"macro_agent": 1.3, "volatility_agent": 1.2, "sentiment_agent": 1.1, "technical_agent": 0.5, "liquidity_agent": 0.8},
    "near":     {"macro_agent": 1.1, "volatility_agent": 1.1, "sentiment_agent": 1.0, "technical_agent": 0.7, "liquidity_agent": 0.9},
    "far":      {"macro_agent": 1.0, "volatility_agent": 1.0, "sentiment_agent": 1.0, "technical_agent": 1.0, "liquidity_agent": 1.0},
}

WEIGHTED_AGENTS = ["macro_agent", "volatility_agent", "liquidity_agent", "sentiment_agent", "technical_agent"]


class DynamicWeightResolver:

    def resolve_weights(
        self, asset_class: str, regime: str, timeframe: str = "4H",
        trust_scores: dict[str, float] = None,
        profile_weight_overrides: dict[str, float] = None,
        event_distance_hours: float = None,
    ) -> dict[str, float]:
        trust_scores = trust_scores or {}
        profile_weight_overrides = profile_weight_overrides or {}

        base = DEFAULT_BASE_WEIGHTS.get(asset_class, DEFAULT_BASE_WEIGHTS["fx"]).copy()
        for aid, ov in profile_weight_overrides.items():
            if aid in base:
                base[aid] = ov

        # Try loading calibrated weights from DB
        db_w = self._load_db_weights(regime)
        if db_w:
            for aid, w in db_w.items():
                if aid in base:
                    base[aid] = w

        regime_f = REGIME_FACTORS.get(regime, {a: 0.7 for a in WEIGHTED_AGENTS})
        tf_f = TIMEFRAME_FACTORS.get(timeframe, {a: 1.0 for a in WEIGHTED_AGENTS})
        ev_f = self._get_event_factors(event_distance_hours)

        effective = {}
        for aid in WEIGHTED_AGENTS:
            effective[aid] = round(
                base.get(aid, 0.1)
                * trust_scores.get(aid, 1.0)
                * regime_f.get(aid, 0.7)
                * tf_f.get(aid, 1.0)
                * ev_f.get(aid, 1.0),
                4
            )
        return effective

    def _get_event_factors(self, hours):
        if hours is None: return EVENT_PROXIMITY_FACTORS["far"]
        if hours < 2: return EVENT_PROXIMITY_FACTORS["imminent"]
        if hours < 8: return EVENT_PROXIMITY_FACTORS["near"]
        return EVENT_PROXIMITY_FACTORS["far"]

    def _load_db_weights(self, regime: str):
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                r = conn.execute(text(
                    "SELECT optimal_weights FROM regime_snapshots WHERE regime_type = :r ORDER BY created_at DESC LIMIT 1"
                ), {"r": regime})
                row = r.first()
                if row and row[0] and isinstance(row[0], dict):
                    return row[0]
        except Exception:
            pass
        return None

    def get_weight_explanation(self, asset_class, regime, timeframe="4H",
                               trust_scores=None, event_distance_hours=None):
        trust_scores = trust_scores or {}
        base = DEFAULT_BASE_WEIGHTS.get(asset_class, DEFAULT_BASE_WEIGHTS["fx"])
        rf = REGIME_FACTORS.get(regime, {})
        tf = TIMEFRAME_FACTORS.get(timeframe, {})
        ef = self._get_event_factors(event_distance_hours)
        eff = self.resolve_weights(asset_class, regime, timeframe, trust_scores,
                                    event_distance_hours=event_distance_hours)
        return [{
            "agent_id": a,
            "base_weight": base.get(a, 0.1),
            "trust_multiplier": round(trust_scores.get(a, 1.0), 3),
            "regime_factor": rf.get(a, 0.7),
            "timeframe_factor": tf.get(a, 1.0),
            "event_factor": ef.get(a, 1.0),
            "effective_weight": eff.get(a, 0.1),
        } for a in WEIGHTED_AGENTS]


weight_resolver = DynamicWeightResolver()
