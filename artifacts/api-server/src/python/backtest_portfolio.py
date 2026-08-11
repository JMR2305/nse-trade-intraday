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

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scan_state_store import _connect, db_available

_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNS_FILE = os.path.join(_DIR, "backtest_runs.json")
_TRADES_FILE = os.path.join(_DIR, "backtest_trades.json")

_SCHEMA_READY = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


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
                completed_at TIMESTAMPTZ
            )
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

def create_run(config: Dict[str, Any]) -> str:
    run_id = f"BT-{uuid.uuid4().hex[:10]}"
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO backtest_runs (run_id, status, config)"
                    " VALUES (%s, 'PENDING', %s)",
                    (run_id, json.dumps(config, default=str)),
                )
            conn.commit()
        finally:
            conn.close()
    else:
        rows = _load(_RUNS_FILE)
        rows.append({"run_id": run_id, "created_at": _now_iso(),
                     "status": "PENDING", "config": config, "progress": {},
                     "metrics": None, "missed": None, "validation": None,
                     "error": None, "started_at": None, "completed_at": None})
        _save(_RUNS_FILE, rows)
    return run_id


_JSON_FIELDS = {"config", "progress", "metrics", "missed", "validation"}
_TS_FIELDS = {"started_at", "completed_at"}


def update_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    if db_available():
        conn = _connect()
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
    rows = _load(_RUNS_FILE)
    for r in rows:
        if r["run_id"] == run_id:
            r.update(fields)
    _save(_RUNS_FILE, rows)


def claim_run(run_id: str) -> bool:
    """
    Atomically claim a PENDING run for execution (PENDING → RUNNING).
    Returns False when the run is not PENDING — a duplicate/retried
    backtest_exec must refuse to run so a run can never execute twice.
    """
    now = _now_iso()
    if db_available():
        conn = _connect()
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
             "started_at", "completed_at"]


def _run_row_to_dict(r) -> Dict[str, Any]:
    d = dict(zip(_RUN_COLS, r))
    for k in ("created_at", "started_at", "completed_at"):
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
        conn = _connect()
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
        conn = _connect()
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
        conn = _connect()
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
        conn = _connect()
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
        conn = _connect()
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
