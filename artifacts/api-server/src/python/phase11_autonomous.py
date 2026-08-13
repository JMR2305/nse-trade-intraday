"""
phase11_autonomous.py — Phase 11: Autonomous Paper Trading Platform
Orchestration layer for portfolio dashboard, capital modes, recommendation
queue, session timeline, calendar view, replay mode, and reports.

PAPER ONLY — NO LIVE ORDERS — NO REAL MONEY
Starting capital: ₹50,000 (configurable).
Reuses Phase 20 execution infrastructure (paper_trades, paper_portfolio tables).
All outputs are advisory/display only — execution is handled by Phase 20.
"""
from __future__ import annotations

import json
import os
import math
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Constants ─────────────────────────────────────────────────────────────────

PHASE11_DEFAULT_CAPITAL    = 50_000.0   # ₹50,000 starting capital
PHASE11_TOPUP_THRESHOLD    = 10_000.0   # Mode B: top-up when cash < this
PHASE11_CAPITAL_MODE_KEY   = "phase11_capital_mode"        # "A" or "B"
PHASE11_STARTING_CAP_KEY   = "phase11_starting_capital"
PHASE11_TOPUP_THRESH_KEY   = "phase11_topup_threshold"
PHASE11_TOPUP_TARGET_KEY   = "phase11_topup_target"
ADVISORY_ONLY              = True
PAPER_ONLY                 = True

# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_available() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_topup_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phase11_capital_topups (
                id          SERIAL PRIMARY KEY,
                amount      DOUBLE PRECISION NOT NULL,
                before_cash DOUBLE PRECISION NOT NULL,
                after_cash  DOUBLE PRECISION NOT NULL,
                reason      TEXT NOT NULL DEFAULT '',
                mode        TEXT NOT NULL DEFAULT 'B',
                ts          TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    conn.commit()


def _ensure_price_snapshots_table(conn) -> None:
    """
    Ensure the intraday price snapshot table and indexes exist.

    Idempotency guarantee:
      A PARTIAL unique index on (scan_id, symbol) WHERE scan_id != ''
      lets the INSERT use ON CONFLICT … DO NOTHING, making concurrent
      recording calls race-safe at the database level.  Rows recorded
      without a scan_id (empty string) are unconstrained — they represent
      manual / ad-hoc snapshots and may legitimately repeat.
    """
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phase11_price_snapshots (
                id          SERIAL PRIMARY KEY,
                symbol      TEXT NOT NULL,
                price       DOUBLE PRECISION NOT NULL,
                scan_id     TEXT NOT NULL DEFAULT '',
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        # Fast lookup by symbol + date (read path)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_phase11_price_snaps_sym_ts
            ON phase11_price_snapshots (symbol, recorded_at DESC)
        """)
        # Partial unique index — enforces one row per (scan_id, symbol)
        # for scans that supply a non-empty scan_id.  This is the key
        # constraint that makes ON CONFLICT DO NOTHING race-safe.
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uidx_phase11_price_snaps_scan_sym
            ON phase11_price_snapshots (scan_id, symbol)
            WHERE scan_id != ''
        """)
    conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ist_today() -> str:
    """Return today's date in IST (UTC+5:30) as YYYY-MM-DD."""
    from datetime import timezone as tz
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:
        logger.debug("phase11 safe call failed: %s", exc)
        return default


# ── Capital Mode Management ───────────────────────────────────────────────────

def get_capital_config() -> Dict[str, Any]:
    """Return current capital mode configuration."""
    try:
        from phase20_store import kv_get
        mode       = kv_get(PHASE11_CAPITAL_MODE_KEY, "A")
        starting   = float(kv_get(PHASE11_STARTING_CAP_KEY, PHASE11_DEFAULT_CAPITAL))
        threshold  = float(kv_get(PHASE11_TOPUP_THRESH_KEY, PHASE11_TOPUP_THRESHOLD))
        target     = float(kv_get(PHASE11_TOPUP_TARGET_KEY, starting))
    except Exception:
        mode, starting, threshold, target = "A", PHASE11_DEFAULT_CAPITAL, PHASE11_TOPUP_THRESHOLD, PHASE11_DEFAULT_CAPITAL
    return {
        "mode": mode,
        "mode_label": "Evaluation (fixed capital)" if mode == "A" else "Continuous Research (auto top-up)",
        "starting_capital": starting,
        "topup_threshold": threshold,
        "topup_target": target,
        "advisory_only": ADVISORY_ONLY,
        "paper_only": PAPER_ONLY,
    }


def update_capital_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Update capital mode settings."""
    from phase20_store import kv_set
    if "mode" in patch:
        mode = str(patch["mode"]).upper()
        if mode not in ("A", "B"):
            raise ValueError("mode must be 'A' or 'B'")
        kv_set(PHASE11_CAPITAL_MODE_KEY, mode)
    if "starting_capital" in patch:
        val = float(patch["starting_capital"])
        if val < 1000:
            raise ValueError("starting_capital must be ≥ 1000")
        kv_set(PHASE11_STARTING_CAP_KEY, val)
    if "topup_threshold" in patch:
        kv_set(PHASE11_TOPUP_THRESH_KEY, float(patch["topup_threshold"]))
    if "topup_target" in patch:
        kv_set(PHASE11_TOPUP_TARGET_KEY, float(patch["topup_target"]))
    return get_capital_config()


def get_topup_log(limit: int = 50) -> List[Dict[str, Any]]:
    """Return capital top-up history."""
    if not _db_available():
        return []
    try:
        conn = _connect()
        try:
            _ensure_topup_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, amount, before_cash, after_cash, reason, mode, ts "
                    "FROM phase11_capital_topups ORDER BY ts DESC LIMIT %s",
                    (limit,)
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [
            {
                "id": r[0], "amount": r[1], "before_cash": r[2],
                "after_cash": r[3], "reason": r[4], "mode": r[5],
                "ts": r[6].strftime("%Y-%m-%dT%H:%M:%SZ") if r[6] else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("get_topup_log failed: %s", exc)
        return []


def record_topup(amount: float, before_cash: float, after_cash: float,
                 reason: str, mode: str = "B") -> None:
    """Persist a capital top-up event."""
    if not _db_available():
        return
    conn = _connect()
    try:
        _ensure_topup_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO phase11_capital_topups "
                "(amount, before_cash, after_cash, reason, mode) "
                "VALUES (%s, %s, %s, %s, %s)",
                (amount, before_cash, after_cash, reason, mode)
            )
        conn.commit()
    finally:
        conn.close()


def check_and_apply_topup() -> Optional[Dict[str, Any]]:
    """
    Mode B: if current cash < topup_threshold, top up to topup_target.
    Records the event. Returns topup dict if applied, else None.
    ADVISORY — applies to portfolio cash tracking only.
    """
    cfg = get_capital_config()
    if cfg["mode"] != "B":
        return None
    try:
        from portfolio_store import load_state
        state = load_state()
        cash = float(state.get("cash", 0))
        threshold = cfg["topup_threshold"]
        target    = cfg["topup_target"]
        if cash >= threshold:
            return None
        topup_amount = target - cash
        if topup_amount <= 0:
            return None
        # Apply top-up by saving updated cash
        from portfolio_store import save_state as _save_state, load_state as _load_for_topup
        _state = _load_for_topup()
        new_cash = cash + topup_amount
        _state["cash"] = new_cash
        _save_state(_state)
        reason = (f"Mode B auto top-up: cash ₹{cash:,.0f} fell below "
                  f"threshold ₹{threshold:,.0f}. Added ₹{topup_amount:,.0f}.")
        record_topup(topup_amount, cash, new_cash, reason, "B")
        return {
            "applied": True, "amount": topup_amount,
            "before_cash": cash, "after_cash": new_cash,
            "reason": reason, "ts": _now_iso(),
        }
    except Exception as exc:
        logger.warning("check_and_apply_topup failed: %s", exc)
        return None


# ── Portfolio Summary ─────────────────────────────────────────────────────────

def get_phase11_portfolio() -> Dict[str, Any]:
    """
    Full portfolio summary matching Phase 11 spec:
    Cash, Invested Amount, Buying Power, Current Value, Realised P/L,
    Unrealised P/L, Portfolio Return, Drawdown, Capital Mode.
    """
    cfg = get_capital_config()
    starting_capital = cfg["starting_capital"]

    # Canonical portfolio (phase20 ledger) — single source of truth for
    # positions, cash, realized and unrealized P&L across every page.
    from canonical_portfolio import build_canonical_portfolio
    canon = build_canonical_portfolio()

    cash           = float(canon["cash"])
    invested       = float(canon["invested_value"])
    unrealised_pnl = float(canon["unrealized_pnl"] or 0.0)
    realised_pnl   = float(canon["realized_pnl"] or 0.0)
    open_count     = int(canon["open_position_count"])
    starting_capital = float(canon["initial_capital"] or starting_capital)
    current_value  = float(canon["equity"])

    # Legacy state is retained only for pnl_history charting + daily_pnl memo.
    try:
        from portfolio_store import load_state
        state = load_state() or {}
    except Exception:
        state = {}

    portfolio_value   = current_value
    portfolio_return  = ((portfolio_value - starting_capital) / starting_capital * 100) if starting_capital > 0 else 0.0
    pnl_history       = state.get("pnl_history", [])
    peak_value        = max((float(p.get("value", portfolio_value)) for p in pnl_history if isinstance(p, dict)), default=portfolio_value)
    drawdown          = ((peak_value - portfolio_value) / peak_value * 100) if peak_value > 0 else 0.0
    daily_pnl         = float(state.get("daily_pnl", 0))
    daily_return      = (daily_pnl / starting_capital * 100) if starting_capital > 0 else 0.0
    buying_power      = max(0.0, cash)

    return {
        "starting_capital":  starting_capital,
        "cash":              cash,
        "invested_amount":   invested,
        "buying_power":      buying_power,
        "current_value":     portfolio_value,
        "realised_pnl":      realised_pnl,
        "unrealised_pnl":    unrealised_pnl,
        "total_pnl":         realised_pnl + unrealised_pnl,
        "portfolio_return":  portfolio_return,
        "daily_pnl":         daily_pnl,
        "daily_return":      daily_return,
        "drawdown_pct":      drawdown,
        "open_positions":    open_count,
        "capital_mode":      cfg["mode"],
        "capital_mode_label": cfg["mode_label"],
        "paper_only":        PAPER_ONLY,
        "advisory_only":     ADVISORY_ONLY,
        "as_of":             _now_iso(),
    }


def get_open_positions_detail() -> List[Dict[str, Any]]:
    """
    Enhanced open positions with all Phase 11 spec fields:
    Stock, Buy Time, Buy Price, Current Price, Quantity, Current Value,
    Current P/L, Current %, AI Confidence, Expected Return, Target,
    Stop Loss, Strategy, Market Regime, Risk Level, Holding Duration.
    """
    # Canonical positions (phase20 ledger) adapted to the legacy field names.
    try:
        from canonical_portfolio import build_canonical_portfolio
        canon_positions = build_canonical_portfolio()["positions"]
    except Exception:
        return []

    if not canon_positions:
        return []

    # Try to get regime from latest scan
    regime = _safe(lambda: _get_current_regime(), "UNKNOWN")

    result = []
    now_ts = datetime.now(timezone.utc)

    for pos in canon_positions:
        sym          = pos.get("symbol")
        qty          = int(pos.get("quantity") or 0)
        if qty <= 0:
            continue
        avg_price    = float(pos.get("avg_price") or 0.0)
        mark         = pos.get("mark_price")
        current_price= float(mark) if mark is not None else avg_price
        stop_loss    = float(pos.get("stop_loss") or avg_price * 0.97)
        target       = float(pos.get("target") or avg_price * 1.06)
        buy_ts       = pos.get("opened_at") or ""
        strategy     = pos.get("strategy_id") or "UNKNOWN"
        confidence   = 0.0
        risk_level   = "MEDIUM"
        exp_return   = None

        cost_basis   = qty * avg_price
        cur_val      = float(pos.get("market_value") or qty * current_price)
        pnl          = (float(pos["unrealized_pnl"])
                        if pos.get("unrealized_pnl") is not None
                        else cur_val - cost_basis)
        pnl_pct      = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0

        # Holding duration
        holding_mins = 0
        if buy_ts:
            try:
                bt = datetime.fromisoformat(str(buy_ts).replace("Z", "+00:00"))
                holding_mins = int((now_ts - bt).total_seconds() / 60)
            except Exception:
                pass

        # Current expected return (live price vs target)
        cur_exp_return = ((target - current_price) / current_price * 100) if current_price > 0 else 0.0

        result.append({
            "stock":                  sym,
            "buy_time":               buy_ts,
            "buy_price":              avg_price,
            "current_price":          current_price,
            "quantity":               qty,
            "current_value":          cur_val,
            "current_pnl":            pnl,
            "current_pnl_pct":        pnl_pct,
            "ai_confidence":          confidence,
            "expected_return_entry":  exp_return if exp_return is not None else cur_exp_return,
            "expected_return_current": cur_exp_return,
            "target":                 target,
            "stop_loss":              stop_loss,
            "strategy":               strategy,
            "market_regime":          regime,
            "risk_level":             risk_level,
            "holding_mins":           holding_mins,
            "holding_label":          _fmt_holding(holding_mins),
        })

    result.sort(key=lambda x: x["current_pnl_pct"], reverse=True)
    return result


def get_closed_positions_detail(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Enhanced closed positions with all Phase 11 spec fields:
    Buy Time, Sell Time, Entry Price, Exit Price, Quantity,
    Profit/Loss, Profit %, Holding Period, Exit Reason,
    AI Confidence, Strategy, Lesson Learned.
    """
    try:
        from portfolio_store import load_state
        state = load_state()
        trades = state.get("trades", [])
    except Exception:
        trades = []

    # Also pull from phase20 ledger if available
    phase20_trades = _safe(lambda: _get_phase20_closed_trades(limit), [])
    if phase20_trades:
        trades = phase20_trades

    closed = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        action = t.get("action", "").upper()
        if action not in ("SELL", "EXIT", "CLOSE", "PARTIAL_EXIT"):
            continue

        symbol      = t.get("symbol", t.get("stock", ""))
        entry_price = float(t.get("entry_price", t.get("buy_price", 0)) or 0)
        exit_price  = float(t.get("price", t.get("exit_price", 0)) or 0)
        qty         = int(t.get("quantity", t.get("qty", 0)) or 0)
        pnl         = float(t.get("pnl", t.get("profit", 0)) or 0)
        pnl_pct     = float(t.get("pnl_pct", t.get("profit_pct", 0)) or 0)
        if pnl_pct == 0 and entry_price > 0 and exit_price > 0:
            pnl_pct = (exit_price - entry_price) / entry_price * 100

        buy_ts      = t.get("buy_ts", t.get("entry_time", ""))
        sell_ts     = t.get("trade_ts", t.get("sell_ts", t.get("exit_time", "")))
        holding_mins= _calc_holding_mins(buy_ts, sell_ts)
        exit_reason = t.get("reason", t.get("exit_reason", "MANUAL"))
        confidence  = float(t.get("confidence", t.get("ai_confidence", 0)) or 0)
        strategy    = t.get("strategy", t.get("strategy_name", "UNKNOWN"))
        lesson      = t.get("lesson_learned", t.get("lesson", ""))
        if not lesson and pnl < 0:
            lesson = f"Loss of ₹{abs(pnl):,.0f} ({abs(pnl_pct):.1f}%). Review stop-loss adherence."

        closed.append({
            "symbol":           symbol,
            "buy_time":         buy_ts,
            "sell_time":        sell_ts,
            "entry_price":      entry_price,
            "exit_price":       exit_price,
            "quantity":         qty,
            "pnl":              pnl,
            "pnl_pct":          pnl_pct,
            "holding_label":    _fmt_holding(holding_mins),
            "holding_mins":     holding_mins,
            "exit_reason":      exit_reason,
            "ai_confidence":    confidence,
            "strategy":         strategy,
            "lesson_learned":   lesson,
        })

    closed.sort(key=lambda x: x.get("sell_time", "") or "", reverse=True)
    return closed[:limit]


# ── Recommendation Queue ──────────────────────────────────────────────────────

def get_recommendation_queue() -> Dict[str, Any]:
    """
    Pending opportunities from the latest scan / AI decisions.
    Fields: Stock, Confidence, Risk, Expected Return, Estimated Holding Period,
    Entry, Stop Loss, Target, Reasoning.
    """
    items = []

    # Primary: pull from AI decisions
    items = _safe(lambda: _get_ai_decision_recs(), []) or []

    # Fallback: scan signals
    if not items:
        items = _safe(lambda: _get_scan_signal_recs(), []) or []

    # Filter: only BUY / STRONG BUY
    items = [i for i in items if i.get("action", "").upper() in
             ("BUY", "STRONG BUY", "STRONG_BUY")]

    # Sort by confidence desc
    items.sort(key=lambda x: float(x.get("confidence", 0)), reverse=True)

    # ── Session-date gate ──────────────────────────────────────────────────
    # When the latest scan is from a previous trading day, the recommendation
    # queue must be cleared so yesterday's BUY items don't appear as active.
    _is_today_session = True
    try:
        from phase15_scan_context import build_scan_context as _bsc
        _sc = _bsc()
        _is_today_session = bool(_sc.get("is_today_session", True))
    except Exception:
        pass

    if not _is_today_session:
        return {
            "items":         [],
            "count":         0,
            "advisory_only": ADVISORY_ONLY,
            "paper_only":    PAPER_ONLY,
            "as_of":         _now_iso(),
            "session_mismatch": True,
        }

    return {
        "items":         items,
        "count":         len(items),
        "advisory_only": ADVISORY_ONLY,
        "paper_only":    PAPER_ONLY,
        "as_of":         _now_iso(),
    }


# ── Session Timeline ──────────────────────────────────────────────────────────

def get_session_timeline(session_date: Optional[str] = None,
                         limit: int = 200) -> Dict[str, Any]:
    """
    Chronological trading timeline for a given session date.
    If date is None, uses today (IST).
    Events: MARKET_OPEN, SCAN, BUY, SELL, PARTIAL_EXIT, CONFIDENCE_CHANGE,
    TARGET_UPDATE, STOP_UPDATE, MARKET_CLOSE, LEARNING.
    """
    if not session_date:
        session_date = _ist_today()

    events: List[Dict[str, Any]] = []

    # Standard market milestones
    events += _market_milestones(session_date)

    # Trade events from paper_trades
    events += _safe(lambda: _trade_events(session_date), []) or []

    # Scan events from phase20 notifications
    events += _safe(lambda: _notification_events(session_date), []) or []

    # Sort chronologically
    events.sort(key=lambda x: x.get("ts", ""))

    return {
        "session_date":  session_date,
        "events":        events[:limit],
        "event_count":   len(events),
        "advisory_only": ADVISORY_ONLY,
        "paper_only":    PAPER_ONLY,
    }


# ── Calendar / Daily Summary ──────────────────────────────────────────────────

def get_calendar_data(year: Optional[int] = None, month: Optional[int] = None) -> Dict[str, Any]:
    """
    Calendar view: for each trading day show trade count, P/L, and outcome.
    """
    now = datetime.now(timezone.utc)
    if not year:
        year  = now.year
    if not month:
        month = now.month

    start_date = date(year, month, 1)
    # end of month
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    days_data = {}
    trades = _safe(lambda: _all_trades_in_range(
        start_date.isoformat(), end_date.isoformat()), []) or []

    for t in trades:
        ts_str = t.get("trade_ts", t.get("sell_ts", t.get("buy_ts", "")))
        if not ts_str:
            continue
        try:
            d = ts_str[:10]
        except Exception:
            continue
        if d not in days_data:
            days_data[d] = {"trade_count": 0, "pnl": 0.0, "wins": 0, "losses": 0}
        days_data[d]["trade_count"] += 1
        pnl = float(t.get("pnl", 0) or 0)
        days_data[d]["pnl"] += pnl
        if pnl > 0:
            days_data[d]["wins"] += 1
        elif pnl < 0:
            days_data[d]["losses"] += 1

    # Build calendar array
    days = []
    cur = start_date
    while cur <= end_date:
        ds = cur.isoformat()
        day_info = days_data.get(ds, {})
        days.append({
            "date":        ds,
            "weekday":     cur.weekday(),
            "has_trades":  ds in days_data,
            "trade_count": day_info.get("trade_count", 0),
            "pnl":         day_info.get("pnl", 0.0),
            "wins":        day_info.get("wins", 0),
            "losses":      day_info.get("losses", 0),
            "outcome":     ("WIN" if day_info.get("pnl", 0) > 0 else
                            "LOSS" if day_info.get("pnl", 0) < 0 else
                            "NEUTRAL") if ds in days_data else None,
        })
        cur += timedelta(days=1)

    return {
        "year":          year,
        "month":         month,
        "days":          days,
        "trading_days":  sum(1 for d in days if d["has_trades"]),
        "total_pnl":     sum(d["pnl"] for d in days),
        "total_trades":  sum(d["trade_count"] for d in days),
        "advisory_only": ADVISORY_ONLY,
    }


def get_daily_summary(trade_date: str) -> Dict[str, Any]:
    """
    Full data for a specific date (calendar drill-down):
    Market summary, portfolio snapshot, open positions, closed positions,
    timeline, learning insights, charts data.
    """
    trades = _safe(lambda: _all_trades_in_range(trade_date, trade_date), []) or []
    closed = [t for t in trades if t.get("action", "").upper() in
              ("SELL", "EXIT", "CLOSE", "PARTIAL_EXIT")]
    opened = [t for t in trades if t.get("action", "").upper() in ("BUY", "ADD")]

    total_pnl = sum(float(t.get("pnl", 0) or 0) for t in closed)
    wins      = sum(1 for t in closed if float(t.get("pnl", 0) or 0) > 0)
    losses    = sum(1 for t in closed if float(t.get("pnl", 0) or 0) < 0)
    win_rate  = (wins / len(closed) * 100) if closed else 0.0
    avg_conf  = (sum(float(t.get("confidence", 0) or 0) for t in trades) /
                 len(trades)) if trades else 0.0

    best_trade  = max(closed, key=lambda x: float(x.get("pnl", 0) or 0), default=None)
    worst_trade = min(closed, key=lambda x: float(x.get("pnl", 0) or 0), default=None)

    timeline = _safe(lambda: get_session_timeline(trade_date), {})

    market_summary = _safe(lambda: _get_market_summary(trade_date), {})

    return {
        "date":              trade_date,
        "summary": {
            "total_trades":   len(trades),
            "opened":         len(opened),
            "closed":         len(closed),
            "total_pnl":      total_pnl,
            "wins":           wins,
            "losses":         losses,
            "win_rate":       win_rate,
            "avg_confidence": avg_conf,
        },
        "market_summary":    market_summary,
        "closed_trades":     _enrich_closed(closed),
        "best_trade":        _trade_brief(best_trade),
        "worst_trade":       _trade_brief(worst_trade),
        "timeline":          timeline.get("events", []),
        "learning":          _safe(lambda: _get_learning_for_date(trade_date), {}),
        "advisory_only":     ADVISORY_ONLY,
        "paper_only":        PAPER_ONLY,
    }


# ── Replay Mode ───────────────────────────────────────────────────────────────

def get_replay_data(trade_date: str) -> Dict[str, Any]:
    """
    Full session replay for a date.
    Returns chronological events with portfolio state at each step.
    """
    trades  = _safe(lambda: _all_trades_in_range(trade_date, trade_date), []) or []
    timeline = _safe(lambda: get_session_timeline(trade_date), {})
    events   = timeline.get("events", [])

    # Build portfolio state snapshots
    cfg = get_capital_config()
    cash = cfg["starting_capital"]
    positions: Dict[str, Dict] = {}
    snapshots = []
    total_pnl = 0.0

    # Sort trades by timestamp
    sorted_trades = sorted(trades, key=lambda x: x.get("trade_ts", "") or "")

    for t in sorted_trades:
        action = t.get("action", "").upper()
        sym    = t.get("symbol", "")
        price  = float(t.get("price", 0) or 0)
        qty    = int(t.get("quantity", t.get("qty", 0)) or 0)
        pnl    = float(t.get("pnl", 0) or 0)

        if action in ("BUY", "ADD") and sym and qty > 0 and price > 0:
            cost = qty * price
            cash -= cost
            if sym in positions:
                old = positions[sym]
                total_qty = old["qty"] + qty
                positions[sym] = {
                    "qty": total_qty,
                    "avg_price": (old["qty"] * old["avg_price"] + qty * price) / total_qty,
                    "current_price": price,
                }
            else:
                positions[sym] = {"qty": qty, "avg_price": price, "current_price": price}
        elif action in ("SELL", "EXIT", "CLOSE", "PARTIAL_EXIT") and sym and qty > 0 and price > 0:
            proceeds = qty * price
            cash += proceeds + pnl  # pnl already baked in by most implementations
            total_pnl += pnl
            if sym in positions:
                remaining = positions[sym]["qty"] - qty
                if remaining <= 0:
                    del positions[sym]
                else:
                    positions[sym]["qty"] = remaining

        invested = sum(p["qty"] * p["avg_price"] for p in positions.values())
        portfolio_value = cash + invested

        snapshots.append({
            "ts":              t.get("trade_ts", ""),
            "action":          action,
            "symbol":          sym,
            "quantity":        qty,
            "price":           price,
            "pnl":             pnl,
            "cash":            cash,
            "invested":        invested,
            "portfolio_value": portfolio_value,
            "open_positions":  len(positions),
            "cumulative_pnl":  total_pnl,
        })

    # AI decisions for this date
    ai_decisions = _safe(lambda: _get_ai_decisions_for_date(trade_date), []) or []

    return {
        "date":            trade_date,
        "events":          events,
        "trade_snapshots": snapshots,
        "final_pnl":       total_pnl,
        "trade_count":     len(sorted_trades),
        "ai_decisions":    ai_decisions,
        "advisory_only":   ADVISORY_ONLY,
        "paper_only":      PAPER_ONLY,
    }


# ── Reports ───────────────────────────────────────────────────────────────────

def generate_daily_report(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """Generate a daily P/L and performance report."""
    if not trade_date:
        trade_date = _ist_today()
    summary = get_daily_summary(trade_date)
    cfg     = get_capital_config()
    topups  = [t for t in get_topup_log() if (t.get("ts", "") or "")[:10] == trade_date]

    s = summary["summary"]
    return {
        "report_type":    "DAILY",
        "date":           trade_date,
        "capital_mode":   cfg["mode"],
        "starting_capital": cfg["starting_capital"],
        "trades":         s["total_trades"],
        "closed_trades":  s["closed"],
        "pnl":            s["total_pnl"],
        "win_rate":       s["win_rate"],
        "avg_confidence": s["avg_confidence"],
        "best_trade":     summary.get("best_trade"),
        "worst_trade":    summary.get("worst_trade"),
        "closed_detail":  summary.get("closed_trades", []),
        "top_up_events":  topups,
        "learning":       summary.get("learning", {}),
        "market_summary": summary.get("market_summary", {}),
        "generated_at":   _now_iso(),
        "advisory_only":  ADVISORY_ONLY,
        "paper_only":     PAPER_ONLY,
    }


def generate_weekly_report(week_start: Optional[str] = None) -> Dict[str, Any]:
    """Generate a weekly report covering Mon–Fri."""
    if week_start:
        start = date.fromisoformat(week_start)
    else:
        today = date.today()
        start = today - timedelta(days=today.weekday())  # Monday
    end = start + timedelta(days=4)  # Friday

    trades = _safe(lambda: _all_trades_in_range(start.isoformat(), end.isoformat()), []) or []
    closed = [t for t in trades if t.get("action", "").upper() in
              ("SELL", "EXIT", "CLOSE", "PARTIAL_EXIT")]
    opened = [t for t in trades if t.get("action", "").upper() in ("BUY", "ADD")]

    total_pnl = sum(float(t.get("pnl", 0) or 0) for t in closed)
    wins      = sum(1 for t in closed if float(t.get("pnl", 0) or 0) > 0)
    losses    = len(closed) - wins
    win_rate  = (wins / len(closed) * 100) if closed else 0.0

    # By strategy
    strategy_pnl: Dict[str, float] = {}
    for t in closed:
        strat = t.get("strategy", "UNKNOWN")
        strategy_pnl[strat] = strategy_pnl.get(strat, 0.0) + float(t.get("pnl", 0) or 0)
    best_strategy  = max(strategy_pnl, key=strategy_pnl.get, default=None) if strategy_pnl else None
    worst_strategy = min(strategy_pnl, key=strategy_pnl.get, default=None) if strategy_pnl else None

    # Daily breakdown
    days = {}
    for t in closed:
        d = (t.get("trade_ts", "") or "")[:10]
        if d:
            days.setdefault(d, {"pnl": 0.0, "trades": 0})
            days[d]["pnl"]    += float(t.get("pnl", 0) or 0)
            days[d]["trades"] += 1

    topups = [t for t in get_topup_log()
              if start.isoformat() <= (t.get("ts", "") or "")[:10] <= end.isoformat()]

    return {
        "report_type":    "WEEKLY",
        "week_start":     start.isoformat(),
        "week_end":       end.isoformat(),
        "total_trades":   len(trades),
        "closed_trades":  len(closed),
        "opened_trades":  len(opened),
        "total_pnl":      total_pnl,
        "wins":           wins,
        "losses":         losses,
        "win_rate":       win_rate,
        "best_strategy":  best_strategy,
        "worst_strategy": worst_strategy,
        "strategy_pnl":   strategy_pnl,
        "daily_breakdown": days,
        "top_up_events":  topups,
        "generated_at":   _now_iso(),
        "advisory_only":  ADVISORY_ONLY,
        "paper_only":     PAPER_ONLY,
    }


def generate_monthly_report(year: Optional[int] = None,
                             month: Optional[int] = None) -> Dict[str, Any]:
    """Generate a monthly report."""
    now = datetime.now(timezone.utc)
    if not year:
        year  = now.year
    if not month:
        month = now.month

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    trades = _safe(lambda: _all_trades_in_range(start.isoformat(), end.isoformat()), []) or []
    closed = [t for t in trades if t.get("action", "").upper() in
              ("SELL", "EXIT", "CLOSE", "PARTIAL_EXIT")]

    total_pnl  = sum(float(t.get("pnl", 0) or 0) for t in closed)
    wins       = sum(1 for t in closed if float(t.get("pnl", 0) or 0) > 0)
    losses     = len(closed) - wins
    win_rate   = (wins / len(closed) * 100) if closed else 0.0
    avg_conf   = (sum(float(t.get("confidence", 0) or 0) for t in trades) /
                  len(trades)) if trades else 0.0

    # Profit factor
    gross_wins   = sum(float(t.get("pnl", 0) or 0) for t in closed if float(t.get("pnl", 0) or 0) > 0)
    gross_losses = abs(sum(float(t.get("pnl", 0) or 0) for t in closed if float(t.get("pnl", 0) or 0) < 0))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (float("inf") if gross_wins > 0 else 0.0)

    cfg        = get_capital_config()
    topups     = [t for t in get_topup_log()
                  if start.isoformat() <= (t.get("ts", "") or "")[:10] <= end.isoformat()]
    total_topup = sum(float(t["amount"]) for t in topups)
    capital_end = cfg["starting_capital"] + total_pnl  # approximate

    calendar = get_calendar_data(year, month)

    return {
        "report_type":      "MONTHLY",
        "year":             year,
        "month":            month,
        "month_label":      start.strftime("%B %Y"),
        "starting_capital": cfg["starting_capital"],
        "capital_mode":     cfg["mode"],
        "total_trades":     len(trades),
        "closed_trades":    len(closed),
        "total_pnl":        total_pnl,
        "wins":             wins,
        "losses":           losses,
        "win_rate":         win_rate,
        "avg_confidence":   avg_conf,
        "profit_factor":    profit_factor,
        "top_up_count":     len(topups),
        "total_topup":      total_topup,
        "capital_end":      capital_end,
        "calendar":         calendar.get("days", []),
        "generated_at":     _now_iso(),
        "advisory_only":    ADVISORY_ONLY,
        "paper_only":       PAPER_ONLY,
    }


# ── AI Performance ────────────────────────────────────────────────────────────

def get_ai_performance_metrics() -> Dict[str, Any]:
    """
    AI Performance summary: Trades Analysed, Executed, Win Rate,
    Average Gain/Loss, Profit Factor, Recommendation Accuracy,
    Average Confidence, Average Holding Time, Best/Worst Strategy.
    """
    try:
        from paper_analytics.shared_services import get_paper_analytics_snapshot
        snap = get_paper_analytics_snapshot()
    except Exception:
        snap = {}

    # Pull from portfolio store for raw numbers
    try:
        from portfolio_store import load_state
        state = load_state()
        trades = state.get("trades", [])
    except Exception:
        trades = []

    closed = [t for t in trades if isinstance(t, dict) and
              t.get("action", "").upper() in ("SELL", "EXIT", "CLOSE", "PARTIAL_EXIT")]

    wins   = [t for t in closed if float(t.get("pnl", 0) or 0) > 0]
    losses = [t for t in closed if float(t.get("pnl", 0) or 0) < 0]

    avg_gain = (sum(float(t.get("pnl", 0) or 0) for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(float(t.get("pnl", 0) or 0) for t in losses) / len(losses)) if losses else 0.0
    gross_win  = sum(float(t.get("pnl", 0) or 0) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl", 0) or 0) for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    win_rate = (len(wins) / len(closed) * 100) if closed else 0.0
    avg_conf = (sum(float(t.get("confidence", 0) or 0) for t in trades) /
                len(trades)) if trades else 0.0

    # Average holding time (minutes)
    holding_times = []
    for t in closed:
        buy_ts  = t.get("buy_ts", t.get("entry_time", ""))
        sell_ts = t.get("trade_ts", t.get("sell_ts", t.get("exit_time", "")))
        mins = _calc_holding_mins(buy_ts, sell_ts)
        if mins > 0:
            holding_times.append(mins)
    avg_holding_mins = (sum(holding_times) / len(holding_times)) if holding_times else 0

    # Best / worst strategy by average P/L
    strategy_data: Dict[str, List[float]] = {}
    for t in closed:
        strat = t.get("strategy", "UNKNOWN") or "UNKNOWN"
        strategy_data.setdefault(strat, [])
        strategy_data[strat].append(float(t.get("pnl", 0) or 0))
    strategy_avg = {s: sum(v) / len(v) for s, v in strategy_data.items() if v}
    best_strategy  = max(strategy_avg, key=strategy_avg.get, default=None) if strategy_avg else None
    worst_strategy = min(strategy_avg, key=strategy_avg.get, default=None) if strategy_avg else None

    # Recommendation accuracy: proportion of BUY recs that became profitable closed trades
    rec_accuracy = float(snap.get("recommendation_accuracy", win_rate))

    return {
        "trades_analysed":       len(trades),
        "trades_executed":       len(closed) + len([t for t in trades if t.get("action", "").upper() in ("BUY", "ADD")]),
        "closed_trades":         len(closed),
        "win_rate":              win_rate,
        "avg_gain":              avg_gain,
        "avg_loss":              avg_loss,
        "profit_factor":         round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
        "recommendation_accuracy": rec_accuracy,
        "avg_confidence":        avg_conf,
        "avg_holding_mins":      avg_holding_mins,
        "avg_holding_label":     _fmt_holding(int(avg_holding_mins)),
        "best_strategy":         best_strategy,
        "worst_strategy":        worst_strategy,
        "strategy_breakdown":    strategy_avg,
        "advisory_only":         ADVISORY_ONLY,
        "as_of":                 _now_iso(),
    }


# ── Learning Summary ──────────────────────────────────────────────────────────

def get_learning_summary() -> Dict[str, Any]:
    """
    Generate: Best Trade, Worst Trade, Most Reliable Strategy,
    Common Mistakes, Tomorrow's Watchlist, Tomorrow's Risks, Lessons Learned.
    """
    try:
        from paper_analytics.shared_services import get_paper_analytics_snapshot
        snap = get_paper_analytics_snapshot()
    except Exception:
        snap = {}

    try:
        from portfolio_store import load_state
        trades = load_state().get("trades", [])
    except Exception:
        trades = []

    closed = [t for t in trades if isinstance(t, dict) and
              t.get("action", "").upper() in ("SELL", "EXIT", "CLOSE", "PARTIAL_EXIT")]

    best_trade  = max(closed, key=lambda x: float(x.get("pnl", 0) or 0), default=None)
    worst_trade = min(closed, key=lambda x: float(x.get("pnl", 0) or 0), default=None)

    # Most reliable strategy (best win rate with ≥3 trades)
    strat_data: Dict[str, Dict] = {}
    for t in closed:
        s = t.get("strategy", "UNKNOWN") or "UNKNOWN"
        strat_data.setdefault(s, {"wins": 0, "total": 0})
        strat_data[s]["total"] += 1
        if float(t.get("pnl", 0) or 0) > 0:
            strat_data[s]["wins"] += 1
    reliable = {s: d["wins"] / d["total"] for s, d in strat_data.items() if d["total"] >= 3}
    most_reliable = max(reliable, key=reliable.get, default=None) if reliable else None

    # Common mistakes
    loss_reasons = {}
    for t in closed:
        if float(t.get("pnl", 0) or 0) < 0:
            r = t.get("exit_reason", t.get("reason", "STOP_LOSS")) or "STOP_LOSS"
            loss_reasons[r] = loss_reasons.get(r, 0) + 1
    common_mistakes = [{"reason": r, "count": c}
                       for r, c in sorted(loss_reasons.items(), key=lambda x: -x[1])[:5]]

    # Tomorrow's watchlist from scan signals
    tomorrow_watchlist = _safe(lambda: _get_watch_candidates(), []) or []

    # Lessons
    lessons = []
    if best_trade:
        lessons.append(f"Best trade: {best_trade.get('symbol', '')} "
                       f"+₹{float(best_trade.get('pnl', 0)):,.0f} via {best_trade.get('strategy', 'N/A')}")
    if worst_trade:
        lessons.append(f"Worst trade: {worst_trade.get('symbol', '')} "
                       f"₹{float(worst_trade.get('pnl', 0)):,.0f}. "
                       f"Review stop-loss discipline for {worst_trade.get('strategy', 'N/A')}.")
    if most_reliable:
        wr = reliable.get(most_reliable, 0) * 100
        lessons.append(f"Most reliable strategy: {most_reliable} ({wr:.0f}% win rate).")

    return {
        "best_trade":           _trade_brief(best_trade),
        "worst_trade":          _trade_brief(worst_trade),
        "most_reliable_strategy": most_reliable,
        "common_mistakes":      common_mistakes,
        "tomorrow_watchlist":   tomorrow_watchlist,
        "lessons_learned":      lessons,
        "advisory_only":        ADVISORY_ONLY,
        "as_of":                _now_iso(),
    }


# ── Full Snapshot ─────────────────────────────────────────────────────────────

def get_phase11_snapshot() -> Dict[str, Any]:
    """Master snapshot for Command Centre Paper Trading Centre card."""
    portfolio  = _safe(get_phase11_portfolio, {})
    rec_queue  = _safe(get_recommendation_queue, {})
    ai_perf    = _safe(get_ai_performance_metrics, {})
    cfg        = get_capital_config()
    today_date = _ist_today()

    return {
        "portfolio_value":   portfolio.get("current_value", 0),
        "cash":              portfolio.get("cash", 0),
        "today_pnl":         portfolio.get("daily_pnl", 0),
        "today_return":      portfolio.get("daily_return", 0),
        "unrealised_pnl":    portfolio.get("unrealised_pnl", 0),
        "realised_pnl":      portfolio.get("realised_pnl", 0),
        "open_positions":    portfolio.get("open_positions", 0),
        "buying_power":      portfolio.get("buying_power", 0),
        "portfolio_return":  portfolio.get("portfolio_return", 0),
        "drawdown_pct":      portfolio.get("drawdown_pct", 0),
        "recommendations":   rec_queue.get("count", 0),
        "top_opportunity":   (rec_queue.get("items", []) or [{}])[0].get("symbol", "—"),
        "win_rate":          ai_perf.get("win_rate", 0),
        "avg_confidence":    ai_perf.get("avg_confidence", 0),
        "capital_mode":      cfg["mode"],
        "capital_mode_label": cfg["mode_label"],
        "date":              today_date,
        "advisory_only":     ADVISORY_ONLY,
        "paper_only":        PAPER_ONLY,
        "as_of":             _now_iso(),
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _fmt_holding(minutes: int) -> str:
    if minutes < 0:
        return "—"
    if minutes < 60:
        return f"{minutes}m"
    h = minutes // 60
    m = minutes % 60
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}m"


def _calc_holding_mins(buy_ts, sell_ts) -> int:
    try:
        if not buy_ts or not sell_ts:
            return 0
        bt = datetime.fromisoformat(str(buy_ts).replace("Z", "+00:00"))
        st = datetime.fromisoformat(str(sell_ts).replace("Z", "+00:00"))
        return max(0, int((st - bt).total_seconds() / 60))
    except Exception:
        return 0


def _get_current_regime() -> str:
    try:
        from phase15_canonical_context import get_canonical_context
        ctx = get_canonical_context()
        return str(ctx.get("market_regime", ctx.get("regime", "UNKNOWN")))
    except Exception:
        pass
    try:
        from market_scanner import get_market_regime
        return str(get_market_regime())
    except Exception:
        return "UNKNOWN"


def _get_phase20_closed_trades(limit: int) -> List[Dict]:
    if not _db_available():
        return []
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT symbol, action, quantity, price, (metadata->>'pnl')::float,
                       (metadata->>'buy_ts') as buy_ts, trade_ts, reason,
                       (metadata->>'strategy') as strategy,
                       (metadata->>'confidence')::float as confidence,
                       metadata
                FROM paper_trades
                WHERE action IN ('SELL','EXIT','CLOSE','PARTIAL_EXIT')
                  AND archived_at IS NULL
                ORDER BY trade_ts DESC LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        meta = r[10] or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        result.append({
            "symbol": r[0], "action": r[1], "quantity": r[2], "price": r[3],
            "pnl": r[4], "buy_ts": r[5],
            "trade_ts": r[6].strftime("%Y-%m-%dT%H:%M:%SZ") if r[6] else None,
            "reason": r[7], "strategy": r[8], "confidence": r[9],
            "entry_price": meta.get("entry_price", meta.get("buy_price")),
            "lesson_learned": meta.get("lesson_learned", ""),
            "exit_reason": r[7],
        })
    return result


def _all_trades_in_range(start_date: str, end_date: str) -> List[Dict]:
    if not _db_available():
        return []
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT symbol, action, quantity, price,
                       (metadata->>'pnl')::float as pnl,
                       (metadata->>'buy_ts') as buy_ts,
                       trade_ts, reason,
                       (metadata->>'strategy') as strategy,
                       (metadata->>'confidence')::float as confidence,
                       metadata
                FROM paper_trades
                WHERE date(trade_ts AT TIME ZONE 'Asia/Kolkata') BETWEEN %s AND %s
                  AND archived_at IS NULL
                ORDER BY trade_ts
            """, (start_date, end_date))
            rows = cur.fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        meta = r[10] or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        result.append({
            "symbol": r[0], "action": r[1], "quantity": r[2], "price": r[3],
            "pnl": r[4] or 0.0, "buy_ts": r[5],
            "trade_ts": r[6].strftime("%Y-%m-%dT%H:%M:%SZ") if r[6] else None,
            "reason": r[7], "strategy": r[8] or "UNKNOWN",
            "confidence": r[9] or 0.0,
            "entry_price": meta.get("entry_price", meta.get("buy_price")),
            "exit_reason": r[7],
            "lesson_learned": meta.get("lesson_learned", ""),
        })
    return result


def _get_ai_decision_recs() -> List[Dict]:
    try:
        from ai_decision_agent.agent import AIDecisionAgent
        agent  = AIDecisionAgent()
        result = agent.execute()
        recs   = result.get("recommendations", [])
        return [
            {
                "symbol":               r.get("symbol", ""),
                "action":               r.get("action", r.get("recommendation", "")),
                "confidence":           float(r.get("confidence", 0)),
                "risk_level":           r.get("risk_level", "MEDIUM"),
                "expected_return":      r.get("expected_return", r.get("reward_risk_ratio", 0)),
                "estimated_holding":    r.get("holding_period", "1–3 days"),
                "entry":                r.get("entry_price", r.get("entry", 0)),
                "stop_loss":            r.get("stop_loss", 0),
                "target":               r.get("target", 0),
                "reasoning":            r.get("reasoning", r.get("explanation", "")),
                "strategy":             r.get("strategy", ""),
            }
            for r in recs
        ]
    except Exception:
        return []


def _get_scan_signal_recs() -> List[Dict]:
    try:
        from live_scan_engine import get_latest_scan
        scan = get_latest_scan()
        items = scan.get("items", scan.get("signals", []))
        return [
            {
                "symbol":            it.get("stock", it.get("symbol", "")),
                "action":            it.get("final_action", it.get("action", "WATCH")),
                "confidence":        float(it.get("final_confidence", it.get("confidence", 0))),
                "risk_level":        it.get("risk_level", "MEDIUM"),
                "expected_return":   it.get("expected_return", it.get("rr_ratio", 0)),
                "estimated_holding": it.get("estimated_holding", "Intraday"),
                "entry":             it.get("price", 0),
                "stop_loss":         it.get("stop_loss", 0),
                "target":            it.get("target", 0),
                "reasoning":         it.get("reasoning", ""),
                "strategy":          it.get("best_strategy_name", ""),
            }
            for it in items
            if it.get("final_action", it.get("action", "")).upper() in
               ("BUY", "STRONG BUY", "STRONG_BUY")
        ]
    except Exception:
        return []


def _market_milestones(session_date: str) -> List[Dict]:
    """Standard IST market milestones for a trading day."""
    weekday = date.fromisoformat(session_date).weekday()
    if weekday >= 5:  # weekend — no milestones
        return []
    base = f"{session_date}T"
    IST_OFFSET = "+05:30"
    return [
        {"ts": f"{base}03:45:00{IST_OFFSET}", "type": "MARKET_OPEN",  "label": "Pre-open session starts", "category": "MARKET"},
        {"ts": f"{base}04:00:00{IST_OFFSET}", "type": "MARKET_OPEN",  "label": "NSE pre-open order matching", "category": "MARKET"},
        {"ts": f"{base}04:15:00{IST_OFFSET}", "type": "MARKET_OPEN",  "label": "Market OPEN — normal trading begins", "category": "MARKET"},
        {"ts": f"{base}10:00:00{IST_OFFSET}", "type": "SCAN",         "label": "Mid-morning scan checkpoint", "category": "SCAN"},
        {"ts": f"{base}11:30:00{IST_OFFSET}", "type": "SCAN",         "label": "Pre-noon scan checkpoint", "category": "SCAN"},
        {"ts": f"{base}13:00:00{IST_OFFSET}", "type": "SCAN",         "label": "Post-lunch scan checkpoint", "category": "SCAN"},
        {"ts": f"{base}14:30:00{IST_OFFSET}", "type": "SCAN",         "label": "Pre-close scan checkpoint", "category": "SCAN"},
        {"ts": f"{base}09:45:00{IST_OFFSET}", "type": "MARKET_CLOSE", "label": "Market CLOSE — positions finalised", "category": "MARKET"},
        {"ts": f"{base}10:00:00{IST_OFFSET}", "type": "LEARNING",     "label": "End-of-day learning + reports scheduled", "category": "LEARNING"},
    ]


def _trade_events(session_date: str) -> List[Dict]:
    trades = _all_trades_in_range(session_date, session_date)
    events = []
    for t in trades:
        action = t.get("action", "").upper()
        sym    = t.get("symbol", "")
        price  = t.get("price", 0)
        pnl    = t.get("pnl", 0)
        ts     = t.get("trade_ts", "")
        label  = f"{action} {sym} @ ₹{price:,.0f}"
        if pnl:
            label += f" | P/L: ₹{pnl:+,.0f}"
        events.append({
            "ts":       ts,
            "type":     action,
            "label":    label,
            "symbol":   sym,
            "price":    price,
            "pnl":      pnl,
            "strategy": t.get("strategy", ""),
            "category": "TRADE",
        })
    return events


def _notification_events(session_date: str) -> List[Dict]:
    if not _db_available():
        return []
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT kind, title, body, created_at
                    FROM phase20_notifications
                    WHERE date(created_at AT TIME ZONE 'Asia/Kolkata') = %s
                    ORDER BY created_at
                """, (session_date,))
                rows = cur.fetchall()
        finally:
            conn.close()
        return [
            {
                "ts":       r[3].strftime("%Y-%m-%dT%H:%M:%SZ") if r[3] else "",
                "type":     str(r[0]).upper(),
                "label":    r[1],
                "detail":   r[2],
                "category": "NOTIFICATION",
            }
            for r in rows
        ]
    except Exception:
        return []


# ── Price Snapshot Functions ───────────────────────────────────────────────────

def record_price_snapshots(scan_id: str = "") -> Dict[str, Any]:
    """
    Record current_price for every open position.
    Call post-scan to build intraday price history for sparklines.
    Idempotent per scan_id+symbol — duplicate rows are skipped when
    a non-empty scan_id is supplied.
    """
    if not _db_available():
        return {"recorded": 0, "skipped": 0, "reason": "no_db"}

    try:
        from portfolio_store import load_state
        state = load_state()
    except Exception as exc:
        return {"recorded": 0, "skipped": 0, "reason": str(exc)}

    positions = state.get("positions", {})
    if not positions:
        return {"recorded": 0, "skipped": 0, "reason": "no_open_positions"}

    rows: List[tuple] = []
    for sym, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        qty = int(pos.get("qty", pos.get("quantity", 0)))
        if qty <= 0:
            continue
        price = float(pos.get("current_price", pos.get("avg_price", 0)))
        if price <= 0:
            continue
        rows.append((sym, price, scan_id or ""))

    if not rows:
        return {"recorded": 0, "skipped": 0, "reason": "no_valid_positions"}

    recorded = 0
    skipped  = 0
    try:
        conn = _connect()
        try:
            _ensure_price_snapshots_table(conn)
            with conn.cursor() as cur:
                for sym, price, sid in rows:
                    if sid:
                        # Partial-unique-index path: ON CONFLICT DO NOTHING is
                        # race-safe — the DB enforces (scan_id, symbol) uniqueness.
                        cur.execute(
                            """
                            INSERT INTO phase11_price_snapshots (symbol, price, scan_id)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (scan_id, symbol) WHERE scan_id != ''
                            DO NOTHING
                            """,
                            (sym, price, sid)
                        )
                        # rowcount == 0 means conflict (already recorded)
                        if cur.rowcount == 0:
                            skipped += 1
                        else:
                            recorded += 1
                    else:
                        # No scan_id — unconstrained; always insert
                        cur.execute(
                            "INSERT INTO phase11_price_snapshots (symbol, price, scan_id) "
                            "VALUES (%s, %s, %s)",
                            (sym, price, sid)
                        )
                        recorded += 1
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("record_price_snapshots failed: %s", exc)
        return {"recorded": 0, "skipped": skipped, "reason": str(exc)}

    return {
        "recorded":  recorded,
        "skipped":   skipped,
        "symbols":   [r[0] for r in rows],
        "scan_id":   scan_id,
        "as_of":     _now_iso(),
    }


def get_price_history(symbol: str = "", limit: int = 50) -> Dict[str, Any]:
    """
    Return intraday price snapshots for sparklines.
    - symbol given  → { symbol, prices[], timestamps[], count, as_of }
    - symbol absent → { snapshots: { sym: prices[] }, as_of }   (all open positions)
    Prices are ordered oldest-first (left→right for sparklines).
    """
    if not _db_available():
        return {"snapshots": {}, "as_of": _now_iso()}

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    today_ist = datetime.now(ist_tz).strftime("%Y-%m-%d")
    limit = max(1, min(limit, 200))

    try:
        conn = _connect()
        try:
            _ensure_price_snapshots_table(conn)

            if symbol:
                sym_upper = symbol.upper()
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT price, recorded_at
                        FROM phase11_price_snapshots
                        WHERE symbol = %s
                          AND DATE(recorded_at AT TIME ZONE 'Asia/Kolkata') = %s
                        ORDER BY recorded_at ASC
                        LIMIT %s
                    """, (sym_upper, today_ist, limit))
                    rows = cur.fetchall()
                return {
                    "symbol":      sym_upper,
                    "prices":      [float(r[0]) for r in rows],
                    "timestamps":  [
                        r[1].strftime("%Y-%m-%dT%H:%M:%SZ") if r[1] else None
                        for r in rows
                    ],
                    "count":       len(rows),
                    "as_of":       _now_iso(),
                }

            # All open symbols — single query
            try:
                from portfolio_store import load_state
                state = load_state()
            except Exception:
                state = {}

            open_syms = [
                s for s, pos in (state.get("positions") or {}).items()
                if isinstance(pos, dict)
                and int(pos.get("qty", pos.get("quantity", 0))) > 0
            ]
            if not open_syms:
                return {"snapshots": {}, "as_of": _now_iso()}

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, price, recorded_at
                    FROM phase11_price_snapshots
                    WHERE symbol = ANY(%s)
                      AND DATE(recorded_at AT TIME ZONE 'Asia/Kolkata') = %s
                    ORDER BY symbol, recorded_at ASC
                """, (open_syms, today_ist))
                rows = cur.fetchall()

            snapshots: Dict[str, List[float]] = {}
            for sym, price, _ts in rows:
                snapshots.setdefault(sym, []).append(float(price))

            return {"snapshots": snapshots, "as_of": _now_iso()}
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("get_price_history failed: %s", exc)
        return {"snapshots": {}, "as_of": _now_iso()}


def _get_market_summary(trade_date: str) -> Dict:
    return _safe(lambda: _fetch_market_summary(), {}) or {}


def _fetch_market_summary() -> Dict:
    try:
        from live_scan_engine import get_latest_scan
        scan = get_latest_scan()
        return {
            "regime":   scan.get("regime", "UNKNOWN"),
            "nifty":    scan.get("nifty_close", scan.get("nifty", 0)),
            "bank_nifty": scan.get("bank_nifty", 0),
            "india_vix": scan.get("india_vix", 0),
        }
    except Exception:
        return {}


def _get_learning_for_date(trade_date: str) -> Dict:
    try:
        from paper_analytics.shared_services import get_paper_analytics_snapshot
        return get_paper_analytics_snapshot().get("learning", {})
    except Exception:
        return {}


def _get_watch_candidates() -> List[str]:
    try:
        from live_scan_engine import get_latest_scan
        scan  = get_latest_scan()
        items = scan.get("items", [])
        return [it.get("stock", "") for it in items if it.get("final_action") == "WATCH"][:10]
    except Exception:
        return []


def _get_ai_decisions_for_date(trade_date: str) -> List[Dict]:
    if not _db_available():
        return []
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, decision, confidence, reasoning, created_at
                    FROM ai_decisions_cache
                    WHERE date(created_at AT TIME ZONE 'Asia/Kolkata') = %s
                    ORDER BY created_at
                """, (trade_date,))
                rows = cur.fetchall()
        finally:
            conn.close()
        return [
            {
                "symbol":     r[0], "decision": r[1],
                "confidence": r[2], "reasoning": r[3],
                "ts": r[4].strftime("%Y-%m-%dT%H:%M:%SZ") if r[4] else "",
            }
            for r in rows
        ]
    except Exception:
        return []


def _enrich_closed(trades: List[Dict]) -> List[Dict]:
    return [
        {
            "symbol":       t.get("symbol", ""),
            "action":       t.get("action", ""),
            "quantity":     t.get("quantity", 0),
            "entry_price":  t.get("entry_price", 0),
            "exit_price":   t.get("price", 0),
            "pnl":          t.get("pnl", 0),
            "pnl_pct":      t.get("pnl_pct", 0),
            "strategy":     t.get("strategy", ""),
            "exit_reason":  t.get("exit_reason", t.get("reason", "")),
            "confidence":   t.get("confidence", 0),
            "trade_ts":     t.get("trade_ts", ""),
        }
        for t in trades
    ]


def _trade_brief(t: Optional[Dict]) -> Optional[Dict]:
    if not t:
        return None
    return {
        "symbol":   t.get("symbol", ""),
        "pnl":      float(t.get("pnl", 0) or 0),
        "strategy": t.get("strategy", ""),
        "action":   t.get("action", ""),
        "price":    t.get("price", 0),
    }
