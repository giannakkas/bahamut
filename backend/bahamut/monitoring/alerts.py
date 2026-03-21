"""
Bahamut Alert Engine — Actionable trading alerts with throttling.

Alert levels:
  CRITICAL — immediate action needed (Telegram + Email)
  WARNING  — attention required (Telegram)
  INFO     — informational (log + dashboard only)

Throttling: same alert type max once per 30 min via Redis.
"""
import os
import time
import json
import structlog
from datetime import datetime, timezone
from typing import Optional

logger = structlog.get_logger()

# ── Alert storage (in-memory fallback if no Redis) ──
_alert_history: list[dict] = []
_last_fired: dict[str, float] = {}  # alert_key → timestamp
THROTTLE_SECONDS = 1800  # 30 minutes


def _get_redis():
    """Try to get Redis connection for throttling."""
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def _is_throttled(alert_key: str) -> bool:
    """Check if this alert was fired recently."""
    r = _get_redis()
    if r:
        try:
            last = r.get(f"bahamut:alert:throttle:{alert_key}")
            if last and time.time() - float(last) < THROTTLE_SECONDS:
                return True
            return False
        except Exception:
            pass

    # Fallback to in-memory
    last = _last_fired.get(alert_key, 0)
    return time.time() - last < THROTTLE_SECONDS


def _mark_fired(alert_key: str):
    """Record that this alert was just fired."""
    now = time.time()
    r = _get_redis()
    if r:
        try:
            r.setex(f"bahamut:alert:throttle:{alert_key}", THROTTLE_SECONDS, str(now))
        except Exception:
            pass
    _last_fired[alert_key] = now


def fire_alert(level: str, title: str, message: str, key: str = "",
               data: dict = None):
    """
    Fire an alert if not throttled.

    level: CRITICAL / WARNING / INFO
    title: short summary
    message: detailed text
    key: throttle key (same key = throttled together)
    data: optional structured data
    """
    alert_key = key or f"{level}:{title}"

    if level != "INFO" and _is_throttled(alert_key):
        logger.debug("alert_throttled", key=alert_key)
        return

    alert = {
        "level": level,
        "title": title,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data or {},
    }

    # Store in history
    _alert_history.append(alert)
    if len(_alert_history) > 200:
        _alert_history.pop(0)

    # Log
    log_fn = logger.critical if level == "CRITICAL" else (
        logger.warning if level == "WARNING" else logger.info)
    log_fn("alert_fired", level=level, title=title)

    # Dispatch
    if level == "CRITICAL":
        _send_telegram(alert)
        _send_email(alert)
        _mark_fired(alert_key)
    elif level == "WARNING":
        _send_telegram(alert)
        _mark_fired(alert_key)
    # INFO = dashboard only (already stored in history)

    # Store in Redis for dashboard
    _store_alert(alert)


def _send_telegram(alert: dict):
    try:
        from bahamut.monitoring.telegram import send_telegram_alert
        send_telegram_alert(alert["message"], alert["level"], alert["title"])
    except Exception as e:
        logger.error("telegram_send_failed", error=str(e))


def _send_email(alert: dict):
    try:
        from bahamut.monitoring.email import send_email_alert
        subject = f"[{alert['level']}] Bahamut: {alert['title']}"
        send_email_alert(subject, alert["message"])
    except Exception as e:
        logger.error("email_send_failed", error=str(e))


def _store_alert(alert: dict):
    """Store in Redis for dashboard retrieval."""
    r = _get_redis()
    if r:
        try:
            r.lpush("bahamut:alerts", json.dumps(alert))
            r.ltrim("bahamut:alerts", 0, 199)
        except Exception:
            pass


def get_recent_alerts(limit: int = 50) -> list[dict]:
    """Get recent alerts for dashboard."""
    r = _get_redis()
    if r:
        try:
            raw = r.lrange("bahamut:alerts", 0, limit - 1)
            return [json.loads(x) for x in raw]
        except Exception:
            pass
    return list(reversed(_alert_history[-limit:]))


# ═══════════════════════════════════════════════════════
# ALERT RULES — check_alerts() called from orchestrator
# ═══════════════════════════════════════════════════════

def check_alerts(portfolio_state: dict, engine_state: dict = None):
    """
    Run all alert rules against current system state.
    Called after each orchestrator cycle.
    """
    equity = portfolio_state.get("total_equity", 100000)
    initial = portfolio_state.get("initial_capital", 100000)
    dd_pct = portfolio_state.get("drawdown_pct", 0)
    open_risk = portfolio_state.get("total_open_risk", 0)
    open_risk_pct = open_risk / max(1, equity) * 100
    kill_switch = portfolio_state.get("kill_switch", False)

    # ── CRITICAL ──

    if dd_pct > 8:
        fire_alert("CRITICAL", "Drawdown exceeded 8%",
                   f"Current drawdown: {dd_pct:.1f}%\nEquity: ${equity:,.0f}\n"
                   f"Action: Review positions immediately.",
                   key="dd_critical")

    if open_risk_pct > 5:
        fire_alert("CRITICAL", "Open risk exceeded 5%",
                   f"Open risk: {open_risk_pct:.1f}% (${open_risk:,.0f})\n"
                   f"Action: Consider reducing exposure.",
                   key="risk_critical")

    if kill_switch:
        fire_alert("CRITICAL", "Kill switch activated",
                   f"Portfolio drawdown triggered kill switch.\n"
                   f"Drawdown: {dd_pct:.1f}%\nAll trading halted.",
                   key="kill_switch")

    # ── WARNING ──

    if 5 < dd_pct <= 8:
        fire_alert("WARNING", "Drawdown elevated",
                   f"Current drawdown: {dd_pct:.1f}%\nMonitor closely.",
                   key="dd_warning")

    if 4 < open_risk_pct <= 5:
        fire_alert("WARNING", "Open risk approaching limit",
                   f"Open risk: {open_risk_pct:.1f}% (limit: 5%)",
                   key="risk_warning")

    # Strategy-level checks
    sleeves = portfolio_state.get("sleeves", {})
    for name, sleeve in sleeves.items():
        trades = sleeve.get("trades", 0)
        wins = sleeve.get("wins", 0)
        if trades >= 10:
            wr = wins / trades * 100
            if wr < 30:
                fire_alert("WARNING", f"{name} win rate critically low",
                           f"{name}: {wr:.0f}% WR over {trades} trades",
                           key=f"wr_low_{name}")

    # Engine-level checks
    if engine_state:
        errors = engine_state.get("execution_errors", 0)
        dupes = engine_state.get("duplicate_signals", 0)
        if errors > 0:
            fire_alert("CRITICAL", "Execution errors detected",
                       f"{errors} execution errors in current session",
                       key="exec_errors")
        if dupes > 5:
            fire_alert("WARNING", "High duplicate signal count",
                       f"{dupes} duplicate signals rejected",
                       key="dupes_high")


def fire_trade_alert(trade: dict, action: str = "closed"):
    """Fire INFO alert for trade open/close events."""
    asset = trade.get("asset", "?")
    strategy = trade.get("strategy", "?")
    direction = trade.get("direction", trade.get("dir", "?"))

    if action == "opened":
        entry = trade.get("entry_price", trade.get("entry", 0))
        fire_alert("INFO", f"Trade opened: {asset}",
                   f"{strategy} {direction} {asset} @ ${entry:,.2f}",
                   key=f"trade_open_{asset}_{strategy}")
    else:
        pnl = trade.get("pnl", 0)
        reason = trade.get("exit_reason", trade.get("reason", "?"))
        emoji = "✅" if pnl > 0 else "❌"
        fire_alert("INFO", f"Trade closed: {asset} {emoji}",
                   f"{strategy} {direction} {asset}\n"
                   f"PnL: ${pnl:+,.2f} | Reason: {reason}",
                   key=f"trade_close_{asset}_{strategy}_{time.time():.0f}")


def fire_regime_change(asset: str, old_regime: str, new_regime: str):
    """Fire INFO alert for regime changes."""
    emoji = "📈" if new_regime == "TREND" else ("🔻" if new_regime == "CRASH" else "↔️")
    fire_alert("INFO", f"Regime change: {asset}",
               f"{asset}: {old_regime} → {new_regime} {emoji}",
               key=f"regime_{asset}_{new_regime}")
