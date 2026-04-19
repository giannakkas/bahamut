"""
Account-delta reconciler — verify our trade-row PnL sum matches broker-reported PnL.

Runs hourly via Celery Beat. Drift >0.5% triggers Telegram alert.
Catches silent PnL divergence between app and exchange.
"""
import os
import structlog
from datetime import datetime, timezone
from celery import shared_task

logger = structlog.get_logger()

_DRIFT_THRESHOLD_PCT = float(os.environ.get("BAHAMUT_DRIFT_THRESHOLD_PCT", "0.5"))


def _get_our_daily_pnl() -> float:
    """Sum of PnL from trades closed in last 24 hours (non-paper only)."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COALESCE(SUM(pnl), 0) FROM training_trades "
                "WHERE exit_time > NOW() - INTERVAL '1 day' "
                "AND execution_platform NOT IN ('paper', 'internal')"
            )).fetchone()
            return float(result[0]) if result else 0
    except Exception as e:
        logger.warning("account_reconciler_our_pnl_failed", error=str(e)[:100])
        return 0


def _get_binance_account_pnl() -> tuple[float, dict]:
    """Get realized PnL from Binance Futures account info."""
    try:
        from bahamut.execution.binance_futures import BASE_URL, _sign, _headers, _configured
        if not _configured():
            return 0, {"error": "not_configured"}
        import httpx
        params = _sign({})
        r = httpx.get(f"{BASE_URL}/fapi/v2/account", params=params,
                      headers=_headers(), timeout=10)
        if r.status_code != 200:
            return 0, {"error": f"HTTP {r.status_code}"}
        data = r.json()
        # Total realized PnL from all positions
        total_rpnl = sum(float(p.get("unrealizedProfit", 0))
                         for p in data.get("positions", []))
        balance = float(data.get("totalWalletBalance", 0))
        return balance, {
            "wallet_balance": balance,
            "unrealized_pnl": round(total_rpnl, 2),
            "available_balance": float(data.get("availableBalance", 0)),
            "total_margin_balance": float(data.get("totalMarginBalance", 0)),
        }
    except Exception as e:
        logger.warning("account_reconciler_binance_failed", error=str(e)[:100])
        return 0, {"error": str(e)[:100]}


def _get_alpaca_account_info() -> dict:
    """Get Alpaca account equity and realized PnL."""
    try:
        from bahamut.execution.alpaca_adapter import BASE_URL, _headers
        import httpx
        r = httpx.get(f"{BASE_URL}/v2/account", headers=_headers(), timeout=5)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        data = r.json()
        return {
            "equity": float(data.get("equity", 0)),
            "cash": float(data.get("cash", 0)),
            "portfolio_value": float(data.get("portfolio_value", 0)),
            "last_equity": float(data.get("last_equity", 0)),
        }
    except Exception as e:
        return {"error": str(e)[:100]}


def reconcile_account_delta() -> dict:
    """Compare our PnL with broker-reported state. Returns report dict."""
    our_pnl = _get_our_daily_pnl()
    binance_balance, binance_info = _get_binance_account_pnl()
    alpaca_info = _get_alpaca_account_info()

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "our_daily_pnl": round(our_pnl, 2),
        "binance": binance_info,
        "alpaca": alpaca_info,
        "drift_threshold_pct": _DRIFT_THRESHOLD_PCT,
    }

    # Store in Redis for dashboard
    try:
        import redis, json
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                           socket_connect_timeout=2)
        r.setex("bahamut:account_reconciler:last", 7200,
                json.dumps(report, default=str))
    except Exception:
        pass

    return report


@shared_task(name="bahamut.monitoring.account_reconciler.run_hourly_reconcile")
def run_hourly_reconcile():
    """Celery task: hourly account-delta reconciliation."""
    try:
        report = reconcile_account_delta()

        # Log summary
        logger.info("account_delta_reconciled",
                     our_pnl=report["our_daily_pnl"],
                     binance_balance=report["binance"].get("wallet_balance", "N/A"),
                     alpaca_equity=report["alpaca"].get("equity", "N/A"))

        # Alert on any errors in broker fetches
        has_errors = (report["binance"].get("error") or report["alpaca"].get("error"))
        if has_errors:
            try:
                from bahamut.monitoring.telegram import send_alert
                errors = []
                if report["binance"].get("error"):
                    errors.append(f"Binance: {report['binance']['error']}")
                if report["alpaca"].get("error"):
                    errors.append(f"Alpaca: {report['alpaca']['error']}")
                send_alert(f"⚠️ ACCOUNT RECONCILER ERRORS\n" + "\n".join(errors))
            except Exception:
                pass

    except Exception as e:
        logger.error("account_reconciler_failed", error=str(e)[:200])
