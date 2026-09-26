"""Kullanıcı aksiyonları (Okudum / Takip et / Sustur) ve e-posta için imzalı aksiyon bağlantıları.

Gönderim hiçbir zaman "okundu" sayılmaz. "Okundu" yalnızca açık kullanıcı aksiyonuyla (web düğmesi,
Telegram düğmesi, e-postadaki bağlantıdan açılan onay sayfası) işaretlenir.
"""
from __future__ import annotations

import sqlite3

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import load_config
from ..db import tx
from ..timeutil import now_iso

ACTIONS = {"read", "unread", "follow", "unfollow", "mute", "unmute", "view"}
ACTION_TR = {"read": "Okundu olarak işaretlendi", "unread": "Okunmadı olarak işaretlendi",
             "follow": "Takibe alındı", "unfollow": "Takipten çıkarıldı", "mute": "Susturuldu",
             "unmute": "Susturma kaldırıldı", "view": "Görüntülendi"}


def _ensure_row(conn: sqlite3.Connection, event_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO user_event_state(event_id, updated_at) VALUES (?, ?)", (event_id, now_iso()))


def apply_action(conn: sqlite3.Connection, event_id: int, action: str, *, via: str, version: int | None = None) -> bool:
    if action not in ACTIONS:
        raise ValueError(f"Bilinmeyen aksiyon: {action}")
    ev = conn.execute("SELECT id, current_version FROM events WHERE id = ?", (event_id,)).fetchone()
    if ev is None:
        return False
    ver = version or ev["current_version"]
    ts = now_iso()
    with tx(conn):
        _ensure_row(conn, event_id)
        if action == "read":
            conn.execute("UPDATE user_event_state SET read_at = ?, read_version = MAX(COALESCE(read_version, 0), ?), "
                         "updated_at = ? WHERE event_id = ?", (ts, ver, ts, event_id))
        elif action == "unread":
            conn.execute("UPDATE user_event_state SET read_at = NULL, read_version = NULL, updated_at = ? WHERE event_id = ?",
                         (ts, event_id))
        elif action == "follow":
            conn.execute("UPDATE user_event_state SET followed = 1, followed_at = ?, updated_at = ? WHERE event_id = ?",
                         (ts, ts, event_id))
            conn.execute("UPDATE events SET relevance = relevance + 3 WHERE id = ?", (event_id,))
        elif action == "unfollow":
            row = conn.execute("SELECT followed FROM user_event_state WHERE event_id = ?", (event_id,)).fetchone()
            conn.execute("UPDATE user_event_state SET followed = 0, updated_at = ? WHERE event_id = ?", (ts, event_id))
            if row and row["followed"]:
                conn.execute("UPDATE events SET relevance = relevance - 3 WHERE id = ?", (event_id,))
        elif action == "mute":
            conn.execute("UPDATE user_event_state SET muted_at = ?, muted_version = ?, updated_at = ? WHERE event_id = ?",
                         (ts, ver, ts, event_id))
        elif action == "unmute":
            conn.execute("UPDATE user_event_state SET muted_at = NULL, muted_version = NULL, updated_at = ? "
                         "WHERE event_id = ?", (ts, event_id))
        elif action == "view":
            conn.execute("UPDATE user_event_state SET viewed_at = COALESCE(viewed_at, ?), "
                         "viewed_version = MAX(COALESCE(viewed_version, 0), ?), updated_at = ? WHERE event_id = ?",
                         (ts, ver, ts, event_id))
        conn.execute("INSERT INTO user_actions(event_id, action, via, version, at) VALUES (?, ?, ?, ?, ?)",
                     (event_id, action, via, ver, ts))
    return True


def mark_viewed(conn: sqlite3.Connection, event_ids: list[int]) -> None:
    for eid in set(event_ids):
        row = conn.execute("SELECT viewed_version, (SELECT current_version FROM events WHERE id = ?) AS cv "
                           "FROM user_event_state WHERE event_id = ?", (eid, eid)).fetchone()
        if row and row["viewed_version"] and row["cv"] and row["viewed_version"] >= row["cv"]:
            continue
        apply_action(conn, eid, "view", via="web")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(load_config().secret_key, salt="bulten-eylem")


def make_action_token(event_id: int, version: int, action: str) -> str:
    return _serializer().dumps({"e": event_id, "v": version, "a": action})


def read_action_token(token: str, max_age_days: int = 45) -> dict | None:
    try:
        data = _serializer().loads(token, max_age=max_age_days * 86400)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or data.get("a") not in ACTIONS:
        return None
    return data


def action_url(event_id: int, version: int, action: str) -> str:
    return f"{load_config().app_base_url}/eylem/{make_action_token(event_id, version, action)}"
