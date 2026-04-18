"""
Bahamut.AI — Per-Broker REST Latency Tracker

Records REST API call latencies per broker in Redis (last 100 calls).
Provides p95 latency for dashboard display and alerting.

Usage:
    from bahamut.execution._latency import record, p95
    record("binance", 142.5)   # 142.5ms
    print(p95("binance"))       # e.g. 245.0
"""
import os


def _r():
    try:
        import redis
        return redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1,
        )
    except Exception:
        return None


_KEY_PREFIX = "bahamut:latency:rest:"


def record(broker: str, latency_ms: float) -> None:
    """Record a single REST API call latency (ms)."""
    r = _r()
    if not r:
        return
    try:
        k = f"{_KEY_PREFIX}{broker}"
        r.lpush(k, str(int(latency_ms)))
        r.ltrim(k, 0, 99)
        r.expire(k, 3600)
    except Exception:
        pass


def p95(broker: str) -> float:
    """Return p95 latency in ms for the last 100 calls. Returns -1 if no data."""
    r = _r()
    if not r:
        return -1
    try:
        vals = [int(x) for x in r.lrange(f"{_KEY_PREFIX}{broker}", 0, -1)]
        if not vals:
            return -1
        vals.sort()
        idx = int(len(vals) * 0.95)
        return float(vals[min(idx, len(vals) - 1)])
    except Exception:
        return -1
