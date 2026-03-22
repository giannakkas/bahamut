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


_ACTION_ADVICE = {
    # ── DATA ──
    "Stale data": {
        "advice": "Safe to ignore. System is using cached prices — not live market data.",
        "fix": "Set TWELVE_DATA_KEY in Railway → backend → Variables to get live BTC/ETH prices.",
        "severity": "low",
    },
    "Data error": {
        "advice": "Data feed is down or returning errors. System will retry automatically.",
        "fix": "Check Twelve Data API status. If persistent, verify TWELVE_DATA_KEY is valid.",
        "severity": "medium",
    },
    # ── RISK ──
    "Drawdown exceeded 8%": {
        "advice": "Portfolio has lost more than 8% from peak. Review open positions immediately.",
        "fix": "Consider closing losing positions or activating kill switch.",
        "severity": "high",
    },
    "Drawdown elevated": {
        "advice": "Drawdown is between 5-8%. Not critical yet but monitor closely.",
        "fix": "No action needed unless it continues rising. Check open positions.",
        "severity": "medium",
    },
    "Open risk exceeded 5%": {
        "advice": "Total risk from open positions exceeds 5% of equity.",
        "fix": "Reduce position sizes or close some positions to lower risk.",
        "severity": "high",
    },
    "Open risk approaching limit": {
        "advice": "Open risk is approaching the 5% limit. Monitor but no action needed yet.",
        "fix": "Avoid opening new positions until risk decreases.",
        "severity": "medium",
    },
    "Kill switch activated": {
        "advice": "All trading has been halted. No new trades will be opened.",
        "fix": "Review what triggered it. Resume trading via Dashboard → Resume when ready.",
        "severity": "high",
    },
    # ── EXECUTION ──
    "Execution errors detected": {
        "advice": "Trade execution is failing. Orders may not be placed correctly.",
        "fix": "Check Railway backend logs for error details.",
        "severity": "high",
    },
    "Multiple cycle errors": {
        "advice": "The trading engine is crashing repeatedly.",
        "fix": "Check Railway backend logs. May need a redeploy.",
        "severity": "high",
    },
    "High cycle skip rate": {
        "advice": "Many cycles are being skipped — engine may be overloaded.",
        "fix": "Check Redis connection and backend memory usage.",
        "severity": "medium",
    },
    "High duplicate signal count": {
        "advice": "Same signals being generated repeatedly — possible logic issue.",
        "fix": "Safe to ignore unless trades are duplicated. Check position count.",
        "severity": "low",
    },
    # ── STRATEGY ──
    "win rate critically low": {
        "advice": "Strategy performance is poor. May need review.",
        "fix": "Check if market regime has changed. Consider disabling the strategy temporarily.",
        "severity": "medium",
    },
    # ── TRADES ──
    "Trade opened": {
        "advice": "New position opened. Monitor entry and risk levels.",
        "fix": "No action needed — system managing SL/TP automatically.",
        "severity": "info",
    },
    "Trade closed": {
        "advice": "Position closed. Review P&L and exit reason.",
        "fix": "No action needed — this is informational.",
        "severity": "info",
    },
    # ── REGIME ──
    "Regime change": {
        "advice": "Market regime shifted. Strategy behavior may change.",
        "fix": "No action needed — strategies adapt automatically to regimes.",
        "severity": "info",
    },
}


def _get_action_advice(title: str, level: str, message: str) -> dict:
    """Get actionable advice for an alert based on its title."""
    # Try exact match first
    if title in _ACTION_ADVICE:
        return _ACTION_ADVICE[title]

    # Try partial match
    for pattern, advice in _ACTION_ADVICE.items():
        if pattern.lower() in title.lower():
            return advice

    # Default advice by level
    if level == "CRITICAL":
        return {"advice": "Requires immediate attention.", "fix": "Review dashboard and check backend logs.", "severity": "high"}
    elif level == "WARNING":
        return {"advice": "Monitor this situation.", "fix": "Check dashboard for details.", "severity": "medium"}
    else:
        return {"advice": "Informational — no action needed.", "fix": "", "severity": "info"}


def fire_alert(level: str, title: str, message: str, key: str = "",
               data: dict = None):
    """
    Fire an alert with deduplication.

    Same key = update existing alert (increment count, update timestamp).
    Different key = new alert.
    """
    alert_key = key or f"{level}:{title}"
    now = datetime.now(timezone.utc).isoformat()

    if level != "INFO" and _is_throttled(alert_key):
        # Still update the occurrence count even if throttled
        _update_occurrence(alert_key, now)
        return

    alert = {
        "level": level,
        "title": title,
        "message": message,
        "timestamp": now,
        "first_seen": now,
        "last_seen": now,
        "occurrences": 1,
        "status": "ACTIVE",
        "key": alert_key,
        "data": data or {},
        "action": _get_action_advice(title, level, message),
    }

    # Store/update in-memory
    _upsert_alert(alert_key, alert)

    # Log
    log_fn = logger.critical if level == "CRITICAL" else (
        logger.warning if level == "WARNING" else logger.info)
    log_fn("alert_fired", level=level, title=title)

    # Dispatch notifications (only on first occurrence or after throttle expires)
    if level in ("CRITICAL", "WARNING"):
        _send_telegram(alert)
        _send_email_templated(alert)
        _mark_fired(alert_key)
    elif level == "INFO":
        try:
            from bahamut.admin.config import get_config
            if get_config("notify.level.info", False):
                _send_email_templated(alert)
        except Exception:
            pass

    # Store in Redis
    _store_alert_dedup(alert_key, alert)


def _send_telegram(alert: dict):
    try:
        from bahamut.monitoring.telegram import send_telegram_alert
        send_telegram_alert(alert["message"], alert["level"], alert["title"])
    except Exception as e:
        logger.error("telegram_send_failed", error=str(e))


def _send_email_templated(alert: dict):
    """Send email using HTML templates based on alert level."""
    try:
        from bahamut.monitoring.email_templates import critical_template, warning_template, info_template
        from bahamut.monitoring.email import send_email_alert

        level = alert.get("level", "INFO")
        title = alert.get("title", "")
        message = alert.get("message", "")
        data = alert.get("data", {})

        if level == "CRITICAL":
            subject, html = critical_template(title, message, data)
        elif level == "WARNING":
            subject, html = warning_template(title, message, data)
        else:
            subject, html = info_template(title, message, data)

        _send_email_html(subject, html)
    except Exception as e:
        logger.error("email_template_failed", error=str(e))
        # Fallback to plain text
        _send_email(alert)


def _send_email_html(subject: str, html: str):
    """Send an HTML email via the email module."""
    try:
        from bahamut.monitoring.email import _get_config
        import json, urllib.request

        cfg = _get_config()
        if not cfg.get("enabled") or not cfg.get("api_key") or not cfg.get("to_email"):
            return

        from_email = cfg.get("from_email") or "noreply@bahamut.ai"
        payload = {
            "sender": {"name": "Bahamut Alerts", "email": from_email},
            "to": [{"email": cfg["to_email"]}],
            "subject": subject,
            "htmlContent": html,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", data=data, method="POST")
        req.add_header("accept", "application/json")
        req.add_header("content-type", "application/json")
        req.add_header("api-key", cfg["api_key"])
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("email_html_sent", subject=subject)
    except Exception as e:
        logger.error("email_html_failed", error=str(e))


def _send_email(alert: dict):
    try:
        from bahamut.monitoring.email import send_email_alert
        subject = f"[{alert['level']}] Bahamut: {alert['title']}"
        send_email_alert(subject, alert["message"])
    except Exception as e:
        logger.error("email_send_failed", error=str(e))


def _upsert_alert(alert_key: str, alert: dict):
    """Update existing alert in memory or add new one."""
    for i, existing in enumerate(_alert_history):
        if existing.get("key") == alert_key and existing.get("status") == "ACTIVE":
            # Update existing
            _alert_history[i]["last_seen"] = alert["last_seen"]
            _alert_history[i]["occurrences"] = existing.get("occurrences", 1) + 1
            _alert_history[i]["message"] = alert["message"]
            return
    # New alert
    _alert_history.append(alert)
    if len(_alert_history) > 200:
        _alert_history.pop(0)


def _update_occurrence(alert_key: str, timestamp: str):
    """Update occurrence count for a throttled alert."""
    for alert in _alert_history:
        if alert.get("key") == alert_key and alert.get("status") == "ACTIVE":
            alert["last_seen"] = timestamp
            alert["occurrences"] = alert.get("occurrences", 1) + 1
            break
    # Also update in Redis
    r = _get_redis()
    if r:
        try:
            raw = r.hget("bahamut:active_alerts", alert_key)
            if raw:
                existing = json.loads(raw)
                existing["last_seen"] = timestamp
                existing["occurrences"] = existing.get("occurrences", 1) + 1
                r.hset("bahamut:active_alerts", alert_key, json.dumps(existing))
        except Exception:
            pass


def _store_alert_dedup(alert_key: str, alert: dict):
    """Store/update alert in Redis with deduplication."""
    r = _get_redis()
    if r:
        try:
            existing_raw = r.hget("bahamut:active_alerts", alert_key)
            if existing_raw:
                existing = json.loads(existing_raw)
                alert["first_seen"] = existing.get("first_seen", alert["first_seen"])
                alert["occurrences"] = existing.get("occurrences", 0) + 1
            r.hset("bahamut:active_alerts", alert_key, json.dumps(alert))
        except Exception:
            pass


def resolve_alert(alert_key: str, reason: str = "condition cleared"):
    """Mark an alert as RESOLVED. Called when the condition that triggered it clears."""
    now = datetime.now(timezone.utc).isoformat()

    # Update in-memory
    for alert in _alert_history:
        if alert.get("key") == alert_key and alert.get("status") == "ACTIVE":
            alert["status"] = "RESOLVED"
            alert["resolved_at"] = now
            alert["resolve_reason"] = reason

    # Update in Redis
    r = _get_redis()
    if r:
        try:
            raw = r.hget("bahamut:active_alerts", alert_key)
            if raw:
                alert = json.loads(raw)
                alert["status"] = "RESOLVED"
                alert["resolved_at"] = now
                alert["resolve_reason"] = reason
                # Move from active to resolved
                r.hset("bahamut:active_alerts", alert_key, json.dumps(alert))
        except Exception:
            pass


def get_recent_alerts(limit: int = 50) -> list[dict]:
    """Get recent alerts for dashboard — deduped, sorted by last_seen."""
    r = _get_redis()
    if r:
        try:
            raw = r.hgetall("bahamut:active_alerts")
            if raw:
                alerts = []
                for k, v in raw.items():
                    try:
                        alert = json.loads(v)
                        alerts.append(alert)
                    except Exception:
                        pass
                # Sort by last_seen descending
                alerts.sort(key=lambda a: a.get("last_seen", ""), reverse=True)
                return alerts[:limit]
        except Exception:
            pass
    # Fallback: in-memory, deduped by key
    seen = set()
    result = []
    for alert in reversed(_alert_history):
        key = alert.get("key", alert.get("title", ""))
        if key not in seen:
            seen.add(key)
            result.append(alert)
        if len(result) >= limit:
            break
    return result


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

    # Data health checks — auto-resolve when data recovers
    try:
        from bahamut.data.live_data import get_data_status
        for asset, info in get_data_status().items():
            status = info.get("status", "") if isinstance(info, dict) else str(info)
            detail = info.get("detail", "") if isinstance(info, dict) else ""
            if status == "ERROR":
                fire_alert("CRITICAL", f"Data error: {asset}",
                           f"Live data fetch failed for {asset}.\n{detail}",
                           key=f"data_error_{asset}")
            elif status == "STALE":
                fire_alert("WARNING", f"Stale data: {asset}",
                           f"Using cached/stale data for {asset}.\n{detail}",
                           key=f"data_stale_{asset}")
            elif status == "OK":
                # Auto-resolve stale/error alerts when data recovers
                resolve_alert(f"data_stale_{asset}", reason=f"{asset} data recovered")
                resolve_alert(f"data_error_{asset}", reason=f"{asset} data recovered")
    except Exception:
        pass

    # Cycle health checks
    try:
        from bahamut.monitoring.cycle_log import get_cycle_stats
        stats = get_cycle_stats()
        if stats.get("errors", 0) >= 3:
            fire_alert("CRITICAL", "Multiple cycle errors",
                       f"{stats['errors']} errors in last {stats['total']} cycles",
                       key="cycle_errors_high")
        if stats.get("skipped", 0) >= 5:
            fire_alert("WARNING", "High cycle skip rate",
                       f"{stats['skipped']} skipped in last {stats['total']} cycles",
                       key="cycle_skips_high")
    except Exception:
        pass


def fire_trade_alert(trade: dict, action: str = "closed"):
    """Fire alert + send rich email + rich Telegram for trade events."""
    asset = trade.get("asset", "?")
    strategy = trade.get("strategy", "?")
    direction = trade.get("direction", trade.get("dir", "?"))

    if action == "opened":
        entry = trade.get("entry_price", trade.get("entry", 0))
        fire_alert("INFO", f"Trade opened: {asset}",
                   f"{strategy} {direction} {asset} @ ${entry:,.2f}",
                   key=f"trade_open_{asset}_{strategy}")

        # Rich email
        try:
            from bahamut.monitoring.email_templates import trade_opened_template
            subject, html = trade_opened_template(trade)
            _send_email_html(subject, html)
        except Exception as e:
            logger.debug("trade_open_email_failed", error=str(e))

        # Rich Telegram
        try:
            from bahamut.monitoring.telegram import send_trade_opened
            send_trade_opened(trade)
        except Exception as e:
            logger.debug("trade_open_tg_failed", error=str(e))
    else:
        pnl = trade.get("pnl", 0)
        reason = trade.get("exit_reason", trade.get("reason", "?"))
        emoji = "✅" if pnl > 0 else "❌"
        fire_alert("INFO", f"Trade closed: {asset} {emoji}",
                   f"{strategy} {direction} {asset}\n"
                   f"PnL: ${pnl:+,.2f} | Reason: {reason}",
                   key=f"trade_close_{asset}_{strategy}_{time.time():.0f}")

        # Rich email
        try:
            from bahamut.monitoring.email_templates import trade_closed_template
            subject, html = trade_closed_template(trade)
            _send_email_html(subject, html)
        except Exception as e:
            logger.debug("trade_close_email_failed", error=str(e))

        # Rich Telegram
        try:
            from bahamut.monitoring.telegram import send_trade_closed
            send_trade_closed(trade)
        except Exception as e:
            logger.debug("trade_close_tg_failed", error=str(e))


def fire_regime_change(asset: str, old_regime: str, new_regime: str):
    """Fire INFO alert for regime changes."""
    emoji = "📈" if new_regime == "TREND" else ("🔻" if new_regime == "CRASH" else "↔️")
    fire_alert("INFO", f"Regime change: {asset}",
               f"{asset}: {old_regime} → {new_regime} {emoji}",
               key=f"regime_{asset}_{new_regime}")


# ═══════════════════════════════════════════════════════
# 4H CYCLE REPORT — EMAIL + TELEGRAM
# ═══════════════════════════════════════════════════════

def send_cycle_report(cycle: dict):
    """
    Send 4H cycle report via email AND Telegram.
    Includes: status, portfolio, asset evaluations, strategy conditions.
    """
    try:
        # Get portfolio data
        portfolio = {}
        try:
            from bahamut.portfolio.manager import get_portfolio_manager
            pm = get_portfolio_manager()
            pm.update()
            portfolio = {
                "equity": round(pm.total_equity, 2),
                "pnl_total": round(pm.total_equity - pm.initial_capital, 2),
                "drawdown_pct": round((1 - pm.total_equity / pm.peak_equity) * 100 if pm.peak_equity > 0 else 0, 2),
                "open_risk_pct": 0,
                "open_positions": 0,
            }
            try:
                from bahamut.execution.engine import get_execution_engine
                engine = get_execution_engine()
                open_risk = sum(p.risk_amount for p in engine.open_positions)
                portfolio["open_risk_pct"] = round(open_risk / max(1, pm.total_equity) * 100, 2)
                portfolio["open_positions"] = len(engine.open_positions)
            except Exception:
                pass
        except Exception:
            pass

        # Get strategy conditions
        conditions = {}
        try:
            from bahamut.monitoring.strategy_conditions import get_latest_snapshots
            conditions = get_latest_snapshots()
        except Exception:
            pass

        # Send email
        try:
            from bahamut.monitoring.email import _get_config
            cfg = _get_config()
            if cfg.get("enabled") and cfg.get("api_key") and cfg.get("to_email"):
                from bahamut.monitoring.email_templates import cycle_report_template
                subject, html = cycle_report_template(cycle, portfolio, conditions)
                _send_email_html(subject, html)
        except Exception as e:
            logger.debug("cycle_report_email_failed", error=str(e))

        # Send Telegram
        try:
            from bahamut.monitoring.telegram import send_cycle_report as tg_cycle_report
            tg_cycle_report(cycle, portfolio, conditions)
        except Exception as e:
            logger.debug("cycle_report_tg_failed", error=str(e))

        logger.info("cycle_report_sent", status=cycle.get("status"),
                     signals=cycle.get("signals_generated", 0))

    except Exception as e:
        logger.error("cycle_report_failed", error=str(e))
