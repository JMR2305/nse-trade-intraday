"""
phase26_store.py — Phase 26A: End-to-End Validation run storage.

Append-only store for E2E validation runs. Each run is a permanent record —
runs are never overwritten or re-evaluated. History stays queryable forever
(subject to the file-fallback cap in local dev).

With DATABASE_URL: Postgres is authoritative. Without it (local dev / tests):
JSON file fallback in this directory.

READ path never mutates. WRITE path is insert-only (ON CONFLICT DO NOTHING).
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
# File-fallback path (module-level so tests can point it at a tmpdir)
RUNS_FILE = os.path.join(_DIR, "phase26_validation_runs.json")
_FALLBACK_CAP = 500          # keep local-dev file bounded

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
            CREATE TABLE IF NOT EXISTS phase26_validation_runs (
                run_id     TEXT PRIMARY KEY,
                scan_id    TEXT,
                verdict    TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                result     JSONB NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_p26_runs_created
            ON phase26_validation_runs (created_at DESC)
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
    """Serialize cross-process read-modify-write on the fallback file."""
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


def new_run_id() -> str:
    return f"e2e-{uuid.uuid4().hex[:12]}"


def append_run(result: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a completed validation run. Append-only — an existing run_id
    is never overwritten. Returns the stored record."""
    run_id = str(result.get("run_id") or new_run_id())
    record = {
        "run_id": run_id,
        "scan_id": result.get("scan_id"),
        "verdict": result.get("verdict"),
        "created_at": result.get("generated_at") or _now(),
        "result": result,
    }

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase26_validation_runs
                    (run_id, scan_id, verdict, created_at, result)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (run_id, record["scan_id"], str(record["verdict"]),
                 record["created_at"], json.dumps(result, default=str)),
            )
        return record

    def in_file():
        with _file_lock(RUNS_FILE):
            rows = _read_json(RUNS_FILE, [])
            if any(r.get("run_id") == run_id for r in rows):
                return record      # append-only: never overwrite
            rows.append(record)
            _write_json(RUNS_FILE, rows[-_FALLBACK_CAP:])
        return record

    return _with_db(in_db, in_file)


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    """Newest-first run summaries (no full result payload)."""
    limit = max(1, min(int(limit or 50), 500))

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, scan_id, verdict, created_at,
                       result->'totals' AS totals
                FROM phase26_validation_runs
                ORDER BY created_at DESC LIMIT %s
                """, (limit,))
            return [{"run_id": r[0], "scan_id": r[1], "verdict": r[2],
                     "created_at": str(r[3]), "totals": r[4]}
                    for r in cur.fetchall()]

    def in_file():
        rows = _read_json(RUNS_FILE, [])
        rows = sorted(rows, key=lambda r: str(r.get("created_at") or ""),
                      reverse=True)[:limit]
        return [{"run_id": r.get("run_id"), "scan_id": r.get("scan_id"),
                 "verdict": r.get("verdict"),
                 "created_at": r.get("created_at"),
                 "totals": (r.get("result") or {}).get("totals")}
                for r in rows]

    return _with_db(in_db, in_file)


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT result FROM phase26_validation_runs WHERE run_id = %s",
                (str(run_id),))
            row = cur.fetchone()
        return row[0] if row else None

    def in_file():
        for r in _read_json(RUNS_FILE, []):
            if r.get("run_id") == run_id:
                return r.get("result")
        return None

    return _with_db(in_db, in_file)
