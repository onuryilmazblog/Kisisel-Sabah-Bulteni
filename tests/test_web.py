"""Web arayüzü duman testleri: sayfalar, CSRF, oturum, e-posta aksiyon onayı."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from helpers import FakeFetcher, freeze, make_db, only_sources, wrh_page

from bulten.config import load_config
from bulten.delivery.actions import make_action_token
from bulten.demo import load_demo
from bulten.pipeline.run import collect_and_process

WRH25 = "https://learn.microsoft.com/en-us/windows/release-health/status-windows-11-25h2"


@pytest.fixture
def client(tmp_path):
    freeze(2026, 9, 24, 5, 10)
    conn = make_db(tmp_path)
    ff = FakeFetcher(pages={WRH25: wrh_page([dict(id="9201", title="Remote Desktop connections might fail", kb="5999100",
                                                  body="After installing KB5999100 RDP fails.", client="Windows 11, version 25H2")])})
    collect_and_process(conn, fetcher=ff, source_ids=only_sources(conn, ["wrh-status-win11-25h2"]))
    load_demo(conn)
    from bulten.web import app as webapp
    webapp._initialized = False
    with TestClient(webapp.app, base_url="http://127.0.0.1") as c:
        c.conn = conn
        yield c


def csrf_of(html: str) -> str:
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def test_pages_render(client):
    for path in ["/", "/kritik", "/takip", "/arsiv", "/arsiv?q=KB5999100&status=open", "/arsiv?demo=1", "/ayarlar",
                 "/kurulum", "/kaynaklar", "/durum", "/saglik"]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.text[:500])
    ev = client.conn.execute("SELECT id FROM events WHERE is_demo = 0 LIMIT 1").fetchone()[0]
    r = client.get(f"/olay/{ev}")
    assert r.status_code == 200 and "Kanıtlar" in r.text


def test_actions_require_csrf_and_do_not_mark_read_on_view(client):
    ev = client.conn.execute("SELECT id FROM events WHERE is_demo = 0 LIMIT 1").fetchone()[0]
    page = client.get(f"/olay/{ev}")
    token = csrf_of(page.text)
    st = client.conn.execute("SELECT viewed_at, read_at FROM user_event_state WHERE event_id = ?", (ev,)).fetchone()
    assert st["viewed_at"] is not None and st["read_at"] is None, "görüntüleme okundu sayılmaz"
    assert client.post(f"/api/olay/{ev}/read").status_code == 403
    r = client.post(f"/api/olay/{ev}/read", headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and r.json()["ok"]
    st = client.conn.execute("SELECT read_at FROM user_event_state WHERE event_id = ?", (ev,)).fetchone()
    assert st["read_at"] is not None


def test_email_action_link_requires_confirmation(client):
    ev = client.conn.execute("SELECT id, current_version FROM events WHERE is_demo = 0 LIMIT 1").fetchone()
    tok = make_action_token(ev["id"], ev["current_version"], "mute")
    r = client.get(f"/eylem/{tok}")
    assert r.status_code == 200 and "Onayla" in r.text
    assert client.conn.execute("SELECT muted_at FROM user_event_state WHERE event_id = ?", (ev["id"],)).fetchone() is None or \
        client.conn.execute("SELECT muted_at FROM user_event_state WHERE event_id = ?", (ev["id"],)).fetchone()["muted_at"] is None
    r = client.post(f"/eylem/{tok}")
    assert r.status_code == 200
    assert client.conn.execute("SELECT muted_at FROM user_event_state WHERE event_id = ?", (ev["id"],)).fetchone()["muted_at"]
    assert client.get("/eylem/bozuk-token").status_code == 400


def test_settings_save_and_ssrf_rejection(client):
    token = csrf_of(client.get("/ayarlar").text)
    form = {"_csrf": token, "_sections": ["bildirim"], "ch_telegram": "on", "telegram_chat_id": "12345",
            "crit_enabled": "on", "crit_interval": "60", "crit_min_risk": "high", "crit_min_evidence": "ms_official",
            "resurface_read": "notify", "resurface_muted": "silent"}
    r = client.post("/ayarlar", data=form, follow_redirects=False)
    assert r.status_code == 303
    from bulten.settings_store import get_settings
    s = get_settings(client.conn)
    assert s["telegram_chat_id"] == "12345" and s["critical"]["enabled"] is True
    r = client.post("/kaynaklar/ekle", data={"_csrf": token, "name": "iç ağ", "url": "http://192.168.1.10/feed",
                                             "module": "community", "trust": "official"}, follow_redirects=False)
    assert r.status_code == 303 and "hata=" in r.headers["location"]
    r = client.post("/kaynaklar/ekle", data={"_csrf": token, "name": "loc", "url": "http://localhost:8080/rss",
                                             "module": "community"}, follow_redirects=False)
    assert "hata=" in r.headers["location"]


def test_password_mode_requires_login(client):
    cfg = load_config()
    cfg.app_password = "gizli-parola"
    try:
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/giris"
        assert client.post("/giris", data={"password": "yanlis"}).status_code == 401
        r = client.post("/giris", data={"password": "gizli-parola"}, follow_redirects=False)
        assert r.status_code == 303
        assert client.get("/").status_code == 200
    finally:
        cfg.app_password = ""


def test_remote_access_blocked_without_password(tmp_path):
    freeze(2026, 9, 24, 5, 10)
    make_db(tmp_path)
    from bulten.web import app as webapp
    with TestClient(webapp.app, base_url="http://example.org", client=("203.0.113.5", 5000)) as c:
        r = c.get("/")
        assert r.status_code == 403


def test_reddit_credentials_shown_only_as_defined_or_not(client):
    from helpers import enable_reddit_api

    kaynak, durum = client.get("/kaynaklar").text, client.get("/durum").text
    assert "Reddit API kimlik bilgileri (.env): tanımlı değil" in kaynak
    assert "Reddit Data API tanımlı değil" in durum and "REDDIT_CLIENT_SECRET" in durum
    cfg = enable_reddit_api()
    cfg.reddit_client_secret = "gizli-reddit-sirri-123"
    for path in ("/kaynaklar", "/durum", "/ayarlar"):
        html = client.get(path).text
        assert cfg.reddit_client_secret not in html and cfg.reddit_client_id not in html, path
    assert "Reddit API kimlik bilgileri (.env): tanımlı<" in client.get("/kaynaklar").text
    assert "Reddit Data API tanımlı değil" not in client.get("/durum").text
