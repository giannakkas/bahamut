"""
Bahamut Telegram Alerts — Rich formatted messages

Templates:
- CRITICAL alerts (🚨)
- WARNING alerts (⚠️)
- INFO alerts (ℹ️)
- 4H Cycle Reports (📊)
- Trade Opened (📈)
- Trade Closed (✅/❌)
"""
import structlog
import urllib.request
import urllib.parse
import json

logger = structlog.get_logger()


def _get_config():
    try:
        from bahamut.admin.config import get_config
        return {
            "enabled": get_config("notify.telegram.enabled", False),
            "token": get_config("notify.telegram.bot_token", ""),
            "chat_id": get_config("notify.telegram.chat_id", ""),
        }
    except Exception:
        return {"enabled": False, "token": "", "chat_id": ""}


def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API."""
    cfg = _get_config()
    if not cfg["enabled"] or not cfg["token"] or not cfg["chat_id"]:
        return False

    try:
        url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": cfg["chat_id"],
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": "true",
        }).encode()

        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                return True
            logger.error("telegram_api_error", result=result)
    except Exception as e:
        logger.error("telegram_send_failed", error=str(e))
    return False


def _check_level(level: str) -> bool:
    """Check if this alert level should be sent."""
    try:
        from bahamut.admin.config import get_config
        if level == "CRITICAL":
            return get_config("notify.level.critical", True)
        if level == "WARNING":
            return get_config("notify.level.warning", True)
        if level == "INFO":
            return get_config("notify.level.info", False)
    except Exception:
        pass
    return True


# ═══════════════════════════════════════════════════════
# ALERT TEMPLATES
# ═══════════════════════════════════════════════════════

def send_telegram_alert(message: str, level: str = "INFO", title: str = "") -> bool:
    """Send a templated alert via Telegram."""
    if not _check_level(level):
        return False

    if level == "CRITICAL":
        text = (
            f"🚨 <b>CRITICAL ALERT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>{title}</b>\n\n"
            f"{message}\n\n"
            f"⚠️ <i>Immediate action required</i>"
        )
    elif level == "WARNING":
        text = (
            f"⚠️ <b>WARNING</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>{title}</b>\n\n"
            f"{message}\n\n"
            f"👁 <i>Monitor closely</i>"
        )
    else:
        text = (
            f"ℹ️ <b>{title}</b>\n\n"
            f"{message}"
        )

    return _send(text)


# ═══════════════════════════════════════════════════════
# CYCLE REPORT
# ═══════════════════════════════════════════════════════

def send_cycle_report(cycle: dict, portfolio: dict = None,
                      conditions: dict = None) -> bool:
    """Send 4H cycle report via Telegram."""
    status = cycle.get("status", "?")
    duration = cycle.get("duration_ms", 0)
    signals = cycle.get("signals_generated", 0)
    orders = cycle.get("orders_created", 0)
    assets = cycle.get("assets", [])
    data_src = cycle.get("data_source", "?")

    status_emoji = "✅" if status == "SUCCESS" else "❌" if status == "ERROR" else "⏭️"

    lines = [
        f"📊 <b>4H Cycle Report</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"{status_emoji} Status: <b>{status}</b>  ⏱ {duration}ms  📡 {data_src}",
        f"📶 Signals: {signals}  📋 Orders: {orders}",
    ]

    # Portfolio
    if portfolio:
        equity = portfolio.get("equity", portfolio.get("total_equity", 0))
        pnl = portfolio.get("pnl_total", 0)
        dd = portfolio.get("drawdown_pct", 0)
        risk = portfolio.get("open_risk_pct", 0)
        pos = portfolio.get("open_positions", 0)

        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        dd_emoji = "🟢" if dd < 3 else "🟡" if dd < 5 else "🔴"

        lines += [
            f"",
            f"💰 <b>Portfolio</b>",
            f"├ Equity: <code>${equity:,.0f}</code>",
            f"├ P&L: {pnl_emoji} <code>${pnl:+,.0f}</code>",
            f"├ Drawdown: {dd_emoji} <code>{dd:.1f}%</code>",
            f"├ Risk: <code>{risk:.1f}%</code>",
            f"└ Positions: <code>{pos}</code>",
        ]

    # Per-asset evaluations
    for a in assets:
        asset_name = a.get("asset", "?")
        regime = a.get("regime", "?")
        price = a.get("bar_close", 0)
        new_bar = a.get("new_bar", False)
        strats = a.get("strategies_evaluated", [])

        regime_emoji = "📈" if regime == "TREND" else "🔻" if regime == "CRASH" else "↔️"
        bar_tag = "🆕" if new_bar else "🔄"

        lines += [
            f"",
            f"{bar_tag} <b>{asset_name}</b> — {regime_emoji} {regime} — <code>${price:,.0f}</code>",
        ]

        if strats:
            for i, s in enumerate(strats):
                result = s.get("result", "?")
                reason = s.get("reason", "")
                r_emoji = "✅" if result == "EXECUTED" else "🔒" if result == "BLOCKED" else "⬜"
                prefix = "└" if i == len(strats) - 1 else "├"
                lines.append(f"{prefix} {r_emoji} {s.get('strategy', '?')}: <i>{reason[:50]}</i>")
        elif a.get("summary"):
            lines.append(f"└ {a['summary']}")

    # Strategy conditions summary
    if conditions:
        for asset_name, cdata in conditions.items():
            for strat in cdata.get("strategies", []):
                for cond in strat.get("conditions", []):
                    if not cond.get("passed") and cond.get("distance", "N/A") != "N/A":
                        lines.append(f"   📐 {cond['name']}: {cond.get('distance', '')}")

    # Error
    error = cycle.get("error", "")
    if error:
        lines += [f"", f"❌ <b>Error:</b> <code>{error[:100]}</code>"]

    lines += [f"", f"🔗 <a href='https://admin.bahamut.ai/v7-operations'>Open Dashboard</a>"]

    return _send("\n".join(lines))


# ═══════════════════════════════════════════════════════
# TRADE TEMPLATES
# ═══════════════════════════════════════════════════════

def send_trade_opened(trade: dict) -> bool:
    """Send trade opened notification via Telegram."""
    asset = trade.get("asset", "?")
    strategy = trade.get("strategy", "?")
    direction = trade.get("direction", "LONG")
    entry = trade.get("entry_price", trade.get("entry", 0))
    sl = trade.get("stop_loss", trade.get("sl_price", 0))
    tp = trade.get("take_profit", trade.get("tp_price", 0))
    risk = trade.get("risk_amount", 0)
    risk_pct = trade.get("risk_pct", 0)
    size = trade.get("size", 0)
    regime = trade.get("regime", "?")

    dir_emoji = "📈" if direction == "LONG" else "📉"

    text = (
        f"{dir_emoji} <b>Trade Opened: {direction} {asset}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"📋 Strategy: <b>{strategy}</b>\n"
        f"🏷 Regime: {regime}\n"
        f"\n"
        f"▶️ Entry: <code>${entry:,.2f}</code>\n"
        f"🛑 Stop Loss: <code>${sl:,.2f}</code>\n"
        f"🎯 Take Profit: <code>${tp:,.2f}</code>\n"
        f"\n"
        f"📦 Size: <code>{size:.6f}</code>\n"
        f"⚠️ Risk: <code>${risk:,.0f} ({risk_pct:.1f}%)</code>\n"
        f"\n"
        f"🔗 <a href='https://admin.bahamut.ai/v7-operations'>Open Dashboard</a>"
    )

    return _send(text)


def send_trade_closed(trade: dict) -> bool:
    """Send trade closed notification via Telegram."""
    asset = trade.get("asset", "?")
    strategy = trade.get("strategy", "?")
    direction = trade.get("direction", "LONG")
    entry = trade.get("entry_price", trade.get("entry", 0))
    exit_price = trade.get("exit_price", trade.get("exit", 0))
    pnl = trade.get("pnl", 0)
    reason = trade.get("exit_reason", trade.get("reason", "?"))
    bars = trade.get("bars_held", 0)
    risk_amount = trade.get("risk_amount", 0)

    is_win = pnl > 0
    result_emoji = "✅" if is_win else "❌"
    result_text = "WIN" if is_win else "LOSS"
    r_multiple = abs(pnl / risk_amount) if risk_amount > 0 else 0
    r_sign = "+" if is_win else "-"

    reason_emoji = "🎯" if "TP" in reason.upper() else "🛑" if "SL" in reason.upper() else "⏰" if "MAX" in reason.upper() or "HOLD" in reason.upper() else "📋"

    text = (
        f"{result_emoji} <b>Trade Closed: {asset} {direction}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"{'🟢' if is_win else '🔴'} <b>{result_text}</b> — <code>${pnl:+,.2f}</code> ({r_sign}{r_multiple:.1f}R)\n"
        f"\n"
        f"📋 Strategy: {strategy}\n"
        f"▶️ Entry: <code>${entry:,.2f}</code>\n"
        f"⏹ Exit: <code>${exit_price:,.2f}</code>\n"
        f"{reason_emoji} Reason: <b>{reason}</b>\n"
        f"⏱ Duration: {bars} bars\n"
        f"\n"
        f"🔗 <a href='https://admin.bahamut.ai/v7-operations'>Open Dashboard</a>"
    )

    return _send(text)


# ═══════════════════════════════════════════════════════
# UTILITY
# ═══════════════════════════════════════════════════════

def is_configured() -> bool:
    cfg = _get_config()
    return bool(cfg["enabled"] and cfg["token"] and cfg["chat_id"])


def test_connection() -> dict:
    cfg = _get_config()
    if not cfg["token"] or not cfg["chat_id"]:
        return {"ok": False, "error": "Bot token or chat ID not set"}

    try:
        url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": cfg["chat_id"],
            "text": "✅ <b>Bahamut Alert Test</b>\n\nTelegram notifications are working!",
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                return {"ok": True}
            return {"ok": False, "error": str(result)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
