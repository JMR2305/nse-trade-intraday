"""
data_quality/history_store.py — Task #257
Postgres-backed store for data quality validation run history.

Table (auto-created on first call):
  data_quality_runs(
    id             SERIAL PRIMARY KEY,
    run_ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    quality_score  REAL        NOT NULL,
    grade          TEXT        NOT NULL,
    critical_count INT         NOT NULL DEFAULT 0,
    warning_count  INT         NOT NULL DEFAULT 0,
    domain_scores  JSONB       NOT NULL DEFAULT '{}'::jsonb
  )

Behaviour:
- With DATABASE_URL: all writes and reads go to Postgres.
- Without DATABASE_URL (local dev / tests): falls back to a local JSON file
  (dq_history_fallback.json in this package directory).

Retention: runs older than 90 days are pruned lazily (1% probability per call
to get_history, or explicitly via prune_old_runs()).

READ-WRITE · internal only — called from shared_services.get_summary() and
shared_services.get_history().
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

_DIR = os.path.dirname(os.path.abspath(__file__))
_FALLBACK_FILE = os.path.join(_DIR, "dq_history_fallback.json")
_SCHEMA_READY = False
_MAX_FALLBACK = 30   # max rows kept in the JSON fallback


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def db_available() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    """Open a psycopg2 connection. Lazily imported so no-DB envs don't need it."""
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_schema(conn) -> None:
    """Create the data_quality_runs table if it doesn't exist yet."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS data_quality_runs (
                id             SERIAL      PRIMARY KEY,
                run_ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                quality_score  REAL        NOT NULL,
                grade          TEXT        NOT NULL,
                critical_count INT         NOT NULL DEFAULT 0,
                warning_count  INT         NOT NULL DEFAULT 0,
                domain_scores  JSONB       NOT NULL DEFAULT '{}'::jsonb
            )
        """)
    conn.commit()
    _SCHEMA_READY = True


# ── JSON file fallback ────────────────────────────────────────────────────────

def _read_fallback() -> list[dict]:
    if not os.path.exists(_FALLBACK_FILE):
        return []
    try:
        with open(_FALLBACK_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_fallback(runs: list[dict]) -> None:
    try:
        with open(_FALLBACK_FILE, "w") as f:
            json.dump(runs, f, indent=2)
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def persist_run(summary: dict) -> None:
    """
    Append one validation run record derived from a get_summary() result.

    This is fire-and-forget — shared_services wraps it in try/except so a
    transient DB failure never breaks the summary response.
    """
    score    = float(summary.get("quality_score", 0))
    grade    = str(summary.get("grade", "D"))
    critical = int(summary.get("critical_count", 0))
    warning  = int(summary.get("warning_count", 0))
    domain_scores: dict = {
        d["domain"]: float(d.get("score", 0))
        for d in summary.get("domains", [])
        if "domain" in d
    }

    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO data_quality_runs
                        (quality_score, grade, critical_count,
                         warning_count, domain_scores)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (score, grade, critical, warning, json.dumps(domain_scores)),
                )
            conn.commit()
        finally:
            conn.close()
        return

    # ── File fallback ─────────────────────────────────────────────────────────
    runs = _read_fallback()
    runs.append({
        "run_ts":         _iso(_now_utc()),
        "quality_score":  score,
        "grade":          grade,
        "critical_count": critical,
        "warning_count":  warning,
        "domain_scores":  domain_scores,
    })
    # Keep only the most recent _MAX_FALLBACK entries
    if len(runs) > _MAX_FALLBACK:
        runs = runs[-_MAX_FALLBACK:]
    _write_fallback(runs)


def get_history(limit: int = 30) -> list[dict]:
    """
    Return up to `limit` validation runs, most-recent first.

    Each run dict has:
      id, run_ts, quality_score, grade, critical_count,
      warning_count, domain_scores
    """
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, run_ts, quality_score, grade,
                           critical_count, warning_count, domain_scores
                    FROM   data_quality_runs
                    ORDER  BY run_ts DESC
                    LIMIT  %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
            return [
                {
                    "id":             r[0],
                    "run_ts":         (
                        r[1].isoformat()
                        if hasattr(r[1], "isoformat") else str(r[1])
                    ),
                    "quality_score":  float(r[2]),
                    "grade":          r[3],
                    "critical_count": r[4],
                    "warning_count":  r[5],
                    "domain_scores":  r[6] if isinstance(r[6], dict) else {},
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ── File fallback — stored oldest-first, return most-recent-first ─────────
    runs = _read_fallback()
    return list(reversed(runs[-limit:]))


def prune_old_runs(days: int = 90) -> int:
    """
    Delete runs older than `days`. Returns the number of rows deleted.
    Called lazily by get_history (1 % probability) to keep the table tidy.
    """
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            cutoff = _now_utc() - timedelta(days=days)
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM data_quality_runs WHERE run_ts < %s",
                    (cutoff,),
                )
                deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    # File fallback — compare ISO strings (lexicographic order works for UTC)
    runs = _read_fallback()
    cutoff_str = _iso(_now_utc() - timedelta(days=days))
    kept = [r for r in runs if r.get("run_ts", "") >= cutoff_str]
    removed = len(runs) - len(kept)
    if removed:
        _write_fallback(kept)
    return removed
