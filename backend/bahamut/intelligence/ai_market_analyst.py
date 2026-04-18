"""
AI Market Analyst — GLOBAL POSTURE engine.

DeepSeek V3.2 primary + Gemini 2.5 Flash-Lite fallback.
Budget: ~EUR10-15/month at one call per 10-minute cycle.

This is Layer A: a global posture call, NOT a per-asset decider.
Called once per cycle max. Returns narrow schema only.

Architecture:
  - Redis-backed cache (cross-process: Celery worker + Uvicorn both read/write)
  - Fresh cache: 60s
  - Stale fallback: 5 min (used on timeout/error)
  - Hard timeout: 3s per provider
  - Daily cost cap: configurable via MAX_DAILY_AI_USD (default $0.75)
  - Provider cascade: DeepSeek -> Gemini -> None (fallback_rules)
"""
import time
import json
import os
import structlog

logger = structlog.get_logger()

_PRIMARY_MODEL = "deepseek-chat"
_FALLBACK_MODEL = "gemini-2.5-flash-lite"
_DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
_MAX_DAILY_USD = float(os.environ.get("MAX_DAILY_AI_USD", "0.75"))

FRESH_TTL = 60
STALE_TTL = 300
MAX_TOKENS = 400
TIMEOUT = 3.0

_CACHE_KEY = "bahamut:ai_posture:cache"
_CACHE_TS_KEY = "bahamut:ai_posture:cache_ts"
_DAILY_COST_KEY = "bahamut:ai_posture:daily_cost"
_PROVIDER_KEY = "bahamut:ai_posture:provider"

_last_error: str = ""
_call_count: int = 0
_timeout_count: int = 0
_cache_hits: int = 0
_stale_uses: int = 0
_fallback_uses: int = 0

# Back-compat: ai_decision_service imports these directly
_analysis_cache_ts: float = 0
_stale_cache_ts: float = 0

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

Rules: Be decisive. If crypto F&G <=25, crypto_longs_allowed=false. FROZEN=no trading."""


def _r():
    try:
        import redis
        return redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1,
        )
    except Exception:
        return None


def _get_daily_cost() -> float:
    r = _r()
    if not r:
        return 0
    try:
        raw = r.get(_DAILY_COST_KEY)
        return float(raw) if raw else 0
    except Exception:
        return 0


def _add_daily_cost(usd: float, provider: str) -> None:
    r = _r()
    if not r:
        return
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        secs_to_midnight = ((24 - now.hour - 1) * 3600
                            + (60 - now.minute) * 60
                            + (60 - now.second))
        r.incrbyfloat(_DAILY_COST_KEY, round(usd, 6))
        r.expire(_DAILY_COST_KEY, max(60, secs_to_midnight))
        r.setex(_PROVIDER_KEY, 600, provider)
    except Exception:
        pass


def _cache_write(result: dict) -> None:
    r = _r()
    if not r:
        return
    try:
        r.setex(_CACHE_KEY, STALE_TTL, json.dumps(result, default=str))
        r.setex(_CACHE_TS_KEY, STALE_TTL, str(time.time()))
    except Exception:
        pass


def _cache_read() -> tuple[dict | None, float]:
    r = _r()
    if not r:
        return None, 0
    try:
        raw = r.get(_CACHE_KEY)
        ts_raw = r.get(_CACHE_TS_KEY)
        if not raw:
            return None, 0
        data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        ts = float(ts_raw) if ts_raw else 0
        return data, ts
    except Exception:
        return None, 0


def _sync_compat_ts():
    """Update module-level ts vars from Redis for back-compat importers."""
    global _analysis_cache_ts, _stale_cache_ts
    _, ts = _cache_read()
    _analysis_cache_ts = ts
    _stale_cache_ts = ts


def _build_prompt(sentiment: dict, events: list) -> str:
    fg = sentiment.get("fear_greed", {})
    cnn = sentiment.get("cnn_fear_greed", {})
    high_ev = sum(1 for e in events if (e.get("impact", "") or "").upper() == "HIGH")
    return (f"Crypto F&G: {fg.get('value', '?')} ({fg.get('classification', '?')})\n"
            f"Stock F&G: {cnn.get('value', '?')} ({cnn.get('classification', '?')})\n"
            f"Crypto action: {sentiment.get('combined_crypto_action', '?')}\n"
            f"High events 24h: {high_ev}\nTotal events: {len(events)}\nReturn JSON.")


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def _call_deepseek(prompt: str) -> tuple[dict | None, float, str]:
    """DeepSeek V3.2 via OpenAI-compatible API. Returns (result, cost_usd, error)."""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None, 0, "DEEPSEEK_API_KEY not set"
    try:
        import httpx
        start = time.time()
        resp = httpx.post(
            _DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": _PRIMARY_MODEL,
                "max_tokens": MAX_TOKENS,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=TIMEOUT,
        )
        latency = round((time.time() - start) * 1000)
        if resp.status_code != 200:
            return None, 0, f"DeepSeek HTTP {resp.status_code} at {latency}ms"
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        cost = (usage.get("prompt_tokens", 0) * 0.28e-6
                + usage.get("completion_tokens", 0) * 0.42e-6)
        result = _parse_json_response(text)
        result["_latency_ms"] = latency
        result["_provider"] = "deepseek"
        result["_cost_usd"] = round(cost, 6)
        return result, cost, ""
    except Exception as e:
        return None, 0, f"DeepSeek {type(e).__name__}: {str(e)[:80]}"


def _call_gemini(prompt: str) -> tuple[dict | None, float, str]:
    """Gemini 2.5 Flash-Lite. Returns (result, cost_usd, error)."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None, 0, "GEMINI_API_KEY not set"
    try:
        import httpx
        start = time.time()
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{_FALLBACK_MODEL}:generateContent?key={api_key}")
        resp = httpx.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\n{prompt}"}]}],
                "generationConfig": {"maxOutputTokens": MAX_TOKENS, "temperature": 0.1},
            },
            timeout=TIMEOUT,
        )
        latency = round((time.time() - start) * 1000)
        if resp.status_code != 200:
            return None, 0, f"Gemini HTTP {resp.status_code} at {latency}ms"
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        cost = (usage.get("promptTokenCount", 0) * 0.10e-6
                + usage.get("candidatesTokenCount", 0) * 0.40e-6)
        result = _parse_json_response(text)
        result["_latency_ms"] = latency
        result["_provider"] = "gemini"
        result["_cost_usd"] = round(cost, 6)
        return result, cost, ""
    except Exception as e:
        return None, 0, f"Gemini {type(e).__name__}: {str(e)[:80]}"


def call_opus_analysis(sentiment: dict, headlines: list, events: list,
                       regimes: dict | None = None) -> dict | None:
    """Call AI posture engine. DeepSeek primary -> Gemini fallback.

    Name kept for back-compat; no longer calls Opus.
    SYNC function — safe to call from Celery workers.
    """
    global _last_error, _call_count, _timeout_count, _cache_hits
    global _stale_uses, _fallback_uses
    now = time.time()

    cached, cached_ts = _cache_read()
    if cached and (now - cached_ts) < FRESH_TTL:
        _cache_hits += 1
        _sync_compat_ts()
        return cached

    daily_cost = _get_daily_cost()
    if daily_cost >= _MAX_DAILY_USD:
        _last_error = f"Daily cap reached: ${daily_cost:.3f} >= ${_MAX_DAILY_USD}"
        logger.info("ai_daily_cap_reached", cost=daily_cost, cap=_MAX_DAILY_USD)
        return _use_stale(now, cached, cached_ts)

    has_deepseek = bool(os.environ.get("DEEPSEEK_API_KEY", ""))
    has_gemini = bool(os.environ.get("GEMINI_API_KEY", ""))
    if not has_deepseek and not has_gemini:
        _last_error = "No AI API keys configured (DEEPSEEK_API_KEY / GEMINI_API_KEY)"
        _fallback_uses += 1
        return _use_stale(now, cached, cached_ts)

    prompt = _build_prompt(sentiment, events)
    _call_count += 1

    result, cost, err = None, 0, ""
    if has_deepseek:
        result, cost, err = _call_deepseek(prompt)
        if result:
            _add_daily_cost(cost, "deepseek")
            result["_call_number"] = _call_count
            _cache_write(result)
            _last_error = ""
            _sync_compat_ts()
            logger.info("ai_posture_ok", provider="deepseek",
                        latency_ms=result.get("_latency_ms"),
                        posture=result.get("posture"),
                        cost_usd=round(cost, 6))
            return result
        logger.warning("ai_deepseek_failed", error=err)

    if has_gemini:
        result, cost, err2 = _call_gemini(prompt)
        if result:
            _add_daily_cost(cost, "gemini")
            result["_call_number"] = _call_count
            _cache_write(result)
            _last_error = ""
            _sync_compat_ts()
            logger.info("ai_posture_ok", provider="gemini",
                        latency_ms=result.get("_latency_ms"),
                        posture=result.get("posture"),
                        cost_usd=round(cost, 6))
            return result
        logger.warning("ai_gemini_failed", error=err2)
        err = f"{err} | {err2}"

    is_timeout = "timeout" in err.lower()
    if is_timeout:
        _timeout_count += 1
    _last_error = err
    _fallback_uses += 1
    logger.warning("ai_posture_all_failed", error=err)
    return _use_stale(now, cached, cached_ts)


def _use_stale(now: float, cached: dict | None = None,
               cached_ts: float = 0) -> dict | None:
    global _stale_uses
    if cached and (now - cached_ts) < STALE_TTL:
        _stale_uses += 1
        return cached
    c, ts = _cache_read()
    if c and (now - ts) < STALE_TTL:
        _stale_uses += 1
        return c
    return None


def get_cached_analysis() -> dict | None:
    cached, _ = _cache_read()
    return cached


def get_analysis_source() -> tuple[dict | None, str]:
    """Return (analysis, source) with explicit freshness.

    source values:
      'fresh'          -- cache hit within FRESH_TTL (60s)
      'stale'          -- cache within STALE_TTL but older than FRESH_TTL
      'fallback_rules' -- no cache at all
      'disabled'       -- no AI API keys configured
    """
    _sync_compat_ts()
    now = time.time()
    has_keys = bool(os.environ.get("DEEPSEEK_API_KEY", "")
                    or os.environ.get("GEMINI_API_KEY", ""))
    if not has_keys:
        return None, "disabled"
    cached, ts = _cache_read()
    if cached and ts > 0:
        age = now - ts
        if age < FRESH_TTL:
            return cached, "fresh"
        if age < STALE_TTL:
            return cached, "stale"
    return None, "fallback_rules"


def get_analysis_status() -> dict:
    _sync_compat_ts()
    cached, ts = _cache_read()
    now = time.time()
    age = round(now - ts) if ts > 0 else None
    daily_cost = _get_daily_cost()
    r = _r()
    provider = "none"
    if r:
        try:
            raw = r.get(_PROVIDER_KEY)
            if raw:
                provider = raw.decode() if isinstance(raw, bytes) else str(raw)
        except Exception:
            pass
    return {
        "model": f"{_PRIMARY_MODEL} -> {_FALLBACK_MODEL}",
        "primary": _PRIMARY_MODEL,
        "fallback": _FALLBACK_MODEL,
        "timeout_ms": int(TIMEOUT * 1000),
        "fresh_ttl": FRESH_TTL, "stale_ttl": STALE_TTL,
        "cached": cached is not None,
        "cache_age_seconds": age,
        "cache_fresh": age is not None and age < FRESH_TTL,
        "total_calls": _call_count, "cache_hits": _cache_hits,
        "stale_uses": _stale_uses, "timeout_count": _timeout_count,
        "fallback_uses": _fallback_uses,
        "last_error": _last_error or None,
        "last_posture": cached.get("posture") if cached else None,
        "last_latency_ms": cached.get("_latency_ms") if cached else None,
        "last_provider": cached.get("_provider") if cached else None,
        "ai_provider_active": provider,
        "ai_daily_cost_usd": round(daily_cost, 4),
        "ai_daily_cost_cap_usd": _MAX_DAILY_USD,
        "ai_is_global_only": True,
        "ai_per_asset_decision_mode": "derived_not_llm",
    }
