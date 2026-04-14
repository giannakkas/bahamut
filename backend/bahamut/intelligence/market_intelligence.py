"""
Market Intelligence Engine — Unified aggregation layer for all market context.

Combines: adaptive news, fear/greed, CNN F&G, economic calendar, sentiment,
and asset-class mappings into a single intelligence snapshot.

This is the SOURCE OF TRUTH for AI-driven market context. Consumed by:
- Selector (priority adjustments, gating)
- Execution (sizing)
- Diagnostics (verification)
- Admin UI (AI Market Intelligence page)
"""
import time
import structlog
from dataclasses import dataclass, asdict, field

logger = structlog.get_logger()

# ═══════════════════════════════════════════
# CACHE — snapshot rebuilt at most once per 60s
# ═══════════════════════════════════════════
_cache: dict = {}
_cache_ts: float = 0
CACHE_TTL = 60  # seconds


def _classify_fear_greed(value: int) -> str:
    if value <= 20: return "Extreme Fear"
    if value <= 40: return "Fear"
    if value <= 60: return "Neutral"
    if value <= 80: return "Greed"
    return "Extreme Greed"


def _mode_from_sentiment(fg_value: int, is_crypto: bool = False) -> str:
    if is_crypto:
        if fg_value <= 20: return "RESTRICTED"
        if fg_value <= 35: return "CAUTION"
        return "NORMAL"
    else:
        if fg_value <= 15: return "CAUTION"
        return "NORMAL"


def _posture(crypto_mode: str, stock_mode: str, macro_mode: str) -> str:
    modes = [crypto_mode, stock_mode, macro_mode]
    if "FROZEN" in modes: return "FROZEN"
    if "RESTRICTED" in modes: return "DEFENSIVE"
    if "CAUTION" in modes: return "SELECTIVE"
    return "AGGRESSIVE"


def _bias_label(bias: str, confidence: float) -> str:
    if confidence < 0.2: return "NEUTRAL"
    return bias


# ═══════════════════════════════════════════
# MAIN BUILDER
# ═══════════════════════════════════════════

def build_market_intelligence_snapshot() -> dict:
    """Build the unified market intelligence snapshot from all sources."""
    global _cache, _cache_ts
    now = time.time()
    if _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache

    snapshot = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "summary": {},
        "class_context": {},
        "asset_context": {},
        "headline_context": [],
        "event_context": [],
        "pipeline_directives": {},
        "source_of_truth": "market_intelligence_engine",
    }

    # ── 1. Sentiment Sources ──
    fg_crypto = {"value": 50, "classification": "Neutral"}
    fg_stocks = {"value": 50, "classification": "Neutral"}
    try:
        from bahamut.sentiment.gate import get_full_sentiment
        full_sent = get_full_sentiment()
        if full_sent.get("fear_greed") and "value" in full_sent["fear_greed"]:
            fg_crypto = {"value": int(full_sent["fear_greed"]["value"]), "classification": full_sent["fear_greed"].get("classification", "")}
        if full_sent.get("cnn_fear_greed") and "value" in full_sent["cnn_fear_greed"]:
            fg_stocks = {"value": int(full_sent["cnn_fear_greed"]["value"]), "classification": full_sent["cnn_fear_greed"].get("classification", "")}
    except Exception:
        pass

    # ── 2. Adaptive News States ──
    news_states = {}
    news_summary = {"NORMAL": 0, "CAUTION": 0, "RESTRICTED": 0, "FROZEN": 0}
    try:
        from bahamut.intelligence.adaptive_news_risk import (
            ADAPTIVE_NEWS_ENABLED, get_all_news_states,
        )
        if ADAPTIVE_NEWS_ENABLED:
            all_states = get_all_news_states()
            for asset, state in all_states.items():
                mode = state.mode if hasattr(state, "mode") else "NORMAL"
                news_states[asset] = {
                    "mode": mode,
                    "bias": state.bias if hasattr(state, "bias") else "NEUTRAL",
                    "confidence": round(state.confidence, 3) if hasattr(state, "confidence") else 0,
                    "shock": state.shock if hasattr(state, "shock") else "NONE",
                    "size_multiplier": round(state.size_multiplier, 2) if hasattr(state, "size_multiplier") else 1.0,
                    "threshold_penalty": state.threshold_penalty if hasattr(state, "threshold_penalty") else 0,
                }
                news_summary[mode] = news_summary.get(mode, 0) + 1
    except Exception:
        pass

    # ── 3. Headlines ──
    headlines = []
    try:
        from bahamut.intelligence.news_impact import get_recent_headlines
        raw_headlines = get_recent_headlines(limit=20)
        for h in (raw_headlines or []):
            age_s = now - h.get("timestamp", now) if isinstance(h.get("timestamp"), (int, float)) else 0
            freshness = "fresh" if age_s < 1800 else "active" if age_s < 7200 else "stale"
            headlines.append({
                "title": h.get("title", "")[:120],
                "source": h.get("source", "unknown"),
                "timestamp": h.get("published", ""),
                "freshness": freshness,
                "impact_score": round(h.get("impact", 0), 3),
                "bias": h.get("bias", "NEUTRAL"),
                "scope": h.get("scope", "all"),
                "affected_classes": h.get("affected_classes", []),
            })
    except Exception:
        pass

    # ── 4. Economic Calendar (from Redis cache, with direct fetch fallback) ──
    events = []
    _rc_cal = None
    try:
        import os, redis as _redis_cal, json as _jcal
        _rc_cal = _redis_cal.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        _cached = _rc_cal.get("bahamut:calendar:events_v6")
        if _cached:
            raw_events = _jcal.loads(_cached)
        else:
            raw_events = None
    except Exception:
        raw_events = None

    # If no cache, fetch fresh from ForexFactory
    if not raw_events:
        try:
            import httpx, json as _jcal2
            with httpx.Client(timeout=15, headers={
                "User-Agent": "Mozilla/5.0 Chrome/120.0.0.0",
                "Accept": "application/json",
            }, follow_redirects=True) as client:
                resp = client.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
                if resp.status_code == 200:
                    raw_events = []
                    for ev in resp.json()[:40]:
                        imp = ev.get("impact", "Low")
                        if imp == "Holiday":
                            continue
                        raw_events.append({
                            "event": ev.get("title", "Unknown"),
                            "country": ev.get("country", ""),
                            "impact": "high" if imp == "High" else "medium" if imp == "Medium" else "low",
                            "actual": ev.get("actual") or None,
                            "estimate": ev.get("forecast") or None,
                            "prev": ev.get("previous") or None,
                            "date": ev.get("date", ""),
                            "source": "forexfactory",
                        })
                    # Cache for 2 hours
                    if _rc_cal and raw_events:
                        try:
                            _rc_cal.setex("bahamut:calendar:events_v6", 7200, _jcal2.dumps(raw_events))
                        except Exception:
                            pass
        except Exception:
            raw_events = []

    for ev in (raw_events or [])[:30]:
        impact_raw = (ev.get("impact", "low") or "low").upper()
        if impact_raw in ("HIGH", "H"): impact = "HIGH"
        elif impact_raw in ("MEDIUM", "MED", "M"): impact = "MEDIUM"
        else: impact = "LOW"
        event_name = ev.get("event", "Unknown")
        country = ev.get("country", "")
        affected = ["all"]
        if any(k in event_name.lower() for k in ["interest rate", "fed", "fomc", "cpi", "gdp", "employment", "nonfarm"]):
            affected = ["stock", "forex", "index", "crypto"]
        elif any(k in event_name.lower() for k in ["earnings", "revenue"]):
            affected = ["stock"]
        elif "oil" in event_name.lower() or "crude" in event_name.lower():
            affected = ["commodity"]
        if impact == "HIGH":
            trade_policy = "reduce_size"
            size_reduction = 25
        elif impact == "MEDIUM":
            trade_policy = "caution"
            size_reduction = 10
        else:
            trade_policy = "normal"
            size_reduction = 0
        events.append({
            "event": event_name,
            "country": country,
            "date": ev.get("date", ""),
            "impact": impact,
            "actual": ev.get("actual"),
            "forecast": ev.get("estimate") or ev.get("forecast"),
            "previous": ev.get("prev") or ev.get("previous"),
            "source": ev.get("source", "unknown"),
            "affected_classes": affected,
            "risk_level": impact,
            "trade_policy": trade_policy,
            "size_reduction_pct": size_reduction,
        })

    # ── 5. Asset Class Context ──
    crypto_mode = _mode_from_sentiment(fg_crypto["value"], is_crypto=True)
    stock_mode = _mode_from_sentiment(fg_stocks["value"], is_crypto=False)
    macro_mode = "CAUTION" if fg_crypto["value"] <= 25 and fg_stocks["value"] <= 35 else "NORMAL"

    crypto_directions = ["SHORT"] if fg_crypto["value"] <= 25 else ["LONG", "SHORT"]
    stock_directions = ["LONG", "SHORT"]

    class_context = {
        "crypto": {
            "sentiment_value": fg_crypto["value"],
            "sentiment_label": fg_crypto["classification"],
            "mode": crypto_mode,
            "bias": "SHORT" if fg_crypto["value"] <= 25 else "NEUTRAL",
            "confidence": min(1.0, (100 - fg_crypto["value"]) / 100) if fg_crypto["value"] <= 50 else 0.5,
            "preferred_directions": crypto_directions,
            "size_multiplier": 0.5 if crypto_mode == "RESTRICTED" else 0.75 if crypto_mode == "CAUTION" else 1.0,
            "threshold_penalty": 6 if crypto_mode == "RESTRICTED" else 3 if crypto_mode == "CAUTION" else 0,
            "trade_policy": "shorts_only" if fg_crypto["value"] <= 25 else "selective" if fg_crypto["value"] <= 40 else "normal",
            "news_mode_counts": {k: v for k, v in news_summary.items() if v > 0} if news_summary else {},
        },
        "stock": {
            "sentiment_value": fg_stocks["value"],
            "sentiment_label": fg_stocks["classification"],
            "mode": stock_mode,
            "bias": "NEUTRAL",
            "confidence": 0.5,
            "preferred_directions": stock_directions,
            "size_multiplier": 1.0,
            "threshold_penalty": 0,
            "trade_policy": "normal",
        },
        "forex": {"mode": "NORMAL", "bias": "NEUTRAL", "confidence": 0.3, "trade_policy": "normal"},
        "commodity": {"mode": "NORMAL", "bias": "NEUTRAL", "confidence": 0.3, "trade_policy": "normal"},
        "index": {"mode": "NORMAL", "bias": "NEUTRAL", "confidence": 0.3, "trade_policy": "normal"},
    }

    # ── 6. Per-Asset Context (merge news + class context) ──
    asset_context = {}
    try:
        from bahamut.config_assets import ASSET_CLASS_MAP
        for asset, ac in ASSET_CLASS_MAP.items():
            cc = class_context.get(ac, class_context.get("crypto", {}))
            ns = news_states.get(asset, {"mode": "NORMAL", "bias": "NEUTRAL", "confidence": 0, "size_multiplier": 1.0, "threshold_penalty": 0})

            # Combined mode = worst of class + news
            mode_rank = {"NORMAL": 0, "CAUTION": 1, "RESTRICTED": 2, "FROZEN": 3}
            combined_mode = ns["mode"] if mode_rank.get(ns["mode"], 0) >= mode_rank.get(cc.get("mode", "NORMAL"), 0) else cc.get("mode", "NORMAL")

            # Combined size = min of class + news
            combined_size = min(cc.get("size_multiplier", 1.0), ns.get("size_multiplier", 1.0))
            # Combined penalty = max of class + news
            combined_penalty = max(cc.get("threshold_penalty", 0), ns.get("threshold_penalty", 0))
            # Allowed directions = intersection
            class_dirs = set(cc.get("preferred_directions", ["LONG", "SHORT"]))
            news_dirs = set(ns.get("aligned_directions", ["LONG", "SHORT"]) if "aligned_directions" in ns else ["LONG", "SHORT"])
            allowed = list(class_dirs & news_dirs) or list(class_dirs)

            asset_context[asset] = {
                "asset_class": ac,
                "news_mode": ns["mode"],
                "sentiment_mode": cc.get("mode", "NORMAL"),
                "combined_mode": combined_mode,
                "ai_bias": ns.get("bias", "NEUTRAL"),
                "ai_confidence": ns.get("confidence", 0),
                "size_multiplier": round(combined_size, 2),
                "threshold_penalty": combined_penalty,
                "allowed_directions": allowed,
            }
    except Exception:
        pass

    # ── 7. Pipeline Directives ──
    posture = _posture(crypto_mode, stock_mode, macro_mode)
    pipeline_directives = {
        "posture": posture,
        "crypto_longs_allowed": fg_crypto["value"] > 25,
        "crypto_shorts_allowed": True,
        "stock_longs_allowed": True,
        "stock_shorts_allowed": True,
        "global_size_multiplier": 0.75 if posture == "DEFENSIVE" else 0.9 if posture == "SELECTIVE" else 1.0,
        "high_impact_events_next_24h": sum(1 for e in events if e.get("impact") == "HIGH"),
    }

    # ── 8. Summary ──
    summary = {
        "overall_market_mode": posture,
        "crypto_market_mode": crypto_mode,
        "stocks_market_mode": stock_mode,
        "macro_risk_mode": macro_mode,
        "crypto_fear_greed": fg_crypto["value"],
        "stocks_fear_greed": fg_stocks["value"],
        "pipeline_posture": posture,
        "active_headlines": len([h for h in headlines if h.get("freshness") != "stale"]),
        "upcoming_high_events": pipeline_directives["high_impact_events_next_24h"],
        "news_modes": news_summary,
        "ai_narrative": _generate_narrative(crypto_mode, stock_mode, macro_mode, fg_crypto["value"], fg_stocks["value"], posture),
    }

    # ── 9. Claude Opus 4.6 AI Analysis (overlay on rule-based) ──
    ai_analysis = None
    ai_status = {}
    try:
        from bahamut.intelligence.ai_market_analyst import get_cached_analysis, get_analysis_status
        ai_analysis = get_cached_analysis()
        ai_status = get_analysis_status()
    except Exception:
        pass

    if ai_analysis:
        # Override narrative with AI-generated one
        if ai_analysis.get("narrative"):
            summary["ai_narrative"] = ai_analysis["narrative"]
            summary["ai_narrative_source"] = "claude-opus-4.6"
        # Override posture if AI has a stronger opinion
        if ai_analysis.get("overall_posture"):
            summary["ai_posture"] = ai_analysis["overall_posture"]
        # Merge class analysis
        if ai_analysis.get("class_analysis"):
            for cls, analysis in ai_analysis["class_analysis"].items():
                if cls in class_context:
                    class_context[cls]["ai_bias"] = analysis.get("bias", "NEUTRAL")
                    class_context[cls]["ai_confidence"] = analysis.get("confidence", 0)
                    class_context[cls]["ai_reasoning"] = analysis.get("reasoning", "")
                    # If AI says a class should be more restricted, upgrade mode
                    ai_mode = analysis.get("mode", "NORMAL")
                    mode_rank = {"NORMAL": 0, "CAUTION": 1, "RESTRICTED": 2, "FROZEN": 3}
                    if mode_rank.get(ai_mode, 0) > mode_rank.get(class_context[cls].get("mode", "NORMAL"), 0):
                        class_context[cls]["mode"] = ai_mode
                        class_context[cls]["ai_upgraded_mode"] = True
        # Add headline interpretations
        if ai_analysis.get("headline_interpretations"):
            for interp in ai_analysis["headline_interpretations"]:
                idx = interp.get("headline_index", -1)
                if 0 <= idx < len(headlines):
                    headlines[idx]["ai_impact"] = interp.get("impact", "NONE")
                    headlines[idx]["ai_bias"] = interp.get("bias", "NEUTRAL")
                    headlines[idx]["ai_reasoning"] = interp.get("reasoning", "")
                    headlines[idx]["ai_affected_classes"] = interp.get("affected_classes", [])
        # Add event risk assessments
        if ai_analysis.get("event_risk_assessments"):
            for assess in ai_analysis["event_risk_assessments"]:
                idx = assess.get("event_index", -1)
                if 0 <= idx < len(events):
                    events[idx]["ai_risk_level"] = assess.get("risk_level", events[idx].get("risk_level"))
                    events[idx]["ai_policy"] = assess.get("pre_event_policy", "normal")
                    events[idx]["ai_reasoning"] = assess.get("reasoning", "")
        # High conviction calls
        if ai_analysis.get("high_conviction_calls"):
            summary["ai_high_conviction"] = ai_analysis["high_conviction_calls"]

    snapshot["ai_analysis_status"] = ai_status
    snapshot["ai_analysis_raw"] = ai_analysis if ai_analysis else None

    snapshot["summary"] = summary
    snapshot["class_context"] = class_context
    snapshot["asset_context"] = asset_context
    snapshot["headline_context"] = headlines
    snapshot["event_context"] = events
    snapshot["pipeline_directives"] = pipeline_directives

    _cache = snapshot
    _cache_ts = now
    logger.info("market_intelligence_snapshot_built",
                posture=posture, crypto_mode=crypto_mode, stock_mode=stock_mode,
                assets=len(asset_context), headlines=len(headlines), events=len(events))
    return snapshot


def _generate_narrative(crypto_mode, stock_mode, macro_mode, crypto_fg, stock_fg, posture) -> str:
    parts = []
    if crypto_fg <= 25:
        parts.append(f"Crypto in Extreme Fear ({crypto_fg}) — LONGs blocked, only SHORTs on rejection patterns.")
    elif crypto_fg <= 40:
        parts.append(f"Crypto sentiment fearful ({crypto_fg}) — selective entries with reduced size.")
    else:
        parts.append(f"Crypto sentiment neutral ({crypto_fg}) — normal trading conditions.")

    if stock_fg <= 35:
        parts.append(f"Stock sentiment cautious ({stock_fg}) — favor high-conviction setups only.")
    elif stock_fg >= 65:
        parts.append(f"Stock sentiment greedy ({stock_fg}) — watch for overextension.")
    else:
        parts.append(f"Stock sentiment balanced ({stock_fg}) — normal stock conditions.")

    if posture == "DEFENSIVE":
        parts.append("Pipeline posture: DEFENSIVE — reduced sizing across all classes.")
    elif posture == "SELECTIVE":
        parts.append("Pipeline posture: SELECTIVE — higher quality bars required.")
    else:
        parts.append("Pipeline posture: AGGRESSIVE — full deployment available.")

    return " ".join(parts)


# ═══════════════════════════════════════════
# SELECTOR INTERFACE — called per-candidate
# ═══════════════════════════════════════════

def get_ai_context_for_asset(asset: str) -> dict:
    """Get the AI market context for a specific asset. Fast (cached)."""
    snap = build_market_intelligence_snapshot()
    ac = snap.get("asset_context", {}).get(asset)
    if not ac:
        return {
            "ai_market_mode": "NORMAL",
            "ai_bias": "NEUTRAL",
            "ai_confidence": 0,
            "ai_threshold_penalty": 0,
            "ai_size_mult": 1.0,
            "ai_allowed_directions": ["LONG", "SHORT"],
            "ai_reason": "no_context_available",
        }
    return {
        "ai_market_mode": ac["combined_mode"],
        "ai_bias": ac["ai_bias"],
        "ai_confidence": ac["ai_confidence"],
        "ai_threshold_penalty": ac["threshold_penalty"],
        "ai_size_mult": ac["size_multiplier"],
        "ai_allowed_directions": ac["allowed_directions"],
        "ai_reason": f"class={ac['sentiment_mode']}, news={ac['news_mode']}, combined={ac['combined_mode']}",
    }


def get_pipeline_directives() -> dict:
    """Get global pipeline directives. Fast (cached)."""
    snap = build_market_intelligence_snapshot()
    return snap.get("pipeline_directives", {})
