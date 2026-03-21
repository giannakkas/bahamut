"""
Bahamut Telegram Alerts

Config via environment:
  TELEGRAM_BOT_TOKEN  — Bot token from @BotFather
  TELEGRAM_CHAT_ID    — Your chat/group ID

Setup:
  1. Message @BotFather on Telegram, create bot, get token
  2. Message your bot, then visit:
     https://api.telegram.org/bot<TOKEN>/getUpdates
     to find your chat_id
  3. Set env vars
"""
import os
import structlog
import urllib.request
import urllib.parse
import json

logger = structlog.get_logger()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

LEVEL_EMOJI = {
    "CRITICAL": "🚨",
    "WARNING": "⚠️",
    "INFO": "ℹ️",
}


def send_telegram_alert(message: str, level: str = "INFO",
                         title: str = "") -> bool:
    """
    Send alert via Telegram Bot API.
    Returns True if sent successfully.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("telegram_not_configured")
        return False

    emoji = LEVEL_EMOJI.get(level, "📌")
    text = f"{emoji} *[{level}] Bahamut Alert*\n\n"
    if title:
        text += f"*{title}*\n\n"
    text += message

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
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
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
