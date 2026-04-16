"""
AI Market Analyst — Claude Opus 4.6 GLOBAL POSTURE engine.

This is Layer A: a global posture call, NOT a per-asset decider.
Called once per cycle max. Returns narrow schema only.

Architecture:
  - Fresh cache: 60s
  - Stale fallback: 5 min (used on timeout/error)
  - Hard timeout: 1.2s
  - Narrow output: posture, class modes, directions, size mult
  - No per-asset JSON from Opus
"""
import time
import json
import os
import asyncio
import structlog

logger = structlog.get_logger()

CLAUDE_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-4-6"
FRESH_TTL = 60
STALE_TTL = 300
MAX_TOKENS = 400
TIMEOUT = 1.2

_analysis_cache: dict | None = None
_analysis_cache_ts: float = 0
_stale_cache: dict | None = None
_stale_cache_ts: float = 0
_last_error: str = ""
_call_count: int = 0
_timeout_count: int = 0
_cache_hits: int = 0
_stale_uses: int = 0
_fallback_uses: int = 0

SYSTEM_PROMPT = """You are Bahamut's market posture engine. Respond with ONLY this JSON — no markdown, no preamble:

{
  "posture": "AGGRESSIVE|SELECTIVE|DEFENSIVE|FROZEN",
  "crypto_mode": "NORMAL|CAUTION|RESTRICTED|FROZEN",
  "stocks_mode": "NORMAL|CAUTION|RESTRICTED|FROZEN",
  "macro_risk": "NORMAL|ELEVATED|HIGH",
  "global_size_multiplier": 0.25-1.0,
  "crypto_longs_allowed": true/false,
  "crypto_shorts_allowed": true/false,
  "stock_longs_allowed": true/false,
  "stock_shorts_allowed": true/false,
  "high_impact_events_next_24h": integer,
  "reason": "one sentence"
}

Rules: Be decisive. If crypto F&G ≤25, crypto_longs_allowed=false. FROZEN=no trading."""


def _build_prompt(sentiment: dict, events: list) -> str:
    fg = sentiment.get("fear_greed", {})
    cnn = sentiment.get("cnn_fear_greed", {})
    high_ev = sum(1 for e in events if (e.get("impact", "") or "").upper() == "HIGH")
    return f"Crypto F&G: {fg.get('value','?')} ({fg.get('classification','?')})\nStock F&G: {cnn.get('value','?')} ({cnn.get('classification','?')})\nCrypto action: {sentiment.get('combined_crypto_action','?')}\nHigh events 24h: {high_ev}\nTotal events: {len(events)}\nReturn JSON."


async def call_opus_analysis(sentiment: dict, headlines: list, events: list, regimes: dict | None = None) -> dict | None:
    global _analysis_cache, _analysis_cache_ts, _stale_cache, _stale_cache_ts
    global _last_error, _call_count, _timeout_count, _cache_hits, _stale_uses, _fallback_uses
    now = time.time()
    if _analysis_cache and (now - _analysis_cache_ts) < FRESH_TTL:
        _cache_hits += 1
        return _analysis_cache
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        _last_error = "ANTHROPIC_API_KEY not set"
        _fallback_uses += 1
        return _use_stale(now)
    prompt = _build_prompt(sentiment, events)
    try:
        import httpx
        _call_count += 1
        start = time.time()
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(CLAUDE_URL, headers={
                "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json",
            }, json={"model": MODEL, "max_tokens": MAX_TOKENS, "system": SYSTEM_PROMPT,
                     "messages": [{"role": "user", "content": prompt}]})
            latency = round((time.time() - start) * 1000)
            if resp.status_code != 200:
                _last_error = f"HTTP {resp.status_code} at {latency}ms"
                _fallback_uses += 1
                return _use_stale(now)
            text = resp.json()["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"): text = text[:-3]
                text = text.strip()
            result = json.loads(text)
            result["_latency_ms"] = latency
            result["_call_number"] = _call_count
            _analysis_cache = result
            _analysis_cache_ts = now
            _stale_cache = result
            _stale_cache_ts = now
            _last_error = ""
            logger.info("opus_global_posture_ok", latency_ms=latency, posture=result.get("posture"))
            return result
    except Exception as e:
        is_timeout = "timeout" in str(type(e).__name__).lower() or "timeout" in str(e).lower()
        if is_timeout:
            _timeout_count += 1
            _last_error = f"Timeout ({TIMEOUT}s)"
        else:
            _last_error = f"{type(e).__name__}: {str(e)[:60]}"
        logger.warning("opus_call_failed", error=_last_error, is_timeout=is_timeout)
        _fallback_uses += 1
        return _use_stale(now)


def _use_stale(now: float) -> dict | None:
    global _stale_uses
    if _stale_cache and (now - _stale_cache_ts) < STALE_TTL:
        _stale_uses += 1
        return _stale_cache
    return None


def get_cached_analysis() -> dict | None:
    return _analysis_cache


def get_analysis_source() -> tuple[dict | None, str]:
    """Phase 4 Item 11: return (analysis, source) with explicit freshness.

    source values:
      'fresh'          — Opus cache hit within FRESH_TTL (60s)
      'stale'          — Opus cache within STALE_TTL but older than FRESH_TTL
                         (Opus call probably failed on last try — using last good)
      'fallback_rules' — No Opus cache at all; callers should use sentiment rules
      'disabled'       — Anthropic API key not configured

    Callers that don't want to disambiguate can keep using get_cached_analysis().
    """
    now = time.time()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None, "disabled"
    if _analysis_cache and _analysis_cache_ts > 0:
        age = now - _analysis_cache_ts
        if age < FRESH_TTL:
            return _analysis_cache, "fresh"
        if age < STALE_TTL:
            return _analysis_cache, "stale"
    if _stale_cache and _stale_cache_ts > 0:
        if (now - _stale_cache_ts) < STALE_TTL:
            return _stale_cache, "stale"
    return None, "fallback_rules"


def get_analysis_status() -> dict:
    now = time.time()
    age = round(now - _analysis_cache_ts) if _analysis_cache_ts > 0 else None
    return {
        "model": MODEL, "timeout_ms": int(TIMEOUT * 1000),
        "fresh_ttl": FRESH_TTL, "stale_ttl": STALE_TTL,
        "cached": _analysis_cache is not None,
        "cache_age_seconds": age,
        "cache_fresh": age is not None and age < FRESH_TTL,
        "total_calls": _call_count, "cache_hits": _cache_hits,
        "stale_uses": _stale_uses, "timeout_count": _timeout_count,
        "fallback_uses": _fallback_uses,
        "last_error": _last_error or None,
        "last_posture": _analysis_cache.get("posture") if _analysis_cache else None,
        "last_latency_ms": _analysis_cache.get("_latency_ms") if _analysis_cache else None,
        "ai_is_global_only": True,
        "ai_per_asset_decision_mode": "derived_not_llm",
    }
