"""
AI Market Analyst — Claude Opus 4.6 powered market interpretation.

Calls Claude Opus 4.6 with structured market data (headlines, calendar,
sentiment) and receives structured JSON analysis with directional bias,
confidence, risk assessment, and trading recommendations.

Results are cached for 5 minutes to control API costs.
Falls back to rule-based analysis if Claude is unavailable.
"""
import time
import json
import os
import asyncio
import structlog

logger = structlog.get_logger()

CLAUDE_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-4-6"
CACHE_TTL = 300  # 5 minutes
MAX_TOKENS = 1500
TIMEOUT = 30.0  # Opus needs more time for deep reasoning

# Cache
_analysis_cache: dict | None = None
_analysis_cache_ts: float = 0
_last_error: str = ""
_call_count: int = 0

SYSTEM_PROMPT = """You are Bahamut's senior market analyst AI. You receive real-time market data and produce structured trading intelligence.

Your role:
- Interpret news headlines for directional bias and impact
- Assess economic calendar events for trading risk
- Synthesize sentiment data into actionable guidance
- Produce asset-class-level and asset-level recommendations

You must respond with ONLY valid JSON, no markdown, no preamble. The JSON must match this exact schema:

{
  "narrative": "2-3 sentence plain English market summary for the trading desk",
  "overall_posture": "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE" | "FROZEN",
  "class_analysis": {
    "crypto": {
      "mode": "NORMAL" | "CAUTION" | "RESTRICTED" | "FROZEN",
      "bias": "LONG" | "SHORT" | "NEUTRAL",
      "confidence": 0.0-1.0,
      "reasoning": "one sentence"
    },
    "stock": { same structure },
    "forex": { same structure },
    "commodity": { same structure },
    "index": { same structure }
  },
  "headline_interpretations": [
    {
      "headline_index": 0,
      "impact": "HIGH" | "MEDIUM" | "LOW" | "NONE",
      "bias": "LONG" | "SHORT" | "NEUTRAL",
      "affected_classes": ["crypto", "stock"],
      "reasoning": "one sentence"
    }
  ],
  "event_risk_assessments": [
    {
      "event_index": 0,
      "risk_level": "HIGH" | "MEDIUM" | "LOW",
      "pre_event_policy": "block_new" | "reduce_size" | "normal",
      "affected_classes": ["stock", "forex"],
      "reasoning": "one sentence"
    }
  ],
  "high_conviction_calls": [
    {
      "asset_or_class": "BTCUSD" or "crypto",
      "direction": "LONG" | "SHORT" | "AVOID",
      "confidence": 0.0-1.0,
      "reasoning": "one sentence"
    }
  ]
}

Rules:
- Be decisive, not wishy-washy. If data is bearish, say SHORT.
- Confidence reflects YOUR certainty, not market direction strength.
- FROZEN means DO NOT TRADE AT ALL. Use sparingly.
- headline_interpretations should only include indices of impactful headlines (skip NONE).
- event_risk_assessments should only include HIGH and MEDIUM events.
- high_conviction_calls: maximum 5, only when you have strong views."""


def _build_user_prompt(sentiment: dict, headlines: list, events: list, regimes: dict) -> str:
    """Build the user prompt with current market data."""
    parts = []

    # Sentiment
    fg_crypto = sentiment.get("fear_greed", {})
    fg_stocks = sentiment.get("cnn_fear_greed", {})
    parts.append(f"""## SENTIMENT DATA
Crypto Fear & Greed: {fg_crypto.get('value', '?')} ({fg_crypto.get('classification', '?')})
Stock Fear & Greed (CNN): {fg_stocks.get('value', '?')} ({fg_stocks.get('classification', '?')})
Combined crypto action: {sentiment.get('combined_crypto_action', '?')}
Combined stock action: {sentiment.get('combined_stock_action', '?')}""")

    # Headlines
    if headlines:
        hl_text = []
        for i, h in enumerate(headlines[:15]):
            hl_text.append(f"[{i}] {h.get('title', '?')} (source: {h.get('source', '?')}, impact: {h.get('impact_score', 0):.2f}, bias: {h.get('bias', '?')})")
        parts.append("## RECENT HEADLINES\n" + "\n".join(hl_text))
    else:
        parts.append("## RECENT HEADLINES\nNo recent headlines available.")

    # Calendar events
    if events:
        ev_text = []
        for i, ev in enumerate(events[:15]):
            ev_text.append(f"[{i}] {ev.get('event', '?')} ({ev.get('country', '?')}) — impact: {ev.get('impact', '?')}, date: {ev.get('date', '?')}, actual: {ev.get('actual', '–')}, forecast: {ev.get('forecast', '–')}, prev: {ev.get('previous', '–')}")
        parts.append("## ECONOMIC CALENDAR\n" + "\n".join(ev_text))
    else:
        parts.append("## ECONOMIC CALENDAR\nNo upcoming events.")

    # Regime summary
    if regimes:
        reg_text = []
        for asset, info in list(regimes.items())[:10]:
            reg_text.append(f"{asset}: {info.get('regime', '?')} (dist_ema200: {info.get('dist_ema200', '?')}%)")
        parts.append("## KEY ASSET REGIMES\n" + "\n".join(reg_text))

    parts.append("\nAnalyze this data and respond with the JSON schema specified in your instructions.")
    return "\n\n".join(parts)


async def call_opus_analysis(
    sentiment: dict,
    headlines: list,
    events: list,
    regimes: dict | None = None,
) -> dict | None:
    """Call Claude Opus 4.6 for market analysis. Returns parsed JSON or None."""
    global _analysis_cache, _analysis_cache_ts, _last_error, _call_count

    # Check cache
    now = time.time()
    if _analysis_cache and (now - _analysis_cache_ts) < CACHE_TTL:
        return _analysis_cache

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        _last_error = "ANTHROPIC_API_KEY not set"
        return None

    prompt = _build_user_prompt(sentiment, headlines, events, regimes or {})

    try:
        import httpx
        _call_count += 1
        start = time.time()

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                CLAUDE_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MODEL,
                    "max_tokens": MAX_TOKENS,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            latency = round((time.time() - start) * 1000)

            if resp.status_code == 429:
                _last_error = f"Rate limited (429) at {latency}ms"
                logger.warning("opus_market_rate_limited", latency_ms=latency)
                return None

            if resp.status_code != 200:
                _last_error = f"HTTP {resp.status_code}: {resp.text[:100]}"
                logger.error("opus_market_http_error", status=resp.status_code, latency_ms=latency)
                return None

            data = resp.json()
            text = data["content"][0]["text"]

            # Parse JSON — strip markdown fences if present
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()

            result = json.loads(clean)
            result["_provider"] = "claude-opus-4.6"
            result["_latency_ms"] = latency
            result["_call_number"] = _call_count
            result["_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

            # Cache it
            _analysis_cache = result
            _analysis_cache_ts = now
            _last_error = ""

            logger.info("opus_market_analysis_complete",
                        latency_ms=latency, posture=result.get("overall_posture"),
                        call_number=_call_count)
            return result

    except json.JSONDecodeError as e:
        _last_error = f"JSON parse error: {str(e)[:80]}"
        logger.error("opus_market_json_error", error=str(e)[:100])
        return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        _last_error = f"Exception: {str(e)[:100]}"
        logger.error("opus_market_exception", error=str(e)[:100])
        return None


def call_opus_sync(sentiment: dict, headlines: list, events: list, regimes: dict | None = None) -> dict | None:
    """Sync wrapper for call_opus_analysis. For use in non-async contexts."""
    global _analysis_cache, _analysis_cache_ts

    # Check cache first (avoid event loop issues)
    now = time.time()
    if _analysis_cache and (now - _analysis_cache_ts) < CACHE_TTL:
        return _analysis_cache

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in an async context — can't use run_until_complete
            # Return cached or None (caller should use async version)
            return _analysis_cache
        return loop.run_until_complete(call_opus_analysis(sentiment, headlines, events, regimes))
    except RuntimeError:
        # No event loop — create one
        return asyncio.run(call_opus_analysis(sentiment, headlines, events, regimes))


def get_cached_analysis() -> dict | None:
    """Get the last cached analysis without triggering a new call."""
    return _analysis_cache


def get_analysis_status() -> dict:
    """Get the status of the AI analysis system."""
    return {
        "model": MODEL,
        "cache_ttl_seconds": CACHE_TTL,
        "cached": _analysis_cache is not None,
        "cache_age_seconds": round(time.time() - _analysis_cache_ts) if _analysis_cache_ts > 0 else None,
        "total_calls": _call_count,
        "last_error": _last_error or None,
        "last_posture": _analysis_cache.get("overall_posture") if _analysis_cache else None,
        "last_latency_ms": _analysis_cache.get("_latency_ms") if _analysis_cache else None,
    }
