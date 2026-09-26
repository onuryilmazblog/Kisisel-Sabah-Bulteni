"""Sunucu tarafı zamanlayıcı ve worker.

- Tarayıcıdan bağımsız çalışır; tüm durum SQLite'tadır, yeniden başlatmada hafıza kaybolmaz.
- İşler `job_runs(job, slot)` ile benzersizdir: aynı bülten günü / aynı toplama dilimi iki kez çalışmaz.
  Çöken (nabzı durmuş) bir iş bir sonraki tikte kaldığı yerden yeniden çalıştırılır; adımlar idempotenttir.
- Kaçırılan sabah bülteni `catch_up_until` saatine kadar telafi edilir; sonrası "kaçırıldı" olarak kaydedilir.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import traceback
from datetime import timedelta
from typing import Callable

from ..config import load_config
from ..db import connect, kv_get, kv_set, migrate
from ..delivery.dispatcher import enqueue_alert, enqueue_bulletin, enqueue_test, process_deliveries, recover_stuck
from ..delivery.telegram import TelegramPoller
from ..daily.service import refresh_daily
from ..pipeline.bulletin import compose_bulletin, is_due_bulletin_day, select_alerts
from ..pipeline.run import collect_and_process
from ..settings_store import get_settings
from ..sources.registry import seed_sources, sync_product_sources
from ..timeutil import local_now, now_iso, now_utc, parse_hhmm, parse_iso, to_iso

log = logging.getLogger(__name__)

STALE_JOB_MIN = 30
MAX_JOB_ATTEMPTS = 3


def enqueue_job(conn: sqlite3.Connection, job: str, requested_by: str = "web") -> int:
    return conn.execute("INSERT INTO job_requests(job, requested_at, requested_by, status) VALUES (?, ?, ?, 'pending')",
                        (job, now_iso(), requested_by)).lastrowid


def run_job(conn: sqlite3.Connection, job: str, slot: str, fn: Callable[[], str | None]) -> str:
    """İşi (job, slot) için en fazla bir kez başarıyla çalıştırır. Dönüş: ran|skipped|done|error."""
    ts = now_iso()
    try:
        conn.execute("INSERT INTO job_runs(job, slot, status, attempt, started_at, heartbeat_at) VALUES (?, ?, 'running', 1, ?, ?)",
                     (job, slot, ts, ts))
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT * FROM job_runs WHERE job = ? AND slot = ?", (job, slot)).fetchone()
        if row["status"] in ("ok", "skipped"):
            return "done"
        hb = parse_iso(row["heartbeat_at"] or row["started_at"])
        stale = hb is None or now_utc() - hb > timedelta(minutes=STALE_JOB_MIN)
        finished = parse_iso(row["finished_at"]) if row["finished_at"] else None
        retry_error = row["status"] == "error" and row["attempt"] < MAX_JOB_ATTEMPTS and (
            finished is None or now_utc() - finished > timedelta(minutes=10))
        if (row["status"] == "running" and stale) or retry_error:
            conn.execute("UPDATE job_runs SET status = 'running', attempt = attempt + 1, started_at = ?, heartbeat_at = ?, "
                         "finished_at = NULL WHERE id = ?", (ts, ts, row["id"]))
        else:
            return "skipped"
    try:
        detail = fn()
        conn.execute("UPDATE job_runs SET status = 'ok', finished_at = ?, detail = ? WHERE job = ? AND slot = ?",
                     (now_iso(), (detail or "")[:4000], job, slot))
        return "ran"
    except Exception as exc:  # noqa: BLE001
        log.error("İş hatası %s/%s: %s", job, slot, traceback.format_exc())
        conn.execute("UPDATE job_runs SET status = 'error', finished_at = ?, detail = ? WHERE job = ? AND slot = ?",
                     (now_iso(), f"{exc.__class__.__name__}: {exc}"[:4000], job, slot))
        return "error"


class Scheduler:
    def __init__(self, db_path=None, *, tick_seconds: float = 30.0, collect_interval_min: int | None = None,
                 fetcher=None, telegram=None, email=None, part_delay: float = 1.05, start_poller: bool = True):
        cfg = load_config()
        self.db_path = db_path or cfg.database_path
        self.tick_seconds = tick_seconds
        self.collect_interval_min = collect_interval_min or int(os.environ.get("COLLECT_INTERVAL_MIN", "180"))
        self.fetcher = fetcher
        self.telegram = telegram
        self.email = email
        self.part_delay = part_delay
        self.start_poller = start_poller
        self.stop_event = threading.Event()
        self.conn: sqlite3.Connection | None = None

    # -- yaşam döngüsü ----------------------------------------------------------------

    def setup(self) -> sqlite3.Connection:
        conn = connect(self.db_path)
        migrate(conn)
        seed_sources(conn)
        sync_product_sources(conn, get_settings(conn))
        n = recover_stuck(conn)
        if n:
            log.warning("%d gönderim parçası belirsiz olarak işaretlendi (önceki çalışma yarıda kalmış).", n)
        kv_set(conn, "worker_started_at", now_iso())
        self.conn = conn
        return conn

    def run_forever(self) -> None:
        conn = self.setup()
        if self.start_poller:
            TelegramPoller(self.db_path, enqueue_job=enqueue_job, stop_event=self.stop_event).start()
        log.info("Worker başladı (tik: %ss, toplama aralığı: %s dk)", self.tick_seconds, self.collect_interval_min)
        while not self.stop_event.is_set():
            try:
                self.tick(conn)
            except Exception:  # noqa: BLE001
                log.exception("Tik hatası")
            self.stop_event.wait(self.tick_seconds)

    def stop(self) -> None:
        self.stop_event.set()

    # -- tik ----------------------------------------------------------------------------

    def tick(self, conn: sqlite3.Connection) -> dict:
        kv_set(conn, "worker_heartbeat", now_iso())
        settings = get_settings(conn)
        result: dict = {}
        result["requests"] = self._handle_requests(conn)
        if settings.get("onboarding_done"):
            result["collect"] = self._maybe_collect(conn, settings)
            result["critical"] = self._maybe_critical(conn, settings)
            result["bulletin"] = self._maybe_bulletin(conn, settings)
        result["deliver"] = process_deliveries(conn, telegram=self.telegram, email=self.email, part_delay=self.part_delay)
        self._maybe_housekeeping(conn, settings)
        return result

    def _collect(self, conn, **kw) -> dict:
        return collect_and_process(conn, fetcher=self.fetcher, **kw)

    def _maybe_collect(self, conn, settings) -> str:
        bucket = int(now_utc().timestamp() // 60 // self.collect_interval_min)
        return run_job(conn, "collect", f"b{bucket}", lambda: _summ(self._collect(conn)))

    def _maybe_critical(self, conn, settings) -> str | None:
        crit = settings.get("critical") or {}
        if not crit.get("enabled"):
            return None
        interval = max(15, int(crit.get("interval_min") or 60))
        bucket = int(now_utc().timestamp() // 60 // interval)

        def job():
            res = self._collect(conn, only_critical=True)
            vids, note = select_alerts(conn, settings)
            ids = enqueue_alert(conn, vids)
            return f"{_summ(res)}; alarm: {len(vids)} sürüm, {len(ids)} gönderim. {note}"

        return run_job(conn, "critical", f"c{interval}-{bucket}", job)

    def _maybe_bulletin(self, conn, settings) -> str | None:
        tzname = settings.get("timezone")
        local = local_now(tzname)
        b = settings.get("bulletin") or {}
        h, m = parse_hhmm(b.get("time", "08:00"))
        ch, cm = parse_hhmm(b.get("catch_up_until", "12:00"), (12, 0))
        due_at = local.replace(hour=h, minute=m, second=0, microsecond=0)
        until = local.replace(hour=ch, minute=cm, second=0, microsecond=0)
        if until <= due_at:
            until = due_at + timedelta(hours=4)
        day = local.date().isoformat()
        # Bülten öncesi toplama: bülten saatinden 25 dk önce
        pre_at = due_at - timedelta(minutes=25)
        if pre_at <= local < due_at and is_due_bulletin_day(settings):
            run_job(conn, "pre_collect", day, lambda: _summ(self._collect(conn)))
        if local < due_at:
            return None
        if not is_due_bulletin_day(settings):
            run_job(conn, "bulletin", day, lambda: "Hafta sonu gönderimi kapalı.")
            return "weekend"
        if local > until:
            row = conn.execute("SELECT 1 FROM job_runs WHERE job = 'bulletin' AND slot = ?", (day,)).fetchone()
            if row is None:
                conn.execute("INSERT OR IGNORE INTO job_runs(job, slot, status, started_at, finished_at, detail) "
                             "VALUES ('bulletin', ?, 'skipped', ?, ?, ?)",
                             (day, now_iso(), now_iso(), "Worker bülten saatinde çalışmıyordu; telafi süresi geçti (kaçırıldı)."))
            return "missed"

        def job():
            pre = conn.execute("SELECT finished_at FROM job_runs WHERE job = 'pre_collect' AND slot = ? AND status = 'ok'",
                               (day,)).fetchone()
            if pre is None:
                self._collect(conn)  # telafi: bülten öncesi toplama yapılmamış
            refresh_daily(conn, fetcher=self.fetcher)
            bid = compose_bulletin(conn, kind="daily")
            ids = enqueue_bulletin(conn, bid)
            return f"bülten #{bid}, {len(ids)} gönderim kuyruğa alındı"

        return run_job(conn, "bulletin", day, job)

    def _handle_requests(self, conn) -> int:
        rows = conn.execute("SELECT * FROM job_requests WHERE status = 'pending' ORDER BY id LIMIT 5").fetchall()
        for r in rows:
            conn.execute("UPDATE job_requests SET status = 'running', started_at = ? WHERE id = ?", (now_iso(), r["id"]))
            try:
                detail = self._run_request(conn, r["job"])
                conn.execute("UPDATE job_requests SET status = 'done', finished_at = ?, detail = ? WHERE id = ?",
                             (now_iso(), (detail or "")[:4000], r["id"]))
            except Exception as exc:  # noqa: BLE001
                log.exception("İstek hatası")
                conn.execute("UPDATE job_requests SET status = 'error', finished_at = ?, detail = ? WHERE id = ?",
                             (now_iso(), f"{exc.__class__.__name__}: {exc}", r["id"]))
        return len(rows)

    def _run_request(self, conn, job: str) -> str:
        settings = get_settings(conn)
        if job == "check_now":
            res = self._collect(conn)
            extra = ""
            if (settings.get("critical") or {}).get("enabled"):
                vids, note = select_alerts(conn, settings)
                enqueue_alert(conn, vids)
                extra = f"; kritik alarm: {len(vids)} {note}"
            return _summ(res) + extra
        if job == "refresh_daily":
            return str(refresh_daily(conn, fetcher=self.fetcher))
        if job == "send_preview":
            refresh_daily(conn, fetcher=self.fetcher)
            bid = compose_bulletin(conn, kind="manual")
            ids = enqueue_bulletin(conn, bid)
            return f"anlık bülten #{bid}, {len(ids)} gönderim"
        if job in ("test_telegram", "test_email"):
            did = enqueue_test(conn, job.split("_")[1])
            return f"test gönderimi #{did}" if did else "kanal yapılandırılmamış"
        if job == "sync_sources":
            sync_product_sources(conn, settings)
            return "kaynaklar eşitlendi"
        raise ValueError(f"Bilinmeyen iş: {job}")

    def _maybe_housekeeping(self, conn, settings) -> None:
        day = now_utc().date().isoformat()

        def job():
            cutoff = to_iso(now_utc() - timedelta(days=120))
            n1 = conn.execute("DELETE FROM source_checks WHERE started_at < ?", (cutoff,)).rowcount
            n2 = conn.execute("DELETE FROM delivery_attempts WHERE at < ?", (cutoff,)).rowcount
            n3 = conn.execute("DELETE FROM daily_data WHERE fetched_at < ? AND id NOT IN "
                              "(SELECT CAST(json_extract(content_json, '$.daily.market') AS INTEGER) FROM bulletins "
                              " WHERE json_extract(content_json, '$.daily.market') IS NOT NULL)", (cutoff,)).rowcount
            n4 = conn.execute("DELETE FROM llm_cache WHERE created_at < ?", (cutoff,)).rowcount
            conn.execute("PRAGMA optimize")
            return f"temizlik: {n1} kontrol, {n2} deneme, {n3} günlük veri, {n4} önbellek kaydı"

        run_job(conn, "housekeeping", day, job)


def _summ(res: dict) -> str:
    c = res.get("collect") or {}
    return (f"kaynak {c.get('sources_ok', 0)}/{c.get('sources_total', 0)} başarılı, {c.get('sources_error', 0)} hata, "
            f"{c.get('sources_warning', 0)} uyarı; {res.get('versions_created', 0)} yeni sürüm")


def worker_alive(conn: sqlite3.Connection, max_age_s: int = 180) -> bool:
    hb = parse_iso(kv_get(conn, "worker_heartbeat"))
    return hb is not None and (now_utc() - hb).total_seconds() < max_age_s

