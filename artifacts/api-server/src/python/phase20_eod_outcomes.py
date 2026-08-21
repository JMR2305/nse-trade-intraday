"""
phase20_eod_outcomes.py — Durable per-trade EOD outcome records.

Every automated EOD process (15:20 intraday squareoff, 15:30 POST_CLOSE
force-close, startup overnight-carry close) must call record_eod_outcome()
for every OPEN trade it evaluates. No silent skips are permitted.

Schema: phase20_eod_outcomes
  id              SERIAL PRIMARY KEY
  session_date    TEXT NOT NULL        — IST trading date (YYYY-MM-DD)
  trade_id        TEXT NOT NULL
  symbol          TEXT NOT NULL
  attempted_at    TEXT NOT NULL        — ISO UTC timestamp
  job_type        TEXT NOT NULL        — 15:20_squareoff | 15:30_force_close
                                         | startup_overnight_carry
  selected_outcome TEXT NOT NULL       — CLOSED | EXIT_PENDING | BLOCKED | ERROR
  exit_rule       TEXT
  exit_price      DOUBLE PRECISION
  exit_price_source TEXT
  realized_pnl    DOUBLE PRECISION
  reason          TEXT
  config_hash     TEXT
  build_id        TEXT
  process_id      TEXT
  correlation_id  TEXT
  error_detail    TEXT
  created_at      TEXT NOT NULL        — ISO UTC insert timestamp

PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_SCHEMA_READY = False


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_build_id() -> str:
    return str(os.environ.get("APEXQUANT_BUILD_ID") or "").strip() or "unknown"


def _get_process_id() -> str:
    import os as _os
    return str(_os.getpid())


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS phase20_eod_outcomes (
                id              SERIAL PRIMARY KEY,
                session_date    TEXT NOT NULL,
                trade_id        TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                attempted_at    TEXT NOT NULL,
                job_type        TEXT NOT NULL,
                selected_outcome TEXT NOT NULL,
                exit_rule       TEXT,
                exit_price      DOUBLE PRECISION,
                exit_price_source TEXT,
                realized_pnl    DOUBLE PRECISION,
                reason          TEXT,
                config_hash     TEXT,
                build_id        TEXT,
                process_id      TEXT,
                correlation_id  TEXT,
                error_detail    TEXT,
                created_at      TEXT NOT NULL
            )
            """
        )
        # Index for fast same-session queries
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_eod_outcomes_session
            ON phase20_eod_outcomes (session_date, trade_id)
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def record_eod_outcome(
    *,
    session_date: str,
    trade_id: str,
    symbol: str,
    job_type: str,
    selected_outcome: str,
    exit_rule: Optional[str] = None,
    exit_price: Optional[float] = None,
    exit_price_source: Optional[str] = None,
    realized_pnl: Optional[float] = None,
    reason: Optional[str] = None,
    config_hash: Optional[str] = None,
    error_detail: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a durable outcome record for one EOD-evaluated trade.

    Never raises. Returns {"ok": True} on success or {"ok": False, "error": ...}.
    Idempotent per (session_date, trade_id, job_type) — a second write for the
    same key is a no-op (ON CONFLICT DO NOTHING).
    """
    now = _now_utc_iso()
    corr = correlation_id or str(uuid.uuid4())[:8]
    bid = _get_build_id()
    pid = _get_process_id()

    try:
        from scan_state_store import db_available, _connect
        if not db_available():
            return {"ok": False, "error": "db_unavailable", "correlation_id": corr}
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phase20_eod_outcomes (
                        session_date, trade_id, symbol, attempted_at,
                        job_type, selected_outcome,
                        exit_rule, exit_price, exit_price_source, realized_pnl,
                        reason, config_hash, build_id, process_id,
                        correlation_id, error_detail, created_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        session_date, trade_id, symbol, now,
                        job_type, selected_outcome,
                        exit_rule, exit_price, exit_price_source, realized_pnl,
                        reason, config_hash, bid, pid,
                        corr, error_detail, now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "correlation_id": corr}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "correlation_id": corr}


def get_eod_outcomes(
    session_date: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Read EOD outcome records, newest first. Never raises."""
    try:
        from scan_state_store import db_available, _connect
        if not db_available():
            return []
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                if session_date:
                    cur.execute(
                        """
                        SELECT session_date, trade_id, symbol, attempted_at,
                               job_type, selected_outcome, exit_rule,
                               exit_price, exit_price_source, realized_pnl,
                               reason, config_hash, build_id, correlation_id,
                               error_detail, created_at
                        FROM phase20_eod_outcomes
                        WHERE session_date = %s
                        ORDER BY id DESC LIMIT %s
                        """,
                        (session_date, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT session_date, trade_id, symbol, attempted_at,
                               job_type, selected_outcome, exit_rule,
                               exit_price, exit_price_source, realized_pnl,
                               reason, config_hash, build_id, correlation_id,
                               error_detail, created_at
                        FROM phase20_eod_outcomes
                        ORDER BY id DESC LIMIT %s
                        """,
                        (limit,),
                    )
                cols = [
                    "session_date", "trade_id", "symbol", "attempted_at",
                    "job_type", "selected_outcome", "exit_rule",
                    "exit_price", "exit_price_source", "realized_pnl",
                    "reason", "config_hash", "build_id", "correlation_id",
                    "error_detail", "created_at",
                ]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        return []
