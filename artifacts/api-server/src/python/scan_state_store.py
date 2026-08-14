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


def count_scans_today_ist() -> int:
    """Return the number of SCAN_COMPLETED pipeline events since midnight IST
    today.

    IST = UTC + 05:30.  The correct approach is:
      1. Convert the current UTC instant to IST (add 5h30m).
      2. Take that IST local date at 00:00:00.
      3. Convert back to UTC (subtract 5h30m) to get the cutoff.

    This correctly handles the post-18:30 UTC case — after 18:30 UTC the IST
    clock has already rolled over to the next day, so the cutoff must advance
    to 18:30 of the *current* UTC date, not the previous one.

    Falls back to 0 on any error or when DB is unavailable.  Never raises.
    """
    if not db_available():
        return 0
    try:
        from datetime import timedelta
        _IST_OFFSET = timedelta(hours=5, minutes=30)
        now_utc = _now_utc()
        # Step 1: shift to IST
        now_ist = now_utc + _IST_OFFSET
        # Step 2: IST midnight (00:00) of the current IST calendar day
        ist_midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        # Step 3: convert back to UTC
        today_ist_midnight_utc = ist_midnight - _IST_OFFSET
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM pipeline_events
                    WHERE event_type = 'SCAN_COMPLETED'
                      AND ts >= %s
                    """,
                    (today_ist_midnight_utc,),
                )
                row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def build_scan_status_response() -> Dict[str, Any]:
    """Build and return the complete enriched scan-status payload.

    Called directly by the main.py ``scan_status`` command so that both
    the production path and tests exercise the *same* code, not a copy.

    Returns:
        {
            "success": True,
            "latest_scan": dict | None,
            "age_minutes": float | None,
            "scan_count_today": int,
            "rotation": int,
            "cadence_minutes": int | None,
            "progress": dict | None,
        }
    """
    meta = load_latest_meta()

    # ── Age in minutes since the last successful snapshot ──────────────────
    age_minutes: Optional[float] = None
    try:
        snap_ts = (meta or {}).get("snapshot_ts") or (meta or {}).get("completed_at")
        if snap_ts:
            snap_dt = datetime.fromisoformat(str(snap_ts).replace("Z", "+00:00"))
            age_minutes = round(
                (_now_utc() - snap_dt).total_seconds() / 60, 1
            )
    except Exception:
        pass

    # ── Cadence from operator-configured settings ──────────────────────────
    cadence_minutes: Optional[int] = None
    try:
        from phase20_store import get_settings as _p20_settings
        cadence_minutes = int(
            (_p20_settings() or {}).get("scan_interval_minutes", 5)
        )
    except Exception:
        pass

    # ── Completed scans today (IST) and rotation index ────────────────────
    scan_count_today = count_scans_today_ist()

    # ── Live in-flight progress from KV (None when scanner is idle) ────────
    progress: Optional[Dict[str, Any]] = None
    try:
        from phase20_store import kv_get as _p20_kv
        _raw = _p20_kv("scan_progress")
        if isinstance(_raw, dict):
            progress = _raw
    except Exception:
        pass

    return {
        "success": True,
        "latest_scan": meta,
        "age_minutes": age_minutes,
        "scan_count_today": scan_count_today,
        "rotation": scan_count_today,
        "cadence_minutes": cadence_minutes,
        "progress": progress,
    }


def _ist_today_cutoff_utc() -> Tuple[datetime, str]:
    """Return (cutoff_utc, ist_date_str) for today's IST calendar day.

    cutoff_utc  — UTC datetime equal to midnight IST today (18:30 UTC yesterday
                  before 18:30 UTC; 18:30 UTC today after 18:30 UTC).
    ist_date_str — 'YYYY-MM-DD' of the current IST calendar day.

    Shared by count_scans_today_ist() and build_scan_history_response() so
    both functions always use the exact same day boundary.
    """
    from datetime import timedelta
    _IST_OFFSET = timedelta(hours=5, minutes=30)
    now_ist = _now_utc() + _IST_OFFSET
    ist_midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return ist_midnight - _IST_OFFSET, now_ist.strftime("%Y-%m-%d")


def build_scan_history_response(limit: int = 10) -> Dict[str, Any]:
    """Return a list of today's completed scans with duration and gap-from-previous.

    Pairs SCAN_STARTED / SCAN_COMPLETED pipeline_events from today's IST day by
    matching them chronologically (oldest-first pairing; no payload scan_id
    dependency so the function is robust to payload schema variation).

    Response shape::

        {
            "success": True,
            "history": [            # newest-first
                {
                    "started_at":      str | None,   # ISO-8601 UTC
                    "completed_at":    str | None,   # ISO-8601 UTC
                    "duration_s":      int | None,   # seconds; None if started_at missing
                    "symbols_scanned": int | None,   # from SCAN_COMPLETED payload
                    "gap_from_prev_s": int | None,   # gap since prev COMPLETED; None for first
                    "status":          "COMPLETED",
                },
                ...
            ],
            "count": int,
            "ist_date": "YYYY-MM-DD",
        }

    Falls back to an empty history on any error or when DB is unavailable.
    Never raises.
    """
    cutoff_utc, ist_date = _ist_today_cutoff_utc()  # type: ignore[misc]

    empty: Dict[str, Any] = {"success": True, "history": [], "count": 0, "ist_date": ist_date}

    if not db_available():
        return empty

    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ts, event_type, payload
                    FROM pipeline_events
                    WHERE event_type IN ('SCAN_STARTED', 'SCAN_COMPLETED')
                      AND ts >= %s
                    ORDER BY ts ASC
                    """,
                    (cutoff_utc,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return empty

    # State-machine pairing: process events in chronological order.
    #
    # Rule: each SCAN_STARTED opens a "pending" slot. If another SCAN_STARTED
    # arrives before a SCAN_COMPLETED, the previous start was abandoned (e.g.
    # SCAN_FAILED or API restart) — discard it and treat the new STARTED as the
    # current pending.  Only pair a SCAN_COMPLETED with the *most recent*
    # SCAN_STARTED, never with one that was superseded.
    #
    # This prevents an abandoned-start duration (e.g. 15 min since a failed scan
    # started) from polluting the next successful scan's duration (5 min).
    history: list[Dict[str, Any]] = []
    pending_start: Optional[datetime] = None   # ts of the open SCAN_STARTED
    prev_completed_ts: Optional[datetime] = None

    def _extract_symbols(p: Dict[str, Any]) -> Optional[int]:
        for key in ("symbols_done", "symbols_received", "symbols_succeeded",
                    "symbols_scanned", "symbols_total", "universe_size"):
            v = p.get(key)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
        return None

    for ts_raw, event_type, payload in rows:
        # psycopg2 returns datetime objects; ensure timezone-aware
        if isinstance(ts_raw, datetime):
            ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=timezone.utc)
        else:
            try:
                ts = datetime.fromisoformat(str(ts_raw))
                if not ts.tzinfo:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                continue

        if not isinstance(payload, dict):
            try:
                payload = json.loads(payload) if payload else {}
            except Exception:
                payload = {}

        if event_type == "SCAN_STARTED":
            # Supersede any abandoned pending start — the previous scan failed
            # or was interrupted without emitting SCAN_COMPLETED.
            pending_start = ts

        elif event_type == "SCAN_COMPLETED":
            duration_s: Optional[int] = None
            if pending_start is not None:
                try:
                    duration_s = max(0, round((ts - pending_start).total_seconds()))
                except Exception:
                    pass

            gap_from_prev_s: Optional[int] = None
            if prev_completed_ts is not None and pending_start is not None:
                try:
                    gap_from_prev_s = max(0, round(
                        (pending_start - prev_completed_ts).total_seconds()))
                except Exception:
                    pass

            history.append({
                "started_at":      _iso(pending_start) if pending_start is not None else None,
                "completed_at":    _iso(ts),
                "duration_s":      duration_s,
                "symbols_scanned": _extract_symbols(payload),
                "gap_from_prev_s": gap_from_prev_s,
                "status":          "COMPLETED",
            })
            prev_completed_ts = ts
            pending_start = None  # consumed — reset for the next scan

    # Apply limit (oldest ones fall off) and return newest-first
    history = list(reversed(history[-limit:]))

    return {
        "success": True,
        "history": history,
        "count":   len(history),
        "ist_date": ist_date,
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
