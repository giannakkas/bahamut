"""
Bahamut.AI — Token Revocation (Phase 2.5 Hardened)

Redis-first + DB fallback token blacklist.
If BOTH fail: fail-closed with degraded flag + critical log.

Rules:
  1. Redis available → use Redis (fast path)
  2. Redis fails → fallback to DB
  3. Both fail → BLOCK access + mark auth_revocation degraded + log CRITICAL
"""
import uuid
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

REDIS_REVOKE_PREFIX = "bahamut:revoked:"


def generate_jti() -> str:
    """Generate a unique JWT ID for token revocation tracking."""
    return str(uuid.uuid4())


async def revoke_token(jti: str, expires_at: datetime, user_id: str = None) -> bool:
    """Revoke a token by adding its JTI to the blacklist."""
    # Try Redis first
    try:
        from bahamut.shared.redis_client import redis_manager
        if redis_manager.redis:
            ttl = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
            key = f"{REDIS_REVOKE_PREFIX}{jti}"
            await redis_manager.redis.set(key, "1", ex=ttl)
            logger.info("token_revoked", jti=jti[:8], ttl=ttl)
            return True
    except Exception as e:
        logger.warning("redis_revoke_failed", jti=jti[:8], error=str(e))

    # Fallback: DB
    try:
        from bahamut.db.query import run_transaction
        run_transaction(
            "INSERT INTO revoked_tokens (jti, user_id, expires_at) VALUES (:j, :u, :e) "
            "ON CONFLICT (jti) DO NOTHING",
            {"j": jti, "u": user_id, "e": expires_at}
        )
        return True
    except Exception as e:
        logger.error("db_revoke_failed", jti=jti[:8], error=str(e))
        return False


async def is_token_revoked(jti: str) -> bool:
    """Check if a token JTI has been revoked.

    FAIL-CLOSED: if both Redis and DB are unavailable, returns True
    (blocks access) and marks auth_revocation as degraded.
    """
    if not jti:
        return False

    # Fast path: Redis
    redis_checked = False
    try:
        from bahamut.shared.redis_client import redis_manager
        if redis_manager.redis:
            key = f"{REDIS_REVOKE_PREFIX}{jti}"
            result = await redis_manager.redis.get(key)
            redis_checked = True
            if result is not None:
                return True
            # Token not in Redis revocation list — it's valid
            return False
    except Exception as e:
        logger.warning("redis_revoke_check_failed", error=str(e))

    # Slow path: DB
    try:
        from bahamut.db.query import run_query_one
        row = run_query_one(
            "SELECT 1 FROM revoked_tokens WHERE jti = :j AND expires_at > NOW()",
            {"j": jti}
        )
        # If we get here, DB is working — clear any degraded flag
        _clear_auth_degraded()
        return row is not None
    except Exception as e:
        logger.warning("db_revoke_check_failed", error=str(e))

    # BOTH FAILED — fail-closed: block access, mark degraded
    logger.critical("auth_revocation_unavailable",
                    msg="Both Redis and DB revocation checks failed — blocking access for safety",
                    jti=jti[:8])
    _mark_auth_degraded("Both Redis and DB revocation checks unavailable")
    return True  # FAIL-CLOSED


def _mark_auth_degraded(reason: str) -> None:
    """Mark auth_revocation subsystem as degraded."""
    try:
        from bahamut.shared.degraded import mark_degraded
        mark_degraded("auth.revocation", reason, ttl=120)
    except Exception:
        pass  # best effort


def _clear_auth_degraded() -> None:
    """Clear auth_revocation degraded flag when service recovers."""
    try:
        from bahamut.shared.degraded import clear_degraded
        clear_degraded("auth.revocation")
    except Exception:
        pass


async def cleanup_expired_tokens() -> int:
    """Remove expired revoked tokens from DB. Redis auto-expires via TTL."""
    try:
        from bahamut.db.query import run_transaction
        run_transaction("DELETE FROM revoked_tokens WHERE expires_at < NOW()")
        return 0
    except Exception as e:
        logger.warning("revoke_cleanup_failed", error=str(e))
        return 0
