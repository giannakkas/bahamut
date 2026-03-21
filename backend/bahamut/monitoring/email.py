"""
Bahamut Email Alerts

Config via environment:
  SMTP_HOST       — e.g. smtp.gmail.com
  SMTP_PORT       — e.g. 587
  SMTP_USER       — sender email
  SMTP_PASS       — app password (NOT regular password)
  ALERT_EMAIL_TO  — recipient email

For Gmail: enable 2FA, create App Password at myaccount.google.com/apppasswords
"""
import os
import smtplib
import structlog
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = structlog.get_logger()

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")


def send_email_alert(subject: str, body: str) -> bool:
    """
    Send alert email via SMTP.
    Returns True if sent successfully.
    """
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO]):
        logger.debug("email_not_configured")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ALERT_EMAIL_TO

        # Plain text
        msg.attach(MIMEText(body, "plain"))

        # HTML version
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; padding: 20px;">
            <div style="background: #1B2A4A; color: white; padding: 15px 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0; font-size: 18px;">🔔 {subject}</h2>
            </div>
            <div style="background: #f8f9fa; padding: 20px; border: 1px solid #e2e8f0; border-radius: 0 0 8px 8px;">
                <pre style="white-space: pre-wrap; font-family: monospace; font-size: 14px; color: #1e293b;">{body}</pre>
            </div>
            <p style="color: #94a3b8; font-size: 12px; margin-top: 10px;">Bahamut.AI Trading System</p>
        </div>
        """
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, ALERT_EMAIL_TO, msg.as_string())

        logger.info("email_sent", subject=subject, to=ALERT_EMAIL_TO)
        return True

    except Exception as e:
        logger.error("email_send_failed", error=str(e))
        return False


def is_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS and ALERT_EMAIL_TO)
