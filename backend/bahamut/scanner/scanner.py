"""
Market Scanner — Scans 57 assets, scores opportunities, surfaces top picks.

Two-phase approach:
1. Quick scan: fetch 50 candles per asset, compute basic indicators, score opportunity
2. Deep scan: run full 6-agent cycle on top 10 picks

Quick scan uses ~57 API calls (well within 55/min Grow plan limit with batching).
"""

import asyncio
import time
import json
import structlog
from datetime import datetime, timezone

from bahamut.ingestion.adapters.twelvedata import twelve_data, to_twelve_symbol, to_twelve_interval
from bahamut.features.indicators import compute_indicators
from bahamut.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── Full Asset Universe ──
ASSET_UNIVERSE = {
    "fx": [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD", "NZDUSD", "EURGBP",
        "EURJPY", "GBPJPY", "AUDJPY", "EURAUD", "EURCHF", "GBPAUD", "NZDJPY",
        "CADJPY", "CHFJPY", "AUDCAD", "AUDNZD", "GBPCAD",
    ],
    "commodities": [
        "XAUUSD", "XAGUSD", "WTIUSD", "NATGASUSD", "PLATINUMUSD",
        "COPPERUSD", "PALLADIUMUSD",
    ],
    "crypto": [
        "BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD", "ADAUSD",
        "DOGEUSD", "AVAXUSD", "DOTUSD", "LINKUSD",
        "TONUSD", "SHIBUSD", "NEARUSD", "SUIUSD", "PEPEUSD",
        "TRXUSD", "LTCUSD", "BCHUSD", "XLMUSD", "UNIUSD",
        "ICPUSD", "HBARUSD", "FILUSD", "APTUSD", "ARBUSD",
        "OPUSD", "MKRUSD", "AAVEUSD", "ATOMUSD", "ALGOUSD",
    ],
    "indices": [
        # Mega Cap
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
        # Finance
        "JPM", "V", "MA", "BAC", "GS", "MS", "AXP", "BLK", "SCHW", "C",
        # Healthcare
        "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "ISRG", "AMGN",
        # Consumer
        "HD", "PG", "KO", "PEP", "COST", "WMT", "NKE", "MCD", "SBUX", "TGT",
        # Tech / Growth
        "AMD", "CRM", "NFLX", "ADBE", "INTC", "PYPL", "UBER", "SQ", "SHOP", "PLTR",
        "AVGO", "MU", "ARM", "QCOM", "AMAT", "LRCX", "KLAC", "MRVL", "PANW", "CRWD",
        "SNOW", "DDOG", "NET", "ZS", "TEAM", "WDAY", "NOW", "FTNT",
        # Crypto-adjacent
        "COIN", "MARA", "RIOT", "MSTR", "HUT",
        # EV / Energy
        "RIVN", "LCID", "ENPH", "FSLR", "NEE",
        # Media / Entertainment
        "DIS", "CMCSA", "WBD", "RBLX", "SPOT", "TTWO",
        # Industrial / Defense
        "GE", "CAT", "BA", "LMT", "RTX", "HON",
        # Other high-volume
        "XOM", "CVX", "COP", "OXY", "SLB",
    ],
}

ALL_SYMBOLS = []
SYMBOL_CLASS = {}
for cls, symbols in ASSET_UNIVERSE.items():
    for s in symbols:
        ALL_SYMBOLS.append(s)
        SYMBOL_CLASS[s] = cls


def score_opportunity(indicators: dict) -> dict:
    """
    Quick scoring based on technical indicators.
    Returns score 0-100 and direction.
    Higher = stronger opportunity.
    """
    close = indicators.get("close", 0)
    rsi = indicators.get("rsi_14", 50)
    macd_hist = indicators.get("macd_histogram", 0)
    adx = indicators.get("adx_14", 20)
    ema_20 = indicators.get("ema_20", close)
    ema_50 = indicators.get("ema_50", close)
    ema_200 = indicators.get("ema_200", close)
    bb_upper = indicators.get("bollinger_upper", close * 1.02)
    bb_lower = indicators.get("bollinger_lower", close * 0.98)
    stoch_k = indicators.get("stoch_k", 50)

    if close == 0:
        return {"score": 0, "direction": "NEUTRAL", "reasons": []}

    score = 0
    direction_votes = {"LONG": 0, "SHORT": 0}
    reasons = []

    # 1. Trend alignment (EMA stack) — 25 points max
    if close > ema_20 > ema_50:
        score += 15
        direction_votes["LONG"] += 2
        reasons.append("Bullish EMA alignment")
        if ema_50 > ema_200:
            score += 10
            direction_votes["LONG"] += 1
            reasons.append("Above 200 EMA")
    elif close < ema_20 < ema_50:
        score += 15
        direction_votes["SHORT"] += 2
        reasons.append("Bearish EMA alignment")
        if ema_50 < ema_200:
            score += 10
            direction_votes["SHORT"] += 1
            reasons.append("Below 200 EMA")

    # 2. RSI extremes — 20 points max
    if rsi < 30:
        score += 20
        direction_votes["LONG"] += 2
        reasons.append(f"RSI oversold ({rsi:.0f})")
    elif rsi > 70:
        score += 20
        direction_votes["SHORT"] += 2
        reasons.append(f"RSI overbought ({rsi:.0f})")
    elif rsi < 40:
        score += 8
        direction_votes["LONG"] += 1
        reasons.append(f"RSI low ({rsi:.0f})")
    elif rsi > 60:
        score += 8
        direction_votes["SHORT"] += 1
        reasons.append(f"RSI high ({rsi:.0f})")

    # 3. MACD momentum — 15 points max
    if macd_hist > 0:
        score += 10
        direction_votes["LONG"] += 1
        reasons.append("MACD bullish")
        if macd_hist > abs(close * 0.001):
            score += 5
    elif macd_hist < 0:
        score += 10
        direction_votes["SHORT"] += 1
        reasons.append("MACD bearish")
        if abs(macd_hist) > abs(close * 0.001):
            score += 5

    # 4. ADX trend strength — 15 points max
    if adx > 25:
        score += 15
        reasons.append(f"Strong trend (ADX {adx:.0f})")
    elif adx > 20:
        score += 8
        reasons.append(f"Moderate trend (ADX {adx:.0f})")

    # 5. Bollinger Band breakout — 15 points max
    bb_width = (bb_upper - bb_lower) / close if close > 0 else 0
    if close > bb_upper:
        score += 15
        direction_votes["LONG"] += 1
        reasons.append("BB upper breakout")
    elif close < bb_lower:
        score += 15
        direction_votes["SHORT"] += 1
        reasons.append("BB lower breakout")
    elif bb_width < 0.02:
        score += 8
        reasons.append("BB squeeze (volatility building)")

    # 6. Stochastic confirmation — 10 points max
    if stoch_k < 20 and direction_votes["LONG"] > 0:
        score += 10
        reasons.append("Stochastic oversold confirmation")
    elif stoch_k > 80 and direction_votes["SHORT"] > 0:
        score += 10
        reasons.append("Stochastic overbought confirmation")

    # Determine direction
    if direction_votes["LONG"] > direction_votes["SHORT"]:
        direction = "LONG"
    elif direction_votes["SHORT"] > direction_votes["LONG"]:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"
        score = int(score * 0.5)  # Halve score if no clear direction

    return {
        "score": min(100, score),
        "direction": direction,
        "reasons": reasons[:4],
        "votes": direction_votes,
    }


async def scan_single_asset(symbol: str, timeframe: str = "4h") -> dict | None:
    """Scan a single asset — fetch candles, compute indicators, score it, check whales."""
    try:
        td_symbol = to_twelve_symbol(symbol)
        candles = await twelve_data.get_candles(td_symbol, timeframe, 60)
        if not candles or len(candles) < 20:
            return None

        # compute_indicators expects list[dict] with keys: close, high, low, open, volume
        indicators = compute_indicators(candles)
        if not indicators:
            return None

        opportunity = score_opportunity(indicators)
        price = indicators.get("close", 0)
        prev_close = candles[-2]["close"] if len(candles) >= 2 else price

        # Whale detection
        from bahamut.whales.tracker import detect_volume_spikes
        whale_data = detect_volume_spikes(candles)
        whale_score = whale_data.get("whale_score", 0)

        # Combined score: technical + whale bonus
        total_score = min(100, opportunity["score"] + whale_score)

        return {
            "symbol": symbol,
            "asset_class": SYMBOL_CLASS.get(symbol, "unknown"),
            "price": price,
            "change_pct": round((price - prev_close) / prev_close * 100, 2) if prev_close else 0,
            "score": total_score,
            "tech_score": opportunity["score"],
            "whale_score": whale_score,
            "whale_signal": whale_data.get("signal", "NORMAL"),
            "volume_ratio": whale_data.get("volume_ratio", 1.0),
            "direction": opportunity["direction"],
            "reasons": opportunity["reasons"],
            "rsi": round(indicators.get("rsi_14", 50), 1),
            "adx": round(indicators.get("adx_14", 20), 1),
            "macd_hist": round(indicators.get("macd_histogram", 0), 6),
            "ema_trend": "UP" if price > indicators.get("ema_50", 0) else "DOWN",
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error("scan_failed", symbol=symbol, error=str(e))
        return None


async def run_full_scan(timeframe: str = "4h") -> dict:
    """
    Scan all assets in batches (respect 55 req/min rate limit).
    Returns ranked results.
    """
    logger.info("full_scan_started", total_assets=len(ALL_SYMBOLS))
    start = time.time()
    results = []
    errors = 0

    # Batch 10 at a time with 8s pause between batches (= ~50/min, within 55 limit)
    batch_size = 10
    for i in range(0, len(ALL_SYMBOLS), batch_size):
        batch = ALL_SYMBOLS[i:i + batch_size]
        tasks = [scan_single_asset(s, timeframe) for s in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, r in enumerate(batch_results):
            if isinstance(r, Exception):
                logger.error("scan_batch_error", symbol=batch[j], error=str(r))
                errors += 1
            elif r:
                results.append(r)
            else:
                errors += 1

        # Rate limit pause (skip on last batch)
        if i + batch_size < len(ALL_SYMBOLS):
            await asyncio.sleep(8)

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    elapsed = round(time.time() - start, 1)
    logger.info("full_scan_completed",
                scanned=len(results), errors=errors,
                top_score=results[0]["score"] if results else 0,
                elapsed_sec=elapsed)

    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_scanned": len(results),
        "errors": errors,
        "elapsed_sec": elapsed,
        "timeframe": timeframe,
        "top_picks": results[:15],  # Top 15
        "all_results": results,
    }


async def get_cached_scan() -> dict | None:
    """Get the latest scan from Redis cache."""
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        cached = r.get("bahamut:market_scan")
        r.close()
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning("scan_cache_read_failed", error=str(e))
    return None


def cache_scan_results(results: dict):
    """Cache scan results in Redis (30 min TTL)."""
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        r.set("bahamut:market_scan", json.dumps(results, default=str), ex=1800)
        r.close()
    except Exception as e:
        logger.warning("scan_cache_failed", error=str(e))
