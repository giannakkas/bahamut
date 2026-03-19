"""
Bahamut.AI — Lightweight Metrics

Simple in-memory counters and latency tracking.
No external dependencies (no Prometheus). Exposed via /metrics endpoint.

Usage:
    from bahamut.middleware.metrics import metrics
    metrics.inc("requests_total")
    metrics.observe_latency("db_query", 12.5)
"""
import time
import threading
import structlog
from collections import defaultdict
from fastapi import APIRouter

logger = structlog.get_logger()
router = APIRouter()


class SimpleMetrics:
    """Thread-safe in-memory metrics store."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._max_latency_samples = 1000  # rolling window

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe_latency(self, name: str, ms: float) -> None:
        with self._lock:
            samples = self._latencies[name]
            samples.append(ms)
            if len(samples) > self._max_latency_samples:
                self._latencies[name] = samples[-self._max_latency_samples:]

    def get_counter(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def snapshot(self) -> dict:
        with self._lock:
            result = {
                "counters": dict(self._counters),
                "latencies": {},
            }
            for name, samples in self._latencies.items():
                if not samples:
                    continue
                sorted_s = sorted(samples)
                n = len(sorted_s)
                result["latencies"][name] = {
                    "count": n,
                    "avg_ms": round(sum(sorted_s) / n, 1),
                    "p50_ms": round(sorted_s[n // 2], 1),
                    "p95_ms": round(sorted_s[int(n * 0.95)], 1),
                    "p99_ms": round(sorted_s[int(n * 0.99)], 1),
                    "max_ms": round(sorted_s[-1], 1),
                }
            return result

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._latencies.clear()


# Global singleton
metrics = SimpleMetrics()


@router.get("/metrics")
async def get_metrics():
    """GET /metrics — lightweight operational metrics."""
    return metrics.snapshot()
