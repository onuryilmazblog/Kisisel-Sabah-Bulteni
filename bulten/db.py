"""SQLite bağlantısı, migration çalıştırıcı ve küçük yardımcılar.

Web ve worker süreçleri aynı veri tabanı dosyasını WAL kipinde paylaşır.
Bağlantılar autocommit kipindedir; birden fazla yazma işlemi `tx()` ile tek
işlemde toplanır.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any, Iterator

from .config import load_config
from .timeutil import now_iso


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    if path is None:
        path = load_config().database_path
    path = Path(path) if str(path) != ":memory:" else path
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Yazma işlemi: BEGIN IMMEDIATE ... COMMIT (hata olursa ROLLBACK).

    İç içe çağrılırsa dıştaki işlem kullanılır.
    """
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _migration_files() -> list[tuple[str, str]]:
    pkg = resources.files("bulten").joinpath("migrations")
    items = []
    for entry in pkg.iterdir():
        name = entry.name
        if name.endswith(".sql"):
            items.append((name, entry.read_text(encoding="utf-8")))
    return sorted(items)


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Uygulanmamış migration dosyalarını sırayla uygular."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for name, sql in _migration_files():
        if name in done:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            # executescript kendi COMMIT'ini yapar; bu yüzden ifadeleri tek tek çalıştırıyoruz.
            for stmt in _split_sql(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (name, now_iso())
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        applied.append(name)
    return applied


def _split_sql(sql: str) -> list[str]:
    stmts, buf = [], []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") and not buf:
            continue
        buf.append(line)
        if stripped.endswith(";") and sqlite3.complete_statement("\n".join(buf)):
            stmt = "\n".join(buf).strip()
            if stmt and stmt != ";":
                stmts.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def jload(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def kv_get(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def kv_set(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    conn.execute(
        "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, now_iso()),
    )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
