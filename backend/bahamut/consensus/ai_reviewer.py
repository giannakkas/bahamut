"""
AI Consensus Reviewer — async-first architecture with short-TTL review cache.

Dual interface:
  - async: ai_consensus_review()         (for async callers)
  - sync:  ai_consensus_review_sync()    (safe wrapper for Celery/sync contexts)

Features:
  - Parallel Gemini + Claude via asyncio.gather
  - Circuit breaker per provider (auto-disable after repeated failures)
  - Latency logging per provider
  - Timeout protection (max 5s per provider)
  - Fail-fast fallback if all AI unavailable
  - Safe cancellation handling
  - Short-TTL review cache (Redis primary, in-memory fallback)
"""

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"

# ── Default Cache Configuration ──────────────────────────────────────────────

_CACHE_TTL_SECONDS: int = 120  # 2 minutes — configurable via set_cache_ttl()
_CACHE_ENABLED: bool = True
_CACHE_REDIS_PREFIX = "bah:ai_review:"

# ── Circuit Breaker ──────────────────────────────────────────────────────────

@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker. Opens after `threshold` failures within `window` seconds."""
    name: str
    threshold: int = 3
    window: float = 300.0  # 5 min window
    cooldown: float = 120.0  # 2 min cooldown before retry
    _failures: list = field(default_factory=list)
    _open_since: float = 0.0

    @property
    def is_open(self) -> bool:
        if self._open_since > 0:
            if time.time() - self._open_since > self.cooldown:
                self._open_since = 0
                logger.info("circuit_breaker_half_open", provider=self.name)
                return False
            return True
        return False

    def record_success(self):
        self._failures.clear()
        self._open_since = 0

    def record_failure(self):
        now = time.time()
        self._failures = [t for t in self._failures if now - t < self.window]
        self._failures.append(now)
        if len(self._failures) >= self.threshold:
            self._open_since = now
            logger.warning("circuit_breaker_opened", provider=self.name,
                           failures=len(self._failures), cooldown=self.cooldown)


_gemini_breaker = CircuitBreaker(name="gemini_reviewer")
_claude_breaker = CircuitBreaker(name="claude_reviewer")


# ══════════════════════════════════════════════════════════════════════════════
# TASK 1 + 2: REVIEW CACHE — deterministic key, short TTL, dual backend
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _CacheStats:
    """Observable counters for cache diagnostics."""
    hits: int = 0
    misses: int = 0
    errors: int = 0
    backend: str = "none"  # "redis" | "memory" | "none"


_cache_stats = _CacheStats()

# In-memory fallback cache: key -> (result_json, expires_at)
_mem_cache: dict[str, tuple[str, float]] = {}


def build_review_cache_key(
    asset: str,
    direction: str,
    score: float,
    agent_summaries: list,
) -> str:
    """
    Build a deterministic SHA-256 cache key from normalized review input.

    Normalization rules:
      - asset/direction uppercased and stripped
      - score rounded to 4 decimal places (avoids float dust)
      - agent_summaries sorted by agent name
      - each agent: only (agent, bias, confidence rounded to 3dp) — reason excluded
        because reason text may vary across cycles for identical decisions
      - dict ordering is canonical via sorted keys
    """
    norm_agents = sorted(
        [
            {
                "agent": str(a.get("agent", "")).strip(),
                "bias": str(a.get("bias", "")).strip().upper(),
                "confidence": round(float(a.get("confidence", 0)), 3),
            }
            for a in agent_summaries
        ],
        key=lambda x: x["agent"],
    )

    canonical = json.dumps(
        {
            "asset": asset.strip().upper(),
            "direction": direction.strip().upper(),
            "score": round(score, 4),
            "agents": norm_agents,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


async def _cache_get(key: str) -> Optional[dict]:
    """
    Try Redis first, fall back to in-memory.
    Returns cached result dict or None.
    Never raises — all errors caught and logged.
    """
    # ── Try Redis ──
    try:
        from bahamut.shared.redis_client import redis_manager
        if redis_manager.redis is not None:
            raw = await redis_manager.get(f"{_CACHE_REDIS_PREFIX}{key}")
            if raw is not None:
                _cache_stats.backend = "redis"
                return json.loads(raw)
    except Exception as e:
        _cache_stats.errors += 1
        logger.debug("review_cache_redis_get_error", error=str(e)[:80])

    # ── Fallback: in-memory ──
    entry = _mem_cache.get(key)
    if entry is not None:
        data_json, expires_at = entry
        if time.time() < expires_at:
            _cache_stats.backend = "memory"
            return json.loads(data_json)
        else:
            # Expired — evict
            _mem_cache.pop(key, None)

    return None


async def _cache_set(key: str, result: dict, ttl: int) -> None:
    """
    Store in Redis (primary) AND in-memory (fallback).
    Never raises — all errors caught.
    """
    result_json = json.dumps(result, separators=(",", ":"))

    # ── Redis ──
    try:
        from bahamut.shared.redis_client import redis_manager
        if redis_manager.redis is not None:
            await redis_manager.set(f"{_CACHE_REDIS_PREFIX}{key}", result_json, ex=ttl)
            _cache_stats.backend = "redis"
    except Exception as e:
        _cache_stats.errors += 1
        logger.debug("review_cache_redis_set_error", error=str(e)[:80])

    # ── Always write to memory as fallback ──
    _mem_cache[key] = (result_json, time.time() + ttl)

    # ── Evict expired memory entries periodically ──
    if len(_mem_cache) > 200:
        now = time.time()
        expired = [k for k, (_, exp) in _mem_cache.items() if exp < now]
        for k in expired:
            del _mem_cache[k]


def _is_cacheable_result(result: dict) -> bool:
    """
    TASK 3 — Safety rule: only cache well-formed, deterministic results.

    Cache if:
      - has score_adjustment (float, clamped)
      - has confidence_in_consensus (HIGH/MEDIUM/LOW)
      - has _provider (not an error state)

    Do NOT cache:
      - None results
      - error dicts
      - partial/malformed responses
    """
    if not isinstance(result, dict):
        return False
    if "score_adjustment" not in result:
        return False
    if not isinstance(result.get("score_adjustment"), (int, float)):
        return False
    if result.get("confidence_in_consensus") not in ("HIGH", "MEDIUM", "LOW"):
        return False
    if not result.get("_provider"):
        return False
    return True


# ── Configuration helpers ────────────────────────────────────────────────────

def set_cache_ttl(seconds: int) -> None:
    """Set the cache TTL. Clamped to 10–600s for safety."""
    global _CACHE_TTL_SECONDS
    _CACHE_TTL_SECONDS = max(10, min(600, seconds))


def set_cache_enabled(enabled: bool) -> None:
    """Enable or disable the cache layer."""
    global _CACHE_ENABLED
    _CACHE_ENABLED = enabled


def clear_cache() -> int:
    """Clear all in-memory cache entries. Returns count evicted."""
    count = len(_mem_cache)
    _mem_cache.clear()
    return count


# ── Prompt Builder ───────────────────────────────────────────────────────────

def _build_review_prompt(asset: str, direction: str, score: float,
                          agent_summaries: list) -> str:
    agents_txt = "\n".join(
        f"  - {a['agent']}: {a['bias']} (conf={a['confidence']:.0%}) — {a['reason']}"
        for a in agent_summaries
    )
    return f"""You are a senior trading desk reviewer. 6 AI agents analyzed {asset} and produced this consensus:

Direction: {direction} | Score: {score:.2f}

AGENT VOTES:
{agents_txt}

As reviewer, assess: Is this consensus reasonable? Are there blind spots?

Respond ONLY with JSON (no markdown, no backticks):
{{"score_adjustment": float between -0.15 and +0.15, "note": "brief 1-sentence review", "confidence_in_consensus": "HIGH" or "MEDIUM" or "LOW"}}"""


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1].lstrip("json\n")
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        result = json.loads(text[start:end])
        adj = result.get("score_adjustment", 0)
        if isinstance(adj, (int, float)):
            result["score_adjustment"] = max(-0.15, min(0.15, float(adj)))
        else:
            result["score_adjustment"] = 0.0
        return result
    raise ValueError("No JSON found in response")


# ── Provider Calls (async, non-blocking) ─────────────────────────────────────

async def _call_gemini(prompt: str, api_key: str, timeout: float = 5.0) -> Optional[dict]:
    """Call Gemini with timeout + circuit breaker."""
    if _gemini_breaker.is_open:
        logger.debug("gemini_reviewer_circuit_open")
        return None

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={api_key}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200},
                },
            )
            if resp.status_code == 429:
                _gemini_breaker.record_failure()
                logger.warning("gemini_reviewer_429", latency_ms=_ms(start))
                return None
            resp.raise_for_status()
            data = resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"]
        result = _parse_json_response(text)
        result["_provider"] = "gemini"
        result["_latency_ms"] = _ms(start)

        _gemini_breaker.record_success()
        logger.info("gemini_reviewer_ok", latency_ms=result["_latency_ms"],
                     adj=result.get("score_adjustment"), confidence=result.get("confidence_in_consensus"))
        return result

    except asyncio.CancelledError:
        logger.debug("gemini_reviewer_cancelled")
        raise
    except Exception as e:
        _gemini_breaker.record_failure()
        logger.warning("gemini_reviewer_failed", error=str(e)[:100], latency_ms=_ms(start))
        return None


async def _call_claude(prompt: str, api_key: str, timeout: float = 5.0) -> Optional[dict]:
    """Call Claude with timeout + circuit breaker."""
    if _claude_breaker.is_open:
        logger.debug("claude_reviewer_circuit_open")
        return None

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                CLAUDE_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            if resp.status_code == 429:
                _claude_breaker.record_failure()
                logger.warning("claude_reviewer_429", latency_ms=_ms(start))
                return None
            resp.raise_for_status()
            data = resp.json()

        text = data["content"][0]["text"]
        result = _parse_json_response(text)
        result["_provider"] = "claude"
        result["_latency_ms"] = _ms(start)

        _claude_breaker.record_success()
        logger.info("claude_reviewer_ok", latency_ms=result["_latency_ms"],
                     adj=result.get("score_adjustment"), confidence=result.get("confidence_in_consensus"))
        return result

    except asyncio.CancelledError:
        logger.debug("claude_reviewer_cancelled")
        raise
    except Exception as e:
        _claude_breaker.record_failure()
        logger.warning("claude_reviewer_failed", error=str(e)[:100], latency_ms=_ms(start))
        return None


# ══════════════════════════════════════════════════════════════════════════════
# CORE ASYNC INTERFACE — with cache integration
# ══════════════════════════════════════════════════════════════════════════════

async def ai_consensus_review(
    asset: str,
    direction: str,
    score: float,
    agent_summaries: list,
) -> Optional[dict]:
    """
    Async-first AI consensus review. Runs Gemini + Claude in parallel.
    Includes short-TTL cache to avoid duplicate AI calls for identical inputs.

    Returns dict with:
      - score_adjustment: float (-0.15 to +0.15)
      - note: str (1-sentence review)
      - confidence_in_consensus: HIGH/MEDIUM/LOW
      - _provider: which provider responded (or "cache")
      - _latency_ms: response time
      - _cache: "hit" | "miss" | "bypass"

    Returns None if:
      - Score outside borderline range (0.40-0.80)
      - No API keys configured
      - All providers failed/timed out
    """
    # ── Gate: only review borderline decisions ──
    if score < 0.40 or score > 0.80:
        return None

    # ── Cache lookup ──
    cache_key = build_review_cache_key(asset, direction, score, agent_summaries)

    if _CACHE_ENABLED:
        try:
            cached = await _cache_get(cache_key)
            if cached is not None:
                _cache_stats.hits += 1
                cached["_cache"] = "hit"
                cached["_latency_ms"] = 0
                logger.info("ai_reviewer_cache_hit", asset=asset, key=cache_key[:12])
                return cached
        except Exception as e:
            _cache_stats.errors += 1
            logger.debug("ai_reviewer_cache_lookup_error", error=str(e)[:80])

    _cache_stats.misses += 1

    # ── Provider dispatch ──
    from bahamut.config import get_settings
    settings = get_settings()
    gemini_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
    claude_key = settings.anthropic_api_key or ""

    if not gemini_key and not claude_key:
        return None

    prompt = _build_review_prompt(asset, direction, score, agent_summaries)

    tasks = []
    if gemini_key and not _gemini_breaker.is_open:
        tasks.append(_call_gemini(prompt, gemini_key, timeout=5.0))
    if claude_key and not _claude_breaker.is_open:
        tasks.append(_call_claude(prompt, claude_key, timeout=5.0))

    if not tasks:
        logger.debug("ai_reviewer_no_providers_available")
        return None

    overall_start = time.time()
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        logger.warning("ai_reviewer_total_timeout", latency_ms=_ms(overall_start))
        return None

    valid = [r for r in results if isinstance(r, dict) and "score_adjustment" in r]

    if not valid:
        logger.info("ai_reviewer_no_valid_results", latency_ms=_ms(overall_start))
        return None

    # ── Build final result ──
    if len(valid) == 1:
        result = valid[0]
    else:
        # Both responded — merge
        g = next((r for r in valid if r.get("_provider") == "gemini"), None)
        c = next((r for r in valid if r.get("_provider") == "claude"), None)
        if g and c:
            avg_adj = (g["score_adjustment"] + c["score_adjustment"]) / 2
            agreement = "AGREE" if (g["score_adjustment"] > 0) == (c["score_adjustment"] > 0) else "SPLIT"
            logger.info("ai_reviewer_dual_result",
                         gemini_adj=g["score_adjustment"], claude_adj=c["score_adjustment"],
                         merged_adj=round(avg_adj, 4), agreement=agreement,
                         gemini_ms=g.get("_latency_ms"), claude_ms=c.get("_latency_ms"))
            result = {
                "score_adjustment": round(avg_adj, 4),
                "note": f"[{agreement}] Gemini: {g.get('note', '')} | Claude: {c.get('note', '')}",
                "confidence_in_consensus": g.get("confidence_in_consensus", "MEDIUM"),
                "_provider": f"dual({agreement})",
                "_latency_ms": _ms(overall_start),
            }
        else:
            result = valid[0]

    result["_cache"] = "miss"

    # ── Cache write (only safe, well-formed results) ──
    if _CACHE_ENABLED and _is_cacheable_result(result):
        try:
            await _cache_set(cache_key, result, _CACHE_TTL_SECONDS)
            logger.debug("ai_reviewer_cache_stored", asset=asset, key=cache_key[:12],
                         ttl=_CACHE_TTL_SECONDS)
        except Exception as e:
            _cache_stats.errors += 1
            logger.debug("ai_reviewer_cache_store_error", error=str(e)[:80])

    return result


# ── Sync Wrapper (for Celery / sync callers) ─────────────────────────────────

def ai_consensus_review_sync(
    asset: str,
    direction: str,
    score: float,
    agent_summaries: list,
) -> Optional[dict]:
    """
    Sync wrapper for ai_consensus_review().
    Safe for Celery workers and sync contexts.
    Always creates a fresh event loop — never pollutes the global loop.
    """
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                ai_consensus_review(asset, direction, score, agent_summaries)
            )
        finally:
            loop.close()
    except Exception as e:
        logger.error("ai_reviewer_sync_failed", error=str(e)[:100])
        return None


# ── Diagnostics ──────────────────────────────────────────────────────────────

def get_reviewer_status() -> dict:
    """Returns circuit breaker AND cache status for monitoring."""
    return {
        "gemini": {
            "circuit_open": _gemini_breaker.is_open,
            "recent_failures": len(_gemini_breaker._failures),
            "threshold": _gemini_breaker.threshold,
        },
        "claude": {
            "circuit_open": _claude_breaker.is_open,
            "recent_failures": len(_claude_breaker._failures),
            "threshold": _claude_breaker.threshold,
        },
        "cache": {
            "enabled": _CACHE_ENABLED,
            "backend": _cache_stats.backend,
            "ttl_seconds": _CACHE_TTL_SECONDS,
            "hits": _cache_stats.hits,
            "misses": _cache_stats.misses,
            "errors": _cache_stats.errors,
            "memory_entries": len(_mem_cache),
        },
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ms(start: float) -> int:
    return round((time.time() - start) * 1000)
