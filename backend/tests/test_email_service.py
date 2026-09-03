import smtplib

import pytest

from services import email_service


class FakeSMTP:
    refused = {}
    message = None

    def __init__(self, host, port, timeout):
        assert host == "smtp.gmail.com"
        assert port == 587
        assert timeout == 30

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def ehlo(self):
        return None

    def starttls(self):
        return None

    def login(self, username, password):
        assert username == "openvisionx@gmail.com"
        assert password == "test-app-password"

    def send_message(self, message):
        type(self).message = message
        return type(self).refused


@pytest.fixture(autouse=True)
def smtp_environment(monkeypatch):
    monkeypatch.setenv("MAIL_SMTP_USERNAME", "openvisionx@gmail.com")
    monkeypatch.setenv("MAIL_SMTP_APP_PASSWORD", "test-app-password")
    monkeypatch.setenv("MAIL_SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("MAIL_SMTP_PORT", "587")
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.refused = {}
    FakeSMTP.message = None


def test_send_email_sets_traceable_headers_and_recipient():
    message_id = email_service.send_email(
        "Attendance report", "Attached report", "recipient@example.com",
    )

    assert FakeSMTP.message["To"] == "recipient@example.com"
    assert FakeSMTP.message["Date"]
    assert FakeSMTP.message["Message-ID"] == message_id


def test_send_email_does_not_mark_refused_recipient_as_sent():
    FakeSMTP.refused = {"recipient@example.com": (550, b"rejected")}

    with pytest.raises(smtplib.SMTPRecipientsRefused):
        email_service.send_email("Attendance report", "Attached report", "recipient@example.com")
