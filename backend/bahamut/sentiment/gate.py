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
    Crypto LONGs: Fear & Greed Index + CryptoPanic
    Stock LONGs: CNN Fear & Greed Index
    """
    if direction != "LONG":
        return False, ""

    # ── Crypto LONGs ──
    if asset_class == "crypto":
        # Layer 1: Fear & Greed Index (primary, free)
        try:
            from bahamut.sentiment.fear_greed import get_fear_greed
            fng = get_fear_greed()
            value = fng.get("value", 50)
            classification = fng.get("classification", "Neutral")

            if value <= 24:
                return True, f"Crypto Fear & Greed: {value} ({classification}) — extreme fear, all crypto LONGs blocked"
            if value <= 39:
                return True, f"Crypto Fear & Greed: {value} ({classification}) — fear market, crypto LONGs blocked"
        except Exception as e:
            logger.warning("sentiment_fng_check_failed", error=str(e)[:50])

        # Layer 2: CryptoPanic (secondary, per-asset)
        try:
            from bahamut.sentiment.cryptopanic import should_block_long, _configured
            if _configured():
                blocked, reason = should_block_long(asset)
                if blocked:
                    return True, reason
        except Exception as e:
            logger.warning("sentiment_cryptopanic_check_failed", error=str(e)[:50])

    # ── Stock LONGs ──
    elif asset_class == "stock":
        try:
            from bahamut.sentiment.cnn_fear_greed import get_stock_fear_greed
            cnn = get_stock_fear_greed()
            value = cnn.get("value", 50)
            classification = cnn.get("classification", "Neutral")

            if value <= 24:
                return True, f"CNN Fear & Greed: {value} ({classification}) — extreme fear, stock LONGs blocked"
        except Exception as e:
            logger.warning("sentiment_cnn_check_failed", error=str(e)[:50])

    return False, ""


def get_full_sentiment() -> dict:
    """Get combined sentiment from all sources. For API/dashboard display."""
    result = {
        "fear_greed": None,
        "cnn_fear_greed": None,
        "cryptopanic": None,
        "combined_crypto_action": "allow",
        "combined_stock_action": "allow",
        "combined_reason": "",
    }

    # Crypto Fear & Greed
    try:
        from bahamut.sentiment.fear_greed import get_fear_greed
        result["fear_greed"] = get_fear_greed()
    except Exception:
        pass

    # CNN Fear & Greed (stocks)
    try:
        from bahamut.sentiment.cnn_fear_greed import get_stock_fear_greed
        result["cnn_fear_greed"] = get_stock_fear_greed()
    except Exception:
        pass

    # CryptoPanic market mood
    try:
        from bahamut.sentiment.cryptopanic import get_market_mood, _configured
        if _configured():
            result["cryptopanic"] = get_market_mood()
    except Exception:
        pass

    # Determine crypto action
    fng = result.get("fear_greed") or {}
    fng_value = fng.get("value", 50)
    if fng_value <= 24:
        result["combined_crypto_action"] = "block_all_longs"
        result["combined_reason"] = f"Crypto Extreme Fear ({fng_value})"
    elif fng_value <= 39:
        result["combined_crypto_action"] = "block_longs"
        result["combined_reason"] = f"Crypto Fear ({fng_value})"
    else:
        result["combined_crypto_action"] = "allow"

    # Determine stock action
    cnn = result.get("cnn_fear_greed") or {}
    cnn_value = cnn.get("value", 50)
    if cnn_value <= 24:
        result["combined_stock_action"] = "block_all_longs"
        result["combined_reason"] += f" | Stock Extreme Fear ({cnn_value})"
    else:
        result["combined_stock_action"] = "allow"

    return result
