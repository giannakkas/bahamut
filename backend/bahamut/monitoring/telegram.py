"""
Bahamut Telegram Alerts

Config stored in DB via admin config system.
Configure at admin.bahamut.ai → Settings → Notifications.

Setup:
  1. Message @BotFather on Telegram → /newbot → get token
  2. Message your bot, then visit:
     https://api.telegram.org/bot<TOKEN>/getUpdates
     to find your chat_id
  3. Enter both in Settings → Telegram
"""
import structlog
import urllib.request
import urllib.parse
import json

logger = structlog.get_logger()

LEVEL_EMOJI = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}


def _get_config():
    """Load Telegram config from DB."""
    try:
        from bahamut.admin.config import get_config
        return {
            "enabled": get_config("notify.telegram.enabled", False),
            "token": get_config("notify.telegram.bot_token", ""),
            "chat_id": get_config("notify.telegram.chat_id", ""),
        }
    except Exception:
        return {"enabled": False, "token": "", "chat_id": ""}


def send_telegram_alert(message: str, level: str = "INFO",
                         title: str = "") -> bool:
    cfg = _get_config()
    if not cfg["enabled"] or not cfg["token"] or not cfg["chat_id"]:
        logger.debug("telegram_not_configured")
        return False

    # Check level preference
    try:
        from bahamut.admin.config import get_config
        if level == "CRITICAL" and not get_config("notify.level.critical", True):
            return False
        if level == "WARNING" and not get_config("notify.level.warning", True):
            return False
        if level == "INFO" and not get_config("notify.level.info", False):
            return False
    except Exception:
        pass

    emoji = LEVEL_EMOJI.get(level, "📌")
    text = f"{emoji} *[{level}] Bahamut Alert*\n\n"
    if title:
        text += f"*{title}*\n\n"
    text += message

    try:
        url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": cfg["chat_id"],
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": "true",
        }).encode()

        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                logger.info("telegram_sent", level=level, title=title)
                return True
            else:
                logger.error("telegram_api_error", result=result)
                return False
    except Exception as e:
        logger.error("telegram_send_failed", error=str(e))
        return False


def is_configured() -> bool:
    cfg = _get_config()
    return bool(cfg["enabled"] and cfg["token"] and cfg["chat_id"])


def test_connection() -> dict:
    """Send a test message. Returns success/error."""
    cfg = _get_config()
    if not cfg["token"] or not cfg["chat_id"]:
        return {"ok": False, "error": "Bot token or chat ID not set"}

    try:
        url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": cfg["chat_id"],
            "text": "✅ *Bahamut Alert Test*\n\nTelegram notifications are working!",
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                return {"ok": True}
            return {"ok": False, "error": str(result)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
