"""
Bahamut.AI — Real Balance Tracker

Fetches actual account balance from brokers and computes
available margin for position sizing.

Replaces the virtual $100K portfolio with real numbers.

Usage:
  from bahamut.execution.balance import get_real_balance, get_available_risk

  balance = get_real_balance()
  # {
  #   "binance_futures": {"total": 10000, "available": 8500, "margin_used": 1500},
  #   "alpaca": {"equity": 25000, "cash": 20000, "buying_power": 40000},
  #   "combined_usd": 35000,
  # }

  # How much can we risk on a single trade?
  risk = get_available_risk(risk_pct=0.02)
  # {"max_risk_usd": 700, "source": "real_balance", "combined_equity": 35000}
"""
import os
import time
import structlog

logger = structlog.get_logger()

# Cache to avoid hammering broker APIs
_balance_cache: dict = {}
_balance_cache_at: float = 0
_CACHE_TTL = 60  # 1 minute


def get_real_balance(force_refresh: bool = False) -> dict:
    """Fetch actual account balance from all configured brokers.

    Returns combined balance in USD. Cached for 60 seconds.
    Falls back to virtual balance if no brokers configured.
    """
    global _balance_cache, _balance_cache_at

    if not force_refresh and _balance_cache and (time.time() - _balance_cache_at) < _CACHE_TTL:
        return _balance_cache

    result = {
        "binance_futures": None,
        "alpaca": None,
        "combined_usd": 0,
        "source": "virtual",
        "fetched_at": time.time(),
    }

    combined = 0

    # Binance Futures
    try:
        from bahamut.execution.binance_futures import get_account, _configured
        if _configured():
            account = get_account()
            if account:
                total = float(account.get("totalWalletBalance", 0) or 0)
                available = float(account.get("availableBalance", 0) or 0)
                margin = float(account.get("totalInitialMargin", 0) or 0)
                unrealized = float(account.get("totalUnrealizedProfit", 0) or 0)
                result["binance_futures"] = {
                    "total_wallet": round(total, 2),
                    "available": round(available, 2),
                    "margin_used": round(margin, 2),
                    "unrealized_pnl": round(unrealized, 2),
                    "equity": round(total + unrealized, 2),
                }
                combined += total + unrealized
                result["source"] = "real"
    except Exception as e:
        logger.debug("balance_binance_fetch_failed", error=str(e)[:100])

    # Alpaca
    try:
        from bahamut.execution.alpaca_adapter import get_account as alpaca_account
        acc = alpaca_account()
        if acc:
            equity = float(acc.get("equity", 0) or 0)
            cash = float(acc.get("cash", 0) or 0)
            buying = float(acc.get("buying_power", 0) or 0)
            result["alpaca"] = {
                "equity": round(equity, 2),
                "cash": round(cash, 2),
                "buying_power": round(buying, 2),
            }
            combined += equity
            result["source"] = "real"
    except Exception as e:
        logger.debug("balance_alpaca_fetch_failed", error=str(e)[:100])

    # No virtual fallback in live/hybrid mode — report broker_unavailable
    if combined <= 0:
        try:
            from bahamut.config_assets import TRAINING_VIRTUAL_CAPITAL
            mode = os.environ.get("BAHAMUT_TRADING_MODE", "paper").lower()
            if mode == "paper":
                combined = TRAINING_VIRTUAL_CAPITAL
                result["source"] = "virtual"
            else:
                result["source"] = "broker_unavailable"
        except Exception:
            result["source"] = "broker_unavailable"

    result["combined_usd"] = round(combined, 2)

    # Cache
    _balance_cache = result
    _balance_cache_at = time.time()

    # Also persist to Redis for cross-worker visibility
    try:
        import redis, json
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                           socket_connect_timeout=2)
        r.setex("bahamut:balance:latest",
                120,
                json.dumps(result, default=str))
    except Exception:
        pass

    return result


def get_available_risk(asset_class: str = "", risk_pct: float = 0.02) -> dict:
    """Compute max risk per trade based on the broker for this asset class.

    Crypto → Binance Futures available balance (no unrealized PnL).
    Stock  → Alpaca cash.
    If broker data unavailable, returns max_risk_usd=0.

    Args:
        asset_class: "crypto" or "stock"
        risk_pct: fraction of available capital to risk per trade (default 2%)
    """
    balance = get_real_balance()

    if asset_class == "crypto":
        bf = balance.get("binance_futures")
        if bf and bf.get("available", 0) > 0:
            return {
                "max_risk_usd": round(bf["available"] * risk_pct, 2),
                "risk_pct": risk_pct,
                "combined_equity": bf["available"],
                "source": "real_binance",
            }
        return {
            "max_risk_usd": 0,
            "risk_pct": risk_pct,
            "combined_equity": 0,
            "source": "broker_unavailable",
            "reason": "binance_futures_unavailable",
        }

    if asset_class == "stock":
        alp = balance.get("alpaca")
        if alp and alp.get("cash", 0) > 0:
            return {
                "max_risk_usd": round(alp["cash"] * risk_pct, 2),
                "risk_pct": risk_pct,
                "combined_equity": alp["cash"],
                "source": "real_alpaca",
            }
        return {
            "max_risk_usd": 0,
            "risk_pct": risk_pct,
            "combined_equity": 0,
            "source": "broker_unavailable",
            "reason": "alpaca_unavailable",
        }

    # Fallback for other asset classes: use combined (paper mode safe)
    equity = balance.get("combined_usd", 0)
    return {
        "max_risk_usd": round(equity * risk_pct, 2),
        "risk_pct": risk_pct,
        "combined_equity": equity,
        "source": balance.get("source", "unknown"),
    }


def get_margin_usage() -> dict:
    """Get current margin usage across all brokers."""
    balance = get_real_balance()
    result = {"total_margin_used": 0, "total_equity": balance["combined_usd"]}

    bf = balance.get("binance_futures")
    if bf:
        result["binance_margin_used"] = bf.get("margin_used", 0)
        result["binance_margin_pct"] = round(
            bf["margin_used"] / max(1, bf["equity"]) * 100, 1
        ) if bf.get("equity", 0) > 0 else 0
        result["total_margin_used"] += bf.get("margin_used", 0)

    alp = balance.get("alpaca")
    if alp:
        equity = alp.get("equity", 0)
        cash = alp.get("cash", 0)
        positions_value = equity - cash
        result["alpaca_positions_value"] = round(positions_value, 2)
        result["alpaca_usage_pct"] = round(
            positions_value / max(1, equity) * 100, 1
        ) if equity > 0 else 0

    return result
