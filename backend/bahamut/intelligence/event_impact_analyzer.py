"""
Bahamut.AI — Event Impact Analyzer

Per-asset directional impact analysis for economic events.
Each event gets individual impact arrows for 8 tracked assets:
  BTCUSD, ETHUSD, SPX, NQ, DXY, XAUUSD, EURUSD, USDJPY

Deterministic first, AI-enriched second.
Works fully without any AI dependency.
"""
import hashlib
import json
import os
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

TRACKED_ASSETS = ["BTCUSD", "ETHUSD", "SPX", "NQ", "DXY", "XAUUSD", "EURUSD", "USDJPY"]

# ═══════════════════════════════════════════════════════════════
# EVENT CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

EVENT_CATEGORIES = {
    "inflation": ["cpi", "ppi", "pce", "inflation", "core inflation", "price index"],
    "rates": ["rate decision", "interest rate", "fomc", "fed", "ecb", "boe", "boj", "rate cut", "rate hike"],
    "labor": ["non-farm", "nfp", "payroll", "unemployment", "jobless", "employment", "adp"],
    "growth": ["gdp", "growth rate", "retail sales", "industrial production", "pmi", "ism"],
    "central_bank": ["fed speak", "powell", "lagarde", "minutes", "monetary policy", "qe", "qt"],
    "earnings": ["earnings", "revenue", "eps"],
    "geopolitics": ["tariff", "sanction", "war", "opec", "embargo", "trade war"],
    "housing": ["housing starts", "building permits", "home sales", "mortgage"],
    "consumer": ["consumer confidence", "consumer sentiment", "michigan"],
}


def classify_event(name: str) -> str:
    n = name.lower()
    for cat, keywords in EVENT_CATEGORIES.items():
        if any(k in n for k in keywords):
            return cat
    return "other"


# ═══════════════════════════════════════════════════════════════
# SURPRISE DIRECTION
# ═══════════════════════════════════════════════════════════════

def compute_surprise(event: dict) -> dict:
    """Compute surprise direction from actual vs estimate."""
    actual = event.get("actual")
    estimate = event.get("estimate")
    prev = event.get("prev")
    name = (event.get("event") or "").lower()

    if actual is None or estimate is None:
        return {"direction": "unknown", "magnitude": 0, "raw": 0}

    try:
        a, e = float(actual), float(estimate)
    except (ValueError, TypeError):
        return {"direction": "unknown", "magnitude": 0, "raw": 0}

    raw = a - e
    mag = abs(raw) / max(abs(e), 0.001)

    # Inflation events: higher = hotter
    if any(k in name for k in ["cpi", "ppi", "pce", "inflation", "price index"]):
        if raw > 0:
            return {"direction": "hotter_than_expected", "magnitude": round(mag, 3), "raw": round(raw, 4)}
        elif raw < 0:
            return {"direction": "cooler_than_expected", "magnitude": round(mag, 3), "raw": round(raw, 4)}

    # Rate decisions
    if any(k in name for k in ["rate decision", "interest rate", "fomc"]):
        if raw > 0:
            return {"direction": "hawkish", "magnitude": round(mag, 3), "raw": round(raw, 4)}
        elif raw < 0:
            return {"direction": "dovish", "magnitude": round(mag, 3), "raw": round(raw, 4)}

    # General: higher = better
    if raw > 0.001:
        return {"direction": "better_than_expected", "magnitude": round(mag, 3), "raw": round(raw, 4)}
    elif raw < -0.001:
        return {"direction": "worse_than_expected", "magnitude": round(mag, 3), "raw": round(raw, 4)}

    return {"direction": "in_line", "magnitude": 0, "raw": 0}


# ═══════════════════════════════════════════════════════════════
# PER-ASSET IMPACT RULES (deterministic)
# ═══════════════════════════════════════════════════════════════

# Impact matrix: event_category → surprise_direction → {asset: (arrow, label, confidence, strength)}
# Arrows: "up", "down", "neutral"
# Labels: "bullish", "bearish", "mixed"

def _default_impact():
    return {"arrow": "neutral", "label": "mixed", "confidence": 0.2, "strength": "low", "reason": "No clear directional signal"}


def analyze_per_asset(category: str, surprise: dict) -> dict:
    """Return impact dict for each tracked asset based on event category + surprise."""
    sd = surprise.get("direction", "unknown")
    mag = surprise.get("magnitude", 0)
    conf_base = min(0.9, 0.4 + mag * 0.5) if sd not in ("unknown", "in_line") else 0.25
    strength = "high" if mag > 0.5 else "medium" if mag > 0.2 else "low"

    impacts = {}

    if category == "inflation":
        if sd == "hotter_than_expected":
            impacts = {
                "BTCUSD": ("down", "bearish", "Higher rates hurt risk assets"),
                "ETHUSD": ("down", "bearish", "Risk-off on hot inflation"),
                "SPX": ("down", "bearish", "Rate hike fear pressures equities"),
                "NQ": ("down", "bearish", "Growth stocks most sensitive to rates"),
                "DXY": ("up", "bullish", "Higher rates strengthen dollar"),
                "XAUUSD": ("down", "bearish", "Real yields rise, gold falls"),
                "EURUSD": ("down", "bearish", "Dollar strength on hawkish Fed"),
                "USDJPY": ("up", "bullish", "Rate differential widens"),
            }
        elif sd == "cooler_than_expected":
            impacts = {
                "BTCUSD": ("up", "bullish", "Rate cut hopes boost crypto"),
                "ETHUSD": ("up", "bullish", "Risk-on on cooling inflation"),
                "SPX": ("up", "bullish", "Lower rates support equities"),
                "NQ": ("up", "bullish", "Growth stocks rally on rate optimism"),
                "DXY": ("down", "bearish", "Dollar weakens on dovish shift"),
                "XAUUSD": ("up", "bullish", "Lower real yields boost gold"),
                "EURUSD": ("up", "bullish", "Dollar weakness lifts EUR"),
                "USDJPY": ("down", "bearish", "Rate differential narrows"),
            }

    elif category == "rates":
        if sd in ("hawkish",):
            impacts = {
                "BTCUSD": ("down", "bearish", "Tighter policy hurts crypto"),
                "ETHUSD": ("down", "bearish", "Risk-off on hawkish stance"),
                "SPX": ("down", "bearish", "Higher rates compress valuations"),
                "NQ": ("down", "bearish", "Tech hammered by rate hikes"),
                "DXY": ("up", "bullish", "Dollar rallies on hawkish Fed"),
                "XAUUSD": ("down", "bearish", "Real yields rise"),
                "EURUSD": ("down", "bearish", "Dollar strength"),
                "USDJPY": ("up", "bullish", "Wide rate differential"),
            }
        elif sd in ("dovish",):
            impacts = {
                "BTCUSD": ("up", "bullish", "Easy money flows to crypto"),
                "ETHUSD": ("up", "bullish", "Risk-on rally on dovish pivot"),
                "SPX": ("up", "bullish", "Lower rates boost equities"),
                "NQ": ("up", "bullish", "Growth stocks surge on rate cuts"),
                "DXY": ("down", "bearish", "Dollar falls on dovish shift"),
                "XAUUSD": ("up", "bullish", "Gold rallies on lower rates"),
                "EURUSD": ("up", "bullish", "EUR gains on weaker dollar"),
                "USDJPY": ("down", "bearish", "Rate gap narrows"),
            }

    elif category == "labor":
        if sd == "better_than_expected":
            impacts = {
                "BTCUSD": ("neutral", "mixed", "Strong jobs: good economy but no rate cuts"),
                "ETHUSD": ("neutral", "mixed", "Mixed signal for crypto"),
                "SPX": ("up", "bullish", "Strong economy supports earnings"),
                "NQ": ("neutral", "mixed", "Good jobs may delay cuts"),
                "DXY": ("up", "bullish", "Strong economy supports dollar"),
                "XAUUSD": ("down", "bearish", "Less safe-haven demand"),
                "EURUSD": ("down", "bearish", "Dollar strength on strong data"),
                "USDJPY": ("up", "bullish", "USD bid on strong labor"),
            }
        elif sd == "worse_than_expected":
            impacts = {
                "BTCUSD": ("neutral", "mixed", "Weak jobs could mean rate cuts"),
                "ETHUSD": ("neutral", "mixed", "Recession fear vs rate cut hope"),
                "SPX": ("down", "bearish", "Weak labor signals recession"),
                "NQ": ("neutral", "mixed", "Bad news could be good news for rates"),
                "DXY": ("down", "bearish", "Dollar weakens on soft data"),
                "XAUUSD": ("up", "bullish", "Safe haven demand rises"),
                "EURUSD": ("up", "bullish", "Dollar weakness lifts EUR"),
                "USDJPY": ("down", "bearish", "USD sold on weak data"),
            }

    elif category == "growth":
        if sd == "better_than_expected":
            impacts = {
                "BTCUSD": ("up", "bullish", "Risk-on: strong growth"),
                "ETHUSD": ("up", "bullish", "Risk appetite increases"),
                "SPX": ("up", "bullish", "GDP beat supports equities"),
                "NQ": ("up", "bullish", "Growth supports tech"),
                "DXY": ("up", "bullish", "Strong economy = strong dollar"),
                "XAUUSD": ("down", "bearish", "Less safe-haven demand"),
                "EURUSD": ("down", "bearish", "US outperformance = USD bid"),
                "USDJPY": ("up", "bullish", "USD bid on growth"),
            }
        elif sd == "worse_than_expected":
            impacts = {
                "BTCUSD": ("down", "bearish", "Risk-off on weak growth"),
                "ETHUSD": ("down", "bearish", "Recession fears hit crypto"),
                "SPX": ("down", "bearish", "GDP miss hurts equities"),
                "NQ": ("down", "bearish", "Weak growth hits tech"),
                "DXY": ("down", "bearish", "Weak economy = weak dollar"),
                "XAUUSD": ("up", "bullish", "Safe haven demand"),
                "EURUSD": ("up", "bullish", "Dollar weakness"),
                "USDJPY": ("down", "bearish", "USD sold"),
            }

    elif category == "geopolitics":
        # Geopolitics is generally risk-off
        impacts = {
            "BTCUSD": ("down", "bearish", "Risk-off on geopolitical tension"),
            "ETHUSD": ("down", "bearish", "Risk-off"),
            "SPX": ("down", "bearish", "Uncertainty hurts equities"),
            "NQ": ("down", "bearish", "Tech sells on uncertainty"),
            "DXY": ("up", "bullish", "Flight to safety = USD bid"),
            "XAUUSD": ("up", "bullish", "Classic safe haven"),
            "EURUSD": ("down", "bearish", "EUR weak on European exposure"),
            "USDJPY": ("down", "bearish", "JPY bid as safe haven"),
        }
        conf_base = 0.5
        strength = "medium"

    elif category == "earnings":
        if sd == "better_than_expected":
            impacts = {
                "BTCUSD": ("neutral", "mixed", "Stock earnings neutral for crypto"),
                "ETHUSD": ("neutral", "mixed", "No direct crypto impact"),
                "SPX": ("up", "bullish", "Earnings beat supports index"),
                "NQ": ("up", "bullish", "Tech earnings beat is bullish"),
                "DXY": ("neutral", "mixed", "Earnings don't directly move USD"),
                "XAUUSD": ("neutral", "mixed", "No direct gold impact"),
                "EURUSD": ("neutral", "mixed", "Minimal FX impact"),
                "USDJPY": ("neutral", "mixed", "Minimal FX impact"),
            }
        elif sd == "worse_than_expected":
            impacts = {
                "BTCUSD": ("neutral", "mixed", "Earnings miss neutral for crypto"),
                "ETHUSD": ("neutral", "mixed", "No direct impact"),
                "SPX": ("down", "bearish", "Earnings miss hurts index"),
                "NQ": ("down", "bearish", "Tech earnings miss is bearish"),
                "DXY": ("neutral", "mixed", "Minimal USD impact"),
                "XAUUSD": ("neutral", "mixed", "No direct impact"),
                "EURUSD": ("neutral", "mixed", "Minimal FX impact"),
                "USDJPY": ("neutral", "mixed", "Minimal FX impact"),
            }

    # Build result with defaults for any missing assets
    result = {}
    for asset in TRACKED_ASSETS:
        if asset in impacts:
            arrow, label, reason = impacts[asset]
            result[asset] = {
                "arrow": arrow,
                "label": label,
                "confidence": round(conf_base, 2),
                "strength": strength,
                "reason": reason,
            }
        else:
            result[asset] = _default_impact()

    return result


# ═══════════════════════════════════════════════════════════════
# EVENT ENRICHMENT — main entry point
# ═══════════════════════════════════════════════════════════════

def generate_event_id(event: dict) -> str:
    """Stable event ID from event fields."""
    raw = f"{event.get('date','')}{event.get('time','')}{event.get('event','')}{event.get('country','')}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def enrich_event(event: dict) -> dict:
    """Add AI impact analysis to a single calendar event.
    Returns the original event dict with added fields:
      id, category, ai_asset_impacts, ai_summary, freeze_recommended, freeze_reason, surprise_direction
    """
    name = event.get("event", "")
    impact_level = (event.get("impact") or "low").lower()

    # Classification
    category = classify_event(name)
    surprise = compute_surprise(event)

    # Per-asset impacts
    asset_impacts = analyze_per_asset(category, surprise)

    # Summary
    sd = surprise["direction"]
    if sd == "unknown":
        summary = f"{name}: Pending data release. Impact uncertain until actual numbers published."
    elif sd == "in_line":
        summary = f"{name}: In line with expectations. Minimal market impact expected."
    else:
        direction_label = sd.replace("_", " ")
        dominant_arrows = [v["arrow"] for v in asset_impacts.values() if v["arrow"] != "neutral"]
        if dominant_arrows:
            dominant = max(set(dominant_arrows), key=dominant_arrows.count)
            summary = f"{name}: {direction_label.title()}. Markets lean {'risk-on' if dominant == 'up' else 'risk-off'}."
        else:
            summary = f"{name}: {direction_label.title()}. Mixed cross-asset impact."

    # Freeze recommendation
    freeze = False
    freeze_reason = ""
    if impact_level == "high":
        if sd in ("hotter_than_expected", "hawkish") and surprise["magnitude"] > 0.3:
            freeze = True
            freeze_reason = f"High-impact {sd.replace('_', ' ')} — elevated volatility expected"
        elif sd in ("cooler_than_expected", "dovish") and surprise["magnitude"] > 0.3:
            freeze = True
            freeze_reason = f"High-impact {sd.replace('_', ' ')} — sharp directional move likely"
        elif sd == "unknown":
            freeze = True
            freeze_reason = f"High-impact event pending release — pre-event freeze"

    return {
        **event,
        "id": generate_event_id(event),
        "category": category,
        "ai_asset_impacts": asset_impacts,
        "ai_summary": summary,
        "freeze_recommended": freeze,
        "freeze_reason": freeze_reason,
        "surprise_direction": sd,
        "surprise_magnitude": surprise.get("magnitude", 0),
    }


def enrich_calendar(events: list[dict]) -> list[dict]:
    """Enrich a full calendar of events."""
    return [enrich_event(ev) for ev in events]


# ═══════════════════════════════════════════════════════════════
# CACHING
# ═══════════════════════════════════════════════════════════════

def get_enriched_calendar_cached(events: list[dict], cache_minutes: int = 10) -> list[dict]:
    """Return enriched calendar, using Redis cache if available."""
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        # Cache key based on event count + first/last event identity
        key_parts = f"{len(events)}"
        if events:
            key_parts += f":{generate_event_id(events[0])}:{generate_event_id(events[-1])}"
            # Include actual values (they change when data is released)
            actuals = "|".join(str(e.get("actual", "")) for e in events[:10])
            key_parts += f":{hashlib.md5(actuals.encode()).hexdigest()[:8]}"

        cache_key = f"bahamut:enriched_calendar:{key_parts}"
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)

        # Enrich and cache
        enriched = enrich_calendar(events)
        r.setex(cache_key, cache_minutes * 60, json.dumps(enriched))
        return enriched
    except Exception:
        # Redis unavailable — enrich without caching
        return enrich_calendar(events)
