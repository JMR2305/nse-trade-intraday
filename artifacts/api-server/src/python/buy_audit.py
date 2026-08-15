"""
buy_audit.py — Phase 20 BUY execution audit helper (read-only).

Retrieves the most recent BUY_GENERATED pipeline events, verifies each one
against IST market hours, and cross-references the phase20_paper_trades ledger
and ORDER_* pipeline events to show whether auto-entry actually attempted
execution and what the final outcome was.

READ-ONLY. PAPER TRADING / RESEARCH ONLY. No live orders.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Canonical paper execution trade IDs always begin with "P20-".
# BTT- (backtest), EXP- (exploration), and any other prefixes are non-canonical
# and must never be counted in live paper execution stats.
_CANONICAL_PREFIX = "P20-"


def _is_canonical_order_event(e: Dict[str, Any]) -> bool:
    """Return True if this ORDER_* event comes from the canonical phase20 executor.

    Events with no trade_id in the payload pass through (backward-compatible).
    Events with an explicit non-P20-... trade_id are rejected.
    """
    tid = str((e.get("payload") or {}).get("trade_id") or "")
    return not tid or tid.startswith(_CANONICAL_PREFIX)


def _ts_to_ist_iso(ts_val) -> str:
    """Convert a timestamp value (datetime or ISO string) to IST ISO-8601."""
    try:
        if isinstance(ts_val, datetime):
            dt = ts_val
        else:
            s = str(ts_val).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ist_dt = dt.astimezone(IST)
        return ist_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    except Exception:
        return str(ts_val)


def _parse_ts(ts_val) -> Optional[datetime]:
    """Parse a timestamp into an aware datetime (UTC). Returns None on failure."""
    try:
        if isinstance(ts_val, datetime):
            dt = ts_val
        else:
            s = str(ts_val).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _is_market_open(ts_val) -> bool:
    """Return True when ts falls inside 09:15–15:30 IST on a non-holiday weekday."""
    try:
        from market_hours import market_state
        dt = _parse_ts(ts_val)
        if dt is None:
            return False
        return market_state(dt) == "OPEN"
    except Exception:
        return False


# ── DB helpers ────────────────────────────────────────────────────────────────

def _fetch_buy_generated_db(conn, limit: int) -> List[Dict[str, Any]]:
    """Query pipeline_events for the most recent BUY_GENERATED events."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ts, scan_id, symbol, payload
            FROM pipeline_events
            WHERE mode = 'LIVE' AND event_type = 'BUY_GENERATED'
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = []
        for row in cur.fetchall():
            payload = row[4]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            rows.append({
                "id": row[0],
                "ts": row[1],
                "scan_id": row[2],
                "symbol": row[3],
                "payload": payload or {},
            })
        return rows


def _fetch_order_events_db(conn, scan_id: str, symbol: str) -> List[Dict[str, Any]]:
    """Fetch ORDER_* pipeline events for a given scan_id + symbol."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_type, ts
            FROM pipeline_events
            WHERE mode = 'LIVE'
              AND scan_id = %s
              AND symbol = %s
              AND event_type IN ('ORDER_SUBMITTED', 'ORDER_EXECUTED',
                                 'ORDER_REJECTED', 'ORDER_CANCELLED')
              AND (payload->>'trade_id' IS NULL
                   OR payload->>'trade_id' LIKE 'P20-%')
            ORDER BY id ASC
            """,
            (scan_id, symbol),
        )
        return [{"event_type": r[0], "ts": r[1]} for r in cur.fetchall()]


def _fetch_trade_db(conn, scan_id: str, symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the AUTO paper trade row for a given scan_id + symbol."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, fill_price, quantity, evidence
            FROM phase20_paper_trades
            WHERE scan_id = %s
              AND symbol = %s
              AND trigger_source = 'AUTO'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (scan_id, symbol),
        )
        row = cur.fetchone()
        if row is None:
            return None
        evidence = row[3]
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except Exception:
                evidence = {}
        return {
            "status": row[0],
            "fill_price": row[1],
            "qty": row[2],
            "evidence": evidence or {},
        }


# ── File-fallback helpers ─────────────────────────────────────────────────────

def _fetch_buy_generated_file(limit: int) -> List[Dict[str, Any]]:
    try:
        from pipeline_events import query_events
        evs = query_events(event_type="BUY_GENERATED", limit=limit, newest_first=True)
        return [
            {
                "id": e.get("id", 0),
                "ts": e.get("ts"),
                "scan_id": e.get("scan_id"),
                "symbol": e.get("symbol"),
                "payload": e.get("payload") or {},
            }
            for e in evs
        ]
    except Exception:
        return []


def _fetch_order_events_file(scan_id: str, symbol: str) -> List[Dict[str, Any]]:
    try:
        from pipeline_events import query_events
        evs = query_events(scan_id=scan_id, symbol=symbol,
                           limit=20, newest_first=False)
        return [
            {"event_type": e["event_type"], "ts": e.get("ts")}
            for e in evs
            if e["event_type"] in ("ORDER_SUBMITTED", "ORDER_EXECUTED",
                                   "ORDER_REJECTED", "ORDER_CANCELLED")
            # Exclude non-canonical events (BTT-, EXP-, replay) from execution audit
            and _is_canonical_order_event(e)
        ]
    except Exception:
        return []


def _fetch_trade_file(scan_id: str, symbol: str) -> Optional[Dict[str, Any]]:
    try:
        from phase20_executor import get_ledger
        for t in get_ledger(500):
            if (str(t.get("scan_id") or "") == scan_id
                    and str(t.get("symbol") or "").upper() == symbol.upper()
                    and str(t.get("trigger_source") or "") == "AUTO"):
                evidence = t.get("evidence") or {}
                if isinstance(evidence, str):
                    try:
                        evidence = json.loads(evidence)
                    except Exception:
                        evidence = {}
                return {
                    "status": t.get("status"),
                    "fill_price": t.get("fill_price"),
                    "qty": t.get("quantity"),
                    "evidence": evidence,
                }
    except Exception:
        pass
    return None


# ── Outcome derivation ────────────────────────────────────────────────────────

def _derive_outcome(order_events: List[Dict[str, Any]],
                    trade: Optional[Dict[str, Any]]) -> str:
    """
    Derive execution_outcome from the ORDER_* pipeline events and trade record.

    ORDER_EXECUTED present                 → ORDER_EXECUTED
    ORDER_REJECTED present (no EXECUTED)   → ORDER_REJECTED
    ORDER_SUBMITTED present (no fill/rej)  → ORDER_SUBMITTED
    Trade row but no ORDER_SUBMITTED       → BLOCKED_BEFORE_SUBMIT
    Nothing at all                         → NO_ATTEMPT
    """
    types = {e["event_type"] for e in order_events}
    if "ORDER_EXECUTED" in types:
        return "ORDER_EXECUTED"
    if "ORDER_REJECTED" in types:
        return "ORDER_REJECTED"
    if "ORDER_SUBMITTED" in types:
        # Has a trade row but not yet an EXECUTED or REJECTED confirmation.
        return "ORDER_SUBMITTED"
    if trade is not None:
        # A trade row exists but no ORDER_SUBMITTED was emitted — execution was
        # reached internally but the order submission was blocked before the event.
        return "BLOCKED_BEFORE_SUBMIT"
    return "NO_ATTEMPT"


def _extract_failed_gates(trade: Optional[Dict[str, Any]]) -> List[str]:
    """Pull failed_gates from the trade evidence JSONB, or return []."""
    if trade is None:
        return []
    evidence = trade.get("evidence") or {}
    fg = evidence.get("failed_gates")
    if isinstance(fg, list):
        return [str(g) for g in fg]
    return []


# ── Public API ────────────────────────────────────────────────────────────────

def get_buy_audit(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Return audit records for the `limit` most recent BUY_GENERATED events.

    Each record contains:
      scan_id, symbol, generated_at_ist, market_open,
      auto_entry_attempted, execution_outcome, failed_gates,
      fill_price, qty, status
    """
    limit = max(1, min(int(limit), 50))

    try:
        from scan_state_store import db_available, _connect
        use_db = db_available()
    except Exception:
        use_db = False

    # ── Fetch BUY_GENERATED events ────────────────────────────────────────────
    if use_db:
        try:
            conn = _connect()
            try:
                # Ensure schema exists before querying
                try:
                    from pipeline_events import _ensure_schema
                    _ensure_schema(conn)
                except Exception:
                    pass
                buy_events = _fetch_buy_generated_db(conn, limit)
            finally:
                conn.close()
        except Exception:
            buy_events = _fetch_buy_generated_file(limit)
            use_db = False
    else:
        buy_events = _fetch_buy_generated_file(limit)

    records: List[Dict[str, Any]] = []
    for ev in buy_events:
        scan_id = ev.get("scan_id") or ""
        symbol = str(ev.get("symbol") or "").upper()
        ts_val = ev.get("ts")

        generated_at_ist = _ts_to_ist_iso(ts_val)
        market_open = _is_market_open(ts_val)

        # ── Cross-reference ledger and ORDER_* events ─────────────────────────
        if use_db and scan_id:
            try:
                conn = _connect()
                try:
                    order_events = _fetch_order_events_db(conn, scan_id, symbol)
                    trade = _fetch_trade_db(conn, scan_id, symbol)
                finally:
                    conn.close()
            except Exception:
                order_events = _fetch_order_events_file(scan_id, symbol)
                trade = _fetch_trade_file(scan_id, symbol)
        elif scan_id:
            order_events = _fetch_order_events_file(scan_id, symbol)
            trade = _fetch_trade_file(scan_id, symbol)
        else:
            order_events = []
            trade = None

        auto_entry_attempted = trade is not None
        execution_outcome = _derive_outcome(order_events, trade)
        failed_gates = _extract_failed_gates(trade)

        records.append({
            "scan_id": scan_id or None,
            "symbol": symbol or None,
            "generated_at_ist": generated_at_ist,
            "market_open": market_open,
            "auto_entry_attempted": auto_entry_attempted,
            "execution_outcome": execution_outcome,
            "failed_gates": failed_gates,
            "fill_price": trade["fill_price"] if trade else None,
            "qty": trade["qty"] if trade else None,
            "status": trade["status"] if trade else None,
        })

    return records
