"""E-posta gönderimi: sınıflandırma ve içerik (smtplib sahte sınıfla değiştirilir)."""
from __future__ import annotations

import smtplib

from bulten.config import load_config
from bulten.delivery.email import EmailSender


class FakeSMTP:
    sent = []
    fail_on = None

    def __init__(self, host, port, timeout=30, **kw):
        if FakeSMTP.fail_on == "connect":
            raise ConnectionRefusedError("refused")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, u, p):
        if FakeSMTP.fail_on == "auth":
            raise smtplib.SMTPAuthenticationError(535, b"bad")

    def send_message(self, msg):
        if FakeSMTP.fail_on == "disconnect":
            raise smtplib.SMTPServerDisconnected("gone")
        if FakeSMTP.fail_on == "busy":
            raise smtplib.SMTPDataError(451, b"try later")
        FakeSMTP.sent.append(msg)
        return {}


def test_email_classification(tmp_path, monkeypatch):
    from helpers import make_config
    make_config(tmp_path)
    cfg = load_config()
    cfg.smtp_host, cfg.email_from, cfg.smtp_user, cfg.smtp_password = "smtp.example.org", "bulten@example.org", "u", "p"
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    s = EmailSender(cfg)
    FakeSMTP.fail_on = None
    r = s.send("me@example.org", "Konu", "<p>x</p>", "x", idempotency_key="k1")
    assert r.classification == "sent"
    msg = FakeSMTP.sent[-1]
    assert msg["Message-ID"] == EmailSender(cfg).send("me@example.org", "Konu", "<p>x</p>", "x", idempotency_key="k1").message_id
    for fail, expected in (("connect", "retryable"), ("auth", "permanent"), ("disconnect", "uncertain"), ("busy", "retryable")):
        FakeSMTP.fail_on = fail
        assert s.send("me@example.org", "K", "<p/>", "t", idempotency_key="k2").classification == expected, fail
    FakeSMTP.fail_on = None
