"""Günlük API/AI bütçesi ve kullanım kaydı."""
from __future__ import annotations

import sqlite3

from .config import Config, load_config
from .timeutil import now_iso, now_utc


def _day() -> str:
    return now_utc().date().isoformat()


def record(conn: sqlite3.Connection, *, provider: str, kind: str, units: int = 1, input_tokens: int | None = None,
           output_tokens: int | None = None, cost_usd: float | None = None, ok: bool = True, note: str | None = None
           ) -> None:
    conn.execute(
        "INSERT INTO usage_log(at, day, provider, kind, units, input_tokens, output_tokens, cost_usd, ok, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), _day(), provider, kind, units, input_tokens, output_tokens, cost_usd, 1 if ok else 0, note),
    )


def today_totals(conn: sqlite3.Connection, kind: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(units),0) AS units, COALESCE(SUM(input_tokens),0) AS tin, "
        "COALESCE(SUM(output_tokens),0) AS tout, COALESCE(SUM(cost_usd),0) AS cost "
        "FROM usage_log WHERE day = ? AND kind = ?", (_day(), kind),
    ).fetchone()
    return dict(row)


def llm_budget_left(conn: sqlite3.Connection, cfg: Config | None = None) -> tuple[bool, str]:
    cfg = cfg or load_config()
    t = today_totals(conn, "llm")
    if t["calls"] >= cfg.llm_max_calls_per_day:
        return False, f"Günlük LLM çağrı sınırı doldu ({t['calls']}/{cfg.llm_max_calls_per_day})."
    if t["cost"] >= cfg.llm_daily_budget_usd:
        return False, f"Günlük LLM bütçesi doldu (${t['cost']:.2f}/${cfg.llm_daily_budget_usd:.2f})."
    return True, ""


def search_budget_left(conn: sqlite3.Connection, cfg: Config | None = None) -> tuple[bool, str]:
    cfg = cfg or load_config()
    t = today_totals(conn, "search")
    if t["units"] >= cfg.search_daily_limit:
        return False, f"Günlük arama sınırı doldu ({t['units']}/{cfg.search_daily_limit})."
    return True, ""


def estimate_llm_cost(cfg: Config, input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * cfg.llm_price_in_per_mtok + output_tokens * cfg.llm_price_out_per_mtok) / 1_000_000


def usage_summary(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    rows = conn.execute(
        "SELECT day, kind, provider, COUNT(*) AS calls, COALESCE(SUM(units),0) AS units, "
        "COALESCE(SUM(input_tokens),0) AS tin, COALESCE(SUM(output_tokens),0) AS tout, "
        "ROUND(COALESCE(SUM(cost_usd),0), 4) AS cost, SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS errors "
        "FROM usage_log GROUP BY day, kind, provider ORDER BY day DESC LIMIT ?", (days * 4,),
    ).fetchall()
    return [dict(r) for r in rows]
