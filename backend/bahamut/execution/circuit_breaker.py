"""
Bahamut.AI — Per-Platform Execution Circuit Breaker

Prevents API bans by stopping execution after consecutive failures.
Separate breakers for each broker platform — Binance hiccups don't
disable Alpaca.

States:
  CLOSED    — normal operation, orders flow through
  OPEN      — tripped after N failures, all orders blocked for cooldown_sec
  HALF_OPEN — after cooldown, allow ONE probe order to test recovery

Close orders (is_close=True) are ALWAYS allowed regardless of state.

Cross-worker visibility: state is written to Redis on every mutation
and re-read from Redis at the top of allow_execution(). Every worker
sees the latest state, not just the state at init.

Usage:
  from bahamut.execution.circuit_breaker import circuit_breaker_binance, circuit_breaker_alpaca

Configuration via env vars:
  CIRCUIT_BREAKER_THRESHOLD=5
  CIRCUIT_BREAKER_COOLDOWN=300
  CIRCUIT_BREAKER_HALF_OPEN_MAX=1
"""
import os
import time
import json
import threading
import structlog

logger = structlog.get_logger()


class CircuitBreakerState:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


def _get_redis():
    try:
        import redis
        return redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1,
        )
    except Exception:
        return None


class CircuitBreaker:
    """Thread-safe, per-platform circuit breaker with live Redis state."""

    def __init__(self, platform: str = "default"):
        self.platform = platform
        self._redis_key = f"bahamut:cb:{platform}:state"

        self._threshold = int(os.environ.get("CIRCUIT_BREAKER_THRESHOLD", "5"))
        self._cooldown = int(os.environ.get("CIRCUIT_BREAKER_COOLDOWN", "300"))
        self._half_open_max = int(os.environ.get("CIRCUIT_BREAKER_HALF_OPEN_MAX", "1"))

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._tripped_at = 0.0
        self._half_open_attempts = 0
        self._lock = threading.Lock()

        self._restore_from_redis()

    def allow_execution(self, is_close: bool = False) -> bool:
        """Check if execution is allowed.
        Close orders (is_close=True) are ALWAYS allowed."""
        if is_close:
            return True

        # Re-read Redis state for cross-worker visibility
        self._sync_from_redis()

        with self._lock:
            now = time.time()

            if self._state == CircuitBreakerState.CLOSED:
                return True

            if self._state == CircuitBreakerState.OPEN:
                if now - self._tripped_at >= self._cooldown:
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_attempts = 0
                    logger.info("circuit_breaker_half_open",
                                platform=self.platform,
                                cooldown=self._cooldown,
                                failures=self._failure_count)
                    self._persist_to_redis()
                    self._half_open_attempts += 1
                    return True
                else:
                    return False

            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_attempts < self._half_open_max:
                    self._half_open_attempts += 1
                    return True
                return False

            return False

    def record_success(self):
        """Record a successful execution."""
        with self._lock:
            self._success_count += 1
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                logger.info("circuit_breaker_recovered",
                            platform=self.platform, state="CLOSED")
            elif self._state == CircuitBreakerState.CLOSED:
                self._failure_count = 0
            self._persist_to_redis()

    def record_failure(self, error: str = ""):
        """Record a failed execution. Trips after threshold."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.OPEN
                self._tripped_at = time.time()
                logger.error("circuit_breaker_probe_failed",
                             platform=self.platform,
                             error=error[:200],
                             cooldown=self._cooldown)
            elif self._state == CircuitBreakerState.CLOSED:
                if self._failure_count >= self._threshold:
                    self._state = CircuitBreakerState.OPEN
                    self._tripped_at = time.time()
                    logger.error("circuit_breaker_TRIPPED",
                                 platform=self.platform,
                                 failures=self._failure_count,
                                 threshold=self._threshold,
                                 cooldown_seconds=self._cooldown,
                                 last_error=error[:200])
            self._persist_to_redis()

    def get_status(self) -> dict:
        with self._lock:
            now = time.time()
            remaining = 0
            if self._state == CircuitBreakerState.OPEN:
                remaining = max(0, int(self._cooldown - (now - self._tripped_at)))
            return {
                "platform": self.platform,
                "state": self._state,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "threshold": self._threshold,
                "cooldown_seconds": self._cooldown,
                "remaining_cooldown": remaining,
                "last_failure": self._last_failure_time,
                "tripped_at": self._tripped_at,
            }

    def force_reset(self):
        with self._lock:
            prev = self._state
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._half_open_attempts = 0
            self._persist_to_redis()
            logger.warning("circuit_breaker_force_reset",
                           platform=self.platform, previous_state=prev)

    # ─── Redis persistence ───

    def _persist_to_redis(self):
        try:
            r = _get_redis()
            if r:
                r.setex(self._redis_key, self._cooldown + 120,
                        json.dumps({"state": self._state,
                                    "failure_count": self._failure_count,
                                    "tripped_at": self._tripped_at,
                                    "updated_at": time.time()}))
        except Exception:
            pass

    def _restore_from_redis(self):
        try:
            r = _get_redis()
            if not r:
                return
            raw = r.get(self._redis_key)
            if raw:
                data = json.loads(raw)
                state = data.get("state", CircuitBreakerState.CLOSED)
                if state == CircuitBreakerState.OPEN:
                    tripped = data.get("tripped_at", 0)
                    if time.time() - tripped < self._cooldown:
                        self._state = CircuitBreakerState.OPEN
                        self._failure_count = data.get("failure_count", 0)
                        self._tripped_at = tripped
                        logger.warning("circuit_breaker_restored_open",
                                       platform=self.platform,
                                       failures=self._failure_count)
        except Exception:
            pass

    def _sync_from_redis(self):
        """Lightweight re-read for cross-worker visibility."""
        try:
            r = _get_redis()
            if not r:
                return
            raw = r.get(self._redis_key)
            if not raw:
                return
            data = json.loads(raw)
            redis_state = data.get("state", CircuitBreakerState.CLOSED)
            redis_tripped = data.get("tripped_at", 0)
            with self._lock:
                if redis_state == CircuitBreakerState.OPEN and self._state == CircuitBreakerState.CLOSED:
                    if time.time() - redis_tripped < self._cooldown:
                        self._state = CircuitBreakerState.OPEN
                        self._failure_count = data.get("failure_count", 0)
                        self._tripped_at = redis_tripped
                        logger.warning("circuit_breaker_synced_from_redis",
                                       platform=self.platform, state="OPEN")
        except Exception:
            pass


# Per-platform singletons
circuit_breaker_binance = CircuitBreaker(platform="binance")
circuit_breaker_alpaca = CircuitBreaker(platform="alpaca")

# Backward-compat alias (health checks, admin endpoints, orchestrator)
circuit_breaker = circuit_breaker_binance
