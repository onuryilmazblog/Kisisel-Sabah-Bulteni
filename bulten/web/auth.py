"""Tek kullanıcılı oturum ve CSRF koruması.

- APP_PASSWORD tanımlıysa giriş gerekir; oturum imzalı çerezdedir (30 gün).
- APP_PASSWORD yoksa yalnızca yerel (loopback) istemcilere izin verilir.
- Durum değiştiren tüm istekler CSRF belirteci ister (form alanı veya X-CSRF-Token başlığı).
"""
from __future__ import annotations

import hmac
import ipaddress
import secrets
import time

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.requests import Request

from ..config import load_config

COOKIE = "bulten_oturum"
MAX_AGE = 30 * 86400
_login_attempts: dict[str, list[float]] = {}


def _ser() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(load_config().secret_key, salt="bulten-oturum")


def make_session() -> str:
    return _ser().dumps({"u": "owner", "csrf": secrets.token_urlsafe(24)})


def read_session(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _ser().loads(raw, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data if isinstance(data, dict) else None


def is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("testclient", "localhost")


def password_ok(candidate: str) -> bool:
    expected = load_config().app_password
    return bool(expected) and hmac.compare_digest(candidate.encode(), expected.encode())


def rate_limited(request: Request) -> bool:
    key = request.client.host if request.client else "?"
    now = time.time()
    attempts = [t for t in _login_attempts.get(key, []) if now - t < 600]
    _login_attempts[key] = attempts
    return len(attempts) >= 8


def note_failed_login(request: Request) -> None:
    key = request.client.host if request.client else "?"
    _login_attempts.setdefault(key, []).append(time.time())


def csrf_token_for(request: Request) -> str:
    sess = getattr(request.state, "session", None)
    if sess:
        return sess["csrf"]
    # Parola yoksa (yerel kullanım): çerez tabanlı çift gönderim belirteci
    return request.cookies.get("bulten_csrf") or getattr(request.state, "new_csrf", "")


def csrf_valid(request: Request, submitted: str | None) -> bool:
    expected = csrf_token_for(request)
    return bool(expected) and bool(submitted) and hmac.compare_digest(expected, submitted)
