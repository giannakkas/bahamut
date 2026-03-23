"""
Bahamut Email Alerts via Brevo

Tries HTTP API first, falls back to SMTP if API fails.
Config stored in DB via admin config system.
"""
import json
import smtplib
import urllib.request
import urllib.parse
import structlog
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = structlog.get_logger()

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _get_config():
    """Load email config from DB."""
    try:
        from bahamut.admin.config import get_config
        return {
            "enabled": get_config("notify.email.enabled", False),
            "api_key": get_config("notify.email.smtp_pass", ""),
            "smtp_host": get_config("notify.email.smtp_host", "smtp-relay.brevo.com"),
            "smtp_port": get_config("notify.email.smtp_port", 587),
            "smtp_user": get_config("notify.email.smtp_user", ""),
            "smtp_key": get_config("notify.email.smtp_key", ""),
            "from_email": get_config("notify.email.from_email", ""),
            "from_name": "Bahamut Alerts",
            "to_email": get_config("notify.email.to_email", ""),
        }
    except Exception:
        return {"enabled": False, "api_key": "", "smtp_host": "", "smtp_port": 587,
                "smtp_user": "", "smtp_key": "", "from_email": "", "from_name": "", "to_email": ""}


def send_email_alert(subject: str, body: str) -> bool:
    """Send alert email. Tries API first, falls back to SMTP."""
    cfg = _get_config()
    if not cfg["enabled"] or not cfg["to_email"]:
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

    # Try API first
    if cfg["api_key"]:
        ok = _send_via_api(cfg, subject, body)
        if ok:
            return True
        logger.warning("brevo_api_failed_trying_smtp")

    # Fallback to SMTP
    if cfg["smtp_user"] and cfg["api_key"]:
        return _send_via_smtp(cfg, subject, body)

    return False


def _send_via_api(cfg: dict, subject: str, body: str) -> bool:
    """Send via Brevo HTTP API."""
    from_email = cfg["from_email"] or "noreply@bahamut.ai"
    payload = {
        "sender": {"name": cfg.get("from_name", "Bahamut Alerts"), "email": from_email},
        "to": [{"email": cfg["to_email"]}],
        "subject": subject,
        "textContent": body,
        "htmlContent": f"""<div style="font-family:-apple-system,sans-serif;max-width:600px">
            <div style="background:#1B2A4A;color:white;padding:16px 24px;border-radius:8px 8px 0 0">
                <h2 style="margin:0;font-size:16px">🔔 {subject}</h2></div>
            <div style="background:#f8fafc;padding:24px;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 8px 8px">
                <pre style="white-space:pre-wrap;font-family:monospace;font-size:13px;color:#1e293b;margin:0">{body}</pre></div>
            <p style="color:#94a3b8;font-size:11px;margin-top:12px">Bahamut.AI Trading System</p></div>""",
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(BREVO_API_URL, data=data, method="POST")
        req.add_header("accept", "application/json")
        req.add_header("content-type", "application/json")
        req.add_header("api-key", cfg["api_key"])
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("email_sent_api", subject=subject, to=cfg["to_email"])
            return True
    except Exception as e:
        logger.error("brevo_api_error", error=str(e))
        return False


def _send_via_smtp(cfg: dict, subject: str, body: str) -> bool:
    """Send via SMTP as fallback."""
    from_addr = cfg["from_email"] or cfg["smtp_user"]
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Bahamut Alerts <{from_addr}>"
        msg["To"] = cfg["to_email"]
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=15) as server:
            server.starttls()
            # SMTP uses login + api_key (which is the SMTP password)
            server.login(cfg["smtp_user"], cfg["smtp_key"])
            server.sendmail(from_addr, cfg["to_email"], msg.as_string())

        logger.info("email_sent_smtp", subject=subject, to=cfg["to_email"])
        return True
    except Exception as e:
        logger.error("smtp_send_failed", error=str(e))
        return False


def is_configured() -> bool:
    cfg = _get_config()
    return bool(cfg["enabled"] and cfg["api_key"] and cfg["to_email"])


def send_html_to(to_email: str, subject: str, html: str) -> bool:
    """Send an HTML email to a specific recipient (not the admin default).
    Used for user-facing emails like approval notifications."""
    cfg = _get_config()
    if not cfg["api_key"]:
        logger.warning("send_html_to_no_api_key")
        return False

    from_email = cfg["from_email"] or "noreply@bahamut.ai"
    payload = {
        "sender": {"name": "Bahamut.AI", "email": from_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(BREVO_API_URL, data=data, method="POST")
        req.add_header("accept", "application/json")
        req.add_header("content-type", "application/json")
        req.add_header("api-key", cfg["api_key"])
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("html_email_sent", subject=subject, to=to_email)
            return True
    except Exception as e:
        logger.error("html_email_failed", to=to_email, error=str(e))

    # SMTP fallback
    try:
        from_addr = cfg["from_email"] or cfg["smtp_user"]
        if not cfg["smtp_user"]:
            return False
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Bahamut.AI <{from_addr}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=15) as server:
            server.starttls()
            server.login(cfg["smtp_user"], cfg["smtp_key"])
            server.sendmail(from_addr, to_email, msg.as_string())
        logger.info("html_email_sent_smtp", subject=subject, to=to_email)
        return True
    except Exception as e:
        logger.error("html_email_smtp_failed", to=to_email, error=str(e))
    return False


def test_connection() -> dict:
    """Test email sending — tries API then SMTP."""
    cfg = _get_config()
    if not cfg["api_key"]:
        return {"ok": False, "error": "Brevo API key not set"}
    if not cfg["to_email"]:
        return {"ok": False, "error": "Recipient email not set"}

    # Try API
    api_err = ""
    try:
        from_email = cfg["from_email"] or "noreply@bahamut.ai"
        payload = {
            "sender": {"name": "Bahamut Alerts", "email": from_email},
            "to": [{"email": cfg["to_email"]}],
            "subject": "✅ Bahamut Alert Test",
            "textContent": "This is a test email from Bahamut.AI.\n\nEmail notifications are working!",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(BREVO_API_URL, data=data, method="POST")
        req.add_header("accept", "application/json")
        req.add_header("content-type", "application/json")
        req.add_header("api-key", cfg["api_key"])
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {"ok": True, "message": f"Test email sent via API to {cfg['to_email']}", "method": "API"}
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
            api_err = err.get("message", str(err))
        except Exception:
            api_err = f"HTTP {e.code}"
    except Exception as e:
        api_err = str(e)

    # Try SMTP fallback
    if cfg["smtp_user"]:
        try:
            from_addr = cfg["from_email"] or cfg["smtp_user"]
            msg = MIMEText("This is a test email from Bahamut.AI.\n\nEmail notifications are working! (sent via SMTP)")
            msg["Subject"] = "✅ Bahamut Alert Test"
            msg["From"] = f"Bahamut Alerts <{from_addr}>"
            msg["To"] = cfg["to_email"]

            with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=15) as server:
                server.starttls()
                server.login(cfg["smtp_user"], cfg["smtp_key"])
                server.sendmail(from_addr, cfg["to_email"], msg.as_string())

            return {"ok": True, "message": f"Test email sent via SMTP to {cfg['to_email']} (API failed: {api_err})", "method": "SMTP"}
        except Exception as e:
            smtp_err = str(e)
            return {"ok": False, "error": f"Both methods failed.\nAPI: {api_err}\nSMTP: {smtp_err}"}

    return {"ok": False, "error": f"API failed: {api_err}. No SMTP credentials for fallback."}
