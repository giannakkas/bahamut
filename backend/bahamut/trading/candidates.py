"""
Bahamut.AI — Trade Candidates Scorer

Evaluates how CLOSE each training asset is to triggering a trade.
Read-only intelligence layer — does NOT execute trades.

For each asset × strategy, computes:
  - readiness_score (0–100): proximity to trigger conditions
  - distance_to_trigger: how far from the actual trigger point
  - reasons: human-readable explanation of the setup
  - key indicators: RSI, EMA alignment, volume, ATR

Scoring logic per strategy:

  v5_base / v5_tuned (EMA20×50 golden cross):
    Required: close > EMA200 (bull regime)
    Trigger: EMA20 crosses above EMA50
    Score based on: EMA gap narrowing, trend alignment, RSI support

  v9_breakout (confirmed breakout):
    Trigger: close above 20-bar high for 3 bars
    Score based on: distance to 20-bar high, bars confirmed, range expansion
"""
import numpy as np
import structlog
from dataclasses import dataclass

logger = structlog.get_logger()


@dataclass
class Candidate:
    asset: str
    asset_class: str
    strategy: str
    direction: str
    score: int          # 0-100
    regime: str
    distance_to_trigger: str
    reasons: list
    indicators: dict
    score_breakdown: dict = None   # component scores
    missing_conditions: list = None  # what's needed to trigger
    explanation: str = ""            # natural-language summary

    def __post_init__(self):
        if self.score_breakdown is None:
            self.score_breakdown = {}
        if self.missing_conditions is None:
            self.missing_conditions = []


def score_ema_cross(
    asset: str,
    asset_class: str,
    strategy_name: str,
    candles: list,
    indicators: dict,
    prev_indicators: dict | None,
) -> Candidate | None:
    """Score proximity to EMA20×50 golden cross in bull regime."""
    close = indicators.get("close", 0)
    ema_20 = indicators.get("ema_20", 0)
    ema_50 = indicators.get("ema_50", 0)
    ema_200 = indicators.get("ema_200", 0)
    rsi = indicators.get("rsi_14", 50)
    atr = indicators.get("atr_14", 0)
    volume = indicators.get("volume", 0)
    vol_sma = indicators.get("volume_sma_20", 1)

    if close <= 0 or ema_20 <= 0 or ema_50 <= 0 or ema_200 <= 0:
        return None

    reasons = []
    missing = []
    direction = "LONG"
    bd = {"regime": 0, "ema_proximity": 0, "ema_convergence": 0, "rsi": 0, "volume": 0}

    # ── 1. Bull regime check (required gate) ──
    above_200 = close > ema_200
    dist_to_200_pct = (close - ema_200) / ema_200 * 100

    if above_200:
        bd["regime"] = 25
        reasons.append(f"Bull regime: price {dist_to_200_pct:.1f}% above EMA200")
    else:
        bd["regime"] = max(0, int(15 + dist_to_200_pct * 2))
        reasons.append(f"Bearish: price {abs(dist_to_200_pct):.1f}% below EMA200")
        missing.append(f"Need price above EMA200 ({abs(dist_to_200_pct):.1f}% away)")
        total = min(bd["regime"], 35)
        return Candidate(
            asset=asset, asset_class=asset_class, strategy=strategy_name,
            direction=direction, score=total, regime="BEAR",
            distance_to_trigger=f"{abs(dist_to_200_pct):.1f}% below EMA200",
            reasons=reasons, indicators=_fmt_indicators(indicators),
            score_breakdown=bd, missing_conditions=missing,
            explanation=f"Bearish regime blocks entry. Price is {abs(dist_to_200_pct):.1f}% below EMA200 — no EMA cross can trigger until price recovers above the 200-period moving average.",
        )

    # ── 2. EMA gap (core signal proximity) ──
    ema_gap_pct = (ema_20 - ema_50) / ema_50 * 100
    ema_gap_abs = abs(ema_gap_pct)

    if ema_gap_pct > 0:
        if ema_gap_abs < 0.5:
            bd["ema_proximity"] = 30
            reasons.append(f"EMA20 just crossed above EMA50 (+{ema_gap_pct:.2f}%)")
        elif ema_gap_abs < 1.5:
            bd["ema_proximity"] = 20
            reasons.append(f"EMA20 above EMA50 (+{ema_gap_pct:.2f}%)")
        else:
            bd["ema_proximity"] = 10
            reasons.append(f"EMAs already spread (+{ema_gap_pct:.1f}%)")
    else:
        if ema_gap_abs < 0.3:
            bd["ema_proximity"] = 35
            reasons.append(f"EMA20 converging on EMA50 (gap: {ema_gap_pct:.2f}%)")
        elif ema_gap_abs < 1.0:
            bd["ema_proximity"] = 25
            reasons.append(f"EMA20 approaching EMA50 (gap: {ema_gap_pct:.2f}%)")
        elif ema_gap_abs < 2.0:
            bd["ema_proximity"] = 15
            reasons.append(f"EMAs narrowing (gap: {ema_gap_pct:.1f}%)")
        else:
            bd["ema_proximity"] = 5
            reasons.append(f"EMAs wide apart ({ema_gap_pct:.1f}%)")
        missing.append(f"Need EMA20 to cross above EMA50 (gap: {ema_gap_abs:.2f}%)")

    # Convergence direction
    if prev_indicators:
        prev_gap = (prev_indicators.get("ema_20", 0) - prev_indicators.get("ema_50", 0))
        curr_gap = ema_20 - ema_50
        if prev_gap < 0 and curr_gap > prev_gap:
            bd["ema_convergence"] = 10
            reasons.append("EMAs converging (gap narrowing)")

    # ── 3. RSI support ──
    if 40 <= rsi <= 60:
        bd["rsi"] = 10
        reasons.append(f"RSI neutral at {rsi:.0f}")
    elif 30 <= rsi < 40:
        bd["rsi"] = 15
        reasons.append(f"RSI approaching oversold ({rsi:.0f})")
    elif rsi < 30:
        bd["rsi"] = 8
        reasons.append(f"RSI oversold ({rsi:.0f}) — reversal likely")
    elif rsi > 70:
        bd["rsi"] = -5
        reasons.append(f"RSI overbought ({rsi:.0f})")
        missing.append(f"RSI overbought at {rsi:.0f} — wait for pullback")

    # ── 4. Volume confirmation ──
    if vol_sma > 0:
        vol_ratio = volume / vol_sma
        if vol_ratio > 1.5:
            bd["volume"] = 10
            reasons.append(f"Volume {vol_ratio:.1f}× above average")
        elif vol_ratio > 1.0:
            bd["volume"] = 5

    # ── Totals ──
    total = sum(bd.values())
    total = min(100, max(0, total))

    if ema_gap_pct > 0:
        distance = "Triggered (EMA20 > EMA50)"
    else:
        distance = f"EMA20 {ema_gap_abs:.2f}% below EMA50"

    regime = "TREND" if above_200 and ema_20 > ema_50 else "RANGE"

    # Build explanation
    if total >= 80:
        expl = f"Setup is very close. Bull regime confirmed, EMAs {'already crossed' if ema_gap_pct > 0 else f'only {ema_gap_abs:.2f}% from crossing'}."
    elif total >= 60:
        expl = f"Bull regime active but EMA20 still {'spreading from' if ema_gap_pct > 0 else f'{ema_gap_abs:.1f}% below'} EMA50. Setup is approaching but not ready."
    elif total >= 40:
        expl = f"Bull regime active. EMAs are {ema_gap_abs:.1f}% apart — convergence needed before a golden cross can form."
    else:
        expl = f"Weak setup. EMAs are {ema_gap_abs:.1f}% apart with no strong convergence signal."

    if not missing:
        missing.append("All conditions met — signal may fire on next bar")

    return Candidate(
        asset=asset, asset_class=asset_class, strategy=strategy_name,
        direction=direction, score=total, regime=regime,
        distance_to_trigger=distance, reasons=reasons,
        indicators=_fmt_indicators(indicators),
        score_breakdown=bd, missing_conditions=missing, explanation=expl,
    )


def score_breakout(
    asset: str,
    asset_class: str,
    candles: list,
    indicators: dict,
) -> Candidate | None:
    """Score proximity to v9 confirmed breakout."""
    close = indicators.get("close", 0)
    atr = indicators.get("atr_14", 0)
    ema_200 = indicators.get("ema_200", 0)
    rsi = indicators.get("rsi_14", 50)

    if close <= 0 or atr <= 0 or len(candles) < 30:
        return None

    lookback = 20
    confirm_bars = 3
    reasons = []
    missing = []
    direction = "LONG"
    bd = {"breakout_proximity": 0, "confirmation": 0, "volatility": 0, "rsi": 0, "crash_penalty": 0}

    ref_candles = candles[-(lookback + confirm_bars + 1):-(confirm_bars + 1)]
    if len(ref_candles) < lookback - 2:
        return None

    ref_high = max(c["high"] for c in ref_candles)
    dist_to_high_pct = (close - ref_high) / ref_high * 100
    dist_in_atr = (close - ref_high) / atr if atr > 0 else 0

    if close > ref_high:
        confirm_candles = candles[-(confirm_bars + 1):-1]
        bars_confirmed = sum(1 for c in confirm_candles if c["close"] > ref_high * 0.995)
        if bars_confirmed >= confirm_bars and close > ref_high * 0.995:
            bd["breakout_proximity"] = 35
            bd["confirmation"] = 15
            reasons.append(f"BREAKOUT CONFIRMED: held above ${ref_high:,.0f} for {bars_confirmed} bars")
        elif bars_confirmed >= 2:
            bd["breakout_proximity"] = 30
            bd["confirmation"] = 10
            reasons.append(f"2/{confirm_bars} confirmation bars above ${ref_high:,.0f}")
            missing.append(f"Need 1 more bar closing above ${ref_high:,.0f}")
        elif bars_confirmed >= 1:
            bd["breakout_proximity"] = 25
            bd["confirmation"] = 5
            reasons.append(f"1/{confirm_bars} confirmation bars above ${ref_high:,.0f}")
            missing.append(f"Need {confirm_bars - 1} more bars above ${ref_high:,.0f}")
        else:
            bd["breakout_proximity"] = 20
            reasons.append(f"Just broke above 20-bar high ${ref_high:,.0f}")
            missing.append(f"Need {confirm_bars} confirmation bars above ${ref_high:,.0f}")
        if dist_in_atr > 3.0:
            bd["crash_penalty"] = -15
            reasons.append(f"Too extended ({dist_in_atr:.1f} ATR above)")
    else:
        if abs(dist_to_high_pct) < 1.0:
            bd["breakout_proximity"] = 30
            reasons.append(f"Price {abs(dist_to_high_pct):.1f}% below 20-bar high (very close)")
        elif abs(dist_to_high_pct) < 3.0:
            bd["breakout_proximity"] = 20
            reasons.append(f"Price {abs(dist_to_high_pct):.1f}% below 20-bar high")
        elif abs(dist_to_high_pct) < 5.0:
            bd["breakout_proximity"] = 10
            reasons.append(f"Price {abs(dist_to_high_pct):.1f}% below 20-bar high")
        else:
            bd["breakout_proximity"] = 3
            reasons.append(f"Price {abs(dist_to_high_pct):.1f}% below breakout level")
        missing.append(f"Need {abs(dist_to_high_pct):.1f}% move to break ${ref_high:,.0f}")

    if len(candles) >= 10:
        recent_ranges = [c["high"] - c["low"] for c in candles[-5:]]
        prior_ranges = [c["high"] - c["low"] for c in candles[-10:-5]]
        if prior_ranges and recent_ranges:
            expansion = np.mean(recent_ranges) / (np.mean(prior_ranges) + 1e-10)
            if expansion > 1.3:
                bd["volatility"] = 15
                reasons.append(f"Range expanding ({expansion:.1f}×)")
            elif expansion > 1.1:
                bd["volatility"] = 8
                reasons.append(f"Range slightly expanding ({expansion:.1f}×)")

    if ema_200 > 0 and close < ema_200 * 0.90:
        cap = 15
        current_total = sum(bd.values())
        if current_total > cap:
            bd["crash_penalty"] = cap - current_total
        reasons.append("Deep below EMA200 — crash risk")
        missing.append("Need recovery above EMA200")

    if 50 < rsi < 70:
        bd["rsi"] = 10
        reasons.append(f"RSI bullish ({rsi:.0f})")
    elif rsi > 70:
        bd["rsi"] = 5
        reasons.append(f"RSI overbought ({rsi:.0f})")

    total = min(100, max(0, sum(bd.values())))
    distance = f"{'above' if close > ref_high else 'below'} by {abs(dist_to_high_pct):.1f}%"
    regime = "BREAKOUT" if close > ref_high else "RANGE"

    if total >= 80:
        expl = f"Strong breakout setup. Price {'confirmed above' if close > ref_high else 'very close to'} 20-bar high at ${ref_high:,.0f}."
    elif total >= 60:
        expl = f"Approaching breakout. Price {abs(dist_to_high_pct):.1f}% {'above' if close > ref_high else 'below'} the 20-bar high."
    elif total >= 30:
        expl = f"Moderate setup. Breakout level at ${ref_high:,.0f} is {abs(dist_to_high_pct):.1f}% away."
    else:
        expl = f"No setup: breakout level at ${ref_high:,.0f} is {abs(dist_to_high_pct):.1f}% away, no momentum."

    if not missing:
        missing.append("All breakout conditions met — signal may fire")

    return Candidate(
        asset=asset, asset_class=asset_class, strategy="v9_breakout",
        direction=direction, score=total, regime=regime,
        distance_to_trigger=distance, reasons=reasons,
        indicators=_fmt_indicators(indicators),
        score_breakdown=bd, missing_conditions=missing, explanation=expl,
    )


def _fmt_indicators(ind: dict) -> dict:
    """Format indicators for API response."""
    close = ind.get("close", 0)
    ema_20 = ind.get("ema_20", 0)
    ema_50 = ind.get("ema_50", 0)
    ema_200 = ind.get("ema_200", 0)

    if ema_20 > ema_50 > ema_200:
        alignment = "bullish_stack"
    elif ema_20 > ema_50:
        alignment = "bullish"
    elif ema_20 < ema_50 < ema_200:
        alignment = "bearish_stack"
    elif ema_20 < ema_50:
        alignment = "bearish"
    else:
        alignment = "neutral"

    return {
        "close": round(close, 4),
        "rsi": round(ind.get("rsi_14", 0), 1),
        "ema_20": round(ema_20, 4),
        "ema_50": round(ema_50, 4),
        "ema_200": round(ema_200, 4),
        "atr": round(ind.get("atr_14", 0), 6),
        "ema_alignment": alignment,
        "volume_ratio": round(ind.get("volume", 0) / max(1, ind.get("volume_sma_20", 1)), 2),
    }


# ═══════════════════════════════════════════
# MAIN SCANNER
# ═══════════════════════════════════════════

def get_training_candidates(max_results: int = 20) -> list[dict]:
    """
    Scan all training assets and return top candidates ranked by readiness score.
    Does NOT execute any trades.
    """
    import time
    from bahamut.config_assets import TRADING_ASSETS, ASSET_CLASS_MAP
    from dataclasses import asdict

    start = time.time()
    candidates = []

    # Process in batches to be kind to data layer
    batch_size = 10
    for i in range(0, len(TRADING_ASSETS), batch_size):
        batch = TRADING_ASSETS[i:i + batch_size]
        for asset in batch:
            try:
                asset_candidates = _evaluate_asset(asset, ASSET_CLASS_MAP.get(asset, "unknown"))
                candidates.extend(asset_candidates)
            except Exception as e:
                logger.debug("candidate_eval_failed", asset=asset, error=str(e))

    # Sort by score descending, take top N
    candidates.sort(key=lambda c: c.score, reverse=True)
    top = candidates[:max_results]

    duration_ms = int((time.time() - start) * 1000)
    logger.info("candidates_scanned",
                assets=len(TRADING_ASSETS), candidates=len(candidates),
                top_returned=len(top), duration_ms=duration_ms)

    return [
        {
            "asset": c.asset,
            "asset_class": c.asset_class,
            "strategy": c.strategy,
            "direction": c.direction,
            "score": c.score,
            "regime": c.regime,
            "distance_to_trigger": c.distance_to_trigger,
            "reasons": c.reasons,
            "indicators": c.indicators,
            "score_breakdown": c.score_breakdown,
            "missing_conditions": c.missing_conditions,
            "explanation": c.explanation,
        }
        for c in top
    ]


def _evaluate_asset(asset: str, asset_class: str) -> list[Candidate]:
    """Evaluate one asset against all strategies. Returns list of candidates."""
    from bahamut.data.live_data import fetch_candles
    from bahamut.features.indicators import compute_indicators

    candles = fetch_candles(asset, count=100)
    if not candles or len(candles) < 50:
        return []

    indicators = compute_indicators(candles)
    if not indicators:
        return []

    prev_indicators = compute_indicators(candles[:-1]) if len(candles) > 1 else None
    results = []

    # v5_base
    c = score_ema_cross(asset, asset_class, "v5_base", candles, indicators, prev_indicators)
    if c and c.score >= 20:
        results.append(c)

    # v5_tuned (same trigger, different score? No — same logic, skip duplicate)
    # Only show one EMA cross candidate per asset

    # v9_breakout
    c = score_breakout(asset, asset_class, candles, indicators)
    if c and c.score >= 20:
        results.append(c)

    return results


def _evaluate_asset_full(asset: str, asset_class: str) -> dict:
    """Evaluate one asset and return its best score across all strategies.
    Always returns a result, even if no signal (score=0)."""
    from bahamut.data.live_data import fetch_candles
    from bahamut.features.indicators import compute_indicators

    base = {
        "asset": asset,
        "asset_class": asset_class,
        "score": 0,
        "status": "no_data",
        "strategy": "—",
        "direction": "—",
        "regime": "—",
        "distance_to_trigger": "—",
        "reason": "Insufficient data",
        "reasons": [],
        "indicators": {},
        "score_breakdown": {},
        "missing_conditions": [],
        "explanation": "",
    }

    try:
        candles = fetch_candles(asset, count=100)
    except Exception:
        return base

    if not candles or len(candles) < 50:
        base["reason"] = f"Only {len(candles) if candles else 0} candles (need 50+)"
        return base

    indicators = compute_indicators(candles)
    if not indicators:
        base["reason"] = "Indicator computation failed"
        return base

    prev_indicators = compute_indicators(candles[:-1]) if len(candles) > 1 else None

    # Evaluate all strategies, keep best
    best: Candidate | None = None

    c = score_ema_cross(asset, asset_class, "v5_base", candles, indicators, prev_indicators)
    if c and (not best or c.score > best.score):
        best = c

    c = score_breakout(asset, asset_class, candles, indicators)
    if c and (not best or c.score > best.score):
        best = c

    if best:
        status = "ready" if best.score >= 80 else "approaching" if best.score >= 60 else "weak" if best.score >= 20 else "no_signal"
        return {
            "asset": asset,
            "asset_class": asset_class,
            "score": best.score,
            "status": status,
            "strategy": best.strategy,
            "direction": best.direction,
            "regime": best.regime,
            "distance_to_trigger": best.distance_to_trigger,
            "reason": best.reasons[0] if best.reasons else "—",
            "reasons": best.reasons,
            "indicators": best.indicators,
            "score_breakdown": best.score_breakdown,
            "missing_conditions": best.missing_conditions,
            "explanation": best.explanation,
        }

    # No candidate passed any threshold
    base["status"] = "no_signal"
    base["reason"] = "No strategy conditions approaching"
    base["explanation"] = "No setup: regime neutral or bearish, momentum weak, no trigger proximity."
    base["indicators"] = _fmt_indicators(indicators)
    base["regime"] = "BEAR" if indicators.get("close", 0) < indicators.get("ema_200", 0) else "RANGE"
    return base


def get_all_training_assets() -> dict:
    """Scan ALL training assets and return full universe view.
    Returns every asset with its best score, including no-signal ones."""
    import time
    from bahamut.config_assets import TRADING_ASSETS, ASSET_CLASS_MAP

    start = time.time()
    results = []

    batch_size = 10
    for i in range(0, len(TRADING_ASSETS), batch_size):
        batch = TRADING_ASSETS[i:i + batch_size]
        for asset in batch:
            try:
                r = _evaluate_asset_full(asset, ASSET_CLASS_MAP.get(asset, "unknown"))
                results.append(r)
            except Exception as e:
                results.append({
                    "asset": asset,
                    "asset_class": ASSET_CLASS_MAP.get(asset, "unknown"),
                    "score": 0, "status": "error",
                    "strategy": "—", "direction": "—", "regime": "—",
                    "distance_to_trigger": "—",
                    "reason": f"Evaluation failed: {str(e)[:60]}",
                    "indicators": {},
                })

    # Sort by score desc
    results.sort(key=lambda r: r["score"], reverse=True)

    # Summary counts
    counts = {"total": len(results), "ready": 0, "approaching": 0, "weak": 0, "no_signal": 0, "no_data": 0, "error": 0}
    for r in results:
        s = r.get("status", "no_signal")
        if s in counts:
            counts[s] += 1

    duration_ms = int((time.time() - start) * 1000)
    logger.info("all_assets_scanned", total=len(results), duration_ms=duration_ms)

    return {
        "assets": results,
        "counts": counts,
        "duration_ms": duration_ms,
    }


# ═══════════════════════════════════════════
# REDIS CACHE — avoids re-scanning 40 assets on every API call
# Written by training cycle, read by API endpoints.
# ═══════════════════════════════════════════

_CACHE_CANDIDATES_KEY = "bahamut:training:cache:candidates"
_CACHE_ASSETS_KEY = "bahamut:training:cache:all_assets"
_CACHE_TTL = 7200  # 2 hours — generous TTL since training data changes slowly


def _get_cache_redis():
    try:
        import os, redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def cache_candidates(data: list[dict]):
    """Save candidates scan results to Redis (called by orchestrator)."""
    r = _get_cache_redis()
    if r:
        try:
            import json
            r.set(_CACHE_CANDIDATES_KEY, json.dumps(data), ex=_CACHE_TTL)
        except Exception:
            pass


def cache_all_assets(data: dict):
    """Save all-assets scan results to Redis (called by orchestrator)."""
    r = _get_cache_redis()
    if r:
        try:
            import json
            r.set(_CACHE_ASSETS_KEY, json.dumps(data), ex=_CACHE_TTL)
        except Exception:
            pass


def get_cached_candidates() -> list[dict] | None:
    """Read candidates from cache. Returns None if cache miss."""
    r = _get_cache_redis()
    if r:
        try:
            import json
            raw = r.get(_CACHE_CANDIDATES_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return None


def get_cached_all_assets() -> dict | None:
    """Read all-assets from cache. Returns None if cache miss."""
    r = _get_cache_redis()
    if r:
        try:
            import json
            raw = r.get(_CACHE_ASSETS_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return None
