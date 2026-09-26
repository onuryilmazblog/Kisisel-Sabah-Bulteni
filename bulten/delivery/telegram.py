"""Telegram Bot API istemcisi, geri çağrı (düğme) işleme ve long polling.

Gönderim sonucu sınıflandırması (idempotency için kritik):
  sent       → Telegram mesaj kimliği döndü.
  retryable  → İstek Telegram'a ulaşmadı (bağlantı kurulamadı), 429 veya 5xx: güvenle yeniden denenir.
  uncertain  → İstek gönderildi ama yanıt alınamadı (okuma zaman aşımı, bağlantı koptu): mesaj
               ulaşmış olabilir. Otomatik yeniden gönderilmez; arayüzde "yeniden gönder" ile elle.
  permanent  → 400/401/403 vb.: düzeltme gerektirir (yanlış chat id, bot engellendi, geçersiz token).
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Config, load_config
from ..db import connect, kv_get, kv_set
from ..settings_store import get_settings
from ..timeutil import now_iso
from .actions import ACTION_TR, apply_action

log = logging.getLogger(__name__)


@dataclass
class SendResult:
    classification: str            # sent|retryable|uncertain|permanent
    message_id: str | None = None
    error: str | None = None
    retry_after: int | None = None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


class TelegramClient:
    def __init__(self, cfg: Config | None = None, http: httpx.Client | None = None):
        self.cfg = cfg or load_config()
        self.base = f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}"
        self.http = http or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    def _post(self, method: str, payload: dict[str, Any], timeout: float | None = None) -> SendResult:
        try:
            r = self.http.post(f"{self.base}/{method}", json=payload, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            return SendResult("retryable", error=f"Bağlantı kurulamadı: {exc.__class__.__name__}")
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError, httpx.ReadError) as exc:
            return SendResult("uncertain", error=f"Yanıt alınamadı ({exc.__class__.__name__}); mesaj ulaşmış olabilir.")
        except httpx.HTTPError as exc:
            return SendResult("retryable", error=str(exc))
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 200 and data.get("ok"):
            res = data.get("result")
            mid = str(res.get("message_id")) if isinstance(res, dict) and res.get("message_id") else None
            return SendResult("sent", message_id=mid)
        desc = data.get("description") or f"HTTP {r.status_code}"
        if r.status_code == 429:
            ra = (data.get("parameters") or {}).get("retry_after") or 30
            return SendResult("retryable", error=desc, retry_after=int(ra))
        if r.status_code >= 500:
            return SendResult("retryable", error=desc)
        return SendResult("permanent", error=desc)

    def send_message(self, chat_id: str, text: str, *, reply_markup: dict | None = None, silent: bool = False,
                     parse_mode: str | None = "HTML") -> SendResult:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True,
                                   "disable_notification": silent}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        res = self._post("sendMessage", payload)
        if res.classification == "permanent" and parse_mode and "parse" in (res.error or "").lower():
            # HTML ayrıştırma hatası: düz metin olarak bir kez dene.
            payload.pop("parse_mode", None)
            payload["text"] = _strip_html(text)
            res = self._post("sendMessage", payload)
        return res

    def answer_callback(self, callback_id: str, text: str) -> None:
        self._post("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:180]})

    def edit_markup(self, chat_id: str, message_id: int, markup: dict | None) -> None:
        self._post("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id,
                                              "reply_markup": markup or {"inline_keyboard": []}})

    def get_updates(self, offset: int | None, timeout: int = 50) -> list[dict]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        try:
            r = self.http.post(f"{self.base}/getUpdates", json=payload, timeout=timeout + 15)
            data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("getUpdates hatası: %s", exc)
            time.sleep(5)
            return []
        if not data.get("ok"):
            log.warning("getUpdates başarısız: %s", data.get("description"))
            time.sleep(10)
            return []
        return data.get("result") or []

    def get_me(self) -> dict | None:
        try:
            r = self.http.get(f"{self.base}/getMe", timeout=15)
            data = r.json()
            return data.get("result") if data.get("ok") else None
        except (httpx.HTTPError, ValueError):
            return None


# --- Güncelleme işleme ------------------------------------------------------------------

def handle_update(conn: sqlite3.Connection, client: TelegramClient, update: dict, *, enqueue_job=None) -> str | None:
    """Tek bir Telegram güncellemesini işler. Yalnızca yapılandırılmış sohbetten gelenler kabul edilir."""
    settings = get_settings(conn)
    allowed_chat = str(settings.get("telegram_chat_id") or "")
    if "callback_query" in update:
        cq = update["callback_query"]
        msg = cq.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        if not allowed_chat or chat_id != allowed_chat:
            client.answer_callback(cq["id"], "Bu sohbet yetkili değil.")
            return "unauthorized"
        data = cq.get("data") or ""
        parts = data.split(":")
        try:
            if parts[0] == "r":
                apply_action(conn, int(parts[1]), "read", via="telegram", version=int(parts[2]))
                client.answer_callback(cq["id"], ACTION_TR["read"])
            elif parts[0] == "f":
                row = conn.execute("SELECT followed FROM user_event_state WHERE event_id = ?", (int(parts[1]),)).fetchone()
                action = "unfollow" if row and row["followed"] else "follow"
                apply_action(conn, int(parts[1]), action, via="telegram")
                client.answer_callback(cq["id"], ACTION_TR[action])
            elif parts[0] == "m":
                apply_action(conn, int(parts[1]), "mute", via="telegram", version=int(parts[2]))
                client.answer_callback(cq["id"], ACTION_TR["mute"])
            elif parts[0] == "rb":
                rows = conn.execute("SELECT event_id, event_version_id FROM bulletin_items WHERE bulletin_id = ? AND section = ?",
                                    (int(parts[1]), parts[2])).fetchall()
                for r in rows:
                    ver = conn.execute("SELECT version FROM event_versions WHERE id = ?", (r["event_version_id"],)).fetchone()
                    apply_action(conn, r["event_id"], "read", via="telegram", version=ver["version"] if ver else None)
                client.answer_callback(cq["id"], f"{len(rows)} haber okundu olarak işaretlendi")
            else:
                client.answer_callback(cq["id"], "Bilinmeyen işlem.")
                return "unknown"
        except (ValueError, IndexError):
            client.answer_callback(cq["id"], "Geçersiz işlem verisi.")
            return "invalid"
        return parts[0]
    if "message" in update:
        msg = update["message"]
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if text.startswith("/start") or text.startswith("/kimlik"):
            client.send_message(chat_id, f"Merhaba. Bu sohbetin kimliği: <code>{chat_id}</code>\n"
                                         "Uygulamada Ayarlar → Bildirimler bölümüne bu kimliği girin.")
            kv_set(conn, "telegram_last_seen_chat", chat_id)
            return "start"
        if not allowed_chat or chat_id != allowed_chat:
            return "unauthorized"
        if text.startswith("/durum"):
            last = kv_get(conn, "last_success_check_at") or "henüz yok"
            hb = kv_get(conn, "worker_heartbeat") or "yok"
            client.send_message(chat_id, f"Son başarılı kontrol: {last}\nWorker nabzı: {hb}", parse_mode=None)
            return "status"
        if text.startswith("/kontrol") and enqueue_job:
            enqueue_job(conn, "check_now", "telegram")
            client.send_message(chat_id, "Kontrol sıraya alındı.", parse_mode=None)
            return "check"
        if text.startswith("/bulten") and enqueue_job:
            enqueue_job(conn, "send_preview", "telegram")
            client.send_message(chat_id, "Anlık bülten önizlemesi hazırlanıyor.", parse_mode=None)
            return "preview"
        client.send_message(chat_id, "Komutlar: /durum, /kontrol, /bulten, /kimlik", parse_mode=None)
        return "help"
    return None


class TelegramPoller(threading.Thread):
    """Worker içinde çalışan long-polling iş parçacığı. Ofset DB'de saklanır (yeniden başlatmada kaybolmaz)."""

    def __init__(self, db_path, enqueue_job=None, stop_event: threading.Event | None = None):
        super().__init__(name="telegram-poller", daemon=True)
        self.db_path = db_path
        self.enqueue_job = enqueue_job
        self.stop_event = stop_event or threading.Event()

    def run(self) -> None:
        cfg = load_config()
        if not cfg.telegram_configured or cfg.telegram_mode != "polling":
            return
        client = TelegramClient(cfg)
        conn = connect(self.db_path)
        while not self.stop_event.is_set():
            raw = kv_get(conn, "telegram_offset")
            offset = int(raw) if raw else None
            updates = client.get_updates(offset, timeout=50)
            for up in updates:
                try:
                    handle_update(conn, client, up, enqueue_job=self.enqueue_job)
                except Exception:  # noqa: BLE001
                    log.exception("Telegram güncellemesi işlenemedi")
                kv_set(conn, "telegram_offset", str(int(up["update_id"]) + 1))
            kv_set(conn, "telegram_poll_at", now_iso())
