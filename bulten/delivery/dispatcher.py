"""Gönderim kuyruğu: idempotency, parça bazlı yeniden deneme ve gönderim kayıtları.

- Her gönderimin benzersiz bir idempotency anahtarı vardır (ör. "bulletin:daily:2026-09-26:telegram:1001").
  Aynı anahtarla ikinci kez kuyruğa ekleme yapılmaz → aynı bülten/aynı olay sürümü iki kez gönderilmez.
- Telegram bülteni birden çok mesajdan oluşur; her mesaj ayrı bir "parça"dır. Yeniden denemede yalnızca
  gönderilmemiş parçalar gönderilir.
- Sonucu belirsiz parçalar (gönderildi ama yanıt alınamadı) otomatik yeniden gönderilmez.
- Worker çökerse "sending" durumunda kalan parçalar başlangıçta "uncertain" yapılır.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from datetime import timedelta

from ..config import load_config
from ..db import jdump, jload, tx
from ..settings_store import get_settings
from ..timeutil import now_iso, now_utc, to_iso
from .email import EmailSender
from .render import email_alert, email_bulletin, telegram_alert_messages, telegram_bulletin_messages
from .telegram import SendResult, TelegramClient

log = logging.getLogger(__name__)

BACKOFF_MIN = [1, 5, 15, 60, 180]
MAX_ATTEMPTS = 6


def active_channels(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(kanal, alıcı) listesi: kullanıcı açmış VE sunucuda yapılandırılmış olanlar."""
    cfg = load_config()
    s = get_settings(conn)
    ch = s.get("channels") or {}
    out = []
    if ch.get("telegram") and cfg.telegram_configured and s.get("telegram_chat_id"):
        out.append(("telegram", str(s["telegram_chat_id"])))
    if ch.get("email") and cfg.email_configured and s.get("email_to"):
        out.append(("email", str(s["email_to"])))
    return out


def channel_problems(conn: sqlite3.Connection) -> list[str]:
    cfg = load_config()
    s = get_settings(conn)
    ch = s.get("channels") or {}
    probs = []
    if ch.get("telegram"):
        if not cfg.telegram_bot_token:
            probs.append("Telegram seçili ama TELEGRAM_BOT_TOKEN tanımlı değil (.env).")
        elif not s.get("telegram_chat_id"):
            probs.append("Telegram sohbet kimliği (chat id) girilmedi.")
    if ch.get("email"):
        if not cfg.email_configured:
            probs.append("E-posta seçili ama SMTP ayarları eksik (.env: SMTP_HOST, EMAIL_FROM).")
        elif not s.get("email_to"):
            probs.append("E-posta alıcısı girilmedi.")
    if not ch.get("telegram") and not ch.get("email"):
        probs.append("Hiçbir bildirim kanalı seçilmedi; bülten yalnızca uygulamada görünür.")
    return probs


def _insert_delivery(conn: sqlite3.Connection, *, key: str, channel: str, kind: str, recipient: str,
                     bulletin_id: int | None, parts: list[dict], items: list[tuple[int, int, str]]) -> int | None:
    with tx(conn):
        if conn.execute("SELECT 1 FROM deliveries WHERE idempotency_key = ?", (key,)).fetchone():
            return None
        did = conn.execute(
            "INSERT INTO deliveries(idempotency_key, channel, kind, bulletin_id, recipient, status, attempts, "
            "next_attempt_at, created_at) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
            (key, channel, kind, bulletin_id, recipient, now_iso(), now_iso()),
        ).lastrowid
        for i, p in enumerate(parts):
            conn.execute("INSERT INTO delivery_parts(delivery_id, seq, payload_json, status) VALUES (?, ?, ?, 'pending')",
                         (did, i, jdump(p)))
        for vid, eid, mode in items:
            conn.execute("INSERT OR IGNORE INTO delivery_items(delivery_id, event_version_id, event_id, render_mode) "
                         "VALUES (?, ?, ?, ?)", (did, vid, eid, mode))
    return did


def enqueue_bulletin(conn: sqlite3.Connection, bulletin_id: int) -> list[int]:
    b = conn.execute("SELECT * FROM bulletins WHERE id = ?", (bulletin_id,)).fetchone()
    items = [(r["event_version_id"], r["event_id"], r["render_mode"]) for r in
             conn.execute("SELECT * FROM bulletin_items WHERE bulletin_id = ?", (bulletin_id,))]
    ids = []
    for channel, recipient in active_channels(conn):
        key = f"bulletin:{b['slot']}:{channel}:{recipient}"
        if channel == "telegram":
            parts = telegram_bulletin_messages(conn, bulletin_id)
        else:
            parts = [email_bulletin(conn, bulletin_id)]
        did = _insert_delivery(conn, key=key, channel=channel, kind="bulletin", recipient=recipient,
                               bulletin_id=bulletin_id, parts=parts, items=items)
        if did:
            ids.append(did)
    return ids


def enqueue_alert(conn: sqlite3.Connection, version_ids: list[int]) -> list[int]:
    if not version_ids:
        return []
    vids = sorted(set(version_ids))
    digest = hashlib.sha1(",".join(map(str, vids)).encode()).hexdigest()[:12]
    ev_ids = {r["id"]: r["event_id"] for r in conn.execute(
        f"SELECT id, event_id FROM event_versions WHERE id IN ({','.join('?' * len(vids))})", vids)}
    items = [(v, ev_ids[v], "full") for v in vids if v in ev_ids]
    ids = []
    for channel, recipient in active_channels(conn):
        key = f"alert:{channel}:{recipient}:{digest}"
        parts = telegram_alert_messages(conn, vids) if channel == "telegram" else [email_alert(conn, vids)]
        did = _insert_delivery(conn, key=key, channel=channel, kind="alert", recipient=recipient, bulletin_id=None,
                               parts=parts, items=items)
        if did:
            ids.append(did)
    return ids


def enqueue_test(conn: sqlite3.Connection, channel: str) -> int | None:
    for ch, recipient in active_channels(conn):
        if ch != channel:
            continue
        key = f"test:{channel}:{recipient}:{now_iso()}"
        text = "Kişisel Sabah Bülteni: test mesajı. Bu kanal çalışıyor."
        parts = ([{"text": text, "reply_markup": None, "silent": False}] if channel == "telegram"
                 else [{"subject": "Sabah Bülteni test e-postası", "html": f"<p>{text}</p>", "text": text}])
        return _insert_delivery(conn, key=key, channel=channel, kind="test", recipient=recipient, bulletin_id=None,
                                parts=parts, items=[])
    return None


def recover_stuck(conn: sqlite3.Connection) -> int:
    """Başlangıçta: 'sending' parçaları belirsiz sayılır (çökme sırasında gönderilmiş olabilir)."""
    with tx(conn):
        n = conn.execute("UPDATE delivery_parts SET status = 'uncertain', last_error = COALESCE(last_error, '') || "
                         "' [worker yeniden başladı; gönderim sonucu bilinmiyor]' WHERE status = 'sending'").rowcount
        for r in conn.execute("SELECT DISTINCT delivery_id FROM delivery_parts WHERE status = 'uncertain'").fetchall():
            _refresh_status(conn, r["delivery_id"])
    return n


def resend_uncertain(conn: sqlite3.Connection, delivery_id: int) -> int:
    with tx(conn):
        n = conn.execute("UPDATE delivery_parts SET status = 'pending' WHERE delivery_id = ? AND status IN ('uncertain', 'failed')",
                         (delivery_id,)).rowcount
        conn.execute("UPDATE deliveries SET status = 'pending', next_attempt_at = ?, attempts = 0 WHERE id = ?",
                     (now_iso(), delivery_id))
    return n


def _refresh_status(conn: sqlite3.Connection, delivery_id: int) -> str:
    rows = [r["status"] for r in conn.execute("SELECT status FROM delivery_parts WHERE delivery_id = ?", (delivery_id,))]
    if rows and all(s == "sent" for s in rows):
        status = "sent"
    elif any(s == "pending" for s in rows):
        status = "pending"
    elif any(s == "uncertain" for s in rows):
        status = "uncertain"
    elif any(s == "sent" for s in rows):
        status = "partial"
    else:
        status = "failed"
    conn.execute("UPDATE deliveries SET status = ?, sent_at = CASE WHEN ? IN ('sent','partial') THEN COALESCE(sent_at, ?) "
                 "ELSE sent_at END WHERE id = ?", (status, status, now_iso(), delivery_id))
    return status


def _send_part(channel: str, recipient: str, payload: dict, key: str, *, telegram: TelegramClient | None,
               email: EmailSender | None) -> SendResult:
    if channel == "telegram":
        if telegram is None:
            return SendResult("retryable", error="Telegram yapılandırılmadı.")
        return telegram.send_message(recipient, payload["text"], reply_markup=payload.get("reply_markup"),
                                     silent=bool(payload.get("silent")))
    if email is None:
        return SendResult("retryable", error="E-posta yapılandırılmadı.")
    return email.send(recipient, payload["subject"], payload["html"], payload["text"], idempotency_key=key)


def process_deliveries(conn: sqlite3.Connection, *, telegram: TelegramClient | None = None,
                       email: EmailSender | None = None, part_delay: float = 1.05) -> dict:
    cfg = load_config()
    if telegram is None and cfg.telegram_configured:
        telegram = TelegramClient(cfg)
    if email is None and cfg.email_configured:
        email = EmailSender(cfg)
    stats = {"sent": 0, "retry": 0, "failed": 0, "uncertain": 0}
    due = conn.execute("SELECT * FROM deliveries WHERE status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
                       "ORDER BY id", (now_iso(),)).fetchall()
    for d in due:
        parts = conn.execute("SELECT * FROM delivery_parts WHERE delivery_id = ? AND status = 'pending' ORDER BY seq",
                             (d["id"],)).fetchall()
        attempts = d["attempts"] + 1
        conn.execute("UPDATE deliveries SET attempts = ? WHERE id = ?", (attempts, d["id"]))
        for i, p in enumerate(parts):
            # Önce "sending" olarak işaretle ve kaydet: çökme olursa parça belirsiz kalır, tekrar gönderilmez.
            conn.execute("UPDATE delivery_parts SET status = 'sending', attempts = attempts + 1 WHERE id = ?", (p["id"],))
            res = _send_part(d["channel"], d["recipient"], jload(p["payload_json"], {}), d["idempotency_key"],
                             telegram=telegram, email=email)
            ts = now_iso()
            with tx(conn):
                conn.execute("INSERT INTO delivery_attempts(delivery_id, part_id, at, ok, classification, error) "
                             "VALUES (?, ?, ?, ?, ?, ?)", (d["id"], p["id"], ts, 1 if res.classification == "sent" else 0,
                                                           res.classification, res.error))
                if res.classification == "sent":
                    conn.execute("UPDATE delivery_parts SET status = 'sent', provider_message_id = ?, sent_at = ?, "
                                 "last_error = NULL WHERE id = ?", (res.message_id, ts, p["id"]))
                    stats["sent"] += 1
                elif res.classification == "uncertain":
                    conn.execute("UPDATE delivery_parts SET status = 'uncertain', last_error = ? WHERE id = ?",
                                 (res.error, p["id"]))
                    stats["uncertain"] += 1
                elif res.classification == "permanent":
                    conn.execute("UPDATE delivery_parts SET status = 'failed', last_error = ? WHERE id = ?",
                                 (res.error, p["id"]))
                    stats["failed"] += 1
                else:  # retryable
                    conn.execute("UPDATE delivery_parts SET status = 'pending', last_error = ? WHERE id = ?",
                                 (res.error, p["id"]))
                    if attempts >= MAX_ATTEMPTS:
                        conn.execute("UPDATE delivery_parts SET status = 'failed' WHERE delivery_id = ? AND status = 'pending'",
                                     (d["id"],))
                        stats["failed"] += 1
                    else:
                        wait = res.retry_after or 60 * BACKOFF_MIN[min(attempts - 1, len(BACKOFF_MIN) - 1)]
                        conn.execute("UPDATE deliveries SET next_attempt_at = ?, last_error = ? WHERE id = ?",
                                     (to_iso(now_utc() + timedelta(seconds=wait)), res.error, d["id"]))
                        stats["retry"] += 1
                    _refresh_status(conn, d["id"])
                    break
                _refresh_status(conn, d["id"])
            if i < len(parts) - 1 and part_delay:
                time.sleep(part_delay)
        with tx(conn):
            status = _refresh_status(conn, d["id"])
            if status != "pending":
                conn.execute("UPDATE deliveries SET last_error = (SELECT last_error FROM delivery_parts WHERE delivery_id = ? "
                             "AND last_error IS NOT NULL ORDER BY seq DESC LIMIT 1) WHERE id = ?", (d["id"], d["id"]))
    return stats


def delivery_overview(conn: sqlite3.Connection, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT d.*, (SELECT COUNT(*) FROM delivery_parts p WHERE p.delivery_id = d.id) AS parts, "
        "(SELECT COUNT(*) FROM delivery_parts p WHERE p.delivery_id = d.id AND p.status = 'sent') AS parts_sent "
        "FROM deliveries d ORDER BY d.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

