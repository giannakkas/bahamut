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
    """Send a test Telegram message using saved config."""
    from bahamut.monitoring.telegram import test_connection
    return test_connection()


class EmailTestRequest(BaseModel):
    api_key: Optional[str] = None
    from_email: Optional[str] = None
    to_email: Optional[str] = None


@router.post("/settings/test/email")
async def test_email(body: EmailTestRequest = None, user=Depends(get_current_user)):
    """Send a test email via Brevo API."""
    import json
    import urllib.request

    api_key = (body.api_key if body and body.api_key else None) or get_config("notify.email.smtp_pass", "")
    from_email = (body.from_email if body and body.from_email else None) or get_config("notify.email.from_email", "") or "noreply@bahamut.ai"
    to_email = (body.to_email if body and body.to_email else None) or get_config("notify.email.to_email", "")

    if not api_key:
        return {"ok": False, "error": "Brevo API key not set"}
    if not to_email:
        return {"ok": False, "error": "Recipient email not set"}

    payload = {
        "sender": {"name": "Bahamut Alerts", "email": from_email},
        "to": [{"email": to_email}],
        "subject": "✅ Bahamut Alert Test",
        "textContent": "This is a test email from Bahamut.AI.\n\nEmail notifications are working!",
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", data=data, method="POST")
        req.add_header("accept", "application/json")
        req.add_header("content-type", "application/json")
        req.add_header("api-key", api_key)

        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return {"ok": True, "message": f"Test email sent to {to_email}"}

    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
            return {"ok": False, "error": f"Brevo error ({e.code}): {err.get('message', str(err))}"}
        except Exception:
            return {"ok": False, "error": f"Brevo error ({e.code})"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
