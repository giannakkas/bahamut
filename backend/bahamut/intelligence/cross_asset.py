"""
Bahamut v3 — Cross-Asset Intelligence Engine

Features:
  1. Rolling Correlation Matrix (20/50/100 periods)
  2. Divergence Detection (historically correlated assets diverging)
  3. Lead-Lag Detection (cross-correlation with lag)
  4. Risk-On/Risk-Off Score (global macro regime)

This module treats the market as a connected system, not isolated assets.
"""
import numpy as np
import time as _time
from dataclasses import dataclass, field
from typing import Optional
import structlog

logger = structlog.get_logger()

# ═══════════════════════════════════════════════════════════════
# KNOWN RELATIONSHIPS — pairs that should move together/inverse
# ═══════════════════════════════════════════════════════════════

CORRELATION_PAIRS = {
    # (asset_a, asset_b): expected_sign (+1 = positive, -1 = inverse)
    ("BTCUSD", "IXIC"): +1,       # BTC ↔ NASDAQ
    ("BTCUSD", "ETHUSD"): +1,     # BTC ↔ ETH
    ("BTCUSD", "SPX"): +1,        # BTC ↔ S&P
    ("EURUSD", "DXY"): -1,        # EUR ↔ DXY (inverse)
    ("GBPUSD", "DXY"): -1,        # GBP ↔ DXY (inverse)
    ("XAUUSD", "DXY"): -1,        # Gold ↔ DXY (inverse)
    ("XAUUSD", "SPX"): -1,        # Gold ↔ SPX (flight to safety)
    ("WTIUSD", "USDCAD"): -1,     # Oil ↔ CAD (Canada is oil exporter)
    ("SPX", "IXIC"): +1,          # SPX ↔ NASDAQ
    ("AUDUSD", "SPX"): +1,        # AUD ↔ Risk sentiment
    ("USDJPY", "SPX"): +1,        # JPY carry ↔ Risk
}

# Assets needed for risk-on/risk-off score
RISK_ASSETS = ["SPX", "IXIC", "BTCUSD", "XAUUSD", "EURUSD"]

# Assets to always fetch for cross-asset context
CONTEXT_ASSETS = [
    "SPX", "IXIC", "DXY", "BTCUSD", "ETHUSD",
    "XAUUSD", "EURUSD", "USDJPY", "WTIUSD",
]


@dataclass
class CorrelationResult:
    asset_a: str
    asset_b: str
    corr_20: float = 0.0
    corr_50: float = 0.0
    corr_100: float = 0.0
    expected_sign: int = 0
    trend: str = "STABLE"  # INCREASING, DECREASING, STABLE
    is_anomalous: bool = False


@dataclass
class DivergenceSignal:
    asset_a: str
    asset_b: str
    type: str = "divergence"
    strength: float = 0.0      # 0-1
    direction_bias: str = ""   # "bullish" or "bearish" for asset_a
    confidence: float = 0.0
    detail: str = ""


@dataclass
class LeadLagResult:
    leader: str
    follower: str
    lag_periods: int = 0
    correlation_at_lag: float = 0.0
    confidence: float = 0.0


@dataclass
class RiskRegimeScore:
    score: float = 0.0        # -1 (risk-off) to +1 (risk-on)
    label: str = "NEUTRAL"    # RISK_ON, RISK_OFF, NEUTRAL
    components: dict = field(default_factory=dict)
    confidence: float = 0.5


@dataclass
class CrossAssetContext:
    """Full cross-asset intelligence for a signal cycle."""
    risk_regime: RiskRegimeScore = field(default_factory=RiskRegimeScore)
    correlations: list = field(default_factory=list)
    divergences: list = field(default_factory=list)
    lead_lags: list = field(default_factory=list)
    signal_adjustment: float = 1.0   # multiplier for consensus score
    bias_adjustment: str = "NONE"    # BULLISH_BOOST, BEARISH_BOOST, CAUTION, BLOCK, NONE
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "risk_regime": {
                "score": self.risk_regime.score,
                "label": self.risk_regime.label,
                "components": self.risk_regime.components,
                "confidence": self.risk_regime.confidence,
            },
            "correlations": [
                {"pair": f"{c.asset_a}/{c.asset_b}", "c20": round(c.corr_20, 3),
                 "c50": round(c.corr_50, 3), "trend": c.trend, "anomaly": c.is_anomalous}
                for c in self.correlations[:5]  # Top 5
            ],
            "divergences": [
                {"pair": f"{d.asset_a}/{d.asset_b}", "strength": d.strength,
                 "bias": d.direction_bias, "confidence": d.confidence}
                for d in self.divergences
            ],
            "signal_adjustment": round(self.signal_adjustment, 3),
            "bias_adjustment": self.bias_adjustment,
        }


class CrossAssetEngine:
    """
    Core cross-asset intelligence engine.
    Operates on pre-fetched price series {asset: [close_prices]}.
    """

    def __init__(self):
        self._cache: dict[str, CrossAssetContext] = {}
        self._cache_ts: dict[str, float] = {}
        self._CACHE_TTL = 300  # 5 min

    def compute(
        self,
        price_series: dict[str, list[float]],
        target_asset: str,
        target_direction: str = "",
    ) -> CrossAssetContext:
        """
        Compute full cross-asset context.

        price_series: {"BTCUSD": [p1,p2,...,pN], "SPX": [...], ...}
                      All series must be aligned (same timestamps, same length).
        target_asset: The asset being analyzed (e.g. "BTCUSD")
        target_direction: "LONG" or "SHORT" if known, for bias calculation
        """
        cache_key = f"{target_asset}:{hash(str(sorted(price_series.keys())))}"
        now = _time.time()
        if cache_key in self._cache and (now - self._cache_ts.get(cache_key, 0)) < self._CACHE_TTL:
            return self._cache[cache_key]

        ctx = CrossAssetContext(updated_at=now)

        # 1. Correlations
        ctx.correlations = self._compute_correlations(price_series)

        # 2. Divergences
        ctx.divergences = self._detect_divergences(price_series, target_asset)

        # 3. Lead-lag
        ctx.lead_lags = self._detect_lead_lag(price_series, target_asset)

        # 4. Risk regime
        ctx.risk_regime = self._compute_risk_regime(price_series)

        # 5. Signal adjustments for the target asset
        ctx.signal_adjustment, ctx.bias_adjustment = self._compute_signal_adjustment(
            ctx, target_asset, target_direction
        )

        self._cache[cache_key] = ctx
        self._cache_ts[cache_key] = now
        return ctx

    # ═══════════════════════════════════════════════════════════
    # 1. ROLLING CORRELATIONS
    # ═══════════════════════════════════════════════════════════

    def _compute_correlations(self, prices: dict[str, list[float]]) -> list[CorrelationResult]:
        results = []

        for (a, b), expected_sign in CORRELATION_PAIRS.items():
            if a not in prices or b not in prices:
                continue

            pa, pb = np.array(prices[a]), np.array(prices[b])
            min_len = min(len(pa), len(pb))
            if min_len < 25:
                continue
            pa, pb = pa[-min_len:], pb[-min_len:]

            # Returns
            ra = np.diff(np.log(pa + 1e-10))
            rb = np.diff(np.log(pb + 1e-10))

            c20 = self._pearson(ra[-20:], rb[-20:]) if len(ra) >= 20 else 0
            c50 = self._pearson(ra[-50:], rb[-50:]) if len(ra) >= 50 else 0
            c100 = self._pearson(ra[-100:], rb[-100:]) if len(ra) >= 100 else c50

            # Trend: is correlation increasing or decreasing?
            trend = "STABLE"
            if abs(c20 - c50) > 0.15:
                trend = "INCREASING" if abs(c20) > abs(c50) else "DECREASING"

            # Anomaly: correlation flipped from expected?
            is_anomalous = False
            if expected_sign != 0 and len(ra) >= 20:
                if expected_sign > 0 and c20 < -0.3:
                    is_anomalous = True
                elif expected_sign < 0 and c20 > 0.3:
                    is_anomalous = True

            results.append(CorrelationResult(
                asset_a=a, asset_b=b,
                corr_20=round(c20, 4), corr_50=round(c50, 4), corr_100=round(c100, 4),
                expected_sign=expected_sign, trend=trend, is_anomalous=is_anomalous,
            ))

        return results

    def _pearson(self, a: np.ndarray, b: np.ndarray) -> float:
        if len(a) < 5 or len(b) < 5:
            return 0.0
        n = min(len(a), len(b))
        a, b = a[-n:], b[-n:]
        if np.std(a) < 1e-10 or np.std(b) < 1e-10:
            return 0.0
        return float(np.corrcoef(a, b)[0, 1])

    # ═══════════════════════════════════════════════════════════
    # 2. DIVERGENCE DETECTION
    # ═══════════════════════════════════════════════════════════

    def _detect_divergences(
        self, prices: dict[str, list[float]], target_asset: str
    ) -> list[DivergenceSignal]:
        divergences = []
        if target_asset not in prices:
            return divergences

        target_prices = prices[target_asset]
        if len(target_prices) < 20:
            return divergences

        target_ret = (target_prices[-1] - target_prices[-10]) / (target_prices[-10] + 1e-10)

        for (a, b), expected_sign in CORRELATION_PAIRS.items():
            # Find pairs involving our target
            related_asset = None
            if a == target_asset:
                related_asset = b
            elif b == target_asset:
                related_asset = a
            else:
                continue

            if related_asset not in prices or len(prices[related_asset]) < 20:
                continue

            rel_prices = prices[related_asset]
            rel_ret = (rel_prices[-1] - rel_prices[-10]) / (rel_prices[-10] + 1e-10)

            # Check for divergence
            # If expected positive correlation: both should move same direction
            # If expected negative: opposite direction
            if expected_sign > 0:
                # Should move together — divergence if opposite
                if target_ret > 0.005 and rel_ret < -0.005:
                    strength = min(1.0, abs(target_ret - rel_ret) * 10)
                    divergences.append(DivergenceSignal(
                        asset_a=target_asset, asset_b=related_asset,
                        strength=round(strength, 3),
                        direction_bias="bearish",  # Target up but related down = target may revert
                        confidence=round(min(0.85, strength * 0.8), 3),
                        detail=f"{target_asset} +{target_ret:.2%} but {related_asset} {rel_ret:.2%}",
                    ))
                elif target_ret < -0.005 and rel_ret > 0.005:
                    strength = min(1.0, abs(target_ret - rel_ret) * 10)
                    divergences.append(DivergenceSignal(
                        asset_a=target_asset, asset_b=related_asset,
                        strength=round(strength, 3),
                        direction_bias="bullish",  # Target down but related up = target may catch up
                        confidence=round(min(0.85, strength * 0.8), 3),
                        detail=f"{target_asset} {target_ret:.2%} but {related_asset} +{rel_ret:.2%}",
                    ))

            elif expected_sign < 0:
                # Should move opposite — divergence if same direction
                if target_ret > 0.005 and rel_ret > 0.005:
                    strength = min(1.0, abs(target_ret + rel_ret) * 8)
                    divergences.append(DivergenceSignal(
                        asset_a=target_asset, asset_b=related_asset,
                        strength=round(strength, 3),
                        direction_bias="caution",
                        confidence=round(min(0.75, strength * 0.7), 3),
                        detail=f"Both {target_asset} and {related_asset} rising (normally inverse)",
                    ))

        return divergences

    # ═══════════════════════════════════════════════════════════
    # 3. LEAD-LAG DETECTION
    # ═══════════════════════════════════════════════════════════

    def _detect_lead_lag(
        self, prices: dict[str, list[float]], target_asset: str
    ) -> list[LeadLagResult]:
        results = []
        if target_asset not in prices:
            return results

        target = np.array(prices[target_asset])
        if len(target) < 30:
            return results

        target_ret = np.diff(np.log(target + 1e-10))

        for (a, b), _ in CORRELATION_PAIRS.items():
            related = None
            if a == target_asset:
                related = b
            elif b == target_asset:
                related = a
            else:
                continue

            if related not in prices or len(prices[related]) < 30:
                continue

            rel = np.array(prices[related])
            n = min(len(target_ret), len(rel) - 1)
            if n < 20:
                continue

            rel_ret = np.diff(np.log(rel + 1e-10))
            t_ret = target_ret[-n:]
            r_ret = rel_ret[-n:]

            # Cross-correlation with lags -5 to +5
            best_lag = 0
            best_corr = 0.0

            for lag in range(-5, 6):
                if lag == 0:
                    continue
                if lag > 0:
                    # Related leads target by `lag` periods
                    c = self._pearson(r_ret[:-lag], t_ret[lag:])
                else:
                    # Target leads related by `|lag|` periods
                    c = self._pearson(t_ret[:lag], r_ret[-lag:])

                if abs(c) > abs(best_corr):
                    best_corr = c
                    best_lag = lag

            if abs(best_corr) > 0.3 and best_lag != 0:
                if best_lag > 0:
                    leader, follower = related, target_asset
                else:
                    leader, follower = target_asset, related

                results.append(LeadLagResult(
                    leader=leader, follower=follower,
                    lag_periods=abs(best_lag),
                    correlation_at_lag=round(best_corr, 4),
                    confidence=round(min(0.85, abs(best_corr)), 3),
                ))

        return results

    # ═══════════════════════════════════════════════════════════
    # 4. RISK-ON / RISK-OFF SCORE
    # ═══════════════════════════════════════════════════════════

    def _compute_risk_regime(self, prices: dict[str, list[float]]) -> RiskRegimeScore:
        components = {}
        score = 0.0
        weight_sum = 0.0

        # SPX trend (10-period return)
        if "SPX" in prices and len(prices["SPX"]) >= 20:
            spx = prices["SPX"]
            spx_ret_10 = (spx[-1] - spx[-10]) / (spx[-10] + 1e-10)
            spx_ret_20 = (spx[-1] - spx[-20]) / (spx[-20] + 1e-10)
            spx_score = np.clip(spx_ret_10 * 20, -1, 1)  # Normalize
            components["spx_trend"] = round(float(spx_score), 3)
            score += spx_score * 0.25
            weight_sum += 0.25

        # NASDAQ trend
        if "IXIC" in prices and len(prices["IXIC"]) >= 10:
            ixic = prices["IXIC"]
            ixic_ret = (ixic[-1] - ixic[-10]) / (ixic[-10] + 1e-10)
            ixic_score = np.clip(ixic_ret * 20, -1, 1)
            components["nasdaq_trend"] = round(float(ixic_score), 3)
            score += ixic_score * 0.15
            weight_sum += 0.15

        # BTC trend (risk appetite proxy)
        if "BTCUSD" in prices and len(prices["BTCUSD"]) >= 10:
            btc = prices["BTCUSD"]
            btc_ret = (btc[-1] - btc[-10]) / (btc[-10] + 1e-10)
            btc_score = np.clip(btc_ret * 15, -1, 1)
            components["btc_trend"] = round(float(btc_score), 3)
            score += btc_score * 0.15
            weight_sum += 0.15

        # Gold (inverse — rising gold = risk-off)
        if "XAUUSD" in prices and len(prices["XAUUSD"]) >= 10:
            gold = prices["XAUUSD"]
            gold_ret = (gold[-1] - gold[-10]) / (gold[-10] + 1e-10)
            gold_score = np.clip(-gold_ret * 15, -1, 1)  # Inverse
            components["gold_trend"] = round(float(gold_score), 3)
            score += gold_score * 0.15
            weight_sum += 0.15

        # DXY (rising DXY = risk-off for most assets)
        if "DXY" in prices and len(prices["DXY"]) >= 10:
            dxy = prices["DXY"]
            dxy_ret = (dxy[-1] - dxy[-10]) / (dxy[-10] + 1e-10)
            dxy_score = np.clip(-dxy_ret * 30, -1, 1)
            components["dxy_trend"] = round(float(dxy_score), 3)
            score += dxy_score * 0.15
            weight_sum += 0.15

        # EUR (as DXY inverse proxy)
        if "EURUSD" in prices and len(prices["EURUSD"]) >= 10:
            eur = prices["EURUSD"]
            eur_ret = (eur[-1] - eur[-10]) / (eur[-10] + 1e-10)
            eur_score = np.clip(eur_ret * 25, -1, 1)
            components["eur_trend"] = round(float(eur_score), 3)
            score += eur_score * 0.15
            weight_sum += 0.15

        # Normalize
        if weight_sum > 0:
            score = score / weight_sum

        score = float(np.clip(score, -1, 1))

        if score > 0.3:
            label = "RISK_ON"
        elif score < -0.3:
            label = "RISK_OFF"
        else:
            label = "NEUTRAL"

        confidence = min(0.95, 0.4 + abs(score) * 0.5)

        return RiskRegimeScore(
            score=round(score, 4),
            label=label,
            components=components,
            confidence=round(confidence, 3),
        )

    # ═══════════════════════════════════════════════════════════
    # 5. SIGNAL ADJUSTMENT LOGIC
    # ═══════════════════════════════════════════════════════════

    def _compute_signal_adjustment(
        self, ctx: CrossAssetContext, target_asset: str, target_direction: str
    ) -> tuple[float, str]:
        """
        Compute signal multiplier and bias based on cross-asset context.
        Returns (multiplier, bias_label)
        """
        multiplier = 1.0
        bias = "NONE"
        risk = ctx.risk_regime

        # Risk regime adjustment
        if target_direction == "LONG":
            if risk.label == "RISK_OFF":
                # Going long in risk-off → reduce conviction
                multiplier *= 0.75
                bias = "CAUTION"
            elif risk.label == "RISK_ON":
                multiplier *= 1.10
                bias = "BULLISH_BOOST"
        elif target_direction == "SHORT":
            if risk.label == "RISK_ON":
                # Shorting in risk-on → reduce conviction
                multiplier *= 0.75
                bias = "CAUTION"
            elif risk.label == "RISK_OFF":
                multiplier *= 1.10
                bias = "BEARISH_BOOST"

        # Divergence adjustment
        for div in ctx.divergences:
            if div.strength > 0.5 and div.confidence > 0.5:
                if div.direction_bias == "bearish" and target_direction == "LONG":
                    multiplier *= 0.85  # Divergence against our direction
                    bias = "CAUTION"
                elif div.direction_bias == "bullish" and target_direction == "SHORT":
                    multiplier *= 0.85
                    bias = "CAUTION"
                elif div.direction_bias == target_direction.lower():
                    multiplier *= 1.05  # Divergence supports our direction

        # Anomalous correlations → extra caution
        anomalies = [c for c in ctx.correlations if c.is_anomalous]
        if len(anomalies) >= 2:
            multiplier *= 0.80
            if bias == "NONE":
                bias = "CAUTION"

        multiplier = round(max(0.5, min(1.3, multiplier)), 3)
        return multiplier, bias


# Singleton
cross_asset_engine = CrossAssetEngine()
