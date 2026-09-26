"""SMTP e-posta gönderimi.

Sınıflandırma Telegram ile aynı mantıktadır. Message-ID, idempotency anahtarından türetilir; aynı
gönderimin olası bir kopyası alıcı tarafında aynı ileti olarak tanınabilir.
"""
from __future__ import annotations

import hashlib
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formatdate

from ..config import Config, load_config
from .telegram import SendResult


class EmailSender:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or load_config()

    def send(self, to: str, subject: str, html: str, text: str, *, idempotency_key: str) -> SendResult:
        cfg = self.cfg
        msg = EmailMessage()
        msg["From"] = cfg.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        domain = cfg.email_from.split("@")[-1] if "@" in cfg.email_from else "bulten.local"
        msg["Message-ID"] = f"<{hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]}@{domain}>"
        msg.set_content(text or "HTML içerik görüntülenemedi.")
        msg.add_alternative(html, subtype="html")
        stage = "connect"
        try:
            context = ssl.create_default_context()
            if cfg.smtp_security == "ssl":
                server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30, context=context)
            else:
                server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
            with server:
                if cfg.smtp_security == "starttls":
                    server.starttls(context=context)
                if cfg.smtp_user:
                    server.login(cfg.smtp_user, cfg.smtp_password)
                stage = "send"
                refused = server.send_message(msg)
            if refused:
                return SendResult("permanent", error=f"Alıcı reddedildi: {', '.join(refused)}")
            return SendResult("sent", message_id=msg["Message-ID"])
        except smtplib.SMTPAuthenticationError as exc:
            return SendResult("permanent", error=f"SMTP kimlik doğrulama hatası: {exc.smtp_code}")
        except smtplib.SMTPRecipientsRefused as exc:
            return SendResult("permanent", error=f"Alıcı reddedildi: {list(exc.recipients)}")
        except smtplib.SMTPResponseException as exc:
            if 400 <= exc.smtp_code < 500:
                return SendResult("retryable", error=f"SMTP geçici hata {exc.smtp_code}")
            return SendResult("permanent", error=f"SMTP hata {exc.smtp_code}")
        except (smtplib.SMTPServerDisconnected, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            if stage == "send":
                return SendResult("uncertain", error=f"Gönderim sırasında bağlantı koptu: {exc}")
            return SendResult("retryable", error=f"SMTP sunucusuna bağlanılamadı: {exc}")
