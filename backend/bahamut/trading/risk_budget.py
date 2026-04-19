"""
Atomic cross-worker risk budget enforcement.

All workers MUST check and claim risk budget atomically via this module.
Uses Redis pipeline for atomic increment + check, preventing concurrent
workers from both claiming budget that exceeds the daily limit.
"""
import os
import time
import structlog

logger = structlog.get_logger()

_DAILY_LOSS_LIMIT_USD = float(os.environ.get("BAHAMUT_DAILY_LOSS_LIMIT", "500.00"))
_PORTFOLIO_DD_LIMIT_PCT = float(os.environ.get("BAHAMUT_PORTFOLIO_DD_LIMIT", "0.15"))


def _r():
    try:
        import redis
        return redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True, socket_connect_timeout=1,
        )
    except Exception:
        return None


def _utc_day_key_ttl() -> int:
    """Return seconds until end of current UTC day."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59)
    return max(60, int((end_of_day - now).total_seconds()))


def check_and_claim_budget(risk_amount: float, asset_class: str) -> tuple[bool, str]:
    """Atomically check if new trade fits within remaining daily budget
    and claim that portion. Returns (allowed, reason_if_not).

    Fails closed: no Redis = no trading.
    """
    r = _r()
    if not r:
        return False, "redis_unavailable_risk_budget"

    daily_key = "bahamut:risk:daily_pending_risk"
    realized_key = "bahamut:risk:daily_realized_loss"

    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(daily_key, risk_amount)
        pipe.get(realized_key)
        new_pending, realized_raw = pipe.execute()

        new_pending = float(new_pending)
        realized = float(realized_raw or 0)

        # Total at-risk = current open pending + unrecovered realized loss
        total_risk = new_pending + abs(realized)

        if total_risk > _DAILY_LOSS_LIMIT_USD:
            # Rollback the claim
            r.incrbyfloat(daily_key, -risk_amount)
            return False, (f"daily_risk_budget_exceeded: "
                           f"total={total_risk:.2f} limit={_DAILY_LOSS_LIMIT_USD}")

        r.expire(daily_key, _utc_day_key_ttl())
        return True, ""
    except Exception as e:
        logger.error("risk_budget_check_failed", error=str(e)[:100])
        # Fail closed on redis errors — try to rollback
        try:
            r.incrbyfloat(daily_key, -risk_amount)
        except Exception:
            pass
        return False, "risk_budget_check_error"


def release_pending(risk_amount: float) -> None:
    """Called when trade closes or open is rejected after claim. Rolls back pending."""
    r = _r()
    if not r:
        return
    try:
        r.incrbyfloat("bahamut:risk:daily_pending_risk", -risk_amount)
    except Exception:
        pass


def record_realized_loss(pnl: float) -> None:
    """Called when trade closes. Accumulates realized loss (only losses, positives ignored)."""
    if pnl >= 0:
        return
    r = _r()
    if not r:
        return
    try:
        r.incrbyfloat("bahamut:risk:daily_realized_loss", pnl)  # pnl is negative
        r.expire("bahamut:risk:daily_realized_loss", _utc_day_key_ttl())
    except Exception:
        pass


def get_budget_status() -> dict:
    """Return current daily budget state for dashboards."""
    r = _r()
    if not r:
        return {"error": "redis_unavailable"}
    try:
        return {
            "daily_pending_risk": float(r.get("bahamut:risk:daily_pending_risk") or 0),
            "daily_realized_loss": float(r.get("bahamut:risk:daily_realized_loss") or 0),
            "daily_loss_limit_usd": _DAILY_LOSS_LIMIT_USD,
        }
    except Exception as e:
        return {"error": str(e)[:100]}
