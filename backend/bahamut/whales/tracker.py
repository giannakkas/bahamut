"""
Whale Detection Module — Tracks where big money is moving.

Three detection methods:
1. Volume Spike Detection — from existing candle data (free, no extra API)
   Compares current volume to 20-period average. Spikes = institutional activity.

2. Finnhub Insider Transactions — for stocks (uses existing FINNHUB_KEY)
   Tracks CEO/CFO buys/sells. Insider buying = bullish signal.

3. Whale Alert API — for crypto (free tier: 10 req/min)
   Monitors large BTC/ETH/SOL transfers to/from exchanges.

All signals feed into the scanner scoring as a "whale_score" bonus.
"""

import httpx
import structlog
import asyncio
from datetime import datetime, timezone, timedelta
from bahamut.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


# ── 1. Volume Spike Detection (works for ALL assets, no extra API) ──

def detect_volume_spikes(candles: list[dict]) -> dict:
    """
    Detect unusual volume from candle data.
    Returns whale score (0-30) and details.
    """
    if not candles or len(candles) < 21:
        return {"whale_score": 0, "volume_ratio": 1.0, "signal": "NORMAL", "details": "Insufficient data"}

    volumes = [c.get("volume", 0) for c in candles]
    current_vol = volumes[-1]

    # Skip if no volume data
    if current_vol == 0 or all(v == 0 for v in volumes):
        return {"whale_score": 0, "volume_ratio": 0, "signal": "NO_DATA", "details": "No volume data"}

    # 20-period average volume
    avg_vol = sum(volumes[-21:-1]) / 20
    if avg_vol == 0:
        return {"whale_score": 0, "volume_ratio": 0, "signal": "NO_DATA", "details": "Zero avg volume"}

    ratio = current_vol / avg_vol

    # Also check if price moved significantly with volume (conviction)
    close_now = candles[-1]["close"]
    close_prev = candles[-2]["close"]
    price_change_pct = abs((close_now - close_prev) / close_prev * 100) if close_prev else 0

    # Score based on volume ratio
    score = 0
    signal = "NORMAL"
    details = []

    if ratio >= 5.0:
        score = 30
        signal = "EXTREME_SPIKE"
        details.append(f"Volume {ratio:.1f}x average — massive institutional activity")
    elif ratio >= 3.0:
        score = 22
        signal = "MAJOR_SPIKE"
        details.append(f"Volume {ratio:.1f}x average — significant whale activity")
    elif ratio >= 2.0:
        score = 15
        signal = "SPIKE"
        details.append(f"Volume {ratio:.1f}x average — above-normal flow")
    elif ratio >= 1.5:
        score = 8
        signal = "ELEVATED"
        details.append(f"Volume {ratio:.1f}x average — slightly elevated")

    # Bonus: high volume + big price move = strong conviction
    if ratio >= 2.0 and price_change_pct >= 1.5:
        score = min(30, score + 5)
        details.append(f"Price moved {price_change_pct:.1f}% on heavy volume (conviction)")

    # Check for volume climax (3 consecutive increasing volume bars)
    if len(volumes) >= 4:
        last3 = volumes[-3:]
        if last3[0] < last3[1] < last3[2] and last3[2] > avg_vol * 1.5:
            score = min(30, score + 5)
            details.append("3-bar volume climax pattern")

    return {
        "whale_score": score,
        "volume_ratio": round(ratio, 2),
        "current_volume": current_vol,
        "avg_volume": round(avg_vol, 0),
        "signal": signal,
        "details": "; ".join(details) if details else "Normal volume",
    }


# ── 2. Finnhub Insider Transactions (stocks only) ──

async def get_insider_transactions(symbol: str, days: int = 30) -> dict:
    """
    Fetch recent insider buying/selling from Finnhub.
    Net insider buying = bullish whale signal.
    """
    key = settings.finnhub_key
    if not key:
        return {"whale_score": 0, "signal": "NO_KEY", "transactions": []}

    try:
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://finnhub.io/api/v1/stock/insider-transactions", params={
                "symbol": symbol, "from": start, "to": end, "token": key,
            })
            resp.raise_for_status()
            data = resp.json()

        transactions = data.get("data", [])
        if not transactions:
            return {"whale_score": 0, "signal": "NO_ACTIVITY", "transactions": []}

        # Analyze: count buys vs sells, sum values
        buys = 0
        sells = 0
        buy_value = 0
        sell_value = 0
        notable = []

        for tx in transactions[:20]:  # Last 20 transactions
            change = tx.get("change", 0)
            price = tx.get("transactionPrice", 0) or 0
            value = abs(change * price) if price else 0
            name = tx.get("name", "Unknown")
            tx_type = tx.get("transactionType", "")

            if "Purchase" in tx_type or "Buy" in tx_type or (change > 0 and "Award" not in tx_type and "Gift" not in tx_type):
                buys += 1
                buy_value += value
                if value > 100_000:
                    notable.append(f"{name} bought ${value:,.0f}")
            elif "Sale" in tx_type or "Sell" in tx_type or change < 0:
                sells += 1
                sell_value += value
                if value > 500_000:
                    notable.append(f"{name} sold ${value:,.0f}")

        # Score
        score = 0
        signal = "NEUTRAL"
        net_ratio = buys / max(sells, 1)

        if buys > sells * 2 and buy_value > 100_000:
            score = 20
            signal = "INSIDER_BUYING"
        elif buys > sells and buy_value > 50_000:
            score = 12
            signal = "NET_BUYING"
        elif sells > buys * 2 and sell_value > 500_000:
            score = -15
            signal = "INSIDER_SELLING"
        elif sells > buys:
            score = -5
            signal = "NET_SELLING"

        return {
            "whale_score": score,
            "signal": signal,
            "buys": buys,
            "sells": sells,
            "buy_value": round(buy_value, 0),
            "sell_value": round(sell_value, 0),
            "net_ratio": round(net_ratio, 2),
            "notable": notable[:3],
            "total_transactions": len(transactions),
        }

    except Exception as e:
        logger.error("insider_fetch_failed", symbol=symbol, error=str(e))
        return {"whale_score": 0, "signal": "ERROR", "error": str(e)}


# ── 3. Whale Alert (crypto large transfers) ──

async def get_whale_alerts(min_value_usd: int = 1_000_000) -> list[dict]:
    """
    Fetch recent large crypto transfers.
    Free API: https://docs.whale-alert.io/ (10 req/min, no key needed for basic)
    """
    try:
        # Whale Alert free endpoint (last 1 hour, min $1M)
        since = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.whale-alert.io/v1/transactions", params={
                "min_value": min_value_usd,
                "start": since,
                "cursor": "",
            })

            if resp.status_code == 401:
                # Free tier might need a key — fall back to empty
                return []

            if resp.status_code != 200:
                return []

            data = resp.json()

        alerts = []
        for tx in data.get("transactions", [])[:20]:
            symbol = tx.get("symbol", "").upper()
            amount = tx.get("amount", 0)
            amount_usd = tx.get("amount_usd", 0)
            from_type = tx.get("from", {}).get("owner_type", "unknown")
            to_type = tx.get("to", {}).get("owner_type", "unknown")

            # Determine if bullish or bearish for the asset
            direction = "NEUTRAL"
            if to_type == "exchange" and from_type == "unknown":
                direction = "BEARISH"  # Moving to exchange = preparing to sell
            elif from_type == "exchange" and to_type == "unknown":
                direction = "BULLISH"  # Moving off exchange = accumulating
            elif to_type == "exchange":
                direction = "BEARISH"

            alerts.append({
                "symbol": f"{symbol}USD",
                "amount": amount,
                "amount_usd": round(amount_usd, 0),
                "from_type": from_type,
                "to_type": to_type,
                "direction": direction,
                "timestamp": tx.get("timestamp"),
                "hash": tx.get("hash", "")[:16],
            })

        return alerts

    except Exception as e:
        logger.error("whale_alert_failed", error=str(e))
        return []


def score_whale_alerts_for_asset(alerts: list[dict], symbol: str) -> dict:
    """Score whale alerts for a specific crypto asset."""
    relevant = [a for a in alerts if a["symbol"] == symbol]
    if not relevant:
        return {"whale_score": 0, "signal": "NO_WHALE_ACTIVITY", "transfers": 0}

    bullish_value = sum(a["amount_usd"] for a in relevant if a["direction"] == "BULLISH")
    bearish_value = sum(a["amount_usd"] for a in relevant if a["direction"] == "BEARISH")
    total_value = bullish_value + bearish_value

    score = 0
    signal = "NEUTRAL"

    if bullish_value > bearish_value * 2 and total_value > 5_000_000:
        score = 25
        signal = "WHALE_ACCUMULATING"
    elif bullish_value > bearish_value and total_value > 2_000_000:
        score = 15
        signal = "NET_INFLOW"
    elif bearish_value > bullish_value * 2 and total_value > 5_000_000:
        score = -20
        signal = "WHALE_DUMPING"
    elif bearish_value > bullish_value and total_value > 2_000_000:
        score = -10
        signal = "NET_OUTFLOW"
    elif total_value > 1_000_000:
        score = 5
        signal = "WHALE_ACTIVE"

    return {
        "whale_score": score,
        "signal": signal,
        "transfers": len(relevant),
        "bullish_value": round(bullish_value, 0),
        "bearish_value": round(bearish_value, 0),
        "total_value": round(total_value, 0),
    }


# ── Combined Whale Score ──

async def get_whale_score(symbol: str, asset_class: str, candles: list[dict] = None) -> dict:
    """
    Combined whale detection for any asset.
    Returns total whale_score (can be negative for bearish whale signals).
    """
    result = {
        "total_whale_score": 0,
        "volume": None,
        "insider": None,
        "whale_alert": None,
    }

    # 1. Volume spikes (works for everything)
    if candles:
        vol_data = detect_volume_spikes(candles)
        result["volume"] = vol_data
        result["total_whale_score"] += vol_data["whale_score"]

    # 2. Insider transactions (stocks only)
    if asset_class == "indices":
        insider_data = await get_insider_transactions(symbol)
        result["insider"] = insider_data
        result["total_whale_score"] += insider_data["whale_score"]

    # 3. Whale alerts (crypto only — skip for now if no API key,
    #    but volume spikes already cover large crypto moves)
    if asset_class == "crypto":
        try:
            alerts = await get_whale_alerts()
            whale_data = score_whale_alerts_for_asset(alerts, symbol)
            result["whale_alert"] = whale_data
            result["total_whale_score"] += whale_data["whale_score"]
        except Exception:
            pass

    # Clamp total score
    result["total_whale_score"] = max(-30, min(30, result["total_whale_score"]))

    return result
