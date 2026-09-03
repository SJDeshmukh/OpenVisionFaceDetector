"""Small provider-neutral email adapter for the Gmail SMTP first release."""

import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


class EmailConfigurationError(RuntimeError):
    pass


def smtp_is_configured():
    return bool(os.environ.get("MAIL_SMTP_USERNAME") and os.environ.get("MAIL_SMTP_APP_PASSWORD"))


def send_email(subject, text_body, recipient, attachments=None):
    username = os.environ.get("MAIL_SMTP_USERNAME", "openvisionx@gmail.com").strip()
    password = os.environ.get("MAIL_SMTP_APP_PASSWORD", "").strip()
    host = os.environ.get("MAIL_SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.environ.get("MAIL_SMTP_PORT", "587"))
    sender = os.environ.get("MAIL_FROM_ADDRESS", username).strip()
    sender_name = os.environ.get("MAIL_FROM_NAME", "OpenVisionX Reports").strip()

    if not username or not password:
        raise EmailConfigurationError(
            "Gmail SMTP is not configured. Set MAIL_SMTP_USERNAME and MAIL_SMTP_APP_PASSWORD."
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((sender_name, sender))
    message["To"] = recipient
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    message.set_content(text_body)

    for item in attachments or []:
        payload = item["content"]
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        maintype, subtype = item.get("mimetype", "application/octet-stream").split("/", 1)
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=item["filename"])

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(username, password)
        refused = server.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    return message["Message-ID"]
