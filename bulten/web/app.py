"""Web arayüzü (FastAPI + Jinja2, sunucu tarafı HTML)."""
from __future__ import annotations

import json
import secrets
from urllib.parse import parse_qs
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..catalog import CONFIGMGR_VERSIONS, INTUNE_PLATFORMS, NEWS_CATEGORIES, PRODUCTS, ROLES
from ..config import load_config
from ..db import connect, migrate, tx
from ..delivery.actions import ACTION_TR, ACTIONS, apply_action, mark_viewed, read_action_token
from ..delivery.dispatcher import resend_uncertain
from ..pipeline.analyze import RISK_TR, STATUS_TR, recompute_relevance
from ..pipeline.evidence import EVIDENCE_LABELS
from ..settings_store import LENGTH_PRESETS, get_settings, save_settings
from ..sources.base import SourceRow
from ..sources.registry import seed_sources, sync_product_sources
from ..timeutil import age_text, fmt_tr, fmt_tr_date
from ..worker.scheduler import enqueue_job
from . import auth, queries
from .forms import FormError, add_user_source, parse_settings_form, sync_youtube_sources

HERE = Path(__file__).parent
app = FastAPI(title="Kişisel Sabah Bülteni", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))
def trnum(value, digits: int = 2) -> str:
    """Türkçe sayı biçimi: 4.615,00 / 19,5"""
    if value is None or value == "":
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    s = f"{v:,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


templates.env.filters["trnum"] = trnum
templates.env.globals.update(fmt_tr=fmt_tr, age_text=age_text, fmt_tr_date=fmt_tr_date, RISK_TR=RISK_TR,
                             STATUS_TR=STATUS_TR, EVIDENCE_LABELS=EVIDENCE_LABELS)

PUBLIC_PATHS = ("/giris", "/static/", "/saglik", "/eylem/", "/telegram/webhook/")
_initialized = False


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def _init_once() -> None:
    global _initialized
    if _initialized:
        return
    with db() as conn:
        migrate(conn)
        seed_sources(conn)
    _initialized = True


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    _init_once()
    cfg = load_config()
    path = request.url.path
    request.state.session = None
    if not path.startswith(PUBLIC_PATHS):
        if cfg.app_password:
            sess = auth.read_session(request)
            if not sess:
                if path.startswith("/api/"):
                    return JSONResponse({"error": "Oturum gerekli"}, status_code=401)
                return RedirectResponse("/giris", status_code=303)
            request.state.session = sess
        elif not auth.is_loopback(request) and not _allow_no_auth():
            return PlainTextResponse(
                "APP_PASSWORD tanımlı olmadığı için uygulamaya yalnızca bu makineden erişilebilir. "
                ".env dosyasında APP_PASSWORD ve APP_SECRET_KEY tanımlayın.", status_code=403)
    new_csrf = None
    if not cfg.app_password and not request.cookies.get("bulten_csrf"):
        new_csrf = secrets.token_urlsafe(24)
        request.state.new_csrf = new_csrf
    if request.method == "POST" and not path.startswith(PUBLIC_PATHS) and path != "/giris":
        token = request.headers.get("x-csrf-token")
        if token is None and request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
            # Gövde burada okunur ve önbelleğe alınır; uç nokta aynı gövdeyi yeniden okuyabilir.
            body = await request.body()
            token = (parse_qs(body.decode("utf-8", "replace")).get("_csrf") or [None])[0]
        if not auth.csrf_valid(request, token):
            return JSONResponse({"error": "CSRF doğrulaması başarısız; sayfayı yenileyin."}, status_code=403)
    response = await call_next(request)
    if new_csrf:
        response.set_cookie("bulten_csrf", new_csrf, httponly=False, samesite="strict", secure=_secure(request))
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
    return response


def _allow_no_auth() -> bool:
    import os

    return os.environ.get("ALLOW_NO_AUTH", "").lower() in ("1", "true", "yes")


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def render(request: Request, template: str, ctx: dict[str, Any], status: int = 200) -> HTMLResponse:
    with db() as conn:
        settings = get_settings(conn)
        base = {
            "request": request, "settings": settings, "csrf": auth.csrf_token_for(request),
            "nav": queries.nav_counts(conn), "worker_alive": queries.system_view(conn)["worker_alive"],
            "cfg": load_config(), "path": request.url.path,
        }
    base.update(ctx)
    return templates.TemplateResponse(request, template, base, status_code=status)


# --- Giriş ------------------------------------------------------------------------------

@app.get("/giris", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})


@app.post("/giris")
def login(request: Request, password: str = Form("")):
    if auth.rate_limited(request):
        return templates.TemplateResponse(request, "login.html", {"request": request,
                                          "error": "Çok fazla deneme. 10 dakika sonra tekrar deneyin."}, status_code=429)
    if not auth.password_ok(password):
        auth.note_failed_login(request)
        return templates.TemplateResponse(request, "login.html", {"request": request, "error": "Parola hatalı."},
                                          status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_session(), max_age=auth.MAX_AGE, httponly=True, samesite="lax",
                    secure=_secure(request))
    return resp


@app.post("/cikis")
def logout():
    resp = RedirectResponse("/giris", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/saglik")
def health():
    with db() as conn:
        sv = queries.system_view(conn)
    return {"ok": True, "worker_alive": sv["worker_alive"], "last_success_check": sv["last_success"]}


# --- Sayfalar -----------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, b: int | None = None):
    with db() as conn:
        settings = get_settings(conn)
        if not settings.get("onboarding_done") and b is None:
            has_demo = conn.execute("SELECT 1 FROM bulletins WHERE is_demo = 1 LIMIT 1").fetchone()
            if not has_demo:
                return RedirectResponse("/kurulum", status_code=303)
        view = queries.bulletin_view(conn, settings, bulletin_id=b)
        history = conn.execute("SELECT id, bulletin_date, kind, created_at FROM bulletins WHERE is_demo = 0 "
                               "ORDER BY id DESC LIMIT 14").fetchall()
    return render(request, "bulletin.html", {"view": view, "history": [dict(h) for h in history], "page": "bulten"})


@app.get("/kritik", response_class=HTMLResponse)
def critical_page(request: Request):
    with db() as conn:
        view = queries.critical_view(conn, get_settings(conn))
    return render(request, "critical.html", {"view": view, "page": "kritik"})


@app.get("/takip", response_class=HTMLResponse)
def tracking_page(request: Request):
    with db() as conn:
        view = queries.tracking_view(conn, get_settings(conn))
    return render(request, "tracking.html", {"view": view, "page": "takip"})


@app.get("/arsiv", response_class=HTMLResponse)
def archive_page(request: Request, sayfa: int = 1):
    f = {k: (request.query_params.get(k) or "").strip() for k in queries.ARCHIVE_FILTERS}
    with db() as conn:
        view = queries.archive_view(conn, f, page=max(1, sayfa))
    return render(request, "archive.html", {"view": view, "f": f, "page": "arsiv", "products": PRODUCTS})


@app.get("/olay/{event_id}", response_class=HTMLResponse)
def event_page(request: Request, event_id: int):
    with db() as conn:
        detail = queries.event_detail(conn, event_id)
        if detail is None:
            return render(request, "message.html", {"title": "Bulunamadı", "message": "Olay bulunamadı."}, status=404)
        mark_viewed(conn, [event_id])
    return render(request, "event.html", {"d": detail, "page": "arsiv"})


@app.get("/kaynaklar", response_class=HTMLResponse)
def sources_page(request: Request, hata: str | None = None, ok: str | None = None):
    with db() as conn:
        rows = queries.sources_view(conn)
    return render(request, "sources.html", {"sources": rows, "page": "kaynaklar", "error": hata, "ok": ok,
                                            "news_categories": NEWS_CATEGORIES})


@app.get("/durum", response_class=HTMLResponse)
def status_page(request: Request):
    with db() as conn:
        view = queries.system_view(conn)
    return render(request, "status.html", {"view": view, "page": "durum"})


def _settings_ctx(settings: dict) -> dict:
    return {"products": PRODUCTS, "roles": ROLES, "cm_versions": CONFIGMGR_VERSIONS, "intune_platforms": INTUNE_PLATFORMS,
            "news_categories": NEWS_CATEGORIES, "length_presets": LENGTH_PRESETS}


@app.get("/ayarlar", response_class=HTMLResponse)
def settings_page(request: Request, ok: str | None = None):
    with db() as conn:
        settings = get_settings(conn)
    return render(request, "settings.html", {**_settings_ctx(settings), "page": "ayarlar", "ok": ok, "error": None,
                                             "wizard": False})


@app.get("/kurulum", response_class=HTMLResponse)
def onboarding_page(request: Request):
    with db() as conn:
        settings = get_settings(conn)
    return render(request, "settings.html", {**_settings_ctx(settings), "page": "kurulum", "ok": None, "error": None,
                                             "wizard": True})


def _save_settings_form(request: Request, form, wizard: bool):
    with db() as conn:
        current = get_settings(conn)
        try:
            updates = parse_settings_form(form, current)
        except FormError as exc:
            return render(request, "settings.html", {**_settings_ctx(current), "page": "kurulum" if wizard else "ayarlar",
                                                     "ok": None, "error": str(exc), "wizard": wizard}, status=400)
        if wizard:
            updates["onboarding_done"] = True
        with tx(conn):
            new = save_settings(conn, updates)
            sync_product_sources(conn, new)
            sync_youtube_sources(conn, new)
        recompute_relevance(conn)
        if wizard:
            enqueue_job(conn, "check_now", "kurulum")
    return RedirectResponse("/?kurulum=1" if wizard else "/ayarlar?ok=1", status_code=303)


@app.post("/ayarlar")
async def settings_save(request: Request):
    return _save_settings_form(request, await request.form(), wizard=False)


@app.post("/kurulum")
async def onboarding_save(request: Request):
    return _save_settings_form(request, await request.form(), wizard=True)


# --- E-posta aksiyon bağlantıları (onay sayfası; GET durum değiştirmez) -------------------

@app.get("/eylem/{token}", response_class=HTMLResponse)
def action_confirm(request: Request, token: str):
    data = read_action_token(token)
    if not data:
        return templates.TemplateResponse(request, "message.html", {"request": request, "title": "Bağlantı geçersiz",
                                          "message": "Bağlantının süresi dolmuş veya geçersiz."}, status_code=400)
    with db() as conn:
        ev = conn.execute("SELECT id, title FROM events WHERE id = ?", (data["e"],)).fetchone()
    return templates.TemplateResponse(request, "action_confirm.html", {"request": request, "token": token, "data": data,
                                      "event": dict(ev) if ev else None, "label": ACTION_TR.get(data["a"], data["a"])})


@app.post("/eylem/{token}", response_class=HTMLResponse)
def action_apply(request: Request, token: str):
    data = read_action_token(token)
    if not data:
        return templates.TemplateResponse(request, "message.html", {"request": request, "title": "Bağlantı geçersiz",
                                          "message": "Bağlantının süresi dolmuş veya geçersiz."}, status_code=400)
    with db() as conn:
        ok = apply_action(conn, int(data["e"]), data["a"], via="email", version=int(data["v"]))
    return templates.TemplateResponse(request, "message.html", {"request": request, "title": "Tamam" if ok else "Bulunamadı",
                                      "message": ACTION_TR.get(data["a"], "") if ok else "Olay bulunamadı."})


# --- JSON API (arayüz düğmeleri) ------------------------------------------------------------

@app.post("/api/olay/{event_id}/{action}")
def api_action(event_id: int, action: str, request: Request):
    if action not in ACTIONS:
        return JSONResponse({"error": "Geçersiz işlem"}, status_code=400)
    version = request.query_params.get("v")
    with db() as conn:
        ok = apply_action(conn, event_id, action, via="web", version=int(version) if version else None)
    return {"ok": ok, "message": ACTION_TR.get(action, "")}


@app.post("/api/gorunum")
async def api_viewed(request: Request):
    try:
        body = await request.json()
        ids = [int(i) for i in body.get("ids", [])][:200]
    except (ValueError, TypeError, json.JSONDecodeError):
        return JSONResponse({"error": "Geçersiz istek"}, status_code=400)
    with db() as conn:
        mark_viewed(conn, ids)
    return {"ok": True}


@app.post("/api/is/{job}")
def api_job(job: str):
    if job not in ("check_now", "send_preview", "refresh_daily", "test_telegram", "test_email"):
        return JSONResponse({"error": "Geçersiz iş"}, status_code=400)
    with db() as conn:
        rid = enqueue_job(conn, job, "web")
        alive = queries.system_view(conn)["worker_alive"]
    return {"ok": True, "request_id": rid, "worker_alive": alive,
            "message": "Sıraya alındı." if alive else "Sıraya alındı ancak worker çalışmıyor görünüyor."}


@app.get("/api/is/{request_id}")
def api_job_status(request_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM job_requests WHERE id = ?", (request_id,)).fetchone()
    return dict(row) if row else JSONResponse({"error": "Bulunamadı"}, status_code=404)


@app.get("/api/konum")
def api_geocode(q: str = ""):
    from ..daily.weather import geocode
    from ..net.fetcher import Fetcher, FetchError

    if len(q.strip()) < 2:
        return {"results": []}
    try:
        with db() as conn, Fetcher(conn) as f:
            return {"results": geocode(f, q.strip()[:80])}
    except (FetchError, ValueError) as exc:
        return JSONResponse({"error": f"Konum araması yapılamadı: {exc}"}, status_code=502)


@app.post("/api/kaynak/{source_id}/test")
def api_source_test(source_id: int):
    from ..pipeline.validate import validate_source

    with db() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            return JSONResponse({"error": "Bulunamadı"}, status_code=404)
        return validate_source(conn, SourceRow.from_row(row))


@app.post("/api/kaynak/{source_id}/durum")
def api_source_toggle(source_id: int, request: Request):
    enabled = request.query_params.get("acik") == "1"
    with db() as conn:
        conn.execute("UPDATE sources SET enabled = ? WHERE id = ?", (1 if enabled else 0, source_id))
    return {"ok": True, "enabled": enabled}


@app.post("/kaynaklar/ekle")
async def source_add(request: Request):
    form = await request.form()
    with db() as conn:
        try:
            add_user_source(conn, name=form.get("name", ""), url=form.get("url", ""), module=form.get("module", ""),
                            category=form.get("category") or None, trust=form.get("trust", "user"))
        except FormError as exc:
            return RedirectResponse(f"/kaynaklar?hata={exc}", status_code=303)
    return RedirectResponse("/kaynaklar?ok=1", status_code=303)


@app.post("/api/teslimat/{delivery_id}/yeniden")
def api_resend(delivery_id: int):
    with db() as conn:
        n = resend_uncertain(conn, delivery_id)
    return {"ok": True, "parts": n}


@app.post("/api/demo/{op}")
def api_demo(op: str):
    from ..demo import load_demo, remove_demo

    with db() as conn:
        if op == "yukle":
            load_demo(conn)
        elif op == "sil":
            remove_demo(conn)
        else:
            return JSONResponse({"error": "Geçersiz"}, status_code=400)
    return {"ok": True}


@app.post("/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    from ..delivery.telegram import TelegramClient, handle_update

    cfg = load_config()
    header = request.headers.get("x-telegram-bot-api-secret-token", "")
    if cfg.telegram_mode != "webhook" or not cfg.telegram_webhook_secret or not (
            secrets.compare_digest(secret, cfg.telegram_webhook_secret) and
            secrets.compare_digest(header, cfg.telegram_webhook_secret)):
        return JSONResponse({"ok": False}, status_code=403)
    update = await request.json()
    with db() as conn:
        handle_update(conn, TelegramClient(cfg), update, enqueue_job=enqueue_job)
    return {"ok": True}
