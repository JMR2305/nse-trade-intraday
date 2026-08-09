"""
phase26c_store.py — Phase 26C: append-only result storage for the recovery,
performance, and trading-quality validation areas.

One table, `phase26c_results`, keyed by result_id with an `area` column
(RECOVERY | PERFORMANCE | QUALITY). Results are append-only — a run is never
overwritten or re-evaluated — but history is BOUNDED: after each append,
rows older than RETENTION_DAYS are pruned (always keeping the newest
KEEP_MIN_PER_AREA rows per area). With DATABASE_URL Postgres is
authoritative; without it a flock-serialized JSON file fallback is used
(redirectable in tests via the module-level RESULTS_FILE).

PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(_DIR, "phase26c_results.json")

AREAS = ("RECOVERY", "PERFORMANCE", "QUALITY")

_SCHEMA_READY = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phase26c_results (
                result_id  TEXT PRIMARY KEY,
                area       TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                verdict    TEXT,
                result     JSONB NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_p26c_area_created
            ON phase26c_results (area, created_at DESC)
        """)
    conn.commit()
    _SCHEMA_READY = True


def _with_db(fn, fallback):
    if not db_available():
        return fallback()
    conn = _connect()
    try:
        _ensure_schema(conn)
        out = fn(conn)
        conn.commit()
        return out
    finally:
        conn.close()


def _read_json(path: str, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data) -> None:
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, default=str)
    os.replace(tmp, path)


@contextmanager
def _file_lock(path: str):
    lock_path = path + ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# ── Retention ────────────────────────────────────────────────────────────────
# History must stay bounded under continuous operation: results older than
# RETENTION_DAYS are pruned after each append, but the newest KEEP_MIN_PER_AREA
# rows per area are always kept so history survives quiet periods (weekends,
# holidays, disabled schedulers) and latest_result() never goes empty.

RETENTION_DAYS = 30
KEEP_MIN_PER_AREA = 20
_FALLBACK_MAX_PER_AREA = 200  # hard cap for the local JSON fallback


def prune_results(days: int = RETENTION_DAYS,
                  keep_min: int = KEEP_MIN_PER_AREA) -> Dict[str, Any]:
    """Delete results older than `days`, always keeping the newest `keep_min`
    rows per area. Fail-safe: NEVER raises (called after each append)."""
    try:
        days = max(1, int(days))
        keep_min = max(0, int(keep_min))

        def in_db(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM phase26c_results
                    WHERE created_at < NOW() - (%s || ' days')::interval
                      AND result_id NOT IN (
                        SELECT result_id FROM (
                            SELECT result_id,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY area
                                       ORDER BY created_at DESC
                                   ) AS rn
                            FROM phase26c_results
                        ) ranked
                        WHERE rn <= %s
                      )
                    """,
                    (days, keep_min),
                )
                deleted = cur.rowcount
            return {"deleted": deleted, "days": days, "keep_min": keep_min}

        def in_file():
            deleted = 0
            with _file_lock(RESULTS_FILE):
                rows = _read_json(RESULTS_FILE, [])
                kept: List[Dict[str, Any]] = []
                by_area: Dict[str, List[Dict[str, Any]]] = {}
                for r in rows:
                    by_area.setdefault(str(r.get("area")), []).append(r)
                cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
                for area_rows in by_area.values():
                    area_rows.sort(key=lambda r: str(r.get("created_at") or ""),
                                   reverse=True)
                    for idx, r in enumerate(area_rows):
                        if idx < keep_min or (
                            idx < _FALLBACK_MAX_PER_AREA
                            and _created_ts(r) >= cutoff
                        ):
                            kept.append(r)
                        else:
                            deleted += 1
                if deleted:
                    _write_json(RESULTS_FILE, kept)
            return {"deleted": deleted, "days": days, "keep_min": keep_min,
                    "fallback": True}

        return _with_db(in_db, in_file)
    except Exception:
        return {"deleted": 0, "days": days, "error": True}


def _created_ts(record: Dict[str, Any]) -> float:
    try:
        raw = str(record.get("created_at") or "")
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        # Unparseable timestamp: treat as fresh so we never delete a row we
        # can't age-judge (append-only bias toward keeping evidence).
        return datetime.now(timezone.utc).timestamp()


def new_result_id(area: str) -> str:
    return f"{area.lower()}-{uuid.uuid4().hex[:12]}"


def append_result(area: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Append one validation result (never overwrites). Returns the stored
    record including its result_id — callers must surface that id."""
    area = str(area).upper()
    if area not in AREAS:
        raise ValueError(f"unknown phase26c area: {area}")
    result_id = str(result.get("result_id") or new_result_id(area))
    result = dict(result)
    result["result_id"] = result_id
    result["area"] = area
    record = {
        "result_id": result_id,
        "area": area,
        "created_at": result.get("generated_at") or _now(),
        "verdict": result.get("verdict"),
        "result": result,
    }

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase26c_results
                    (result_id, area, created_at, verdict, result)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (result_id) DO NOTHING
                """,
                (result_id, area, record["created_at"],
                 str(record["verdict"]), json.dumps(result, default=str)),
            )
        return record

    def in_file():
        with _file_lock(RESULTS_FILE):
            rows = _read_json(RESULTS_FILE, [])
            if any(r.get("result_id") == result_id for r in rows):
                return record
            rows.append(record)
            _write_json(RESULTS_FILE, rows)   # never overwrites existing runs
        return record

    stored = _with_db(in_db, in_file)
    # Retention: bound history after each write; fail-safe, never affects
    # the append result.
    prune_results()
    return stored


# ── Retention ────────────────────────────────────────────────────────────────
# Pruning deliberately lives OUTSIDE the append-only contract above:
# append_result() never truncates. prune_results() is invoked as a
# separate fail-safe job after each validation run persists (on-write
# prune), mirroring the pipeline_events 14-day prune pattern.
#
# Policy (per area): delete rows older than RETENTION_DAYS, but always
# keep the newest RETENTION_MIN_KEEP rows per area regardless of age —
# so latest_result() and recent history are never affected.
RETENTION_DAYS = 30
RETENTION_MIN_KEEP = 20


def prune_results(days: int = RETENTION_DAYS,
                  keep_min: int = RETENTION_MIN_KEEP) -> Dict[str, Any]:
    """Bounded retention for phase26c_results (DB and file fallback).
    NEVER raises. Returns {"deleted": n, "days": days, "keep_min": k}."""
    days = max(1, int(days))
    keep_min = max(1, int(keep_min))
    try:
        def in_db(conn):
            deleted = 0
            with conn.cursor() as cur:
                for area in AREAS:
                    cur.execute(
                        """
                        DELETE FROM phase26c_results
                        WHERE area = %s
                          AND created_at < NOW() - (%s || ' days')::interval
                          AND result_id NOT IN (
                              SELECT result_id FROM phase26c_results
                              WHERE area = %s
                              ORDER BY created_at DESC LIMIT %s
                          )
                        """,
                        (area, days, area, keep_min),
                    )
                    deleted += cur.rowcount
            return {"deleted": deleted, "days": days, "keep_min": keep_min}

        def in_file():
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc)
                      - timedelta(days=days)).isoformat()
            deleted = 0
            with _file_lock(RESULTS_FILE):
                rows = _read_json(RESULTS_FILE, [])
                kept: List[Dict[str, Any]] = []
                for area in AREAS:
                    area_rows = sorted(
                        (r for r in rows if r.get("area") == area),
                        key=lambda r: str(r.get("created_at") or ""),
                        reverse=True)
                    for i, r in enumerate(area_rows):
                        if i < keep_min or \
                                str(r.get("created_at") or "") >= cutoff:
                            kept.append(r)
                        else:
                            deleted += 1
                # preserve rows with unknown areas untouched
                kept.extend(r for r in rows if r.get("area") not in AREAS)
                if deleted:
                    kept.sort(key=lambda r: str(r.get("created_at") or ""))
                    _write_json(RESULTS_FILE, kept)
            return {"deleted": deleted, "days": days, "keep_min": keep_min}

        return _with_db(in_db, in_file)
    except Exception as exc:
        return {"deleted": 0, "days": days, "keep_min": keep_min,
                "error": str(exc)[:200]}


def list_results(area: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Newest-first result summaries for one area."""
    area = str(area).upper()
    limit = max(1, min(int(limit or 50), 500))

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT result_id, created_at, verdict
                FROM phase26c_results WHERE area = %s
                ORDER BY created_at DESC LIMIT %s
                """, (area, limit))
            return [{"result_id": r[0], "created_at": str(r[1]),
                     "verdict": r[2], "area": area}
                    for r in cur.fetchall()]

    def in_file():
        rows = [r for r in _read_json(RESULTS_FILE, [])
                if r.get("area") == area]
        rows = sorted(rows, key=lambda r: str(r.get("created_at") or ""),
                      reverse=True)[:limit]
        return [{"result_id": r.get("result_id"),
                 "created_at": r.get("created_at"),
                 "verdict": r.get("verdict"), "area": area}
                for r in rows]

    return _with_db(in_db, in_file)


def latest_result(area: str) -> Optional[Dict[str, Any]]:
    """Full result payload of the most recent run in one area."""
    area = str(area).upper()

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT result FROM phase26c_results WHERE area = %s"
                " ORDER BY created_at DESC LIMIT 1", (area,))
            row = cur.fetchone()
        return row[0] if row else None

    def in_file():
        rows = [r for r in _read_json(RESULTS_FILE, [])
                if r.get("area") == area]
        if not rows:
            return None
        rows = sorted(rows, key=lambda r: str(r.get("created_at") or ""))
        return rows[-1].get("result")

    return _with_db(in_db, in_file)
