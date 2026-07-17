"""
scan_state_store.py — Phase 19B: durable, Autoscale-safe scan state.

Production runs on Replit Autoscale where process memory and local files are
per-instance and ephemeral. The latest completed scan snapshot, its metadata,
and the scan lock/lease must live in the shared PostgreSQL database
(DATABASE_URL) so every instance reads the same state.

Behaviour:
- With DATABASE_URL: snapshot + metadata + lock live in Postgres.
- Without DATABASE_URL (local dev/tests): falls back to the local JSON file
  (same path as the legacy phase7_scan_cache.json) and an in-process lock.

Safety:
- A FAILED scan NEVER overwrites the last successful snapshot.
- Paper trading / research only. No live orders anywhere in this module.
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

_DIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_SNAPSHOT_FILE = os.path.join(_DIR, "phase7_scan_cache.json")
FALLBACK_META_FILE = os.path.join(_DIR, "phase19b_scan_meta.json")
FALLBACK_LOCK_FILE = os.path.join(_DIR, "phase19b_scan_lock.json")

# A scan lock older than this is considered stuck and may be reclaimed.
LOCK_TIMEOUT_S = 180

_SCHEMA_READY = False


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def db_available() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    import psycopg2  # imported lazily so file-fallback envs don't need it
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_state (
                id INTEGER PRIMARY KEY,
                scan_id TEXT,
                status TEXT,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                snapshot_ts TEXT,
                provider TEXT,
                symbols_requested INTEGER,
                symbols_received INTEGER,
                symbols_missing INTEGER,
                symbols_stale INTEGER,
                missing_symbols JSONB,
                stale_symbols JSONB,
                error TEXT,
                snapshot JSONB,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_lock (
                name TEXT PRIMARY KEY,
                holder TEXT,
                acquired_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ
            )
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def _holder_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


# ── Snapshot (latest successful scan) ─────────────────────────────────────────

def save_successful_scan(snapshot: Dict[str, Any]) -> None:
    """Persist a successful scan snapshot + metadata (durable when DB present)."""
    meta = _meta_from_snapshot(snapshot, status="SUCCESS", error=None)
    # Always keep a local file copy as a warm read cache for this instance.
    try:
        with open(FALLBACK_SNAPSHOT_FILE, "w") as f:
            json.dump(snapshot, f, default=str)
    except Exception:
        pass
    if not db_available():
        _write_json(FALLBACK_META_FILE, meta)
        return
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scan_state (
                    id, scan_id, status, started_at, completed_at, snapshot_ts,
                    provider, symbols_requested, symbols_received, symbols_missing,
                    symbols_stale, missing_symbols, stale_symbols, error, snapshot,
                    updated_at
                ) VALUES (
                    1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    scan_id = EXCLUDED.scan_id,
                    status = EXCLUDED.status,
                    started_at = EXCLUDED.started_at,
                    completed_at = EXCLUDED.completed_at,
                    snapshot_ts = EXCLUDED.snapshot_ts,
                    provider = EXCLUDED.provider,
                    symbols_requested = EXCLUDED.symbols_requested,
                    symbols_received = EXCLUDED.symbols_received,
                    symbols_missing = EXCLUDED.symbols_missing,
                    symbols_stale = EXCLUDED.symbols_stale,
                    missing_symbols = EXCLUDED.missing_symbols,
                    stale_symbols = EXCLUDED.stale_symbols,
                    error = NULL,
                    snapshot = EXCLUDED.snapshot,
                    updated_at = NOW()
                """,
                (
                    meta["scan_id"], meta["status"], meta["started_at"],
                    meta["completed_at"], meta["snapshot_ts"], meta["provider"],
                    meta["symbols_requested"], meta["symbols_received"],
                    meta["symbols_missing"], meta["symbols_stale"],
                    json.dumps(meta["missing_symbols"]),
                    json.dumps(meta["stale_symbols"]),
                    json.dumps(snapshot, default=str),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def record_failed_scan(error: str, scan_id: Optional[str] = None) -> None:
    """Record a failed scan WITHOUT touching the last successful snapshot."""
    now = _iso(_now_utc())
    if not db_available():
        meta = _read_json(FALLBACK_META_FILE) or {}
        meta["last_failed_scan"] = {
            "scan_id": scan_id, "error": str(error)[:500], "failed_at": now,
        }
        _write_json(FALLBACK_META_FILE, meta)
        return
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            # Only update the error column; snapshot/snapshot_ts/etc. untouched.
            cur.execute(
                """
                INSERT INTO scan_state (id, status, error, updated_at)
                VALUES (1, 'FAILED', %s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    error = EXCLUDED.error,
                    updated_at = NOW()
                """,
                (f"[{now}] {str(error)[:500]}",),
            )
        conn.commit()
    finally:
        conn.close()


def load_latest_snapshot() -> Optional[Dict[str, Any]]:
    """Load the latest successful scan snapshot (DB first, file fallback)."""
    if db_available():
        try:
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute("SELECT snapshot FROM scan_state WHERE id = 1")
                    row = cur.fetchone()
                if row and row[0]:
                    snap = row[0]
                    if isinstance(snap, str):
                        snap = json.loads(snap)
                    # Refresh the local warm cache for cheap subsequent reads.
                    try:
                        with open(FALLBACK_SNAPSHOT_FILE, "w") as f:
                            json.dump(snap, f, default=str)
                    except Exception:
                        pass
                    return snap
            finally:
                conn.close()
        except Exception:
            pass  # fall back to local file below
    return _read_json(FALLBACK_SNAPSHOT_FILE)


def load_latest_meta() -> Optional[Dict[str, Any]]:
    """Latest scan metadata (without the big snapshot payload)."""
    if db_available():
        try:
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT scan_id, status, started_at, completed_at,
                               snapshot_ts, provider, symbols_requested,
                               symbols_received, symbols_missing, symbols_stale,
                               missing_symbols, stale_symbols, error, updated_at
                        FROM scan_state WHERE id = 1
                        """
                    )
                    row = cur.fetchone()
                if row:
                    def _ts(v):
                        return _iso(v.astimezone(timezone.utc)) if isinstance(v, datetime) else v
                    return {
                        "scan_id": row[0], "status": row[1],
                        "started_at": _ts(row[2]), "completed_at": _ts(row[3]),
                        "snapshot_ts": row[4], "provider": row[5],
                        "symbols_requested": row[6], "symbols_received": row[7],
                        "symbols_missing": row[8], "symbols_stale": row[9],
                        "missing_symbols": row[10] or [],
                        "stale_symbols": row[11] or [],
                        "error": row[12], "updated_at": _ts(row[13]),
                    }
            finally:
                conn.close()
        except Exception:
            pass
    meta = _read_json(FALLBACK_META_FILE)
    if meta:
        return meta
    snap = _read_json(FALLBACK_SNAPSHOT_FILE)
    if snap:
        return _meta_from_snapshot(snap, status="SUCCESS", error=None)
    return None


# ── Distributed scan lock/lease ───────────────────────────────────────────────

def acquire_scan_lock(name: str = "phase7_scan",
                      timeout_s: float = LOCK_TIMEOUT_S) -> Tuple[bool, str]:
    """
    Try to acquire the distributed scan lease. Returns (acquired, holder_id).
    An expired lease (older than timeout_s) is reclaimed automatically —
    stuck-lock recovery.
    """
    holder = _holder_id()
    now = _now_utc()
    if not db_available():
        lock = _read_json(FALLBACK_LOCK_FILE)
        if lock:
            try:
                exp = datetime.fromisoformat(lock["expires_at"].replace("Z", "+00:00"))
                if exp > now:
                    return False, lock.get("holder", "")
            except Exception:
                pass
        _write_json(FALLBACK_LOCK_FILE, {
            "holder": holder, "acquired_at": _iso(now),
            "expires_at": _iso(datetime.fromtimestamp(now.timestamp() + timeout_s, tz=timezone.utc)),
        })
        return True, holder
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scan_lock (name, holder, acquired_at, expires_at)
                VALUES (%s, %s, NOW(), NOW() + make_interval(secs => %s))
                ON CONFLICT (name) DO UPDATE SET
                    holder = EXCLUDED.holder,
                    acquired_at = NOW(),
                    expires_at = NOW() + make_interval(secs => %s)
                WHERE scan_lock.expires_at < NOW()
                RETURNING holder
                """,
                (name, holder, timeout_s, timeout_s),
            )
            row = cur.fetchone()
        conn.commit()
        return (row is not None and row[0] == holder), holder
    finally:
        conn.close()


def renew_scan_lock(holder: str, name: str = "phase7_scan",
                    timeout_s: float = LOCK_TIMEOUT_S) -> bool:
    """
    Heartbeat-renew the lease while a long scan is still running, so a
    legitimately slow scan (e.g. provider retries) never loses its lock
    mid-run and no second scan can start. Only the current holder can renew.
    Returns True if the lease was renewed.
    """
    now = _now_utc()
    if not db_available():
        lock = _read_json(FALLBACK_LOCK_FILE)
        if lock and lock.get("holder") == holder:
            lock["expires_at"] = _iso(datetime.fromtimestamp(
                now.timestamp() + timeout_s, tz=timezone.utc))
            _write_json(FALLBACK_LOCK_FILE, lock)
            return True
        return False
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE scan_lock
                SET expires_at = NOW() + make_interval(secs => %s)
                WHERE name = %s AND holder = %s
                RETURNING holder
                """,
                (timeout_s, name, holder),
            )
            row = cur.fetchone()
        conn.commit()
        return row is not None
    finally:
        conn.close()


def release_scan_lock(holder: str, name: str = "phase7_scan") -> None:
    if not db_available():
        lock = _read_json(FALLBACK_LOCK_FILE)
        if lock and lock.get("holder") == holder:
            try:
                os.remove(FALLBACK_LOCK_FILE)
            except Exception:
                pass
        return
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM scan_lock WHERE name = %s AND holder = %s",
                        (name, holder))
        conn.commit()
    finally:
        conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _meta_from_snapshot(snapshot: Dict[str, Any], status: str,
                        error: Optional[str]) -> Dict[str, Any]:
    health = snapshot.get("provider_health") or {}
    audit = snapshot.get("scan_audit") or {}
    safety = snapshot.get("safety") or {}
    requested = int(health.get("symbols_requested") or 0)
    received = int(health.get("symbols_succeeded") or 0)
    return {
        "scan_id": snapshot.get("scan_id"),
        "status": status,
        "started_at": snapshot.get("snapshot_ts"),
        "completed_at": audit.get("scan_completed_ts") or snapshot.get("snapshot_ts"),
        "snapshot_ts": snapshot.get("snapshot_ts"),
        "provider": safety.get("data_provider") or health.get("provider") or "unknown",
        "symbols_requested": requested,
        "symbols_received": received,
        "symbols_missing": max(0, requested - received),
        "symbols_stale": int(health.get("symbols_stale") or 0),
        "missing_symbols": list(health.get("unavailable_symbols") or []),
        "stale_symbols": list(health.get("stale_symbols") or []),
        "error": error,
    }


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: str, data: Dict[str, Any]) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f, default=str)
    except Exception:
        pass
