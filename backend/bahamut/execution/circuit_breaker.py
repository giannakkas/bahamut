"""
Bahamut.AI — Execution Circuit Breaker

Prevents API bans by stopping execution after consecutive failures.

States:
  CLOSED  — normal operation, orders flow through
  OPEN    — tripped after N failures, all orders blocked for cooldown_sec
  HALF_OPEN — after cooldown, allow ONE probe order to test recovery

Usage:
  from bahamut.execution.circuit_breaker import circuit_breaker

  if not circuit_breaker.allow_execution():
      return None  # blocked, don't submit

  try:
      result = submit_to_broker(...)
      circuit_breaker.record_success()
  except Exception:
      circuit_breaker.record_failure()

Configuration via env vars:
  CIRCUIT_BREAKER_THRESHOLD=5      # failures before tripping
  CIRCUIT_BREAKER_COOLDOWN=300     # seconds to stay open
  CIRCUIT_BREAKER_HALF_OPEN_MAX=1  # probe orders in half-open
"""
import os
import time
import threading
import structlog

logger = structlog.get_logger()


class CircuitBreakerState:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Thread-safe circuit breaker for broker execution.

    State is in-memory (resets on deploy) + mirrored to Redis for
    cross-worker visibility. After a Railway restart, the breaker
    starts CLOSED — conservative choice is to try once and fail fast
    rather than staying blocked.
    """

    def __init__(self):
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

        # Try to restore state from Redis
        self._restore_from_redis()

    def allow_execution(self) -> bool:
        """Check if execution is allowed. Returns True if the order should proceed."""
        with self._lock:
            now = time.time()

            if self._state == CircuitBreakerState.CLOSED:
                return True

            if self._state == CircuitBreakerState.OPEN:
                # Check if cooldown has elapsed
                if now - self._tripped_at >= self._cooldown:
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_attempts = 0
                    logger.info("circuit_breaker_half_open",
                                cooldown=self._cooldown,
                                failures=self._failure_count)
                    self._persist_to_redis()
                    # Allow the first probe
                    self._half_open_attempts += 1
                    return True
                else:
                    remaining = int(self._cooldown - (now - self._tripped_at))
                    logger.debug("circuit_breaker_blocked",
                                 remaining_seconds=remaining)
                    return False

            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_attempts < self._half_open_max:
                    self._half_open_attempts += 1
                    return True
                return False

            return False

    def record_success(self):
        """Record a successful execution. Resets the breaker if in HALF_OPEN."""
        with self._lock:
            self._success_count += 1
            if self._state == CircuitBreakerState.HALF_OPEN:
                # Recovery confirmed — close the breaker
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                logger.info("circuit_breaker_recovered",
                            state="CLOSED",
                            total_successes=self._success_count)
            elif self._state == CircuitBreakerState.CLOSED:
                # Consecutive success resets failure counter
                self._failure_count = 0
            self._persist_to_redis()

    def record_failure(self, error: str = ""):
        """Record a failed execution. Trips the breaker after threshold."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitBreakerState.HALF_OPEN:
                # Probe failed — back to OPEN
                self._state = CircuitBreakerState.OPEN
                self._tripped_at = time.time()
                logger.error("circuit_breaker_probe_failed",
                             error=error[:200],
                             cooldown=self._cooldown)

            elif self._state == CircuitBreakerState.CLOSED:
                if self._failure_count >= self._threshold:
                    self._state = CircuitBreakerState.OPEN
                    self._tripped_at = time.time()
                    logger.error("circuit_breaker_TRIPPED",
                                 failures=self._failure_count,
                                 threshold=self._threshold,
                                 cooldown_seconds=self._cooldown,
                                 last_error=error[:200])
            self._persist_to_redis()

    def get_status(self) -> dict:
        """Current breaker status for diagnostics."""
        with self._lock:
            now = time.time()
            remaining = 0
            if self._state == CircuitBreakerState.OPEN:
                remaining = max(0, int(self._cooldown - (now - self._tripped_at)))
            return {
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
        """Manual reset — use from admin panel when broker is confirmed back."""
        with self._lock:
            prev = self._state
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._half_open_attempts = 0
            self._persist_to_redis()
            logger.warning("circuit_breaker_force_reset",
                           previous_state=prev)

    # ─────────────────────────────────────────
    # Redis persistence (cross-worker visibility)
    # ─────────────────────────────────────────

    def _persist_to_redis(self):
        try:
            import redis, json
            r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                               socket_connect_timeout=1)
            r.setex("bahamut:circuit_breaker",
                    self._cooldown + 60,
                    json.dumps({
                        "state": self._state,
                        "failure_count": self._failure_count,
                        "tripped_at": self._tripped_at,
                    }))
        except Exception:
            pass

    def _restore_from_redis(self):
        try:
            import redis, json
            r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                               socket_connect_timeout=1)
            raw = r.get("bahamut:circuit_breaker")
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
                                       failures=self._failure_count,
                                       remaining=int(self._cooldown - (time.time() - tripped)))
        except Exception:
            pass


# Singleton instance
circuit_breaker = CircuitBreaker()
