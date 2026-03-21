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
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    from_email: Optional[str] = None
    to_email: Optional[str] = None


@router.post("/settings/test/email")
async def test_email(body: EmailTestRequest = None, user=Depends(get_current_user)):
    """Send a test email. Accepts inline config so user doesn't need to save first."""
    import smtplib
    from email.mime.text import MIMEText

    # Use inline values if provided, otherwise fall back to saved config
    host = body.smtp_host if body and body.smtp_host else get_config("notify.email.smtp_host", "smtp-relay.brevo.com")
    port = body.smtp_port if body and body.smtp_port else get_config("notify.email.smtp_port", 587)
    smtp_user = body.smtp_user if body and body.smtp_user else get_config("notify.email.smtp_user", "")
    smtp_pass = body.smtp_pass if body and body.smtp_pass else get_config("notify.email.smtp_pass", "")
    from_email = body.from_email if body and body.from_email else get_config("notify.email.from_email", "")
    to_email = body.to_email if body and body.to_email else get_config("notify.email.to_email", "")

    if not smtp_user:
        return {"ok": False, "error": "SMTP login not set"}
    if not smtp_pass:
        return {"ok": False, "error": "SMTP key/password not set"}
    if not to_email:
        return {"ok": False, "error": "Recipient email not set"}

    from_addr = from_email or smtp_user

    try:
        msg = MIMEText("This is a test email from Bahamut.AI.\n\nEmail notifications are working!")
        msg["Subject"] = "✅ Bahamut Alert Test"
        msg["From"] = f"Bahamut Alerts <{from_addr}>"
        msg["To"] = to_email

        with smtplib.SMTP(host, int(port), timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, to_email, msg.as_string())

        return {"ok": True, "message": f"Test email sent to {to_email}"}
    except smtplib.SMTPAuthenticationError as e:
        return {"ok": False, "error": f"Authentication failed: {e.smtp_error.decode() if hasattr(e, 'smtp_error') else str(e)}"}
    except smtplib.SMTPSenderRefused as e:
        return {"ok": False, "error": f"Sender rejected (verify '{from_addr}' in Brevo): {str(e)}"}
    except smtplib.SMTPRecipientsRefused as e:
        return {"ok": False, "error": f"Recipient rejected: {str(e)}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)}"}
