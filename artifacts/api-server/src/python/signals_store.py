"""
signals_store.py — Durable persistence for intelligence scan signals.

Stores the latest enriched signal list in PostgreSQL when DATABASE_URL is set.

Behaviour:
- With DATABASE_URL: Postgres is authoritative. DB failures raise so callers
  receive an explicit error; no silent degradation to ephemeral files.
  Local warm-cache files are written AFTER a successful DB write to speed up
  same-instance reads but are never the primary write target.
- Without DATABASE_URL (local dev / no DB): falls back to JSON files.

Schema auto-created on first use.
Paper trading / research only — no live orders anywhere in this module.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))

# Warm-cache / local-dev file paths (one per signal type)
_PATHS = {
    "signals":          os.path.join(_DIR, "signals_cache.json"),
    "ai_decisions":     os.path.join(_DIR, "ai_decisions_cache.json"),
    "opportunity_scan": os.path.join(_DIR, "opportunity_cache.json"),
    "market_context":   os.path.join(_DIR, "market_context_cache.json"),
    "watchlist":        os.path.join(_DIR, "watchlist.json"),
}

_SNAPSHOT_FALLBACK_PATH = os.path.join(_DIR, "signal_snapshots_local.json")
_SNAPSHOT_FALLBACK_MAX = 200  # cap local-dev history file

_SCHEMA_READY = False


# ── Connection helpers ────────────────────────────────────────────────────────

def db_available() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS signals_cache (
                key        TEXT PRIMARY KEY,
                payload    JSONB NOT NULL DEFAULT '[]',
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_snapshots (
                id               BIGSERIAL PRIMARY KEY,
                scan_id          TEXT NOT NULL,
                canonical_scan_id TEXT,
                snapshot_ts      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                signals          JSONB NOT NULL DEFAULT '[]',
                market_context   JSONB NOT NULL DEFAULT '{}'
            )
            """
        )
        cur.execute(
            """
            ALTER TABLE signal_snapshots
            ADD COLUMN IF NOT EXISTS canonical_scan_id TEXT
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS signal_snapshots_scan_id_uidx
            ON signal_snapshots (scan_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS signal_snapshots_ts_idx
            ON signal_snapshots (snapshot_ts DESC)
            """
        )
    conn.commit()
    _SCHEMA_READY = True


# ── Generic save / load ───────────────────────────────────────────────────────

def _save(key: str, data: Any) -> None:
    """
    Persist data under `key`.

    With DATABASE_URL: writes to Postgres (authoritative). Warm-cache file is
    written AFTER a successful DB write. Raises on DB failure.
    Without DATABASE_URL: writes to the local JSON file only.
    """
    fallback_path = _PATHS.get(key)

    if not db_available():
        if fallback_path:
            _write_json(fallback_path, data)
        return

    conn = _connect()  # raises on connection failure
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO signals_cache (key, payload, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    payload    = EXCLUDED.payload,
                    updated_at = NOW()
                """,
                (key, json.dumps(data, default=str)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise  # surface DB write failure
    finally:
        conn.close()

    # Write warm-cache AFTER successful DB commit (read optimisation only)
    if fallback_path:
        _write_json(fallback_path, data)


def _load(key: str) -> Optional[Any]:
    """
    Load data for `key`.

    With DATABASE_URL: reads from Postgres; raises on DB failure.
    Without DATABASE_URL: reads from the local JSON file.
    """
    fallback_path = _PATHS.get(key)

    if db_available():
        conn = _connect()  # raises on connection failure
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM signals_cache WHERE key = %s", (key,)
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if row and row[0] is not None:
            payload = row[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            # Refresh warm-cache for fast same-instance reads
            if fallback_path:
                _write_json(fallback_path, payload)
            return payload
        return None  # key not in DB yet

    # Local-dev fallback
    if fallback_path:
        return _read_json(fallback_path)
    return None


# ── File helpers ──────────────────────────────────────────────────────────────

def _read_json(path: str) -> Optional[Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _write_json(path: str, data: Any) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as exc:
        logger.warning("signals_store: could not write warm-cache %s: %s", path, exc)


# ── Public helpers ────────────────────────────────────────────────────────────

def save_signals(signals: List[Any]) -> None:
    _save("signals", signals)


def load_signals() -> Optional[List[Any]]:
    return _load("signals")


def save_ai_decisions(decisions: List[Any]) -> None:
    _save("ai_decisions", decisions)


def load_ai_decisions() -> Optional[List[Any]]:
    return _load("ai_decisions")


def save_opportunity_scan(opportunities: List[Any]) -> None:
    _save("opportunity_scan", opportunities)


def load_opportunity_scan() -> Optional[List[Any]]:
    return _load("opportunity_scan")


def save_market_context(context: Any) -> None:
    _save("market_context", context)


def load_market_context() -> Optional[Any]:
    return _load("market_context")


def save_watchlist(watchlist: List[str]) -> None:
    _save("watchlist", list(watchlist))


def load_watchlist() -> Optional[List[str]]:
    """
    Load the persisted watchlist (list of symbols) or None if never saved.

    With DATABASE_URL: reads Postgres (authoritative) and refreshes the local
    watchlist.json warm cache. Without: reads the local file.
    Returns None when no watchlist has ever been saved — callers should fall
    back to config.DEFAULT_WATCHLIST.
    """
    wl = _load("watchlist")
    if wl is None:
        return None
    if isinstance(wl, dict):
        wl = wl.get("symbols", [])
    if not isinstance(wl, list):
        return None
    return [str(s) for s in wl]


# ── Signal history snapshots (append-only) ───────────────────────────────────

def append_signal_snapshot(scan_id: str, signals: List[Any],
                           market_context: Any,
                           snapshot_ts: Optional[str] = None,
                           canonical_scan_id: Optional[str] = None) -> bool:
    """
    Append one timestamped snapshot of the scan's signals + market context.

    `scan_id` must be unique PER INTELLIGENCE RUN (the caller generates it);
    `canonical_scan_id` optionally correlates the row with the phase7
    live-data snapshot that was current at scan time (many history rows may
    share the same canonical id).

    Idempotent per scan_id: re-running with the same id does NOT create a
    duplicate row (first write wins — history is append-only, never rewritten).

    Returns True if a new row was inserted, False if the scan_id already
    existed. Raises on DB failure when DATABASE_URL is set.
    """
    if not scan_id:
        raise ValueError("append_signal_snapshot requires a non-empty scan_id")

    if not db_available():
        history = _read_json(_SNAPSHOT_FALLBACK_PATH) or []
        if not isinstance(history, list):
            history = []
        if any(isinstance(r, dict) and r.get("scan_id") == scan_id for r in history):
            return False
        from datetime import datetime, timezone
        history.append({
            "scan_id": scan_id,
            "canonical_scan_id": canonical_scan_id,
            "snapshot_ts": snapshot_ts or datetime.now(timezone.utc).isoformat(),
            "signals": signals,
            "market_context": market_context,
        })
        _write_json(_SNAPSHOT_FALLBACK_PATH, history[-_SNAPSHOT_FALLBACK_MAX:])
        return True

    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            if snapshot_ts:
                cur.execute(
                    """
                    INSERT INTO signal_snapshots
                        (scan_id, canonical_scan_id, snapshot_ts, signals, market_context)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (scan_id) DO NOTHING
                    """,
                    (scan_id, canonical_scan_id, snapshot_ts,
                     json.dumps(signals, default=str),
                     json.dumps(market_context, default=str)),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO signal_snapshots
                        (scan_id, canonical_scan_id, signals, market_context)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (scan_id) DO NOTHING
                    """,
                    (scan_id, canonical_scan_id,
                     json.dumps(signals, default=str),
                     json.dumps(market_context, default=str)),
                )
            inserted = cur.rowcount > 0
        conn.commit()
        return inserted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


RETENTION_FULL_DAYS = 30  # keep every snapshot this many days back


def prune_signal_snapshots(retention_days: int = RETENTION_FULL_DAYS) -> dict:
    """
    Retention policy for the append-only signal history:

    - Every snapshot from the last `retention_days` days is kept untouched.
    - Older than that, history is THINNED to one snapshot per calendar day
      (IST trading day): the day's latest snapshot survives, the rest are
      deleted. The long-range timeline stays meaningful (one point per day)
      while storage stays bounded.

    Returns {"deleted": n, "kept_recent_all": bool}. Never raises for the
    caller-facing path — DB errors propagate so callers can decide, but the
    post-scan pipeline wraps this best-effort.
    """
    retention_days = max(1, int(retention_days))

    if not db_available():
        from datetime import datetime, timedelta, timezone
        history = _read_json(_SNAPSHOT_FALLBACK_PATH) or []
        if not isinstance(history, list):
            return {"deleted": 0, "kept_recent_all": True}
        rows = [r for r in history if isinstance(r, dict)]
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=retention_days)).isoformat()
        recent = [r for r in rows if str(r.get("snapshot_ts", "")) >= cutoff]
        old = [r for r in rows if str(r.get("snapshot_ts", "")) < cutoff]
        # keep latest per day among old rows (day = first 10 chars of ISO ts)
        best_per_day: dict = {}
        for r in old:
            day = str(r.get("snapshot_ts", ""))[:10]
            cur = best_per_day.get(day)
            if cur is None or str(r.get("snapshot_ts", "")) > str(cur.get("snapshot_ts", "")):
                best_per_day[day] = r
        kept = list(best_per_day.values()) + recent
        deleted = len(rows) - len(kept)
        if deleted > 0:
            kept.sort(key=lambda r: str(r.get("snapshot_ts", "")))
            _write_json(_SNAPSHOT_FALLBACK_PATH, kept[-_SNAPSHOT_FALLBACK_MAX:])
        return {"deleted": max(0, deleted), "kept_recent_all": True}

    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM signal_snapshots
                WHERE snapshot_ts < NOW() - (%s || ' days')::interval
                  AND id NOT IN (
                    SELECT DISTINCT ON (
                        date_trunc('day', snapshot_ts AT TIME ZONE 'Asia/Kolkata'))
                        id
                    FROM signal_snapshots
                    WHERE snapshot_ts < NOW() - (%s || ' days')::interval
                    ORDER BY
                        date_trunc('day', snapshot_ts AT TIME ZONE 'Asia/Kolkata'),
                        snapshot_ts DESC, id DESC
                  )
                """,
                (retention_days, retention_days),
            )
            deleted = cur.rowcount
        conn.commit()
        return {"deleted": deleted, "kept_recent_all": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_signal_snapshots(limit: int = 30,
                          start: Optional[str] = None,
                          end: Optional[str] = None) -> List[dict]:
    """
    Load snapshots, newest first.

    limit       : max rows returned (1–200)
    start / end : optional ISO date/datetime bounds on snapshot_ts (inclusive)
    """
    limit = max(1, min(int(limit or 30), 200))

    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            clauses, params = [], []
            if start:
                clauses.append("snapshot_ts >= %s")
                params.append(start)
            if end:
                clauses.append("snapshot_ts <= %s")
                params.append(end)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT scan_id, canonical_scan_id, snapshot_ts, signals, market_context
                    FROM signal_snapshots
                    {where}
                    ORDER BY snapshot_ts DESC, id DESC
                    LIMIT %s
                    """,
                    (*params, limit),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        out = []
        for scan_id, canonical_id, ts, sigs, ctx in rows:
            if isinstance(sigs, str):
                sigs = json.loads(sigs)
            if isinstance(ctx, str):
                ctx = json.loads(ctx)
            out.append({
                "scan_id": scan_id,
                "canonical_scan_id": canonical_id,
                "snapshot_ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "signals": sigs,
                "market_context": ctx,
            })
        return out

    # Local-dev fallback
    history = _read_json(_SNAPSHOT_FALLBACK_PATH) or []
    if not isinstance(history, list):
        return []
    rows = [r for r in history if isinstance(r, dict)]
    if start:
        rows = [r for r in rows if str(r.get("snapshot_ts", "")) >= start]
    if end:
        rows = [r for r in rows if str(r.get("snapshot_ts", ""))[:len(end)] <= end]
    rows.sort(key=lambda r: str(r.get("snapshot_ts", "")), reverse=True)
    return rows[:limit]
