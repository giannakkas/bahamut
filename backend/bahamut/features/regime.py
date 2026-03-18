"""
Bahamut.AI Regime Detection Engine

Classifies market conditions from features:
  RISK_ON / RISK_OFF, TREND / RANGE, HIGH_VOL / LOW_VOL, CRISIS

Feeds into: agent weighting, consensus thresholds, execution policy.
"""
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()


@dataclass
class RegimeState:
    primary_regime: str = "RISK_ON"
    risk_appetite: str = "RISK_ON"
    trend_state: str = "TREND_CONTINUATION"
    volatility_state: str = "LOW_VOL"
    crisis_flag: bool = False
    confidence: float = 0.5
    feature_vector: list[float] = field(default_factory=list)
    transition_reason: str = ""
    previous_regime: str = ""

    def to_dict(self):
        return {
            "primary_regime": self.primary_regime,
            "risk_appetite": self.risk_appetite,
            "trend_state": self.trend_state,
            "volatility_state": self.volatility_state,
            "crisis_flag": self.crisis_flag,
            "confidence": round(self.confidence, 3),
            "transition_reason": self.transition_reason,
            "previous_regime": self.previous_regime,
        }


_current_regime: RegimeState | None = None


def detect_regime_from_features(features: dict) -> RegimeState:
    global _current_regime

    ind = features.get("indicators", {})
    vix = features.get("vix", ind.get("vix", 18.0))
    close = ind.get("close", 0)
    ema20 = ind.get("ema_20", close)
    ema50 = ind.get("ema_50", close)
    ema200 = ind.get("ema_200", close)
    rsi = ind.get("rsi_14", 50)
    adx = ind.get("adx", 20)
    macd = ind.get("macd", 0)
    macd_sig = ind.get("macd_signal", 0)

    previous = _current_regime.primary_regime if _current_regime else "UNKNOWN"

    # Volatility
    if vix >= 35: vol_state, crisis = "HIGH_VOL", True
    elif vix >= 25: vol_state, crisis = "HIGH_VOL", False
    elif vix <= 15: vol_state, crisis = "LOW_VOL", False
    else: vol_state, crisis = "LOW_VOL", False

    # Trend
    if adx >= 25 and close != 0:
        trend = "TREND_CONTINUATION" if (close > ema20 > ema50) or (close < ema20 < ema50) else "RANGE"
    else:
        trend = "RANGE"

    # Risk appetite composite (-1 to +1)
    score = 0.0
    if close > ema200 and ema200 > 0: score += 0.3
    elif close < ema200 and ema200 > 0: score -= 0.3
    if rsi > 60: score += 0.2
    elif rsi < 40: score -= 0.2
    if vix < 15: score += 0.3
    elif vix > 25: score -= 0.3
    elif vix > 20: score -= 0.1
    if macd > macd_sig: score += 0.1
    else: score -= 0.1
    if ema20 > ema50 > 0: score += 0.1
    elif ema20 < ema50 and ema50 > 0: score -= 0.1

    risk_appetite = "RISK_ON" if score > -0.3 else "RISK_OFF"

    # Primary regime
    if crisis: primary = "CRISIS"
    elif vol_state == "HIGH_VOL": primary = "HIGH_VOL"
    elif risk_appetite == "RISK_OFF": primary = "RISK_OFF"
    elif trend == "TREND_CONTINUATION": primary = "TREND_CONTINUATION"
    elif vol_state == "LOW_VOL": primary = "LOW_VOL"
    else: primary = "RISK_ON"

    confidence = min(1.0, abs(score) + 0.3)
    transition = f"{previous} → {primary}" if previous != primary and previous != "UNKNOWN" else ""

    feature_vector = [score, vix / 40.0, rsi / 100.0, adx / 50.0,
                       1.0 if close > ema200 else 0.0, 1.0 if ema20 > ema50 else 0.0]

    state = RegimeState(
        primary_regime=primary, risk_appetite=risk_appetite, trend_state=trend,
        volatility_state=vol_state, crisis_flag=crisis, confidence=confidence,
        feature_vector=feature_vector, transition_reason=transition, previous_regime=previous,
    )
    _current_regime = state

    if transition:
        logger.warning("regime_transition", transition=transition, confidence=confidence)
        _persist_regime(state)
    return state


def get_current_regime() -> RegimeState:
    global _current_regime
    return _current_regime or RegimeState()


def _persist_regime(state: RegimeState):
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO market_regimes (id, regime, confidence, previous_regime, transition_reason, feature_vector, detector_version)
                VALUES (gen_random_uuid(), :r, :c, :p, :t, :f, 'v2')
            """), {"r": state.primary_regime, "c": state.confidence,
                   "p": state.previous_regime, "t": state.transition_reason,
                   "f": state.feature_vector})
            conn.commit()
    except Exception as e:
        logger.warning("regime_persist_failed", error=str(e))


def compute_regime_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b): return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    ma = sum(x * x for x in a) ** 0.5
    mb = sum(x * x for x in b) ** 0.5
    if ma == 0 or mb == 0: return 0.0
    return round(dot / (ma * mb), 4)
