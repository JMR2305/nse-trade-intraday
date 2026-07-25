"""
eod_reconciliation.py — Automated EOD broker order reconciliation.

Runs once per day after 15:35 IST (market close + 5 min buffer) to
compare local orders against the Zerodha broker order book. Any
`requires_manual_review` discrepancies trigger an email alert.

Results are written to:
  - broker_reconciliation_runs        (one row per run)
  - broker_reconciliation_discrepancies (one row per discrepancy)

Design rules:
  * Per-day KV guard (eod_reconcil_date) ensures exactly-once execution.
  * NEVER raises: all failures are captured and returned as status dicts.
  * Works in both paper and live-assisted modes; in paper mode it records
    a clean run immediately (no broker API needed).
  * Synchronous — compatible with the per-request Python spawn pattern.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    print(f"[eod_reconcil] {msg}", file=sys.stderr)


# ── Schema bootstrap ──────────────────────────────────────────────────────────

_SCHEMA_READY = False


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS broker_reconciliation_runs (
                run_id          TEXT PRIMARY KEY,
                trigger         TEXT NOT NULL DEFAULT 'manual',
                started_at      TIMESTAMPTZ NOT NULL,
                completed_at    TIMESTAMPTZ,
                orders_checked  INTEGER NOT NULL DEFAULT 0,
                clean           BOOLEAN NOT NULL DEFAULT TRUE,
                discrepancy_count INTEGER NOT NULL DEFAULT 0,
                paper_mode      BOOLEAN NOT NULL DEFAULT FALSE,
                error           TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS broker_reconciliation_discrepancies (
                id                  SERIAL PRIMARY KEY,
                run_id              TEXT NOT NULL REFERENCES broker_reconciliation_runs(run_id),
                discrepancy_type    TEXT NOT NULL,
                internal_order_id   TEXT,
                broker_order_id     TEXT,
                trading_symbol      TEXT,
                description         TEXT,
                local_value         TEXT,
                broker_value        TEXT,
                requires_manual_review BOOLEAN NOT NULL DEFAULT FALSE,
                resolved            BOOLEAN NOT NULL DEFAULT FALSE,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_recon_discrepancies_run_id
                ON broker_reconciliation_discrepancies(run_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_recon_runs_started_at
                ON broker_reconciliation_runs(started_at DESC)
        """)
        # Migration: add resolved_at / resolved_note columns if not present
        # (safe on an already-populated table — no-op when columns exist)
        cur.execute("""
            ALTER TABLE broker_reconciliation_discrepancies
                ADD COLUMN IF NOT EXISTS resolved_at   TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS resolved_note TEXT
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_recon_discrepancies_resolved
                ON broker_reconciliation_discrepancies(resolved, resolved_at DESC)
        """)
    conn.commit()
    _SCHEMA_READY = True


# ── Market-hours guard ────────────────────────────────────────────────────────

def _is_eod_window() -> bool:
    """True if current IST time is between 15:35 and 23:59 on a weekday."""
    try:
        from zoneinfo import ZoneInfo
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        if now_ist.weekday() >= 5:  # Saturday / Sunday
            return False
        h, m = now_ist.hour, now_ist.minute
        return (h > 15) or (h == 15 and m >= 35)
    except Exception:
        return False  # if TZ unavailable, skip


def _today_ist() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Discrepancy detection (synchronous) ───────────────────────────────────────

def _load_local_orders(conn) -> List[Dict[str, Any]]:
    """Load today's orders from the local orders table. Returns [] on error."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    order_id       AS broker_order_id,
                    symbol,
                    status,
                    quantity,
                    price,
                    created_at
                FROM orders
                WHERE DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE
                ORDER BY id
            """)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        _log(f"Failed to load local orders: {type(exc).__name__}: {exc}")
        return []


def _check_discrepancies(
    local_orders: List[Dict[str, Any]],
    broker_orders: List[Any],
) -> List[Dict[str, Any]]:
    """Compare local DB orders against broker order book. Returns discrepancy dicts."""
    from collections import Counter

    TERMINAL = {"COMPLETE", "CANCELLED", "REJECTED"}

    # Map broker orders by order_id
    broker_by_id: Dict[str, Any] = {}
    for o in broker_orders:
        oid = getattr(o, "order_id", None) or (o.get("order_id") if isinstance(o, dict) else None)
        if oid:
            broker_by_id[str(oid)] = o

    def _bstatus(o: Any) -> str:
        if isinstance(o, dict):
            return str(o.get("status", "")).upper()
        return str(getattr(o, "status", "")).upper()

    def _bsymbol(o: Any) -> str:
        if isinstance(o, dict):
            return str(o.get("symbol", "") or o.get("tradingsymbol", ""))
        return str(getattr(o, "symbol", "") or getattr(o, "tradingsymbol", ""))

    local_by_broker_id: Dict[str, Dict] = {
        str(o["broker_order_id"]): o
        for o in local_orders
        if o.get("broker_order_id")
    }

    discrepancies: List[Dict[str, Any]] = []

    # Check 1: LOCAL_ONLY — local active order not in broker book
    for local in local_orders:
        bid = str(local.get("broker_order_id") or "")
        if bid and bid not in broker_by_id:
            if str(local.get("status", "")).upper() not in TERMINAL:
                discrepancies.append({
                    "discrepancy_type": "LOCAL_ONLY",
                    "internal_order_id": str(local.get("id", "")),
                    "broker_order_id": bid,
                    "trading_symbol": str(local.get("symbol", "")),
                    "description": "Local order not found in broker order book",
                    "local_value": str(local.get("status", "")),
                    "broker_value": None,
                    "requires_manual_review": True,
                })

    # Check 2: BROKER_ONLY — broker order with no local counterpart (active only)
    for bid, bo in broker_by_id.items():
        if bid not in local_by_broker_id:
            bs = _bstatus(bo)
            if bs not in TERMINAL:
                discrepancies.append({
                    "discrepancy_type": "BROKER_ONLY",
                    "internal_order_id": None,
                    "broker_order_id": bid,
                    "trading_symbol": _bsymbol(bo),
                    "description": "Broker order has no local counterpart",
                    "local_value": None,
                    "broker_value": bs,
                    "requires_manual_review": True,
                })

    # Check 3: STATE_MISMATCH — terminal state disagrees
    for local in local_orders:
        bid = str(local.get("broker_order_id") or "")
        if not bid or bid not in broker_by_id:
            continue
        bo = broker_by_id[bid]
        local_terminal = str(local.get("status", "")).upper() in TERMINAL
        broker_terminal = _bstatus(bo) in TERMINAL
        if local_terminal != broker_terminal:
            discrepancies.append({
                "discrepancy_type": "STATE_MISMATCH",
                "internal_order_id": str(local.get("id", "")),
                "broker_order_id": bid,
                "trading_symbol": str(local.get("symbol", "")),
                "description": "Local and broker terminal states differ",
                "local_value": str(local.get("status", "")),
                "broker_value": _bstatus(bo),
                "requires_manual_review": True,
            })

    # Check 4: FILL_MISMATCH — broker says COMPLETE but filled_qty is 0
    for local in local_orders:
        bid = str(local.get("broker_order_id") or "")
        if not bid or bid not in broker_by_id:
            continue
        bo = broker_by_id[bid]
        bs = _bstatus(bo)
        if bs == "COMPLETE":
            filled = int(getattr(bo, "filled_quantity", 0) or
                         (bo.get("filled_quantity", 0) if isinstance(bo, dict) else 0))
            if filled == 0:
                discrepancies.append({
                    "discrepancy_type": "FILL_MISMATCH",
                    "internal_order_id": str(local.get("id", "")),
                    "broker_order_id": bid,
                    "trading_symbol": str(local.get("symbol", "")),
                    "description": "Order COMPLETE but filled_quantity is 0",
                    "local_value": None,
                    "broker_value": str(filled),
                    "requires_manual_review": True,
                })

    # Check 5: DUPLICATE_ORDER — multiple local rows share a broker_order_id
    bid_counts = Counter(
        str(o["broker_order_id"])
        for o in local_orders
        if o.get("broker_order_id")
    )
    for dup_bid, cnt in bid_counts.items():
        if cnt > 1:
            discrepancies.append({
                "discrepancy_type": "DUPLICATE_ORDER",
                "internal_order_id": None,
                "broker_order_id": dup_bid,
                "trading_symbol": None,
                "description": f"broker_order_id {dup_bid!r} mapped to {cnt} local orders",
                "local_value": str(cnt),
                "broker_value": None,
                "requires_manual_review": True,
            })

    return discrepancies


# ── Persistence ───────────────────────────────────────────────────────────────

def _persist_run(conn, run_id: str, trigger: str,
                 started_at: datetime, completed_at: datetime,
                 orders_checked: int, discrepancies: List[Dict[str, Any]],
                 paper_mode: bool, error: Optional[str]) -> None:
    clean = len(discrepancies) == 0 and error is None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO broker_reconciliation_runs
                (run_id, trigger, started_at, completed_at,
                 orders_checked, clean, discrepancy_count, paper_mode, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO NOTHING
        """, (
            run_id, trigger, started_at, completed_at,
            orders_checked, clean, len(discrepancies), paper_mode,
            error[:500] if error else None,
        ))
        for d in discrepancies:
            cur.execute("""
                INSERT INTO broker_reconciliation_discrepancies
                    (run_id, discrepancy_type, internal_order_id,
                     broker_order_id, trading_symbol, description,
                     local_value, broker_value, requires_manual_review)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                run_id,
                d.get("discrepancy_type"),
                d.get("internal_order_id"),
                d.get("broker_order_id"),
                d.get("trading_symbol"),
                d.get("description"),
                d.get("local_value"),
                d.get("broker_value"),
                bool(d.get("requires_manual_review")),
            ))
    conn.commit()


# ── Email alert ───────────────────────────────────────────────────────────────

def _maybe_email_alert(
    run_id: str,
    discrepancies: List[Dict[str, Any]],
    run_time: Optional[str] = None,
) -> Dict[str, Any]:
    """Fire a durable email alert if any discrepancy requires manual review.

    Uses the RECONCILIATION_DISCREPANCY kind so it is handled by the standard
    alert queue (enqueue + immediate process attempt) rather than a direct
    fire-and-forget call.  The queue retries on a transient provider failure.
    """
    review_needed = [d for d in discrepancies if d.get("requires_manual_review")]
    if not review_needed:
        return {"sent": False, "reason": "NO_REVIEW_NEEDED"}
    try:
        types = list({d.get("discrepancy_type", "UNKNOWN") for d in review_needed})
        run_time_str = run_time or _iso(_now_utc())

        body_lines = [
            f"Run completed at: {run_time_str}",
            f"Discrepancies requiring review: {len(review_needed)}",
            f"Types: {', '.join(sorted(types))}",
            "",
        ]
        for d in review_needed[:10]:
            line = f"  [{d['discrepancy_type']}]"
            if d.get("trading_symbol"):
                line += f" {d['trading_symbol']}"
            if d.get("broker_order_id"):
                line += f" broker={d['broker_order_id']}"
            line += f": {d.get('description', '')}"
            body_lines.append(line)
        if len(review_needed) > 10:
            body_lines.append(f"  ... and {len(review_needed) - 10} more")
        body_lines += [
            "",
            "Open the Broker Execution page on your dashboard to review and",
            "resolve each discrepancy before the next trading session.",
        ]

        title = f"EOD Reconciliation: {len(review_needed)} discrepancy/ies need review"
        body = "\n".join(body_lines)

        # Route through the durable alert queue so a briefly-down provider
        # does not lose the alert — the scheduler retries with backoff.
        import alert_queue
        alert_queue.enqueue_email_alert(
            "RECONCILIATION_DISCREPANCY", title, body, "ERROR"
        )
        result = alert_queue.process_email_queue()
        # process_email_queue returns a summary dict (keys: delivered, failed,
        # retried, expired, skipped).  Normalise to the shape callers expect.
        if isinstance(result, dict):
            delivered = result.get("delivered", 0)
            failed = result.get("failed", 0)
            return {
                "sent": delivered > 0,
                "queued": True,
                "delivered": delivered,
                "failed": failed,
                "reason": "QUEUED_AND_DELIVERED" if delivered > 0 else "QUEUED",
            }
        return {"sent": False, "queued": True, "reason": "QUEUED"}
    except Exception as exc:
        _log(f"Email alert failed: {exc}")
        return {"sent": False, "reason": "ERROR", "error": str(exc)[:200]}


# ── Store helper wrappers ─────────────────────────────────────────────────────

def _kv_get(key: str) -> Any:
    try:
        import phase20_store as store
        return store.kv_get(key)
    except Exception:
        return None


def _kv_set(key: str, value: Any) -> None:
    try:
        import phase20_store as store
        store.kv_set(key, value)
    except Exception:
        pass


def _add_notification(kind: str, title: str, body: str,
                      severity: str = "INFO", context: Optional[Dict] = None) -> None:
    try:
        import phase20_store as store
        store.add_notification(kind, title, body, severity=severity,
                               context=context or {})
    except Exception:
        pass


# ── Main entry points ─────────────────────────────────────────────────────────

def run_eod_reconciliation(
    *,
    trigger: str = "eod",
    force: bool = False,
) -> Dict[str, Any]:
    """
    Run end-of-day broker reconciliation. Idempotent within one IST calendar day.

    Parameters
    ----------
    trigger : "eod" | "manual" | "scheduled"
    force   : bypass the per-day KV guard (for manual triggers / testing)

    Returns a JSON-safe dict.
    """
    today = _today_ist()

    # Per-day guard — run exactly once unless forced
    if not force:
        last_date = _kv_get("eod_reconcil_date")
        if last_date == today:
            return {
                "success": True,
                "skipped": True,
                "reason": f"EOD reconciliation already ran today ({today})",
                "last_date": last_date,
            }

    # EOD window check (skip unless forced)
    if not force and not _is_eod_window():
        return {
            "success": True,
            "skipped": True,
            "reason": "Not in EOD window (after 15:35 IST on a weekday)",
        }

    run_id = str(uuid.uuid4())
    started_at = _now_utc()

    _log(f"Starting EOD reconciliation run={run_id} trigger={trigger!r}")

    # ── Paper mode check ─────────────────────────────────────────────────────
    try:
        import phase20_store as store
        settings = store.get_settings()
        paper_mode = settings.get("execution_mode", "PAPER_TRADING") != "LIVE_ASSISTED"
    except Exception:
        paper_mode = True  # default safe

    # ── Claim the day immediately (idempotency) ──────────────────────────────
    _kv_set("eod_reconcil_date", today)

    # ── Paper mode fast path ─────────────────────────────────────────────────
    if paper_mode:
        completed_at = _now_utc()
        report = {
            "success": True,
            "run_id": run_id,
            "trigger": trigger,
            "started_at": _iso(started_at),
            "completed_at": _iso(completed_at),
            "orders_checked": 0,
            "discrepancy_count": 0,
            "requires_review_count": 0,
            "clean": True,
            "paper_mode": True,
            "email": {"sent": False, "reason": "PAPER_MODE"},
        }
        # Persist to DB if available
        try:
            from scan_state_store import _connect
            conn = _connect()
            try:
                _ensure_schema(conn)
                _persist_run(conn, run_id, trigger, started_at, completed_at,
                             0, [], True, None)
            finally:
                conn.close()
        except Exception as exc:
            _log(f"DB persist skipped (paper): {exc}")
        _kv_set("eod_reconcil_last", report)
        _add_notification("RECONCILIATION_EOD", "EOD reconciliation: clean (paper mode)",
                          f"Run {run_id}", severity="INFO",
                          context={"run_id": run_id, "trigger": trigger})
        return report

    # ── Live mode: fetch broker orders and compare ───────────────────────────
    error_str: Optional[str] = None
    discrepancies: List[Dict[str, Any]] = []
    orders_checked = 0
    broker_orders: List[Any] = []

    try:
        from broker_client import get_broker_client
        client = get_broker_client()
        broker_orders = client.get_orders(limit=200)
    except Exception as exc:
        error_str = f"Broker order fetch failed: {type(exc).__name__}: {str(exc)[:300]}"
        _log(error_str)

    # Try to load local orders and run comparison
    if error_str is None:
        try:
            from scan_state_store import _connect
            conn = _connect()
            try:
                _ensure_schema(conn)
                local_orders = _load_local_orders(conn)
                orders_checked = len(local_orders)
                discrepancies = _check_discrepancies(local_orders, broker_orders)
            finally:
                conn.close()
        except Exception as exc:
            error_str = f"Reconciliation comparison failed: {type(exc).__name__}: {str(exc)[:300]}"
            _log(error_str)

    completed_at = _now_utc()
    review_count = sum(1 for d in discrepancies if d.get("requires_manual_review"))
    clean = len(discrepancies) == 0 and error_str is None

    # ── Persist run + discrepancies ──────────────────────────────────────────
    db_persisted = False
    try:
        from scan_state_store import _connect
        conn = _connect()
        try:
            _ensure_schema(conn)
            _persist_run(conn, run_id, trigger, started_at, completed_at,
                         orders_checked, discrepancies, False, error_str)
            db_persisted = True
        finally:
            conn.close()
    except Exception as exc:
        _log(f"Failed to persist reconciliation run: {exc}")

    # ── Email alert if discrepancies need review ──────────────────────────────
    email_result: Dict[str, Any] = {"sent": False, "reason": "NO_REVIEW_NEEDED"}
    if review_count > 0:
        email_result = _maybe_email_alert(run_id, discrepancies,
                                          run_time=_iso(completed_at))
        severity = "ERROR"
    else:
        severity = "INFO" if clean else "WARN"

    # ── Notification ──────────────────────────────────────────────────────────
    if clean:
        notif_title = "EOD reconciliation: clean"
        notif_body = f"Run {run_id}: {orders_checked} orders checked, no discrepancies."
    elif error_str:
        notif_title = "EOD reconciliation: error"
        notif_body = error_str[:300]
        severity = "ERROR"
    else:
        notif_title = f"EOD reconciliation: {len(discrepancies)} discrepancy/ies"
        notif_body = (f"Run {run_id}: {review_count} require manual review. "
                      f"Open Broker Execution dashboard.")

    _add_notification("RECONCILIATION_EOD", notif_title, notif_body,
                      severity=severity,
                      context={"run_id": run_id, "trigger": trigger,
                               "discrepancy_count": len(discrepancies)})

    report = {
        "success": True,
        "run_id": run_id,
        "trigger": trigger,
        "started_at": _iso(started_at),
        "completed_at": _iso(completed_at),
        "orders_checked": orders_checked,
        "discrepancy_count": len(discrepancies),
        "requires_review_count": review_count,
        "clean": clean,
        "paper_mode": False,
        "db_persisted": db_persisted,
        "error": error_str,
        "email": email_result,
        "discrepancies": discrepancies,
    }
    _kv_set("eod_reconcil_last", {k: v for k, v in report.items()
                                   if k != "discrepancies"})

    _log(f"EOD reconciliation done: {len(discrepancies)} discrepancies, "
         f"clean={clean}, review_needed={review_count}")
    return report


def get_last_run() -> Dict[str, Any]:
    """Return summary of the last EOD reconciliation run."""
    last = _kv_get("eod_reconcil_last")
    if isinstance(last, dict):
        return last
    return {"run_id": None, "message": "No EOD reconciliation has run yet"}


def get_reconciliation_status() -> Dict[str, Any]:
    """Return last run summary + open discrepancies (and recently resolved ones) from DB."""
    last = get_last_run()
    open_discrepancies: List[Dict[str, Any]] = []
    resolved_discrepancies: List[Dict[str, Any]] = []

    try:
        from scan_state_store import _connect, db_available
        if db_available():
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    # Latest run
                    cur.execute("""
                        SELECT run_id, trigger, started_at, completed_at,
                               orders_checked, clean, discrepancy_count,
                               paper_mode, error
                        FROM broker_reconciliation_runs
                        ORDER BY started_at DESC
                        LIMIT 1
                    """)
                    row = cur.fetchone()
                    if row:
                        cols = [d[0] for d in cur.description]
                        last_db = dict(zip(cols, row))
                        # Convert datetimes
                        for f in ("started_at", "completed_at"):
                            if last_db.get(f) and hasattr(last_db[f], "strftime"):
                                last_db[f] = last_db[f].strftime("%Y-%m-%dT%H:%M:%SZ")
                        last["db_latest_run"] = last_db

                    # Open (unresolved) discrepancies from all recent runs
                    cur.execute("""
                        SELECT d.id, d.run_id, d.discrepancy_type,
                               d.internal_order_id, d.broker_order_id,
                               d.trading_symbol, d.description,
                               d.local_value, d.broker_value,
                               d.requires_manual_review, d.resolved,
                               d.created_at
                        FROM broker_reconciliation_discrepancies d
                        JOIN broker_reconciliation_runs r ON r.run_id = d.run_id
                        WHERE d.resolved = FALSE
                          AND r.started_at >= NOW() - INTERVAL '7 days'
                        ORDER BY d.created_at DESC
                        LIMIT 100
                    """)
                    cols = [desc[0] for desc in cur.description]
                    for row in cur.fetchall():
                        d = dict(zip(cols, row))
                        for f in ("created_at",):
                            if d.get(f) and hasattr(d[f], "strftime"):
                                d[f] = d[f].strftime("%Y-%m-%dT%H:%M:%SZ")
                        open_discrepancies.append(d)

                    # Recently resolved discrepancies (last 7 days, limit 50)
                    cur.execute("""
                        SELECT d.id, d.run_id, d.discrepancy_type,
                               d.internal_order_id, d.broker_order_id,
                               d.trading_symbol, d.description,
                               d.local_value, d.broker_value,
                               d.requires_manual_review,
                               d.resolved_at, d.resolved_note,
                               d.created_at
                        FROM broker_reconciliation_discrepancies d
                        JOIN broker_reconciliation_runs r ON r.run_id = d.run_id
                        WHERE d.resolved = TRUE
                          AND r.started_at >= NOW() - INTERVAL '7 days'
                        ORDER BY d.resolved_at DESC NULLS LAST
                        LIMIT 50
                    """)
                    res_cols = [desc[0] for desc in cur.description]
                    resolved_discrepancies: List[Dict[str, Any]] = []
                    for row in cur.fetchall():
                        rd = dict(zip(res_cols, row))
                        for f in ("created_at", "resolved_at"):
                            if rd.get(f) and hasattr(rd[f], "strftime"):
                                rd[f] = rd[f].strftime("%Y-%m-%dT%H:%M:%SZ")
                        resolved_discrepancies.append(rd)

                    # Recent runs history (last 10)
                    cur.execute("""
                        SELECT run_id, trigger, started_at, completed_at,
                               orders_checked, clean, discrepancy_count,
                               paper_mode, error
                        FROM broker_reconciliation_runs
                        ORDER BY started_at DESC
                        LIMIT 10
                    """)
                    cols = [d[0] for d in cur.description]
                    runs = []
                    for row in cur.fetchall():
                        r = dict(zip(cols, row))
                        for f in ("started_at", "completed_at"):
                            if r.get(f) and hasattr(r[f], "strftime"):
                                r[f] = r[f].strftime("%Y-%m-%dT%H:%M:%SZ")
                        runs.append(r)
                    last["recent_runs"] = runs
            finally:
                conn.close()
    except Exception as exc:
        _log(f"get_reconciliation_status DB read failed: {exc}")

    return {
        "success": True,
        "last_run": last,
        "open_discrepancies": open_discrepancies,
        "open_discrepancy_count": len(open_discrepancies),
        "resolved_discrepancies": resolved_discrepancies,
        "today": _today_ist(),
        "last_ran_today": _kv_get("eod_reconcil_date") == _today_ist(),
        "eod_window_active": _is_eod_window(),
    }


def resolve_discrepancy(
    discrepancy_id: int,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Mark a discrepancy as resolved, recording the timestamp and an optional operator note."""
    try:
        from scan_state_store import _connect
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE broker_reconciliation_discrepancies
                    SET resolved      = TRUE,
                        resolved_at   = NOW(),
                        resolved_note = %s
                    WHERE id = %s
                    RETURNING id, resolved_at
                """, (note[:500] if note else None, discrepancy_id))
                row = cur.fetchone()
            conn.commit()
            if row:
                resolved_at = row[1]
                return {
                    "success": True,
                    "resolved_id": discrepancy_id,
                    "resolved_at": resolved_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if hasattr(resolved_at, "strftime") else str(resolved_at),
                }
            return {"success": False, "error": f"Discrepancy {discrepancy_id} not found"}
        finally:
            conn.close()
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300]}
