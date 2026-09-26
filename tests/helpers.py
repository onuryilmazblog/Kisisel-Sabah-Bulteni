"""Test yardımcıları: sahte HTTP okuyucu, geçici veri tabanı ve sayfa üreticileri."""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bulten import config as config_mod
from bulten.db import connect, migrate
from bulten.net.fetcher import FetchError, FetchResult
from bulten.settings_store import save_settings
from bulten.sources.registry import seed_sources, sync_product_sources
from bulten.timeutil import now_iso, set_clock

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class FakeFetcher:
    """URL → metin eşlemesi. Eşlemede olmayan veya 'down' işaretli adresler FetchError verir."""
    pages: dict[str, str] = field(default_factory=dict)
    down: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url in self.down or any(url.startswith(d) for d in self.down if d.endswith("*")):
            raise FetchError("Bağlantı kurulamadı (test: kaynak kesintisi)", kind="network", url=url)
        if url not in self.pages:
            raise FetchError(f"HTTP 404 (test): {url}", kind="http", status=404, retryable=False, url=url)
        return FetchResult(url=url, status=200, text=self.pages[url], content_type="text/html", fetched_at=now_iso())

    def close(self):
        pass


def make_config(tmp_path: Path, **overrides):
    cfg = config_mod.load_config(env_file=str(tmp_path / "none.env"), reload=True)
    cfg.data_dir = tmp_path
    cfg.database_path = tmp_path / "test.db"
    cfg.llm_provider = "none"
    cfg.telegram_bot_token = overrides.pop("telegram_bot_token", "")
    cfg.search_provider = "none"
    for k, v in overrides.items():
        setattr(cfg, k, v)
    config_mod.set_config(cfg)
    return cfg


def make_db(tmp_path: Path, *, products=("win11-25h2", "win11-24h2", "ws2025"), roles=("rds", "dc", "vpn"),
            modules: dict | None = None, **settings):
    make_config(tmp_path)
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    seed_sources(conn)
    base = {
        "onboarding_done": True, "products": list(products), "roles": list(roles),
        "modules": {"windows": True, "intune": True, "configmgr": True, "community": True, "weather": False,
                    "markets": False, "news": True, "content": False, "calendar": False, **(modules or {})},
        "channels": {"telegram": True, "email": False}, "telegram_chat_id": "1001",
        "configmgr_version": "2509",
    }
    base.update(settings)
    s = save_settings(conn, base)
    sync_product_sources(conn, s)
    return conn


def freeze(y, mo, d, h=5, mi=0):
    set_clock(datetime(y, mo, d, h, mi, tzinfo=timezone.utc))


def wrh_page(issues: list[dict], title: str = "Windows 11, version 25H2 known issues and notifications") -> str:
    """Release health durum sayfası üretir. issue: id, title, desc, kb, build, status, updated, opened,
    workaround, resolution, next, client, server, body."""
    rows, details = [], []
    for i in issues:
        rows.append(
            f'<tr><td><a href="#{i["id"]}msgdesc"><b>{html.escape(i["title"])}</b></a><br>{html.escape(i.get("desc", ""))}</td>'
            f'<td>OS Build {i.get("build", "26200.9445")}<br>KB{i["kb"]}<br>{i.get("date", "2026-09-08")}</td>'
            f'<td>{i.get("status", "Confirmed")}</td><td>{i.get("updated", "2026-09-10")}<br>10:00 PT</td></tr>')
        parts = [f'<div id="{i["id"]}msgdesc"></div><b>{html.escape(i["title"])}</b>',
                 f'<table><tr><th>Status</th><th>Originating update</th><th>History</th></tr><tr><td>{i.get("status", "Confirmed")}</td>'
                 f'<td>OS Build {i.get("build", "26200.9445")}<br>KB{i["kb"]}<br>{i.get("date", "2026-09-08")}</td>'
                 f'<td>Last updated: {i.get("updated", "2026-09-10")}, 10:00 PT<br>Opened: {i.get("opened", "2026-09-09")}, 09:00 PT</td></tr></table>',
                 f'<p>{html.escape(i.get("body", i.get("desc", "")))}</p>']
        if i.get("workaround"):
            parts.append(f'<p><b>Workaround:</b> {html.escape(i["workaround"])}</p>')
        if i.get("resolution"):
            parts.append(f'<p><b>Resolution:</b> {html.escape(i["resolution"])}</p>')
        plats = []
        if i.get("client"):
            plats.append(f'<li>Client: {html.escape(i["client"])}</li>')
        if i.get("server"):
            plats.append(f'<li>Server: {html.escape(i["server"])}</li>')
        parts.append('<p><b>Affected platforms:</b></p><ul>' + "".join(plats) + "</ul>")
        if i.get("next"):
            parts.append(f'<p><b>Next steps:</b> {html.escape(i["next"])}</p>')
        details.append("<tr><td>" + "\n".join(parts) + "</td></tr>")
    return (f"<html><body><main><h1>{html.escape(title)}</h1><h2 id='known-issues'>Known issues</h2>"
            "<table><thead><tr><th>Summary</th><th>Originating update</th><th>Status</th><th>Last updated</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table><h2>Issue details</h2><h3>September 2026</h3><table>{''.join(details)}</table>"
            "</main></body></html>")


def rss_feed(items: list[dict], title: str = "Feed") -> str:
    entries = []
    for it in items:
        entries.append(
            f"<item><title>{html.escape(it['title'])}</title><link>{html.escape(it['link'])}</link>"
            f"<guid>{html.escape(it.get('guid', it['link']))}</guid><pubDate>{it.get('date', 'Thu, 24 Sep 2026 10:00:00 GMT')}</pubDate>"
            f"<description>{html.escape(it.get('desc', ''))}</description>"
            + (f"<author>{html.escape(it['author'])}</author>" if it.get("author") else "") + "</item>")
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title><link>https://example.org</link>'
            f"<description>t</description>{''.join(entries)}</channel></rss>")


def source_id(conn, slug: str) -> int:
    return conn.execute("SELECT id FROM sources WHERE slug = ?", (slug,)).fetchone()["id"]


def only_sources(conn, slugs: list[str]) -> list[int]:
    return [source_id(conn, s) for s in slugs]
