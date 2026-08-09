"""
pipeline_events.py — Phase 23: canonical Pipeline Event Store.

ONE append-only event stream for everything the AI pipeline does. Every
stage of the production pipeline (scanner → research → market intelligence →
monitoring → strategy → risk → AI decision → execution → portfolio) emits
events here, and every dashboard renders from these events — no page computes
its own pipeline state.

Design:
- Postgres table `pipeline_events` (lazy CREATE TABLE, scan_state_store
  connection helper). File fallback for DATABASE_URL-less dev/tests.
- Emission is ALWAYS fail-safe: a failed emit never breaks the pipeline.
- Events are immutable; consumers read via since-id / scan_id / filters.
- `mode` separates LIVE pipeline runs from BACKTEST runs so historical
  replays never pollute live dashboards (and vice versa).

PAPER TRADING / RESEARCH ONLY. No live orders anywhere in this module.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scan_state_store import db_available, _connect

_DIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_FILE = os.path.join(_DIR, "pipeline_events.json")
_FALLBACK_MAX = 5000          # cap file fallback growth
_SCHEMA_READY = False

# Canonical stages, in pipeline order (used by summaries and the UI).
STAGES = [
    "SUPERVISOR", "SCANNER", "RESEARCH", "MARKET_INTELLIGENCE", "MONITORING",
    "STRATEGY", "PORTFOLIO_PRECHECK", "RISK", "AI_DECISION", "EXECUTION",
    "PORTFOLIO",
]

# Canonical event types (open set — emitters may add narrower types, but
# these are the ones dashboards understand).
EVENT_TYPES = [
    "SCAN_STARTED", "SCAN_FETCH_COMPLETED", "SYMBOL_SCANNED", "SYMBOL_REJECTED",
    "RESEARCH_COMPLETED", "MARKET_INTELLIGENCE_COMPLETED", "MONITORING_COMPLETED",
    "STRATEGY_SELECTED", "STRATEGY_REJECTED",
    "PRECHECK_APPROVED", "PRECHECK_REJECTED",
    "RISK_APPROVED", "RISK_REJECTED",
    "BUY_GENERATED", "SELL_GENERATED", "WATCH_GENERATED", "IGNORE_GENERATED",
    "ORDER_SUBMITTED", "ORDER_EXECUTED", "ORDER_REJECTED", "ORDER_CANCELLED",
    "POSITION_OPENED", "POSITION_UPDATED", "POSITION_CLOSED",
    "PORTFOLIO_UPDATED", "PNL_UPDATED",
    "SCAN_COMPLETED", "SCAN_FAILED",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_events (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                mode TEXT NOT NULL DEFAULT 'LIVE',
                run_id TEXT,
                scan_id TEXT,
                event_type TEXT NOT NULL,
                stage TEXT NOT NULL,
                symbol TEXT,
                payload JSONB
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_pipeline_events_scan"
            " ON pipeline_events (scan_id, id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_pipeline_events_mode_id"
            " ON pipeline_events (mode, id DESC)"
        )
    conn.commit()
    _SCHEMA_READY = True


# ── Emit ─────────────────────────────────────────────────────────────────────

def emit(event_type: str, stage: str, *, scan_id: Optional[str] = None,
         symbol: Optional[str] = None, payload: Optional[Dict[str, Any]] = None,
         mode: str = "LIVE", run_id: Optional[str] = None) -> None:
    """Append one event. NEVER raises — pipeline safety first."""
    try:
        _emit_unsafe(event_type, stage, scan_id=scan_id, symbol=symbol,
                     payload=payload, mode=mode, run_id=run_id)
    except Exception:
        pass


def _emit_unsafe(event_type: str, stage: str, *, scan_id, symbol, payload,
                 mode, run_id) -> None:
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_events
                        (mode, run_id, scan_id, event_type, stage, symbol, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (mode, run_id, scan_id, event_type, stage.upper(),
                     (symbol or None), json.dumps(payload or {}, default=str)),
                )
            conn.commit()
        finally:
            conn.close()
        return

    # File fallback (dev/tests without DATABASE_URL)
    rows: List[Dict[str, Any]] = []
    try:
        with open(FALLBACK_FILE, "r") as f:
            rows = json.load(f)
    except Exception:
        rows = []
    next_id = (rows[-1]["id"] + 1) if rows else 1
    rows.append({
        "id": next_id, "ts": _now_iso(), "mode": mode, "run_id": run_id,
        "scan_id": scan_id, "event_type": event_type, "stage": stage.upper(),
        "symbol": symbol, "payload": payload or {},
    })
    rows = rows[-_FALLBACK_MAX:]
    tmp = FALLBACK_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rows, f, default=str)
    os.replace(tmp, FALLBACK_FILE)


def emit_many(events: List[Dict[str, Any]]) -> None:
    """
    Batch-append events (one connection / one commit). Each dict accepts the
    same keys as emit(): event_type, stage, scan_id, symbol, payload, mode,
    run_id. NEVER raises.
    """
    if not events:
        return
    try:
        if db_available():
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO pipeline_events
                            (mode, run_id, scan_id, event_type, stage, symbol, payload)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (e.get("mode", "LIVE"), e.get("run_id"),
                             e.get("scan_id"), e["event_type"],
                             str(e["stage"]).upper(), e.get("symbol") or None,
                             json.dumps(e.get("payload") or {}, default=str))
                            for e in events
                        ],
                    )
                conn.commit()
            finally:
                conn.close()
        else:
            for e in events:
                _emit_unsafe(e["event_type"], e["stage"],
                             scan_id=e.get("scan_id"), symbol=e.get("symbol"),
                             payload=e.get("payload"), mode=e.get("mode", "LIVE"),
                             run_id=e.get("run_id"))
    except Exception:
        pass


# ── Query ────────────────────────────────────────────────────────────────────

def _row_to_dict(r) -> Dict[str, Any]:
    payload = r[8]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    return {
        "id": r[0],
        "ts": r[1].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
              if hasattr(r[1], "strftime") else str(r[1]),
        "mode": r[2], "run_id": r[3], "scan_id": r[4],
        "event_type": r[5], "stage": r[6], "symbol": r[7],
        "payload": payload or {},
    }


def query_events(*, since_id: int = 0, scan_id: Optional[str] = None,
                 run_id: Optional[str] = None, mode: str = "LIVE",
                 event_type: Optional[str] = None, stage: Optional[str] = None,
                 symbol: Optional[str] = None, limit: int = 200,
                 newest_first: bool = False) -> List[Dict[str, Any]]:
    """Read events with filters. Returns [] on any failure (read-only view)."""
    limit = max(1, min(int(limit), 2000))
    try:
        if db_available():
            clauses, args = ["mode = %s"], [mode]
            if since_id:
                clauses.append("id > %s"); args.append(int(since_id))
            if scan_id:
                clauses.append("scan_id = %s"); args.append(scan_id)
            if run_id:
                clauses.append("run_id = %s"); args.append(run_id)
            if event_type:
                clauses.append("event_type = %s"); args.append(event_type)
            if stage:
                clauses.append("stage = %s"); args.append(stage.upper())
            if symbol:
                clauses.append("symbol = %s"); args.append(symbol.upper())
            order = "DESC" if newest_first else "ASC"
            sql = (
                "SELECT id, ts, mode, run_id, scan_id, event_type, stage, symbol, payload"
                f" FROM pipeline_events WHERE {' AND '.join(clauses)}"
                f" ORDER BY id {order} LIMIT %s"
            )
            args.append(limit)
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(sql, args)
                    return [_row_to_dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        with open(FALLBACK_FILE, "r") as f:
            rows = json.load(f)
        out = []
        for r in rows:
            if r.get("mode", "LIVE") != mode: continue
            if since_id and r["id"] <= since_id: continue
            if scan_id and r.get("scan_id") != scan_id: continue
            if run_id and r.get("run_id") != run_id: continue
            if event_type and r.get("event_type") != event_type: continue
            if stage and r.get("stage") != stage.upper(): continue
            if symbol and (r.get("symbol") or "").upper() != symbol.upper(): continue
            out.append(r)
        out.sort(key=lambda x: x["id"], reverse=newest_first)
        return out[:limit]
    except Exception:
        return []


# Explicit event-state semantics (review finding: no substring heuristics).
# COMPLETED = the stage successfully processed the item.
# REJECTED  = the stage explicitly declined/blocked/failed the item
#             (CANCELLED counts as rejected: the item did not proceed).
# Anything else (SCAN_STARTED, ORDER_SUBMITTED, SCAN_FETCH_COMPLETED …) is a
# lifecycle/progress marker: counted in `events` only.
COMPLETED_EVENT_TYPES = frozenset({
    "SYMBOL_SCANNED", "RESEARCH_COMPLETED", "MARKET_INTELLIGENCE_COMPLETED",
    "MONITORING_COMPLETED", "STRATEGY_SELECTED", "PRECHECK_APPROVED",
    "RISK_APPROVED",
    "BUY_GENERATED", "SELL_GENERATED", "WATCH_GENERATED", "IGNORE_GENERATED",
    "ORDER_EXECUTED", "POSITION_OPENED", "POSITION_UPDATED", "POSITION_CLOSED",
    "PORTFOLIO_UPDATED", "PNL_UPDATED", "SCAN_COMPLETED",
})
REJECTED_EVENT_TYPES = frozenset({
    "SYMBOL_REJECTED", "STRATEGY_REJECTED", "PRECHECK_REJECTED",
    "RISK_REJECTED",
    "ORDER_REJECTED", "ORDER_CANCELLED", "SCAN_FAILED",
})


def stage_summary(*, scan_id: Optional[str] = None, run_id: Optional[str] = None,
                  mode: str = "LIVE") -> Dict[str, Any]:
    """
    Per-stage counts derived purely from events: in/out/rejected + errors.
    This powers the Live Pipeline visual; identical numbers everywhere by
    construction because everything reads this one function.

    With Postgres the aggregation runs in SQL over ALL matching rows (no
    truncation). The file fallback aggregates in-process and sets
    `truncated` if the fallback file may have rolled over.
    """
    base = {
        s: {"stage": s, "events": 0, "completed": 0, "rejected": 0, "errors": 0,
            "last_ts": None, "last_symbol": None}
        for s in STAGES
    }
    total = 0
    truncated = False
    try:
        if db_available():
            clauses, args = ["mode = %s"], [mode]
            if scan_id:
                clauses.append("scan_id = %s"); args.append(scan_id)
            if run_id:
                clauses.append("run_id = %s"); args.append(run_id)
            where = " AND ".join(clauses)
            completed_list = list(COMPLETED_EVENT_TYPES)
            rejected_list = list(REJECTED_EVENT_TYPES)
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT stage,
                               COUNT(*) AS events,
                               COUNT(*) FILTER (WHERE event_type = ANY(%s)) AS completed,
                               COUNT(*) FILTER (WHERE event_type = ANY(%s)) AS rejected,
                               COUNT(*) FILTER (WHERE payload ? 'error'
                                                AND payload->>'error' IS NOT NULL
                                                AND payload->>'error' <> '') AS errors,
                               MAX(ts) AS last_ts
                        FROM pipeline_events WHERE {where}
                        GROUP BY stage
                        """,
                        [completed_list, rejected_list, *args],
                    )
                    for stage, events, completed, rejected, errors, last_ts in cur.fetchall():
                        st = base.get(stage)
                        if st is None:
                            continue
                        st.update(events=events, completed=completed,
                                  rejected=rejected, errors=errors,
                                  last_ts=last_ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                                  if hasattr(last_ts, "strftime") else str(last_ts))
                        total += events
                    # last_symbol per stage (latest non-null symbol)
                    cur.execute(
                        f"""
                        SELECT DISTINCT ON (stage) stage, symbol
                        FROM pipeline_events
                        WHERE {where} AND symbol IS NOT NULL
                        ORDER BY stage, id DESC
                        """,
                        args,
                    )
                    for stage, symbol in cur.fetchall():
                        if stage in base:
                            base[stage]["last_symbol"] = symbol
            finally:
                conn.close()
        else:
            events = query_events(scan_id=scan_id, run_id=run_id, mode=mode,
                                  limit=_FALLBACK_MAX)
            truncated = len(events) >= _FALLBACK_MAX
            total = len(events)
            for e in events:
                st = base.get(e["stage"])
                if st is None:
                    continue
                st["events"] += 1
                st["last_ts"] = e["ts"]
                if e.get("symbol"):
                    st["last_symbol"] = e["symbol"]
                et = e["event_type"]
                if et in REJECTED_EVENT_TYPES:
                    st["rejected"] += 1
                elif et in COMPLETED_EVENT_TYPES:
                    st["completed"] += 1
                if (e.get("payload") or {}).get("error"):
                    st["errors"] += 1
    except Exception:
        pass
    return {
        "scan_id": scan_id, "run_id": run_id, "mode": mode,
        "total_events": total,
        "truncated": truncated,
        "stages": [base[s] for s in STAGES],
        "generated_at": _now_iso(),
    }


# ── Retention ────────────────────────────────────────────────────────────────

RETENTION_DAYS = 14


def prune_events(days: int = RETENTION_DAYS) -> Dict[str, Any]:
    """
    Delete events older than `days` (indexed by ts). Called fail-safe after
    each scan completes, so the table stays bounded under continuous
    operation. NEVER raises.
    """
    try:
        if db_available():
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM pipeline_events"
                        " WHERE ts < NOW() - (%s || ' days')::interval",
                        (int(days),),
                    )
                    deleted = cur.rowcount
                conn.commit()
                return {"deleted": deleted, "days": days}
            finally:
                conn.close()
        # File fallback already caps itself at _FALLBACK_MAX rows.
        return {"deleted": 0, "days": days, "fallback": True}
    except Exception:
        return {"deleted": 0, "days": days, "error": True}


def latest_scan_id(mode: str = "LIVE") -> Optional[str]:
    """scan_id of the most recent SCAN_STARTED event in this mode."""
    ev = query_events(mode=mode, event_type="SCAN_STARTED", limit=1,
                      newest_first=True)
    return ev[0]["scan_id"] if ev else None
