"""
Bahamut.AI — Unified Sentiment Gate

Combines multiple sentiment sources to decide whether to allow crypto trades:

Layer 1: Fear & Greed Index (free, no key)
  - Market-wide signal: extreme fear → block ALL crypto LONGs
  - Score 0-39 → BLOCK, 40-100 → ALLOW

Layer 2: CryptoPanic (per-asset, needs key)
  - Per-asset signal: individual asset heavily bearish → block that asset
  - Falls back gracefully if key not configured

Both layers must pass for a LONG to be allowed.
"""
import structlog

logger = structlog.get_logger()


def check_sentiment(asset: str, direction: str, asset_class: str) -> tuple[bool, str]:
    """Check if a trade should be blocked by sentiment.

    Returns (should_block, reason).
    Only applies to crypto LONGs — all other trades pass through.
    """
    # Only gate crypto LONGs
    if asset_class != "crypto" or direction != "LONG":
        return False, ""

    # ── Layer 1: Fear & Greed Index (primary, free) ──
    try:
        from bahamut.sentiment.fear_greed import get_fear_greed
        fng = get_fear_greed()
        value = fng.get("value", 50)
        classification = fng.get("classification", "Neutral")

        if value <= 24:
            return True, f"Fear & Greed: {value} ({classification}) — extreme fear, all crypto LONGs blocked"
        if value <= 39:
            return True, f"Fear & Greed: {value} ({classification}) — fear market, crypto LONGs blocked"
    except Exception as e:
        logger.warning("sentiment_fng_check_failed", error=str(e)[:50])

    # ── Layer 2: CryptoPanic (secondary, per-asset) ──
    try:
        from bahamut.sentiment.cryptopanic import should_block_long, _configured
        if _configured():
            blocked, reason = should_block_long(asset)
            if blocked:
                return True, reason
    except Exception as e:
        logger.warning("sentiment_cryptopanic_check_failed", error=str(e)[:50])

    return False, ""


def get_full_sentiment() -> dict:
    """Get combined sentiment from all sources. For API/dashboard display."""
    result = {
        "fear_greed": None,
        "cryptopanic": None,
        "combined_action": "allow",
        "combined_reason": "",
    }

    # Fear & Greed
    try:
        from bahamut.sentiment.fear_greed import get_fear_greed
        result["fear_greed"] = get_fear_greed()
    except Exception:
        pass

    # CryptoPanic market mood
    try:
        from bahamut.sentiment.cryptopanic import get_market_mood, _configured
        if _configured():
            result["cryptopanic"] = get_market_mood()
    except Exception:
        pass

    # Determine combined action
    fng = result.get("fear_greed") or {}
    fng_value = fng.get("value", 50)

    if fng_value <= 24:
        result["combined_action"] = "block_all_longs"
        result["combined_reason"] = f"Extreme Fear ({fng_value})"
    elif fng_value <= 39:
        result["combined_action"] = "block_longs"
        result["combined_reason"] = f"Fear ({fng_value})"
    elif fng_value >= 75:
        result["combined_action"] = "caution_greed"
        result["combined_reason"] = f"Extreme Greed ({fng_value}) — watch for reversal"
    else:
        result["combined_action"] = "allow"
        result["combined_reason"] = f"Neutral/Greed ({fng_value})"

    return result
