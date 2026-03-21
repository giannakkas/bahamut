"""
Bahamut Email Alerts via Brevo HTTP API

Uses Brevo's transactional email API (not SMTP).
Config stored in DB via admin config system.

Setup:
  1. Get API key from brevo.com → SMTP & API → API Keys
  2. Enter in Settings → Notifications → Email section
  3. Verify sender email in Brevo → Settings → Senders
"""
import json
import urllib.request
import urllib.parse
import structlog

logger = structlog.get_logger()

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _get_config():
    """Load email config from DB."""
    try:
        from bahamut.admin.config import get_config
        return {
            "enabled": get_config("notify.email.enabled", False),
            "api_key": get_config("notify.email.smtp_pass", ""),  # Reuse smtp_pass field for API key
            "from_email": get_config("notify.email.from_email", ""),
            "from_name": "Bahamut Alerts",
            "to_email": get_config("notify.email.to_email", ""),
        }
    except Exception:
        return {"enabled": False, "api_key": "", "from_email": "", "from_name": "", "to_email": ""}


def send_email_alert(subject: str, body: str) -> bool:
    """Send alert email via Brevo API."""
    cfg = _get_config()
    if not cfg["enabled"] or not cfg["api_key"] or not cfg["to_email"]:
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

    return _send_via_api(cfg, subject, body)


def _send_via_api(cfg: dict, subject: str, body: str) -> bool:
    """Send email via Brevo HTTP API."""
    from_email = cfg["from_email"] or "noreply@bahamut.ai"

    payload = {
        "sender": {"name": cfg.get("from_name", "Bahamut Alerts"), "email": from_email},
        "to": [{"email": cfg["to_email"]}],
        "subject": subject,
        "textContent": body,
        "htmlContent": f"""
        <div style="font-family: -apple-system, sans-serif; max-width: 600px;">
            <div style="background: #1B2A4A; color: white; padding: 16px 24px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0; font-size: 16px;">🔔 {subject}</h2>
            </div>
            <div style="background: #f8fafc; padding: 24px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px;">
                <pre style="white-space: pre-wrap; font-family: monospace; font-size: 13px; color: #1e293b; margin: 0;">{body}</pre>
            </div>
            <p style="color: #94a3b8; font-size: 11px; margin-top: 12px;">Bahamut.AI Trading System</p>
        </div>""",
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(BREVO_API_URL, data=data, method="POST")
        req.add_header("accept", "application/json")
        req.add_header("content-type", "application/json")
        req.add_header("api-key", cfg["api_key"])

        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            logger.info("email_sent_brevo", subject=subject, to=cfg["to_email"], messageId=result.get("messageId"))
            return True

    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        logger.error("brevo_api_error", status=e.code, error=error_body)
        return False
    except Exception as e:
        logger.error("email_send_failed", error=str(e))
        return False


def is_configured() -> bool:
    cfg = _get_config()
    return bool(cfg["enabled"] and cfg["api_key"] and cfg["to_email"])


def test_connection() -> dict:
    """Send a test email via Brevo API."""
    cfg = _get_config()
    if not cfg["api_key"]:
        return {"ok": False, "error": "Brevo API key not set"}
    if not cfg["to_email"]:
        return {"ok": False, "error": "Recipient email not set"}

    from_email = cfg["from_email"] or "noreply@bahamut.ai"

    payload = {
        "sender": {"name": "Bahamut Alerts", "email": from_email},
        "to": [{"email": cfg["to_email"]}],
        "subject": "✅ Bahamut Alert Test",
        "textContent": "This is a test email from Bahamut.AI.\n\nEmail notifications are working!",
        "htmlContent": """
        <div style="font-family: -apple-system, sans-serif; max-width: 600px; padding: 20px;">
            <h2 style="color: #1B2A4A;">✅ Bahamut Alert Test</h2>
            <p>Email notifications are working!</p>
            <p style="color: #94a3b8; font-size: 12px;">Bahamut.AI Trading System</p>
        </div>""",
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(BREVO_API_URL, data=data, method="POST")
        req.add_header("accept", "application/json")
        req.add_header("content-type", "application/json")
        req.add_header("api-key", cfg["api_key"])

        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return {"ok": True, "message": f"Test email sent to {cfg['to_email']}", "messageId": result.get("messageId")}

    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode()
            error_json = json.loads(error_body)
            error_msg = error_json.get("message", error_body)
        except Exception:
            error_msg = error_body or str(e)
        return {"ok": False, "error": f"Brevo API error ({e.code}): {error_msg}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
