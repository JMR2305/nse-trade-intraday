"""
Phase 23 Part 2G/J — Backtest runs + isolated backtest portfolio ledger.

HARD ISOLATION RULE: backtests NEVER touch the live phase20 paper ledger.
All backtest state lives in dedicated tables:

    backtest_runs    — one row per run (config, status, progress, metrics)
    backtest_trades  — the backtest execution ledger (per run_id)

File fallback (dev/tests without DATABASE_URL): backtest_runs.json /
backtest_trades.json next to this module.

The fill/charges model is imported from phase20_executor (compute_fill /
compute_charges) so backtests use the SAME execution cost model as live
paper trading — only the storage is separate.
"""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    import fcntl as _fcntl
    _HAVE_FCNTL = True
except ImportError:          # Windows — not a supported backtest-worker platform
    _HAVE_FCNTL = False

from scan_state_store import _connect, db_available

_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNS_FILE = os.path.join(_DIR, "backtest_runs.json")
_TRADES_FILE = os.path.join(_DIR, "backtest_trades.json")
# Advisory lock file — patchable in tests: set backtest_portfolio._LOCK_FILE.
_LOCK_FILE = os.path.join(_DIR, "backtest_runs.lock")

_SCHEMA_READY = False


@contextlib.contextmanager
def _file_store_lock():
    """Cross-process advisory lock for file-store queue admission/lifecycle.

    Uses ``fcntl.flock`` (POSIX exclusive lock) so that two backtest worker
    *processes* finishing at the same instant cannot both read the same QUEUED
    row and both promote it, leaving the second QUEUED run without a worker.
    The DB path uses ``pg_advisory_xact_lock(74230912)`` for the same purpose.

    Falls back silently on non-POSIX platforms (e.g. Windows).
    Not reentrant — do not call while already holding this lock.
    """
    if not _HAVE_FCNTL:
        yield
        return
    # "a" mode: create if absent, never truncates — safe for concurrent opens.
    with open(_LOCK_FILE, "a") as lf:
        _fcntl.flock(lf, _fcntl.LOCK_EX)
        try:
            yield
        finally:
            _fcntl.flock(lf, _fcntl.LOCK_UN)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ── DB connection resilience ──────────────────────────────────────────────────

def _is_connection_error(exc: Exception) -> bool:
    """Return True for transient DB connectivity / auth errors worth retrying.

    Covers:
    - psycopg2 OperationalError / InterfaceError (connection reset, auth
      failure, SSL EOF — all common with Neon serverless cold-starts)
    - Generic string patterns for environments without psycopg2 on the path
    """
    try:
        import psycopg2
        if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
            return True
    except ImportError:
        pass
    msg = str(exc).lower()
    return any(token in msg for token in (
        "connection", "auth", "timeout", "ssl", "eof",
        "broken pipe", "server closed", "reset by peer",
        "could not connect", "terminating connection",
    ))


def _connect_with_retry():
    """Open a DB connection, retrying ONCE on transient connectivity errors.

    A single retry covers:
    - Neon serverless compute node waking from scale-to-zero (~200–800 ms)
    - Transient network blips and SSL/EOF resets
    - Short auth-token refresh windows

    A persistent outage (Neon fully down, wrong credentials) will still raise
    on the second attempt — we never swallow a non-transient failure.
    """
    import time as _time
    try:
        return _connect()
    except Exception as exc:
        if _is_connection_error(exc):
            _time.sleep(1.0)
            return _connect()   # let a persistent failure propagate naturally
        raise


def _emergency_mark_failed(run_id: str, error_msg: str) -> None:
    """Mark a run FAILED. Tries DB (with retry) first; falls back to the file
    store when the DB is also unavailable.

    Used exclusively inside exception handlers where a second DB failure would
    leave the run stuck as RUNNING forever.  Never raises.
    """
    now = _now_iso()
    _guard = {"COMPLETED", "CANCELLED", "STALE", "FAILED"}
    if db_available():
        try:
            conn = _connect_with_retry()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE backtest_runs"
                        " SET status = 'FAILED', error = %s, completed_at = %s"
                        " WHERE run_id = %s"
                        "   AND status NOT IN ('COMPLETED','CANCELLED','STALE','FAILED')",
                        (error_msg[:500], now, run_id),
                    )
                conn.commit()
                return                  # DB write succeeded — done
            finally:
                conn.close()
        except Exception:
            pass                        # DB unavailable even after retry
    # File-store fallback (also the primary path when DATABASE_URL is absent).
    # _file_store_lock() serialises concurrent *process* calls so two workers
    # failing at the same instant cannot race on the read-modify-write cycle
    # and leave one run stuck as RUNNING.
    try:
        with _file_store_lock():
            rows = _load(_RUNS_FILE)
            for r in rows:
                if r["run_id"] == run_id and r.get("status") not in _guard:
                    r["status"] = "FAILED"
                    r["error"] = error_msg[:500]
                    r["completed_at"] = now
            _save(_RUNS_FILE, rows)
    except Exception:
        pass                            # truly best-effort — nothing more we can do


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        # Serialize DDL across concurrent backtest workers — the tranche
        # migration below takes AccessExclusiveLock and two workers running
        # it simultaneously deadlock.
        cur.execute("SELECT pg_advisory_xact_lock(74230911)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_runs (
                run_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                status TEXT NOT NULL DEFAULT 'PENDING',
                config JSONB NOT NULL DEFAULT '{}'::jsonb,
                progress JSONB NOT NULL DEFAULT '{}'::jsonb,
                metrics JSONB,
                missed JSONB,
                validation JSONB,
                error TEXT,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                pending_at TIMESTAMPTZ
            )
            """
        )
        # Add pending_at to existing tables that pre-date the column.
        cur.execute(
            """
            ALTER TABLE backtest_runs
            ADD COLUMN IF NOT EXISTS pending_at TIMESTAMPTZ
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_trades (
                trade_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                scan_id TEXT,
                symbol TEXT NOT NULL,
                strategy_id TEXT,
                strategy_name TEXT,
                side TEXT NOT NULL DEFAULT 'BUY',
                signal_ts TEXT,
                fill_ts TEXT,
                signal_price DOUBLE PRECISION,
                fill_price DOUBLE PRECISION,
                quantity INTEGER,
                stop_loss DOUBLE PRECISION,
                target DOUBLE PRECISION,
                est_charges DOUBLE PRECISION,
                slippage DOUBLE PRECISION,
                confidence DOUBLE PRECISION,
                opportunity_score DOUBLE PRECISION,
                regime TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                exit_ts TEXT,
                exit_price DOUBLE PRECISION,
                exit_rule TEXT,
                realized_pnl DOUBLE PRECISION,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_backtest_trades_run"
            " ON backtest_trades (run_id, created_at)"
        )
        # Scale-in support: tranche 0 = initial entry, 1..N = scale-ins.
        # Existing rows/databases get tranche 0 (identical behaviour).
        cur.execute(
            "ALTER TABLE backtest_trades"
            " ADD COLUMN IF NOT EXISTS tranche INTEGER NOT NULL DEFAULT 0"
        )
        # Create the replacement index FIRST, drop the legacy one after — a
        # failure between the two statements must never leave the table
        # without a uniqueness guarantee on open positions.
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_trades_open_tranche"
            " ON backtest_trades (run_id, symbol, tranche) WHERE status = 'OPEN'"
        )
        cur.execute("DROP INDEX IF EXISTS idx_backtest_trades_open")
    conn.commit()
    _SCHEMA_READY = True


# ── File fallback helpers ────────────────────────────────────────────────────

def _load(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save(path: str, rows: List[Dict[str, Any]]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rows, f, default=str)
    os.replace(tmp, path)


# ── Runs ─────────────────────────────────────────────────────────────────────

# Maximum number of concurrently RUNNING+PENDING backtest workers.
# On Replit (2 vCPU / 4 GB RAM) a single 20-symbol 15m run already saturates
# the interpreter; running three or more in parallel causes OOM and stalls.
MAX_CONCURRENT_BACKTESTS = 2

# Threshold for the server-side watchdog (minutes without a heartbeat).
_STALE_RUNNING_THRESHOLD_MIN = 30   # RUNNING/CANCEL_REQUESTED with no progress
_STALE_PENDING_THRESHOLD_MIN = 30   # PENDING with no worker claim

# Watchdog TTL: a RUNNING run that has not completed within this many minutes
# is assumed dead (OOM-killed, container restart, etc.) and is marked FAILED so
# the queue can proceed.  The default covers the worst-case production run
# (~6 min for 5-sym 15m 30d) with a generous safety margin; it can be overridden
# per call for testing.
WATCHDOG_TTL_MIN: int = 60


def count_active_runs() -> int:
    """Count RUNNING + PENDING + CANCEL_REQUESTED runs."""
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM backtest_runs"
                    " WHERE status IN ('RUNNING','PENDING','CANCEL_REQUESTED')"
                )
                return int(cur.fetchone()[0])
        finally:
            conn.close()
    return sum(1 for r in _load(_RUNS_FILE)
               if r.get("status") in ("RUNNING", "PENDING", "CANCEL_REQUESTED"))


def create_run(config: Dict[str, Any]) -> str:
    """Create a run. Status is QUEUED if MAX_CONCURRENT_BACKTESTS are already active.

    DB path acquires pg_advisory_xact_lock(74230912) before counting and
    inserting, serializing all admission decisions across concurrent processes.
    Without this, two READ COMMITTED transactions can each snapshot the
    active-run count before either commits and both insert as PENDING,
    exceeding MAX_CONCURRENT_BACKTESTS and causing OOM / stalled runs.
    """
    run_id = f"BT-{uuid.uuid4().hex[:10]}"
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                # Serialize admission: only one transaction may count + insert
                # at a time. Released automatically at commit/rollback.
                cur.execute("SELECT pg_advisory_xact_lock(74230912)")
                cur.execute(
                    """
                    WITH active AS (
                        SELECT count(*) AS cnt FROM backtest_runs
                        WHERE status IN ('RUNNING','PENDING','CANCEL_REQUESTED')
                    )
                    INSERT INTO backtest_runs (run_id, status, config, pending_at)
                    SELECT %s,
                        CASE WHEN (SELECT cnt FROM active) >= %s
                             THEN 'QUEUED' ELSE 'PENDING' END,
                        %s::jsonb,
                        CASE WHEN (SELECT cnt FROM active) >= %s
                             THEN NULL ELSE NOW() END
                    RETURNING status
                    """,
                    (run_id, MAX_CONCURRENT_BACKTESTS,
                     json.dumps(config, default=str),
                     MAX_CONCURRENT_BACKTESTS),
                )
            conn.commit()
        finally:
            conn.close()
    else:
        with _file_store_lock():
            initial_status = ("QUEUED" if count_active_runs() >= MAX_CONCURRENT_BACKTESTS
                              else "PENDING")
            now = _now_iso()
            rows = _load(_RUNS_FILE)
            rows.append({"run_id": run_id, "created_at": now,
                         "status": initial_status, "config": config, "progress": {},
                         "metrics": None, "missed": None, "validation": None,
                         "error": None, "started_at": None, "completed_at": None,
                         "pending_at": now if initial_status == "PENDING" else None})
            _save(_RUNS_FILE, rows)
    return run_id


_JSON_FIELDS = {"config", "progress", "metrics", "missed", "validation"}
_TS_FIELDS = {"started_at", "completed_at"}


def update_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            sets, args = [], []
            for k, v in fields.items():
                if k in _JSON_FIELDS:
                    sets.append(f"{k} = %s::jsonb")
                    args.append(json.dumps(v, default=str))
                else:
                    sets.append(f"{k} = %s")
                    args.append(v)
            args.append(run_id)
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE backtest_runs SET {', '.join(sets)} WHERE run_id = %s",
                    args,
                )
            conn.commit()
        finally:
            conn.close()
        return
    with _file_store_lock():
        rows = _load(_RUNS_FILE)
        for r in rows:
            if r["run_id"] == run_id:
                r.update(fields)
        _save(_RUNS_FILE, rows)


def complete_run(run_id: str, **fields: Any) -> bool:
    """Atomically finalize a run as COMPLETED, only if it is still RUNNING.

    Returns True iff the update was applied (rowcount == 1).
    Returns False when the run is no longer RUNNING (e.g. a watchdog marked it
    STALE between the worker's status check and this write) — the caller must
    not proceed, and the watchdog state is preserved.

    All ``fields`` (metrics, progress, config, completed_at, …) are written
    together with the status change in a single conditional UPDATE so there is
    no window where the STALE mark can be overwritten.
    """
    now = datetime.now(timezone.utc)
    fields.setdefault("status", "COMPLETED")
    fields.setdefault("completed_at", now)
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            sets, args = [], []
            for k, v in fields.items():
                if k in _JSON_FIELDS:
                    sets.append(f"{k} = %s::jsonb")
                    args.append(json.dumps(v, default=str))
                else:
                    sets.append(f"{k} = %s")
                    args.append(v)
            args.append(run_id)
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE backtest_runs SET {', '.join(sets)}"
                    " WHERE run_id = %s AND status = 'RUNNING'",
                    args,
                )
                applied = cur.rowcount == 1
            conn.commit()
            return applied
        finally:
            conn.close()
    # File fallback: reload + conditional update in one write.
    with _file_store_lock():
        rows = _load(_RUNS_FILE)
        applied = False
        for r in rows:
            if r["run_id"] == run_id and r.get("status") == "RUNNING":
                r.update(fields)
                applied = True
        if applied:
            _save(_RUNS_FILE, rows)
    return applied


def cancel_checkpoint_run(run_id: str) -> bool:
    """Atomically write CANCELLED, only if the run is still CANCEL_REQUESTED.

    Returns True iff the update was applied (rowcount == 1).
    Returns False when the run has already been marked STALE (or another
    terminal state) between the checkpoint read and this write.
    """
    now = datetime.now(timezone.utc)
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE backtest_runs SET status = 'CANCELLED',"
                    " error = 'Cancelled by operator',"
                    " completed_at = %s"
                    " WHERE run_id = %s AND status = 'CANCEL_REQUESTED'",
                    (now, run_id),
                )
                applied = cur.rowcount == 1
            conn.commit()
            return applied
        finally:
            conn.close()
    with _file_store_lock():
        rows = _load(_RUNS_FILE)
        applied = False
        for r in rows:
            if r["run_id"] == run_id and r.get("status") == "CANCEL_REQUESTED":
                r["status"] = "CANCELLED"
                r["error"] = "Cancelled by operator"
                r["completed_at"] = now.isoformat()
                applied = True
        if applied:
            _save(_RUNS_FILE, rows)
    return applied


def claim_run(run_id: str) -> bool:
    """
    Atomically claim a PENDING run for execution (PENDING → RUNNING).
    Returns False when the run is not PENDING — a duplicate/retried
    backtest_exec must refuse to run so a run can never execute twice.
    """
    now = _now_iso()
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE backtest_runs SET status = 'RUNNING',"
                    " started_at = %s WHERE run_id = %s AND status = 'PENDING'",
                    (now, run_id),
                )
                claimed = cur.rowcount == 1
            conn.commit()
            return claimed
        finally:
            conn.close()
    with _file_store_lock():
        rows = _load(_RUNS_FILE)
        claimed = False
        for r in rows:
            if r["run_id"] == run_id and r.get("status") == "PENDING":
                r["status"] = "RUNNING"
                r["started_at"] = now
                claimed = True
        if claimed:
            _save(_RUNS_FILE, rows)
    return claimed


_RUN_COLS = ["run_id", "created_at", "status", "config", "progress",
             "metrics", "missed", "validation", "error",
             "started_at", "completed_at", "pending_at"]


def _run_row_to_dict(r) -> Dict[str, Any]:
    d = dict(zip(_RUN_COLS, r))
    for k in ("created_at", "started_at", "completed_at", "pending_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    for k in _JSON_FIELDS:
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    return d


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_RUN_COLS)} FROM backtest_runs"
                    " WHERE run_id = %s", (run_id,))
                r = cur.fetchone()
                return _run_row_to_dict(r) if r else None
        finally:
            conn.close()
    for r in _load(_RUNS_FILE):
        if r["run_id"] == run_id:
            return r
    return None


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_RUN_COLS)} FROM backtest_runs"
                    " ORDER BY created_at DESC LIMIT %s", (limit,))
                return [_run_row_to_dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    return list(reversed(_load(_RUNS_FILE)))[:limit]


# ── Run lifecycle controls (cancel / stale / retry) ───────────────────────────

TERMINAL_STATUSES = {"COMPLETED", "CANCELLED", "STALE", "FAILED"}


def promote_next_queued() -> Optional[str]:
    """Promote the oldest QUEUED run to PENDING when a concurrency slot is free.
    Returns the promoted run_id, or None if nothing was promoted.

    DB path acquires pg_advisory_xact_lock(74230912) — the same lock used by
    create_run() — before counting and promoting, so concurrent workers and
    new-run requests cannot both see a free slot and both act on it.
    """
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                # Same admission lock as create_run() — serialize all slot
                # decisions across processes. Released at commit/rollback.
                cur.execute("SELECT pg_advisory_xact_lock(74230912)")
                cur.execute(
                    """
                    WITH active AS (
                        SELECT count(*) AS cnt FROM backtest_runs
                        WHERE status IN ('RUNNING','PENDING','CANCEL_REQUESTED')
                    )
                    UPDATE backtest_runs
                    SET status = 'PENDING', pending_at = NOW()
                    WHERE run_id = (
                        SELECT run_id FROM backtest_runs WHERE status = 'QUEUED'
                        ORDER BY created_at ASC LIMIT 1
                    )
                    AND status = 'QUEUED'
                    AND (SELECT cnt FROM active) < %s
                    RETURNING run_id
                    """,
                    (MAX_CONCURRENT_BACKTESTS,),
                )
                row = cur.fetchone()
                if row:
                    conn.commit()
                    return row[0]
            conn.rollback()
            return None
        finally:
            conn.close()
    # File fallback — fast path for dev/tests.
    # _file_store_lock() serialises concurrent *process* calls so two workers
    # finishing at the same instant cannot both read the same QUEUED row and
    # promote it twice (leaving the second QUEUED run without a worker).
    # The DB path uses pg_advisory_xact_lock for the same guarantee.
    with _file_store_lock():
        if count_active_runs() >= MAX_CONCURRENT_BACKTESTS:
            return None
        rows = _load(_RUNS_FILE)
        for r in rows:
            if r.get("status") == "QUEUED":
                r["status"] = "PENDING"
                r["pending_at"] = _now_iso()
                _save(_RUNS_FILE, rows)
                return r["run_id"]
    return None


def revert_pending_to_queued(run_id: str) -> bool:
    """Atomically revert a PENDING run back to QUEUED on spawn failure.

    Returns True iff the run was actually reverted (it was still PENDING).
    Returns False (safely) if the run had already been claimed (RUNNING or
    any other status) — prevents overwriting an executing worker.

    DB path uses a single conditional UPDATE with ``WHERE status = 'PENDING'``
    so there is no read-modify-write gap where a concurrent claim_run() could
    transition PENDING → RUNNING between our check and our write.

    File path reloads and re-checks before saving, which is safe because the
    file fallback is single-process.
    """
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE backtest_runs SET status = 'QUEUED', pending_at = NULL"
                    " WHERE run_id = %s AND status = 'PENDING'",
                    (run_id,),
                )
                reverted = cur.rowcount == 1
            conn.commit()
            return reverted
        finally:
            conn.close()
    # File fallback: reload + conditional update in one write.
    with _file_store_lock():
        rows = _load(_RUNS_FILE)
        reverted = False
        for r in rows:
            if r["run_id"] == run_id and r.get("status") == "PENDING":
                r["status"] = "QUEUED"
                r["pending_at"] = None
                reverted = True
        if reverted:
            _save(_RUNS_FILE, rows)
    return reverted


def _sweep_stale_runs_file() -> Dict[str, Any]:
    """File-fallback implementation of sweep_stale_runs() for dev/test environments.

    The entire body runs inside _file_store_lock() so that a concurrent
    promote_next_queued() call (from another process finishing a run at the
    same instant) cannot race on the same QUEUED rows.
    """
    now = datetime.now(timezone.utc)
    marked_stale: list = []
    promoted: list = []

    with _file_store_lock():
        rows = _load(_RUNS_FILE)

        for r in rows:
            status = r.get("status")
            if status in ("RUNNING", "CANCEL_REQUESTED"):
                progress = r.get("progress") or {}
                last_ts_str = (progress.get("progress_updated_at")
                               or r.get("started_at")
                               or r.get("created_at"))
                try:
                    last_dt = datetime.fromisoformat(
                        str(last_ts_str).replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    minutes = (now - last_dt).total_seconds() / 60.0
                except Exception:
                    continue
                if minutes >= _STALE_RUNNING_THRESHOLD_MIN:
                    r["status"] = "STALE"
                    r["error"] = (f"Run stalled — no progress for {round(minutes, 1)} minutes. "
                                  "Worker likely stopped. Retry required.")
                    marked_stale.append(r["run_id"])

            elif status == "PENDING":
                # Use pending_at (set at admission/promotion) rather than
                # created_at so a run that waited a long time in QUEUED is not
                # immediately classified as stale the moment it is promoted.
                pending_str = r.get("pending_at") or r.get("created_at")
                if not pending_str:
                    continue
                try:
                    pending_dt = datetime.fromisoformat(
                        str(pending_str).replace("Z", "+00:00"))
                    if pending_dt.tzinfo is None:
                        pending_dt = pending_dt.replace(tzinfo=timezone.utc)
                    minutes = (now - pending_dt).total_seconds() / 60.0
                except Exception:
                    continue
                if minutes >= _STALE_PENDING_THRESHOLD_MIN:
                    r["status"] = "STALE"
                    r["error"] = (f"Run stalled — PENDING with no worker for {round(minutes, 1)} minutes. "
                                  "Worker likely stopped. Retry required.")
                    marked_stale.append(r["run_id"])

        _save(_RUNS_FILE, rows)

        # Promote QUEUED runs into vacated slots.
        # CANCEL_REQUESTED counts as occupied: the worker is still executing
        # until its next checkpoint, so we must not over-subscribe the limit.
        active_count = sum(1 for r in rows
                           if r.get("status") in ("RUNNING", "PENDING",
                                                  "CANCEL_REQUESTED"))
        slots = max(0, MAX_CONCURRENT_BACKTESTS - active_count)
        queued = [r for r in rows if r.get("status") == "QUEUED"][:slots]
        _promotion_ts = _now_iso()
        for r in queued:
            r["status"] = "PENDING"
            r["pending_at"] = _promotion_ts  # stale clock from promotion, not creation
            promoted.append(r["run_id"])
        if queued:
            _save(_RUNS_FILE, rows)

    return {
        "swept": len(marked_stale),
        "marked_stale": marked_stale,
        "promoted": len(promoted),
        "promoted_runs": promoted,
    }
def sweep_stale_runs() -> Dict[str, Any]:
    """Server-side watchdog — auto-marks orphaned/stale runs and promotes queued ones.

    Phase 1 — absolute TTL watchdog: RUNNING runs older than WATCHDOG_TTL_MIN
    are marked FAILED (not STALE) so the queue slot is freed immediately and
    the next QUEUED run can start.  This fires even when no run is finishing
    (e.g. all slots are occupied by ghost processes that died silently).

    Phase 2 — heartbeat stale sweep: RUNNING / CANCEL_REQUESTED runs with no
    progress heartbeat for _STALE_RUNNING_THRESHOLD_MIN minutes are marked STALE.

    Phase 3 — PENDING orphan sweep: PENDING with no worker claim for
    _STALE_PENDING_THRESHOLD_MIN minutes are marked STALE.

    Phase 4 — queue promotion: QUEUED runs are promoted to PENDING to fill
    newly vacated concurrency slots.

    Designed to be called on every ``backtest_runs`` list request (sweep-on-read)
    so it runs automatically every 5 s while the Investigation Center is open.
    """
    # Phase 1: absolute TTL watchdog — must run first so freed slots are
    # visible to the heartbeat sweep and queue promotion below.
    try:
        sweep_watchdog_timeouts()
    except Exception:
        pass   # never let a watchdog failure abort the rest of the sweep

    if not db_available():
        return _sweep_stale_runs_file()

    now = datetime.now(timezone.utc)
    marked_stale: list = []

    conn = _connect_with_retry()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            # ── 1. Stale RUNNING / CANCEL_REQUESTED runs ───────────────────
            cur.execute(
                f"SELECT {', '.join(_RUN_COLS)} FROM backtest_runs"
                " WHERE status IN ('RUNNING','CANCEL_REQUESTED')"
            )
            active_rows = [_run_row_to_dict(r) for r in cur.fetchall()]

        for r in active_rows:
            progress = r.get("progress") or {}
            last_ts_str = (progress.get("progress_updated_at")
                           or r.get("started_at")
                           or r.get("created_at"))
            try:
                last_dt = datetime.fromisoformat(
                    str(last_ts_str).replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                minutes = (now - last_dt).total_seconds() / 60.0
            except Exception:
                continue
            if minutes >= _STALE_RUNNING_THRESHOLD_MIN:
                reason = (f"Run stalled — no progress for {round(minutes, 1)} minutes. "
                          "Worker likely stopped. Retry required.")
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE backtest_runs SET status = 'STALE', error = %s"
                        " WHERE run_id = %s"
                        "   AND status IN ('RUNNING','CANCEL_REQUESTED')",
                        (reason, r["run_id"]),
                    )
                marked_stale.append(r["run_id"])

        # ── 2. Orphaned PENDING runs (worker died before claim) ────────────
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(_RUN_COLS)} FROM backtest_runs WHERE status = 'PENDING'"
            )
            pending_rows = [_run_row_to_dict(r) for r in cur.fetchall()]

        for r in pending_rows:
            # Use pending_at (set at admission/promotion) rather than
            # created_at so a long-queued run is not immediately stale on
            # promotion. Fall back to created_at for rows that pre-date the
            # pending_at column.
            pending_str = r.get("pending_at") or r.get("created_at")
            if not pending_str:
                continue
            try:
                pending_dt = datetime.fromisoformat(
                    str(pending_str).replace("Z", "+00:00"))
                if pending_dt.tzinfo is None:
                    pending_dt = pending_dt.replace(tzinfo=timezone.utc)
                minutes = (now - pending_dt).total_seconds() / 60.0
            except Exception:
                continue
            if minutes >= _STALE_PENDING_THRESHOLD_MIN:
                reason = (f"Run stalled — PENDING with no worker for {round(minutes, 1)} minutes. "
                          "Worker likely stopped. Retry required.")
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE backtest_runs SET status = 'STALE', error = %s"
                        " WHERE run_id = %s AND status = 'PENDING'",
                        (reason, r["run_id"]),
                    )
                marked_stale.append(r["run_id"])

        conn.commit()
    finally:
        conn.close()

    # ── 3. Promote QUEUED runs under the shared admission lock ─────────────
    # Delegate to promote_next_queued() which acquires
    # pg_advisory_xact_lock(74230912), so sweep promotion cannot race with a
    # concurrent create_run() or another sweep call that also sees free slots.
    # Without this, a sweep and a concurrent create can each count N-1 active
    # runs and both act on the result, exceeding MAX_CONCURRENT_BACKTESTS.
    promoted: list = []
    for _ in range(MAX_CONCURRENT_BACKTESTS):
        next_rid = promote_next_queued()
        if next_rid is None:
            break
        promoted.append(next_rid)

    return {
        "swept": len(marked_stale),
        "marked_stale": marked_stale,
        "promoted": len(promoted),
        "promoted_runs": promoted,
    }


def sweep_watchdog_timeouts(ttl_min: Optional[int] = None) -> Dict[str, Any]:
    """Watchdog sweep — marks timed-out runs FAILED so the queue is never
    permanently blocked by a dead worker process.

    A run can stay RUNNING indefinitely when its worker is killed silently
    (OOM, container restart, SIGKILL) without reaching an exception handler.
    The heartbeat sweep in sweep_stale_runs() catches no-progress runs at 30
    minutes but only marks them STALE — NOT FAILED — so queue slots are not
    immediately freed.  This function enforces an absolute wall-clock TTL
    anchored to ``started_at`` and writes FAILED (the terminal state
    _spawn_next_queued treats as a vacancy signal).

    Critically, this function targets **both** ``RUNNING`` and ``STALE`` rows
    that have a ``started_at`` older than the TTL.  In the normal schedule
    a ghost worker's row is first caught by the 30-minute heartbeat sweep
    (RUNNING → STALE); this function then converts it to FAILED at the TTL
    boundary.  Without targeting STALE as well, the watchdog would never see
    the row because the heartbeat sweep fires first.

    CANCEL_REQUESTED rows are excluded: the operator's cancellation is in
    flight and the existing stale sweep manages that lifecycle.

    Args:
        ttl_min: Override the default WATCHDOG_TTL_MIN.  Values ≤ 0 are
                 ignored and the default is used.  Intended for testing only.

    Returns a dict with:
        ``failed``      — number of runs marked FAILED
        ``failed_runs`` — list of affected run_ids
    """
    effective_ttl = int(ttl_min) if (ttl_min is not None and int(ttl_min) > 0) else WATCHDOG_TTL_MIN
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=effective_ttl)
    failed_runs: List[str] = []

    def _watchdog_error(minutes: float) -> str:
        return (
            f"Watchdog timeout: run exceeded {effective_ttl} min TTL "
            f"(ran for ~{round(minutes, 1)} min). "
            "Worker process likely OOM-killed or container restarted. "
            "Safe to retry."
        )

    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            # Target RUNNING and STALE rows with a started_at older than the
            # cutoff.  STALE is included because the heartbeat sweep converts
            # ghost RUNNING rows to STALE at 30 min — by 60 min they are STALE
            # and would be missed if we only queried status = 'RUNNING'.
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_RUN_COLS)} FROM backtest_runs"
                    " WHERE status IN ('RUNNING', 'STALE')"
                    "   AND started_at IS NOT NULL"
                    "   AND started_at < %s",
                    (cutoff,),
                )
                candidates = [_run_row_to_dict(r) for r in cur.fetchall()]

            for r in candidates:
                try:
                    started = datetime.fromisoformat(
                        str(r["started_at"]).replace("Z", "+00:00"))
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    minutes = (datetime.now(timezone.utc) - started).total_seconds() / 60.0
                except Exception:
                    minutes = float(effective_ttl)
                reason = _watchdog_error(minutes)
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE backtest_runs"
                        " SET status = 'FAILED', error = %s, completed_at = NOW()"
                        " WHERE run_id = %s"
                        "   AND status IN ('RUNNING', 'STALE')",
                        (reason[:500], r["run_id"]),
                    )
                    if cur.rowcount == 1:
                        failed_runs.append(r["run_id"])

            conn.commit()
        finally:
            conn.close()
    else:
        # File-store fallback (dev / tests without DATABASE_URL).
        # _file_store_lock() serialises this sweep with any concurrent
        # promote_next_queued / _emergency_mark_failed call so a watchdog
        # save cannot overwrite a promoted PENDING row with the stale QUEUED
        # snapshot it read before the promotion was written.
        now = datetime.now(timezone.utc)
        with _file_store_lock():
            rows = _load(_RUNS_FILE)
            changed = False
            for r in rows:
                if r.get("status") not in ("RUNNING", "STALE"):
                    continue
                started_str = r.get("started_at")
                if not started_str:
                    continue
                try:
                    started = datetime.fromisoformat(
                        str(started_str).replace("Z", "+00:00"))
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    minutes = (now - started).total_seconds() / 60.0
                except Exception:
                    continue
                if minutes >= effective_ttl:
                    r["status"] = "FAILED"
                    r["error"] = _watchdog_error(minutes)[:500]
                    r["completed_at"] = _now_iso()
                    failed_runs.append(r["run_id"])
                    changed = True
            if changed:
                _save(_RUNS_FILE, rows)

    return {"failed": len(failed_runs), "failed_runs": failed_runs}


def find_unclaimed_pending(older_than_min: float = 2.0) -> List[str]:
    """Return run_ids that have been PENDING for > older_than_min minutes.

    Used by the queue scheduler (bt_queue_tick) to recover from spawn failures:
    a run PENDING for longer than a normal worker startup time (~60 s) has no
    live worker and needs a new subprocess spawned.

    Safe to call redundantly: claim_run() is atomic (PENDING → RUNNING via
    conditional UPDATE), so a redundant worker exits immediately if the original
    worker already claimed the run.

    Uses created_at as a proxy for pending_since.  For runs promoted from
    QUEUED this is conservative (created_at pre-dates the promotion), but the
    redundant-spawn safety guarantee means false positives are harmless.
    """
    if not db_available():
        return []
    threshold = datetime.now(timezone.utc) - timedelta(minutes=older_than_min)
    try:
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id FROM backtest_runs"
                    " WHERE status = 'PENDING' AND created_at < %s",
                    (threshold,),
                )
                return [str(r[0]) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        return []


def get_run_status(run_id: str) -> Optional[str]:
    """Fast status-only check — avoids deserialising the full run row.

    Returns None on any DB error so callers inside the replay loop
    (cancellation checkpoint) continue gracefully through transient outages
    instead of terminating the run with a bare connection error.
    """
    if db_available():
        try:
            conn = _connect_with_retry()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status FROM backtest_runs WHERE run_id = %s",
                        (run_id,))
                    r = cur.fetchone()
                    return r[0] if r else None
            finally:
                conn.close()
        except Exception:
            # DB unavailable after retry — return None so the cancellation
            # checkpoint skips gracefully rather than crashing the worker.
            return None
    for r in _load(_RUNS_FILE):
        if r["run_id"] == run_id:
            return r.get("status")
    return None


def cancel_run(run_id: str) -> Dict[str, Any]:
    """Cancel a QUEUED, PENDING, or RUNNING run.
    QUEUED   → CANCELLED immediately (was waiting; never had a worker).
    PENDING  → CANCELLED immediately.
    RUNNING  → CANCEL_REQUESTED (worker stops at next tick checkpoint).
    Terminal statuses (COMPLETED/CANCELLED/STALE/FAILED) → error.
    Partial events and trades are always preserved."""
    run = get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Run {run_id} not found"}
    status = run.get("status")
    if status in TERMINAL_STATUSES:
        return {"ok": False,
                "error": f"Run {run_id} is already {status}; cannot cancel a terminal run"}
    if status == "CANCEL_REQUESTED":
        return {"ok": True, "run_id": run_id, "status": "CANCEL_REQUESTED",
                "message": "Cancel already requested — worker will stop at next checkpoint"}
    now = _now_iso()
    if status in ("QUEUED", "PENDING"):
        update_run(run_id, status="CANCELLED", error="Cancelled by operator",
                   completed_at=now)
        return {"ok": True, "run_id": run_id, "status": "CANCELLED",
                "message": f"Run was {status}; cancelled immediately. Partial data preserved."}
    # RUNNING → CANCEL_REQUESTED
    progress = dict(run.get("progress") or {})
    progress["cancel_requested_at"] = now
    update_run(run_id, status="CANCEL_REQUESTED", progress=progress)
    return {"ok": True, "run_id": run_id, "status": "CANCEL_REQUESTED",
            "message": ("Cancel requested. Worker stops at next checkpoint (≤5 ticks). "
                        "Partial events and trades preserved.")}


def mark_stale_run(run_id: str) -> Dict[str, Any]:
    """Mark a RUNNING or CANCEL_REQUESTED run STALE.
    Use when the worker appears dead (no progress for 30+ minutes).
    Preserves all partial events and trades for audit."""
    run = get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Run {run_id} not found"}
    status = run.get("status")
    if status not in ("RUNNING", "CANCEL_REQUESTED"):
        return {"ok": False,
                "error": (f"Run {run_id} is {status}; mark-stale only applies "
                          "to RUNNING or CANCEL_REQUESTED runs")}
    progress = run.get("progress") or {}
    last_ts_str = (progress.get("progress_updated_at")
                   or run.get("started_at")
                   or run.get("created_at"))
    minutes: Optional[float] = None
    if last_ts_str:
        try:
            last_dt = datetime.fromisoformat(str(last_ts_str).replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            minutes = round(
                (datetime.now(timezone.utc) - last_dt).total_seconds() / 60.0, 1)
        except Exception:
            pass
    reason = (f"No progress for {minutes} minutes. Worker likely stopped."
              if minutes is not None else "No recent progress. Worker likely stopped.")
    update_run(run_id, status="STALE", error=reason)
    return {"ok": True, "run_id": run_id, "status": "STALE",
            "minutes_stale": minutes, "message": reason}


def retry_run(run_id: str) -> Dict[str, Any]:
    """Create a new PENDING run with the same config as `run_id`.
    The original run is preserved unchanged for audit.
    Does NOT resume — always starts fresh from tick 0."""
    run = get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Run {run_id} not found"}
    config = dict(run.get("config") or {})
    # Strip replay-time state that must not carry over to a fresh run
    config.pop("cash_by_tick", None)
    config.pop("learning_fingerprint", None)
    new_run_id = create_run(config)
    # Report the actual admission status (PENDING or QUEUED) so callers
    # can gate worker spawning on truly-PENDING runs only.
    new_status = get_run_status(new_run_id) or "PENDING"
    return {"ok": True, "original_run_id": run_id, "new_run_id": new_run_id,
            "status": new_status,
            "message": (f"New run {new_run_id} created from config of {run_id}. "
                        f"Original run preserved for audit.")}


# ── Trades (backtest execution ledger) ───────────────────────────────────────

_TRADE_COLS = ["trade_id", "run_id", "scan_id", "symbol", "strategy_id",
               "strategy_name", "side", "signal_ts", "fill_ts", "signal_price",
               "fill_price", "quantity", "stop_loss", "target", "est_charges",
               "slippage", "confidence", "opportunity_score", "regime",
               "status", "exit_ts", "exit_price", "exit_rule", "realized_pnl",
               "tranche"]


def open_trade(row: Dict[str, Any]) -> Optional[str]:
    """
    Insert an OPEN backtest trade. Returns trade_id, or None when an OPEN
    trade already exists for (run_id, symbol, tranche) — the unique partial
    index makes duplicate entries impossible at the database level.

    Default tranche is 0 (the initial entry), which preserves the historical
    one-open-position-per-symbol rule exactly: a second tranche-0 insert for
    the same symbol is always rejected. Scale-ins (tranche 1..N) are only ever
    attempted by the runner when scale_in_enabled is set for the run.
    """
    trade_id = row.get("trade_id") or f"BTT-{uuid.uuid4().hex[:10]}"
    row = {**row, "trade_id": trade_id, "status": "OPEN",
           "tranche": int(row.get("tranche") or 0)}
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            cols = [c for c in _TRADE_COLS if c in row]
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO backtest_trades ({', '.join(cols)})"
                        f" VALUES ({', '.join(['%s'] * len(cols))})",
                        [row[c] for c in cols],
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                return None    # duplicate OPEN for symbol → blocked
        finally:
            conn.close()
        return trade_id
    rows = _load(_TRADES_FILE)
    if any(t["run_id"] == row["run_id"] and t["symbol"] == row["symbol"]
           and int(t.get("tranche") or 0) == row["tranche"]
           and t["status"] == "OPEN" for t in rows):
        return None
    rows.append(row)
    _save(_TRADES_FILE, rows)
    return trade_id


def close_trade(trade_id: str, exit_ts: str, exit_price: float,
                exit_rule: str) -> Optional[Dict[str, Any]]:
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE backtest_trades SET status='CLOSED', exit_ts=%s,"
                    " exit_price=%s, exit_rule=%s,"
                    " realized_pnl=ROUND(((%s - fill_price) * quantity)::numeric, 2)"
                    " WHERE trade_id=%s AND status='OPEN'"
                    f" RETURNING {', '.join(_TRADE_COLS)}",
                    (exit_ts, exit_price, exit_rule, exit_price, trade_id),
                )
                r = cur.fetchone()
            conn.commit()
            return dict(zip(_TRADE_COLS, r)) if r else None
        finally:
            conn.close()
    rows = _load(_TRADES_FILE)
    out = None
    for t in rows:
        if t["trade_id"] == trade_id and t["status"] == "OPEN":
            t.update(status="CLOSED", exit_ts=exit_ts, exit_price=exit_price,
                     exit_rule=exit_rule,
                     realized_pnl=round((exit_price - t["fill_price"])
                                        * t["quantity"], 2))
            out = t
    _save(_TRADES_FILE, rows)
    return out


def trades(run_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    if db_available():
        conn = _connect_with_retry()
        try:
            _ensure_schema(conn)
            q = (f"SELECT {', '.join(_TRADE_COLS)} FROM backtest_trades"
                 " WHERE run_id = %s")
            args: List[Any] = [run_id]
            if status:
                q += " AND status = %s"
                args.append(status)
            q += " ORDER BY created_at ASC"
            with conn.cursor() as cur:
                cur.execute(q, args)
                return [dict(zip(_TRADE_COLS, r)) for r in cur.fetchall()]
        finally:
            conn.close()
    rows = [t for t in _load(_TRADES_FILE) if t["run_id"] == run_id]
    if status:
        rows = [t for t in rows if t["status"] == status]
    return rows


def open_trades(run_id: str) -> List[Dict[str, Any]]:
    return trades(run_id, status="OPEN")


# ── Portfolio snapshot & metrics ─────────────────────────────────────────────

def portfolio_snapshot(run_id: str, marks: Optional[Dict[str, float]] = None
                       ) -> Dict[str, Any]:
    """
    Full backtest portfolio state derived purely from the run's trade ledger.
    `marks` maps symbol → latest known close for unrealized P&L.
    """
    run = get_run(run_id) or {}
    cfg = run.get("config") or {}
    starting_capital = float(cfg.get("capital") or 100000.0)
    marks = marks or {}

    all_trades = trades(run_id)
    cash = starting_capital
    realized = 0.0
    wins = losses = 0
    equity_curve: List[Dict[str, Any]] = [
        {"ts": run.get("started_at") or run.get("created_at"),
         "equity": round(starting_capital, 2)}]

    # chronological cash walk
    events: List[Dict[str, Any]] = []
    for t in all_trades:
        cost = float(t["fill_price"]) * int(t["quantity"]) + float(t.get("est_charges") or 0)
        events.append({"ts": t.get("fill_ts") or t.get("signal_ts"),
                       "cash_delta": -cost, "pnl": 0.0})
        if t["status"] == "CLOSED":
            proceeds = float(t["exit_price"]) * int(t["quantity"])
            pnl = float(t.get("realized_pnl") or 0.0)
            events.append({"ts": t.get("exit_ts"), "cash_delta": proceeds,
                           "pnl": pnl})
            realized += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
    events.sort(key=lambda e: str(e["ts"]))
    running_realized = 0.0
    for e in events:
        cash += e["cash_delta"]
        running_realized += e["pnl"]
        equity_curve.append({"ts": e["ts"],
                             "equity": round(starting_capital + running_realized, 2)})

    open_pos = []
    unrealized = 0.0
    open_value = 0.0
    for t in all_trades:
        if t["status"] != "OPEN":
            continue
        mark = float(marks.get(str(t["symbol"]).upper())
                     or t.get("fill_price") or 0.0)
        u = (mark - float(t["fill_price"])) * int(t["quantity"])
        unrealized += u
        open_value += mark * int(t["quantity"])
        open_pos.append({**{k: t.get(k) for k in
                            ("trade_id", "symbol", "strategy_name", "quantity",
                             "fill_price", "stop_loss", "target", "fill_ts")},
                         "mark": mark, "unrealized_pnl": round(u, 2)})

    portfolio_value = cash + open_value
    peak = starting_capital
    max_dd = 0.0
    for p in equity_curve:
        peak = max(peak, p["equity"])
        if peak > 0:
            max_dd = max(max_dd, (peak - p["equity"]) / peak * 100.0)

    closed_n = wins + losses
    return {
        "run_id": run_id,
        "starting_capital": round(starting_capital, 2),
        "cash": round(cash, 2),
        "open_positions": open_pos,
        "open_positions_count": len(open_pos),
        "closed_positions_count": closed_n,
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "portfolio_value": round(portfolio_value, 2),
        "net_return_pct": round((portfolio_value - starting_capital)
                                / starting_capital * 100.0, 2)
        if starting_capital else 0.0,
        "win_rate": round(wins / closed_n * 100.0, 1) if closed_n else 0.0,
        "wins": wins, "losses": losses,
        "max_drawdown_pct": round(max_dd, 2),
        "equity_curve": equity_curve,
        "total_trades": len(all_trades),
        "label": "BACKTEST — SIMULATED, ISOLATED FROM LIVE",
    }
