"""
Bahamut Email Alerts via Brevo (Sendinblue) SMTP

Config stored in DB via admin config system.
Configure at admin.bahamut.ai → Settings → Notifications.

Brevo setup:
  1. Sign up at brevo.com
  2. Go to SMTP & API → SMTP → Generate SMTP Key
  3. Enter in Settings:
     - SMTP Host: smtp-relay.brevo.com
     - SMTP Port: 587
     - SMTP User: your Brevo login email
     - SMTP Pass: the SMTP key (not your password)
     - From Email: your verified sender email
     - To Email: where alerts should go
"""
import smtplib
import structlog
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = structlog.get_logger()


def _get_config():
    """Load email config from DB."""
    try:
        from bahamut.admin.config import get_config
        return {
            "enabled": get_config("notify.email.enabled", False),
            "host": get_config("notify.email.smtp_host", "smtp-relay.brevo.com"),
            "port": get_config("notify.email.smtp_port", 587),
            "user": get_config("notify.email.smtp_user", ""),
            "password": get_config("notify.email.smtp_pass", ""),
            "from_email": get_config("notify.email.from_email", ""),
            "to_email": get_config("notify.email.to_email", ""),
        }
    except Exception:
        return {"enabled": False, "host": "", "port": 587, "user": "",
                "password": "", "from_email": "", "to_email": ""}


def send_email_alert(subject: str, body: str) -> bool:
    cfg = _get_config()
    if not cfg["enabled"] or not cfg["user"] or not cfg["password"] or not cfg["to_email"]:
        logger.debug("email_not_configured")
        return False

    # Check level preference
    try:
        from bahamut.admin.config import get_config
        if "CRITICAL" in subject and not get_config("notify.level.critical", True):
            return False
        if "WARNING" in subject and not get_config("notify.level.warning", True):
            return False
        if "INFO" in subject and not get_config("notify.level.info", False):
            return False
    except Exception:
        pass

    from_addr = cfg["from_email"] or cfg["user"]

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Bahamut Alerts <{from_addr}>"
        msg["To"] = cfg["to_email"]

        msg.attach(MIMEText(body, "plain"))

        html = f"""
        <div style="font-family: -apple-system, sans-serif; max-width: 600px; padding: 0;">
            <div style="background: #1B2A4A; color: white; padding: 16px 24px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0; font-size: 16px;">🔔 {subject}</h2>
            </div>
            <div style="background: #f8fafc; padding: 24px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px;">
                <pre style="white-space: pre-wrap; font-family: 'SF Mono', monospace; font-size: 13px; color: #1e293b; margin: 0;">{body}</pre>
            </div>
            <p style="color: #94a3b8; font-size: 11px; margin-top: 12px;">Bahamut.AI Trading System</p>
        </div>"""
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=15) as server:
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(from_addr, cfg["to_email"], msg.as_string())

        logger.info("email_sent", subject=subject, to=cfg["to_email"])
        return True
    except Exception as e:
        logger.error("email_send_failed", error=str(e))
        return False


def is_configured() -> bool:
    cfg = _get_config()
    return bool(cfg["enabled"] and cfg["user"] and cfg["password"] and cfg["to_email"])


def test_connection() -> dict:
    """Send a test email. Returns success/error."""
    cfg = _get_config()
    if not cfg["user"] or not cfg["password"] or not cfg["to_email"]:
        return {"ok": False, "error": "SMTP credentials or recipient not set"}

    from_addr = cfg["from_email"] or cfg["user"]
    try:
        msg = MIMEText("This is a test email from Bahamut.AI.\n\nEmail notifications are working!")
        msg["Subject"] = "✅ Bahamut Alert Test"
        msg["From"] = f"Bahamut Alerts <{from_addr}>"
        msg["To"] = cfg["to_email"]

        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=15) as server:
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(from_addr, cfg["to_email"], msg.as_string())

        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
