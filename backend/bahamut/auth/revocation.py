"""
Bahamut.AI — Token Revocation

Simple Redis-based token blacklist.
On logout, the access token's JTI is added to a Redis set.
On each authenticated request, the JTI is checked.

Tokens auto-expire from Redis when their JWT expiry passes.
Falls back to DB-based revocation if Redis unavailable.
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
    """Revoke a token by adding its JTI to the blacklist.

    Stores in Redis with TTL matching token expiry (auto-cleanup).
    Falls back to DB if Redis unavailable.
    """
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

    # Fallback: write to DB
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

    Checks Redis first (fast path), falls back to DB.
    Returns False on error (fail-open for auth — fail-closed would lock everyone out).
    """
    if not jti:
        return False

    # Fast path: Redis
    try:
        from bahamut.shared.redis_client import redis_manager
        if redis_manager.redis:
            key = f"{REDIS_REVOKE_PREFIX}{jti}"
            result = await redis_manager.redis.get(key)
            if result is not None:
                return True
            # If not in Redis, it's either not revoked or Redis was down during revocation
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
        return row is not None
    except Exception as e:
        logger.warning("db_revoke_check_failed", error=str(e))
        return False  # fail-open: don't lock out users if revocation check fails


async def cleanup_expired_tokens() -> int:
    """Remove expired revoked tokens from DB. Redis auto-expires via TTL."""
    try:
        from bahamut.db.query import run_transaction
        run_transaction("DELETE FROM revoked_tokens WHERE expires_at < NOW()")
        return 0  # count not easily available with raw SQL
    except Exception as e:
        logger.warning("revoke_cleanup_failed", error=str(e))
        return 0
