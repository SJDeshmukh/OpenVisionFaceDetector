"""Provider-neutral email adapter supporting AWS SES and standard SMTP."""

import os
import smtplib
import logging
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

logger = logging.getLogger(__name__)


class EmailConfigurationError(RuntimeError):
    pass


def smtp_is_configured():
    username = (os.environ.get("SMTP_USERNAME") or os.environ.get("MAIL_SMTP_USERNAME") or "").strip()
    password = (os.environ.get("SMTP_PASSWORD") or os.environ.get("MAIL_SMTP_APP_PASSWORD") or "").strip()
    return bool(username and password)


def _log_vendor_email(vendor_id, recipient, subject, email_type="general", status="sent", error_message=None):
    if not vendor_id:
        return
    try:
        from utils import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        is_pg = getattr(conn, "_is_pg", False)
        if is_pg:
            c.execute("""
                INSERT INTO vendor_email_logs (vendor_id, recipient, subject, email_type, status, error_message, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (vendor_id, recipient, subject, email_type, status, error_message))
        else:
            c.execute("""
                INSERT INTO vendor_email_logs (vendor_id, recipient, subject, email_type, status, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (vendor_id, recipient, subject, email_type, status, error_message))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to log vendor email: {e}")


def send_email(subject, text_body, recipient, attachments=None, html_body=None, vendor_id=None, email_type="general"):
    username = (os.environ.get("SMTP_USERNAME") or os.environ.get("MAIL_SMTP_USERNAME") or "").strip()
    password = (os.environ.get("SMTP_PASSWORD") or os.environ.get("MAIL_SMTP_APP_PASSWORD") or "").strip()
    host = (os.environ.get("SMTP_HOST") or os.environ.get("MAIL_SMTP_HOST") or "email-smtp.us-east-1.amazonaws.com").strip()
    port = int(os.environ.get("SMTP_PORT") or os.environ.get("MAIL_SMTP_PORT") or "587")
    sender = (os.environ.get("SMTP_FROM_EMAIL") or os.environ.get("MAIL_FROM_ADDRESS") or "noreply@openvisionx.in").strip()
    sender_name = os.environ.get("MAIL_FROM_NAME", "TapInX Alerts").strip()

    if not username or not password:
        err_msg = "SMTP is not configured. Set SMTP_USERNAME and SMTP_PASSWORD."
        _log_vendor_email(vendor_id, recipient, subject, email_type, status="failed", error_message=err_msg)
        raise EmailConfigurationError(err_msg)

    # Check vendor subscription feature if vendor_id is provided
    if vendor_id:
        try:
            from utils import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            is_pg = getattr(conn, "_is_pg", False)
            try:
                if is_pg:
                    c.execute("SELECT features FROM subscriptions WHERE vendor_id = %s", (vendor_id,))
                else:
                    c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
                row = c.fetchone()
            finally:
                conn.close()

            if row and row[0]:
                features_str = str(row[0] or "")
                # Allow if email_notifications is toggled, or if this is a leave alert and vendor has leave_management
                is_leave_alert = (email_type == "leave_stage_notification")
                has_perm = (
                    "email_notifications" in features_str
                    or "automated_email_reports" in features_str
                    or (is_leave_alert and "leave_management" in features_str)
                )
                if not has_perm:
                    logger.info(f"Skipping email to {recipient} for vendor {vendor_id}: email_notifications feature is not enabled")
                    return None
        except Exception as ex:
            logger.warning(f"Could not check vendor features for email: {ex}")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((sender_name, sender))
    message["To"] = recipient
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    message.set_content(text_body)

    if html_body:
        message.add_alternative(html_body, subtype="html")

    for item in attachments or []:
        payload = item["content"]
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        maintype, subtype = item.get("mimetype", "application/octet-stream").split("/", 1)
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=item["filename"])

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(username, password)
            refused = server.send_message(message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
        _log_vendor_email(vendor_id, recipient, subject, email_type, status="sent")
    except Exception as e:
        _log_vendor_email(vendor_id, recipient, subject, email_type, status="failed", error_message=str(e))
        raise

    return message["Message-ID"]
