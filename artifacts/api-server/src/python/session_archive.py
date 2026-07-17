"""
session_archive.py — Priority 2 (#21): Archived session review and restore.

Archives a complete snapshot of the paper-trading session every time the
portfolio is reset, lets the user inspect archives read-only, and supports
guarded restoration of an archived session.

Safety guarantees (enforced here, never weakened):
- Restore only touches simulated paper state (cash / positions / pnl_history
  in paper_portfolio). It NEVER modifies Zerodha credentials, API tokens,
  live-order controls, the model registry, historical evidence
  (phase22_evidence), or immutable audit history (phase20_notifications,
  paper_trades archived rows).
- Restoration requires the exact confirmation phrase AND a second
  confirmation step (a one-time restore token issued by step 1).
- Before restoring, the CURRENT active session is archived. If that backup
  archive cannot be created and verified, restoration is BLOCKED.
- If applying the restored state fails, the previous state is rolled back.
- Every restore attempt (allowed or blocked) records an audit event.

Storage: Postgres table `session_archives` when DATABASE_URL is set
(authoritative), with a local JSON file fallback for local dev only.
Archives are append-only: rows are never updated destructively except for
stamping restored_at.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import portfolio_store

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_FILE = os.path.join(_DIR, "session_archives.json")

RESTORE_CONFIRMATION_PHRASE = "RESTORE PAPER SESSION"
RESTORE_TOKEN_TTL_MINUTES = 5

_SCHEMA_READY = False


# ── Schema ───────────────────────────────────────────────────────────────────

def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS session_archives (
                id            TEXT PRIMARY KEY,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reset_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reset_reason  TEXT NOT NULL DEFAULT '',
                snapshot      JSONB NOT NULL,
                metrics       JSONB NOT NULL DEFAULT '{}',
                restored_at   TIMESTAMPTZ,
                restore_token TEXT,
                token_expires TIMESTAMPTZ
            )
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def _connect():
    return portfolio_store._connect()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Any) -> Any:
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc).isoformat()
    return dt


# ── Metric capture ───────────────────────────────────────────────────────────

def _session_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    """Compute review metrics from a raw portfolio state dict."""
    cash = float(state.get("cash", 0.0))
    positions = state.get("positions", {}) or {}
    invested = sum(p["quantity"] * p["avg_price"] for p in positions.values())
    portfolio_value = cash + invested

    realized = 0.0
    try:
        import analytics_engine  # optional; realized P&L from trade history
        perf = analytics_engine.performance_summary()
        realized = float(perf.get("realized_pnl", 0.0) or 0.0)
    except Exception:
        # Fall back: realized = value - capital - unrealized(0 at avg price)
        realized = round(portfolio_value - portfolio_store.INITIAL_CAPITAL, 2)

    unrealized = 0.0  # at archive time we only have avg price (proxy = 0)

    pending_orders = 0
    try:
        import phase20_store
        pending = phase20_store.list_pending_entries()  # may not exist
        pending_orders = len(pending or [])
    except Exception:
        pending_orders = 0

    config_hash = ""
    try:
        import experiment_manager
        import config as _cfg
        cfg = {k: getattr(_cfg, k) for k in dir(_cfg)
               if k.isupper() and isinstance(getattr(_cfg, k), (int, float, str, list, tuple))}
        config_hash = experiment_manager.get_config_hash(cfg)
    except Exception:
        config_hash = ""

    latest_scan_id = ""
    try:
        import scan_state_store
        meta = scan_state_store.load_latest_meta() or {}
        latest_scan_id = meta.get("scan_id") or ""
    except Exception:
        latest_scan_id = ""

    return {
        "portfolio_value": round(portfolio_value, 2),
        "cash": round(cash, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "open_positions": len(positions),
        "pending_orders": pending_orders,
        "config_hash": config_hash,
        "latest_scan_id": latest_scan_id,
    }


# ── Archive creation ─────────────────────────────────────────────────────────

def archive_current_session(reason: str) -> Dict[str, Any]:
    """
    Snapshot the CURRENT paper session into session_archives.
    Returns the archive record. Raises on failure (callers treat a failed
    archive as a hard block for destructive follow-up actions).
    """
    state = portfolio_store.load_state()
    if not isinstance(state, dict) or "cash" not in state:
        raise RuntimeError("Cannot archive: current portfolio state unreadable")

    record = {
        "id": f"arch_{_now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "created_at": _iso(_now()),
        "reset_at": _iso(_now()),
        "reset_reason": (reason or "")[:300],
        "snapshot": {
            "cash": state.get("cash"),
            "positions": state.get("positions", {}),
            "pnl_history": state.get("pnl_history", []),
        },
        "metrics": _session_metrics(state),
        "restored_at": None,
    }

    if portfolio_store.db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO session_archives (id, reset_reason, snapshot, metrics)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (record["id"], record["reset_reason"],
                     json.dumps(record["snapshot"]), json.dumps(record["metrics"])),
                )
            conn.commit()
        finally:
            conn.close()
    else:
        items = _read_fallback()
        items.append(record)
        _write_fallback(items)

    # Verify the archive is readable back (block-on-failure guarantee)
    check = get_archive(record["id"])
    if not check or "snapshot" not in check:
        raise RuntimeError("Archive verification failed after write")
    return record


# ── Read-only review ─────────────────────────────────────────────────────────

def list_archives(limit: int = 50) -> List[Dict[str, Any]]:
    """List archived sessions (metadata + metrics), newest first. Read-only."""
    if portfolio_store.db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, created_at, reset_at, reset_reason, metrics, restored_at
                    FROM session_archives ORDER BY created_at DESC LIMIT %s
                    """, (limit,))
                rows = cur.fetchall()
            return [{
                "id": r[0], "created_at": _iso(r[1]), "reset_at": _iso(r[2]),
                "reset_reason": r[3],
                "metrics": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                "restored_at": _iso(r[5]),
            } for r in rows]
        finally:
            conn.close()
    items = _read_fallback()
    out = [{k: v for k, v in it.items() if k != "snapshot"} for it in items]
    return list(reversed(out))[:limit]


def get_archive(archive_id: str) -> Optional[Dict[str, Any]]:
    """Full read-only inspection of one archive, including the snapshot."""
    if portfolio_store.db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, created_at, reset_at, reset_reason, snapshot, metrics, restored_at
                    FROM session_archives WHERE id = %s
                    """, (archive_id,))
                r = cur.fetchone()
            if not r:
                return None
            return {
                "id": r[0], "created_at": _iso(r[1]), "reset_at": _iso(r[2]),
                "reset_reason": r[3],
                "snapshot": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                "metrics": r[5] if isinstance(r[5], dict) else json.loads(r[5] or "{}"),
                "restored_at": _iso(r[6]),
            }
        finally:
            conn.close()
    for it in _read_fallback():
        if it.get("id") == archive_id:
            return it
    return None


# ── Guarded restore (two-step) ───────────────────────────────────────────────

def _audit(kind: str, title: str, body: str, severity: str = "WARNING",
           context: Optional[Dict[str, Any]] = None) -> None:
    try:
        import phase20_store
        phase20_store.add_notification(kind, title, body, severity=severity,
                                       context=context or {})
    except Exception:
        logger.warning("audit event could not be recorded: %s / %s", kind, title)


def _validate_snapshot(snapshot: Dict[str, Any]) -> Optional[str]:
    """Return a rejection reason, or None if the snapshot is restorable."""
    if not isinstance(snapshot, dict):
        return "snapshot is not an object"
    cash = snapshot.get("cash")
    if not isinstance(cash, (int, float)) or cash < 0:
        return "snapshot cash is missing or negative"
    positions = snapshot.get("positions")
    if not isinstance(positions, dict):
        return "snapshot positions missing or malformed"
    for sym, pos in positions.items():
        if (not isinstance(pos, dict)
                or not isinstance(pos.get("quantity"), int)
                or pos.get("quantity", 0) <= 0
                or not isinstance(pos.get("avg_price"), (int, float))
                or pos.get("avg_price", 0) <= 0):
            return f"snapshot position for {sym} is malformed"
    if not isinstance(snapshot.get("pnl_history", []), list):
        return "snapshot pnl_history malformed"
    return None


def request_restore(archive_id: str, confirmation: str) -> Dict[str, Any]:
    """
    Step 1: validate archive + confirmation phrase; issue a one-time
    restore token (second-confirmation requirement).
    """
    if confirmation != RESTORE_CONFIRMATION_PHRASE:
        _audit("session_restore_blocked", "Session restore blocked",
               f"Wrong confirmation phrase for archive {archive_id}",
               context={"archive_id": archive_id, "step": 1})
        return {"success": False,
                "error": f'Confirmation must be exactly "{RESTORE_CONFIRMATION_PHRASE}"'}
    archive = get_archive(archive_id)
    if not archive:
        return {"success": False, "error": f"Archive {archive_id} not found"}
    bad = _validate_snapshot(archive.get("snapshot", {}))
    if bad:
        _audit("session_restore_blocked", "Session restore blocked",
               f"Archive {archive_id} failed validation: {bad}",
               context={"archive_id": archive_id, "reason": bad})
        return {"success": False, "error": f"Archive failed validation: {bad}"}

    token = secrets.token_urlsafe(24)
    expires = _now() + timedelta(minutes=RESTORE_TOKEN_TTL_MINUTES)
    if portfolio_store.db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE session_archives SET restore_token=%s, token_expires=%s WHERE id=%s",
                    (token, expires, archive_id))
            conn.commit()
        finally:
            conn.close()
    else:
        items = _read_fallback()
        for it in items:
            if it.get("id") == archive_id:
                it["restore_token"] = token
                it["token_expires"] = _iso(expires)
        _write_fallback(items)

    return {
        "success": True,
        "restore_token": token,
        "expires_at": _iso(expires),
        "archive": {k: archive[k] for k in ("id", "reset_reason", "metrics")},
        "message": ("Second confirmation required: re-submit with this "
                    f"restore_token within {RESTORE_TOKEN_TTL_MINUTES} minutes."),
    }


def _consume_token(archive_id: str, token: str) -> bool:
    """Atomically validate + clear the one-time token."""
    if not token:
        return False
    if portfolio_store.db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE session_archives SET restore_token=NULL, token_expires=NULL
                    WHERE id=%s AND restore_token=%s AND token_expires > NOW()
                    RETURNING id
                    """, (archive_id, token))
                ok = cur.fetchone() is not None
            conn.commit()
            return ok
        finally:
            conn.close()
    items = _read_fallback()
    ok = False
    for it in items:
        if it.get("id") == archive_id and it.get("restore_token") == token:
            exp = it.get("token_expires")
            if exp and datetime.fromisoformat(exp) > _now():
                ok = True
            it["restore_token"] = None
            it["token_expires"] = None
    _write_fallback(items)
    return ok


def confirm_restore(archive_id: str, confirmation: str, restore_token: str) -> Dict[str, Any]:
    """
    Step 2: verify phrase again + one-time token, archive the current
    session, then apply the archived snapshot. Rolls back on failure.
    Restores ONLY simulated paper state.
    """
    if confirmation != RESTORE_CONFIRMATION_PHRASE:
        _audit("session_restore_blocked", "Session restore blocked",
               f"Wrong confirmation phrase at step 2 for archive {archive_id}",
               context={"archive_id": archive_id, "step": 2})
        return {"success": False,
                "error": f'Confirmation must be exactly "{RESTORE_CONFIRMATION_PHRASE}"'}
    if not _consume_token(archive_id, restore_token):
        _audit("session_restore_blocked", "Session restore blocked",
               f"Invalid or expired restore token for archive {archive_id}",
               context={"archive_id": archive_id, "step": 2})
        return {"success": False, "error": "Invalid or expired restore token — restart the restore flow"}

    archive = get_archive(archive_id)
    if not archive:
        return {"success": False, "error": f"Archive {archive_id} not found"}
    snapshot = archive.get("snapshot", {})
    bad = _validate_snapshot(snapshot)
    if bad:
        _audit("session_restore_blocked", "Session restore blocked",
               f"Archive {archive_id} failed validation at apply time: {bad}",
               context={"archive_id": archive_id, "reason": bad})
        return {"success": False, "error": f"Archive failed validation: {bad}"}

    # Mandatory pre-restore backup of the current session — block on failure.
    try:
        backup = archive_current_session(
            f"Auto-archive before restoring session {archive_id}")
    except Exception as exc:
        _audit("session_restore_blocked", "Session restore blocked",
               f"Pre-restore backup failed: {exc}",
               severity="CRITICAL", context={"archive_id": archive_id})
        return {"success": False,
                "error": f"Pre-restore backup of the current session failed — restore blocked: {exc}"}

    previous_state = portfolio_store.load_state()
    new_state = {
        "cash": float(snapshot["cash"]),
        "positions": snapshot.get("positions", {}),
        "pnl_history": snapshot.get("pnl_history", []),
        "trades": previous_state.get("trades", []),
    }
    try:
        portfolio_store.save_state(new_state)
        # verify round-trip
        applied = portfolio_store.load_state()
        if abs(float(applied.get("cash", -1)) - float(snapshot["cash"])) > 0.01:
            raise RuntimeError("post-restore verification failed (cash mismatch)")
    except Exception as exc:
        # Safe rollback to the previous state
        try:
            portfolio_store.save_state(previous_state)
            rolled_back = True
        except Exception:
            rolled_back = False
        _audit("session_restore_failed", "Session restore FAILED",
               f"Applying archive {archive_id} failed: {exc}. Rolled back: {rolled_back}",
               severity="CRITICAL",
               context={"archive_id": archive_id, "rolled_back": rolled_back,
                        "backup_archive_id": backup["id"]})
        return {"success": False, "rolled_back": rolled_back,
                "error": f"Restore failed and previous state was "
                         f"{'rolled back' if rolled_back else 'NOT rolled back — manual review required'}: {exc}"}

    # Stamp restored_at (non-destructive metadata update)
    if portfolio_store.db_available():
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE session_archives SET restored_at=NOW() WHERE id=%s",
                            (archive_id,))
            conn.commit()
        finally:
            conn.close()
    else:
        items = _read_fallback()
        for it in items:
            if it.get("id") == archive_id:
                it["restored_at"] = _iso(_now())
        _write_fallback(items)

    _audit("session_restored", "Paper session restored",
           f"Archive {archive_id} restored. Current session was archived as {backup['id']}.",
           severity="WARNING",
           context={"archive_id": archive_id, "backup_archive_id": backup["id"],
                    "restored_metrics": archive.get("metrics", {})})
    return {
        "success": True,
        "restored_archive_id": archive_id,
        "backup_archive_id": backup["id"],
        "metrics": archive.get("metrics", {}),
        "message": "Paper session restored. The previous session was archived first.",
    }


# ── Local-dev fallback storage ───────────────────────────────────────────────

def _read_fallback() -> List[Dict[str, Any]]:
    if os.path.exists(FALLBACK_FILE):
        try:
            with open(FALLBACK_FILE) as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _write_fallback(items: List[Dict[str, Any]]) -> None:
    tmp = FALLBACK_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f, indent=2, default=str)
    os.replace(tmp, FALLBACK_FILE)
