"""
phase26c_store.py — Phase 26C: append-only result storage for the recovery,
performance, and trading-quality validation areas.

One table, `phase26c_results`, keyed by result_id with an `area` column
(RECOVERY | PERFORMANCE | QUALITY). Results are append-only — a run is never
overwritten. With DATABASE_URL Postgres is authoritative; without it a
flock-serialized JSON file fallback is used (redirectable in tests via the
module-level RESULTS_FILE).

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
            _write_json(RESULTS_FILE, rows)   # append-only: never truncate
        return record

    return _with_db(in_db, in_file)


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
