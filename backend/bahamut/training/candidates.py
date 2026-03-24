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

    score = 0
    reasons = []
    direction = "LONG"

    # ── 1. Bull regime check (required gate) ──
    above_200 = close > ema_200
    dist_to_200_pct = (close - ema_200) / ema_200 * 100

    if above_200:
        score += 25
        reasons.append(f"Bull regime: price {dist_to_200_pct:.1f}% above EMA200")
    else:
        # Below EMA200 — can't trigger, but show how close
        score += max(0, int(15 + dist_to_200_pct * 2))  # closer = more points
        reasons.append(f"Bearish: price {abs(dist_to_200_pct):.1f}% below EMA200")
        # Cap score — can never trigger without bull regime
        return Candidate(
            asset=asset, asset_class=asset_class, strategy=strategy_name,
            direction=direction, score=min(score, 35), regime="BEAR",
            distance_to_trigger=f"{abs(dist_to_200_pct):.1f}% below EMA200",
            reasons=reasons,
            indicators=_fmt_indicators(indicators),
        )

    # ── 2. EMA gap (core signal proximity) ──
    ema_gap_pct = (ema_20 - ema_50) / ema_50 * 100
    ema_gap_abs = abs(ema_gap_pct)

    if ema_gap_pct > 0:
        # Already crossed — score based on how recently
        if ema_gap_abs < 0.5:
            score += 30
            reasons.append(f"EMA20 just crossed above EMA50 (+{ema_gap_pct:.2f}%)")
        elif ema_gap_abs < 1.5:
            score += 20
            reasons.append(f"EMA20 above EMA50 (+{ema_gap_pct:.2f}%)")
        else:
            score += 10
            reasons.append(f"EMAs already spread (+{ema_gap_pct:.1f}%)")
    else:
        # Below — score based on how close to crossing
        if ema_gap_abs < 0.3:
            score += 35
            reasons.append(f"EMA20 converging on EMA50 (gap: {ema_gap_pct:.2f}%)")
        elif ema_gap_abs < 1.0:
            score += 25
            reasons.append(f"EMA20 approaching EMA50 (gap: {ema_gap_pct:.2f}%)")
        elif ema_gap_abs < 2.0:
            score += 15
            reasons.append(f"EMAs narrowing (gap: {ema_gap_pct:.1f}%)")
        else:
            score += 5
            reasons.append(f"EMAs wide apart ({ema_gap_pct:.1f}%)")

    # Check convergence direction with previous bar
    if prev_indicators:
        prev_gap = (prev_indicators.get("ema_20", 0) - prev_indicators.get("ema_50", 0))
        curr_gap = ema_20 - ema_50
        if prev_gap < 0 and curr_gap > prev_gap:
            score += 10
            reasons.append("EMAs converging (gap narrowing)")

    # ── 3. RSI support ──
    if 40 <= rsi <= 60:
        score += 10
        reasons.append(f"RSI neutral at {rsi:.0f}")
    elif 30 <= rsi < 40:
        score += 15
        reasons.append(f"RSI approaching oversold ({rsi:.0f})")
    elif rsi < 30:
        score += 8
        reasons.append(f"RSI oversold ({rsi:.0f}) — reversal likely")
    elif rsi > 70:
        score -= 5
        reasons.append(f"RSI overbought ({rsi:.0f})")

    # ── 4. Volume confirmation ──
    if vol_sma > 0:
        vol_ratio = volume / vol_sma
        if vol_ratio > 1.5:
            score += 10
            reasons.append(f"Volume {vol_ratio:.1f}× above average")
        elif vol_ratio > 1.0:
            score += 5

    # ── Distance to trigger ──
    if ema_gap_pct > 0:
        distance = "Triggered (EMA20 > EMA50)"
    else:
        distance = f"EMA20 {ema_gap_abs:.2f}% below EMA50"

    regime = "TREND" if above_200 and ema_20 > ema_50 else "RANGE" if above_200 else "BEAR"

    return Candidate(
        asset=asset, asset_class=asset_class, strategy=strategy_name,
        direction=direction, score=min(100, max(0, score)),
        regime=regime, distance_to_trigger=distance,
        reasons=reasons, indicators=_fmt_indicators(indicators),
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

    score = 0
    reasons = []
    direction = "LONG"

    # ── 1. Find 20-bar reference high ──
    ref_candles = candles[-(lookback + confirm_bars + 1):-(confirm_bars + 1)]
    if len(ref_candles) < lookback - 2:
        return None

    ref_high = max(c["high"] for c in ref_candles)
    dist_to_high_pct = (close - ref_high) / ref_high * 100
    dist_in_atr = (close - ref_high) / atr if atr > 0 else 0

    # ── 2. Proximity to breakout level ──
    if close > ref_high:
        # Above the level — check confirmation bars
        confirm_candles = candles[-(confirm_bars + 1):-1]
        bars_confirmed = sum(1 for c in confirm_candles if c["close"] > ref_high * 0.995)

        if bars_confirmed >= confirm_bars and close > ref_high * 0.995:
            score += 50
            reasons.append(f"BREAKOUT CONFIRMED: held above ${ref_high:,.0f} for {bars_confirmed} bars")
        elif bars_confirmed >= 2:
            score += 40
            reasons.append(f"2/{confirm_bars} confirmation bars above ${ref_high:,.0f}")
        elif bars_confirmed >= 1:
            score += 30
            reasons.append(f"1/{confirm_bars} confirmation bars above ${ref_high:,.0f}")
        else:
            score += 20
            reasons.append(f"Just broke above 20-bar high ${ref_high:,.0f}")

        # Extension check
        if dist_in_atr > 3.0:
            score -= 15
            reasons.append(f"Too extended ({dist_in_atr:.1f} ATR above)")
    else:
        # Below breakout level — how close?
        if abs(dist_to_high_pct) < 1.0:
            score += 30
            reasons.append(f"Price {abs(dist_to_high_pct):.1f}% below 20-bar high (very close)")
        elif abs(dist_to_high_pct) < 3.0:
            score += 20
            reasons.append(f"Price {abs(dist_to_high_pct):.1f}% below 20-bar high")
        elif abs(dist_to_high_pct) < 5.0:
            score += 10
            reasons.append(f"Price {abs(dist_to_high_pct):.1f}% below 20-bar high")
        else:
            score += 3
            reasons.append(f"Price {abs(dist_to_high_pct):.1f}% below breakout level")

    # ── 3. Range expansion (volatility pickup) ──
    if len(candles) >= 10:
        recent_ranges = [c["high"] - c["low"] for c in candles[-5:]]
        prior_ranges = [c["high"] - c["low"] for c in candles[-10:-5]]
        if prior_ranges and recent_ranges:
            expansion = np.mean(recent_ranges) / (np.mean(prior_ranges) + 1e-10)
            if expansion > 1.3:
                score += 15
                reasons.append(f"Range expanding ({expansion:.1f}×)")
            elif expansion > 1.1:
                score += 8
                reasons.append(f"Range slightly expanding ({expansion:.1f}×)")

    # ── 4. Not in crash ──
    if ema_200 > 0 and close < ema_200 * 0.90:
        score = min(score, 15)
        reasons.append("Deep below EMA200 — crash risk")

    # ── 5. RSI momentum ──
    if 50 < rsi < 70:
        score += 10
        reasons.append(f"RSI bullish ({rsi:.0f})")
    elif rsi > 70:
        score += 5
        reasons.append(f"RSI overbought ({rsi:.0f})")

    distance = f"{'above' if close > ref_high else 'below'} by {abs(dist_to_high_pct):.1f}%"
    regime = "BREAKOUT" if close > ref_high else "RANGE"

    return Candidate(
        asset=asset, asset_class=asset_class, strategy="v9_breakout",
        direction=direction, score=min(100, max(0, score)),
        regime=regime, distance_to_trigger=distance,
        reasons=reasons, indicators=_fmt_indicators(indicators),
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
    from bahamut.config_assets import TRAINING_ASSETS, ASSET_CLASS_MAP
    from dataclasses import asdict

    start = time.time()
    candidates = []

    # Process in batches to be kind to data layer
    batch_size = 10
    for i in range(0, len(TRAINING_ASSETS), batch_size):
        batch = TRAINING_ASSETS[i:i + batch_size]
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
                assets=len(TRAINING_ASSETS), candidates=len(candidates),
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
