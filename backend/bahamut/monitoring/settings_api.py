"""
Bahamut Notification Settings API

GET  /api/monitoring/settings           — current notification config
POST /api/monitoring/settings           — update notification config
POST /api/monitoring/settings/test/telegram  — send test Telegram message
POST /api/monitoring/settings/test/email     — send test email
"""
import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from bahamut.auth.router import get_current_user
from bahamut.admin.config import get_config, set_config

logger = structlog.get_logger()
router = APIRouter()


class NotificationSettings(BaseModel):
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    email_enabled: Optional[bool] = None
    email_smtp_host: Optional[str] = None
    email_smtp_port: Optional[int] = None
    email_smtp_user: Optional[str] = None
    email_smtp_pass: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[str] = None
    level_critical: Optional[bool] = None
    level_warning: Optional[bool] = None
    level_info: Optional[bool] = None


# Key mapping: form field → config key
_FIELD_MAP = {
    "telegram_enabled": "notify.telegram.enabled",
    "telegram_bot_token": "notify.telegram.bot_token",
    "telegram_chat_id": "notify.telegram.chat_id",
    "email_enabled": "notify.email.enabled",
    "email_smtp_host": "notify.email.smtp_host",
    "email_smtp_port": "notify.email.smtp_port",
    "email_smtp_user": "notify.email.smtp_user",
    "email_smtp_pass": "notify.email.smtp_pass",
    "email_from": "notify.email.from_email",
    "email_to": "notify.email.to_email",
    "level_critical": "notify.level.critical",
    "level_warning": "notify.level.warning",
    "level_info": "notify.level.info",
}


@router.get("/settings")
async def get_notification_settings(user=Depends(get_current_user)):
    """Get current notification configuration."""
    result = {}
    for field, key in _FIELD_MAP.items():
        val = get_config(key)
        # Mask sensitive fields
        if "token" in field or "pass" in field:
            val_str = str(val) if val else ""
            result[field] = ("●" * 8 + val_str[-4:]) if len(val_str) > 4 else val
        else:
            result[field] = val

    # Add connection status
    from bahamut.monitoring.telegram import is_configured as tg_ok
    from bahamut.monitoring.email import is_configured as em_ok
    result["telegram_connected"] = tg_ok()
    result["email_connected"] = em_ok()

    return result


@router.post("/settings")
async def save_notification_settings(body: NotificationSettings,
                                      user=Depends(get_current_user)):
    """Save notification settings."""
    changes = {}
    data = body.dict(exclude_none=True)

    for field, value in data.items():
        config_key = _FIELD_MAP.get(field)
        if not config_key:
            continue
        result = set_config(config_key, value, changed_by=user.email)
        if "error" in result:
            return {"ok": False, "error": result["error"], "field": field}
        changes[field] = True

    return {"ok": True, "changes": len(changes)}


@router.post("/settings/test/telegram")
async def test_telegram(user=Depends(get_current_user)):
    """Send a test Telegram message."""
    from bahamut.monitoring.telegram import test_connection
    return test_connection()


@router.post("/settings/test/email")
async def test_email(user=Depends(get_current_user)):
    """Send a test email."""
    from bahamut.monitoring.email import test_connection
    return test_connection()
