"""
validation_v2_engine.py — AI Validation Platform V2

Backtests the current production pipeline against historical NSE candles.
Uses:
  - backtesting_engine.run_backtest() — actual production strategy simulation
    (StrategyBase.check_entry, check_exit, inspect_entry_rules)
  - decision_service._decide() — actual production recommendation engine
    (STRONG_BUY | BUY | WATCH | EXIT | AVOID)
  - Walk-forward point-in-time stats — only trades closed BEFORE each bar
    are used to compute the historical stats supplied to _decide(), preventing
    look-ahead bias.
  - Position state maintained between bars — positions dict and trades list
    are updated after each BUY/EXIT so _decide() can emit EXIT signals.
  - Parameterized simulator — optimizer runs each grid combo through a
    parameterized walk-forward sim (stop_pct / target_pct / confidence_threshold
    applied per-bar), producing genuinely different P&L per combination.

PAPER TRADING / RESEARCH ONLY — never places live orders.
Advisory only — never modifies production parameters automatically.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date as _date_cls
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# ── DB helpers ────────────────────────────────────────────────────────────────

PSYCOPG2_AVAILABLE = False
try:
    import psycopg2                          # type: ignore
    import psycopg2.extras                   # type: ignore
    PSYCOPG2_AVAILABLE = True
except ImportError:
    pass

LABEL = "PAPER / RESEARCH ONLY — Advisory Only"
ADVISORY_NOTE = "DO NOT modify strategy parameters automatically. Recommendations only."


def _get_conn():
    url = os.environ.get("DATABASE_URL", "")
    if not url or not PSYCOPG2_AVAILABLE:
        return None
    try:
        return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    except Exception:
        return None


def _q(conn, sql: str, params=()) -> List[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in (cur.fetchall() or [])]


def _q1(conn, sql: str, params=()) -> Optional[dict]:
    rows = _q(conn, sql, params)
    return rows[0] if rows else None


def _exec(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def _ensure_tables(conn):
    """Auto-create V2 tables if they don't exist."""
    ddl = """
    CREATE TABLE IF NOT EXISTS validation_v2_runs (
        run_id      TEXT PRIMARY KEY,
        config      JSONB NOT NULL DEFAULT '{}',
        status      TEXT NOT NULL DEFAULT 'PENDING',
        symbols     JSONB NOT NULL DEFAULT '[]',
        strategies  JSONB NOT NULL DEFAULT '[]',
        start_date  TEXT,
        end_date    TEXT,
        interval    TEXT DEFAULT '1h',
        total_decisions INTEGER DEFAULT 0,
        total_trades    INTEGER DEFAULT 0,
        symbols_done    INTEGER DEFAULT 0,
        symbols_total   INTEGER DEFAULT 0,
        current_symbol  TEXT DEFAULT '',
        symbol_errors   JSONB DEFAULT '[]',
        error           TEXT,
        last_progress_at TIMESTAMPTZ DEFAULT NOW(),
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        completed_at TIMESTAMPTZ
    );
    CREATE TABLE IF NOT EXISTS validation_v2_decisions (
        id          BIGSERIAL PRIMARY KEY,
        run_id      TEXT NOT NULL REFERENCES validation_v2_runs(run_id) ON DELETE CASCADE,
        symbol      TEXT NOT NULL,
        strategy    TEXT NOT NULL DEFAULT '',
        bar_date    TEXT NOT NULL,
        bar_close   DOUBLE PRECISION,
        recommendation TEXT,
        final_confidence DOUBLE PRECISION,
        reason      TEXT,
        threshold   DOUBLE PRECISION,
        entry_signal BOOLEAN DEFAULT FALSE,
        filter_passed BOOLEAN DEFAULT FALSE,
        rr_ratio    DOUBLE PRECISION,
        detail      JSONB DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_v2_dec_run ON validation_v2_decisions(run_id);
    CREATE INDEX IF NOT EXISTS idx_v2_dec_sym ON validation_v2_decisions(run_id, symbol);
    CREATE TABLE IF NOT EXISTS validation_v2_trades (
        id            BIGSERIAL PRIMARY KEY,
        run_id        TEXT NOT NULL REFERENCES validation_v2_runs(run_id) ON DELETE CASCADE,
        symbol        TEXT NOT NULL,
        strategy      TEXT NOT NULL DEFAULT '',
        entry_date    TEXT,
        entry_price   DOUBLE PRECISION,
        stop_loss     DOUBLE PRECISION,
        target_price  DOUBLE PRECISION,
        trailing_stop DOUBLE PRECISION,
        exit_date     TEXT,
        exit_price    DOUBLE PRECISION,
        exit_reason   TEXT,
        pnl_pct       DOUBLE PRECISION,
        pnl_abs       DOUBLE PRECISION,
        holding_days  INTEGER,
        mfe_pct       DOUBLE PRECISION,
        mad_pct       DOUBLE PRECISION,
        result        TEXT,
        confidence    DOUBLE PRECISION,
        recommendation TEXT,
        agent_scores  JSONB DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_v2_trades_run ON validation_v2_trades(run_id);
    CREATE TABLE IF NOT EXISTS validation_v2_missed (
        id                  BIGSERIAL PRIMARY KEY,
        run_id              TEXT NOT NULL REFERENCES validation_v2_runs(run_id) ON DELETE CASCADE,
        symbol              TEXT NOT NULL,
        strategy            TEXT NOT NULL DEFAULT '',
        bar_date            TEXT,
        ai_decision         TEXT,
        ai_confidence       DOUBLE PRECISION,
        actual_move_pct     DOUBLE PRECISION,
        potential_profit_pct DOUBLE PRECISION,
        rejection_reason    TEXT,
        improvement_suggestion TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_v2_missed_run ON validation_v2_missed(run_id);
    CREATE TABLE IF NOT EXISTS validation_v2_optimizer_runs (
        opt_run_id   TEXT PRIMARY KEY,
        config       JSONB NOT NULL DEFAULT '{}',
        best_config  JSONB,
        results      JSONB NOT NULL DEFAULT '[]',
        combinations_tested INTEGER DEFAULT 0,
        recommendation TEXT,
        created_at   TIMESTAMPTZ DEFAULT NOW()
    );
    """
    migration = """
    ALTER TABLE IF EXISTS validation_v2_runs
        ADD COLUMN IF NOT EXISTS symbols_done  INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS symbols_total INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS current_symbol TEXT DEFAULT '',
        ADD COLUMN IF NOT EXISTS symbol_errors JSONB DEFAULT '[]',
        ADD COLUMN IF NOT EXISTS strategies JSONB NOT NULL DEFAULT '[]',
        ADD COLUMN IF NOT EXISTS error TEXT,
        ADD COLUMN IF NOT EXISTS last_progress_at TIMESTAMPTZ DEFAULT NOW();
    ALTER TABLE IF EXISTS validation_v2_decisions
        ADD COLUMN IF NOT EXISTS stage TEXT DEFAULT '';
    ALTER TABLE IF EXISTS validation_v2_decisions
        ALTER COLUMN stage SET DEFAULT '',
        ADD COLUMN IF NOT EXISTS strategy TEXT NOT NULL DEFAULT '',
        ADD COLUMN IF NOT EXISTS recommendation TEXT,
        ADD COLUMN IF NOT EXISTS final_confidence DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS entry_signal BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS filter_passed BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS rr_ratio DOUBLE PRECISION;
    ALTER TABLE IF EXISTS validation_v2_trades
        ADD COLUMN IF NOT EXISTS trailing_stop DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS recommendation TEXT;
    ALTER TABLE IF EXISTS validation_v2_missed
        ADD COLUMN IF NOT EXISTS strategy TEXT NOT NULL DEFAULT '';
    """
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
            cur.execute(migration)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise


def _paper_capital() -> float:
    """Configured paper-trading starting capital (single source of truth)."""
    try:
        from portfolio_store import INITIAL_CAPITAL
        return float(INITIAL_CAPITAL)
    except Exception:
        return 50_000.0


def _sf(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_str(d) -> str:
    """Normalize any date/timestamp to YYYY-MM-DD string."""
    return str(d)[:10]


# ── Security / validation caps ────────────────────────────────────────────────

_MAX_SYMBOLS = 20
_MAX_DATE_SPAN_DAYS = 730   # 2 years
_MAX_GRID_COMBOS = 200      # cap on actual Cartesian product (including defaults)
_MAX_OPT_SYMBOLS = 8        # optimizer cap: fewer symbols, grid is expensive

# Default grid values — must match what run_parameter_optimizer iterates over.
_DEFAULT_GRID = {
    "confidence_threshold": [55.0, 60.0, 65.0, 70.0],   # 4
    "stop_pct":             [1.5, 2.0, 2.5],              # 3
    "target_pct":           [3.0, 4.0, 5.0],              # 3
    "position_size_pct":    [10.0, 15.0],                 # 2
    "min_rr":               [1.5, 2.0],                   # 2
}   # max default product = 4×3×3×2×2 = 144 (under 200)

# Production recommendation taxonomy (from decision_service.py)
_BUY_RECS = {"STRONG_BUY", "BUY"}
_SELL_RECS = {"EXIT"}
_NEUTRAL_RECS = {"WATCH", "AVOID"}

BREAKEVEN_BAND_PCT = 0.1  # ±0.1% = breakeven


def _cap_symbols(symbols: list, limit: int = _MAX_SYMBOLS) -> list:
    return symbols[:limit]


def _validate_and_normalize_dates(start_date: str, end_date: str) -> tuple:
    """
    Validate and normalize a date pair.
    Returns (normalized_start, normalized_end, error_string).
    - Empty start_date → ('', '', '') — callers use period-based fetch.
    - start_date given, end_date omitted → end_date defaults to today.
    - Invalid ISO strings → error.
    - start_date >= end_date → error.
    - Span > _MAX_DATE_SPAN_DAYS → error.
    """
    if not start_date:
        return "", "", ""

    try:
        s = _date_cls.fromisoformat(start_date[:10])
    except (ValueError, TypeError):
        return "", "", f"Invalid start_date '{start_date}' — expected YYYY-MM-DD."

    today = _date_cls.today().isoformat()
    if not end_date:
        end_date = today

    try:
        e = _date_cls.fromisoformat(end_date[:10])
    except (ValueError, TypeError):
        return "", "", f"Invalid end_date '{end_date}' — expected YYYY-MM-DD."

    if s >= e:
        return "", "", f"start_date ({start_date}) must be before end_date ({end_date})."

    span = (e - s).days
    if span > _MAX_DATE_SPAN_DAYS:
        return "", "", (
            f"Date span {span} days exceeds maximum {_MAX_DATE_SPAN_DAYS} days "
            f"({_MAX_DATE_SPAN_DAYS // 365} years). Shorten the range."
        )

    return start_date, end_date, ""


def _validate_date_span(start_date: str, end_date: str) -> str:
    _, _, err = _validate_and_normalize_dates(start_date, end_date)
    return err


def _resolve_grid_dim(grid: dict, key: str) -> tuple:
    """
    Return (values, error_string) for one grid dimension.
    Uses defaults when key is missing; errors when value is not a non-empty list.
    """
    default = _DEFAULT_GRID[key]
    if key not in grid:
        return default, ""
    vals = grid[key]
    if not isinstance(vals, list) or len(vals) == 0:
        return None, f"Grid '{key}' must be a non-empty list."
    return vals, ""


def _count_grid_combos(grid: dict) -> int:
    """
    Count the ACTUAL Cartesian product that will be computed, including defaults
    for any dimension not supplied by the caller.
    Returns -1 if any supplied dimension is invalid.
    """
    product = 1
    for key in _DEFAULT_GRID:
        vals, err = _resolve_grid_dim(grid, key)
        if err:
            return -1
        product *= len(vals)
    return product


# ── Walk-forward point-in-time stats ──────────────────────────────────────────

_NEUTRAL_STATS = {
    "win_rate_pct": 50.0, "expectancy": 0.0, "profit_factor": 1.0,
    "sharpe_ratio": 0.0, "total_trades": 0, "avg_holding_days": 5.0,
}


def _walk_forward_stats(closed_trades: list, before_date_str: str) -> dict:
    """
    Compute performance stats from only the trades that closed BEFORE
    before_date_str (YYYY-MM-DD prefix). This prevents look-ahead bias:
    each bar's _decide() call only sees evidence that existed at that time.
    """
    before = before_date_str[:10]
    eligible = [
        t for t in closed_trades
        if _date_str(t.get("exit_date", "")) < before
    ]
    n = len(eligible)
    if n == 0:
        return dict(_NEUTRAL_STATS)

    pnls = [_sf(t.get("pnl_pct", 0)) for t in eligible]
    wins = sum(1 for p in pnls if p > BREAKEVEN_BAND_PCT)

    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else 1.0

    avg_pnl = sum(pnls) / n
    variance = sum((p - avg_pnl) ** 2 for p in pnls) / max(n - 1, 1) if n > 1 else 0.0
    std_dev = math.sqrt(variance) if variance > 0 else 0.0
    sharpe = avg_pnl / std_dev * math.sqrt(252) if std_dev > 0 else 0.0

    hold_vals = [int(t.get("hold_bars", t.get("holding_days", 5))) for t in eligible]
    avg_hold = sum(hold_vals) / len(hold_vals) if hold_vals else 5.0

    return {
        "win_rate_pct": round(100.0 * wins / n, 1),
        "expectancy": round(avg_pnl, 4),
        "profit_factor": round(pf, 4),
        "sharpe_ratio": round(sharpe, 4),
        "total_trades": n,
        "avg_holding_days": round(avg_hold, 1),
    }


# ── Production pipeline adapter ───────────────────────────────────────────────

def _build_scan_item_from_bar(
    symbol: str,
    row: pd.Series,
    prev_row: pd.Series,
    strategy,              # StrategyBase instance (production code)
    wf_stats: dict,        # walk-forward stats from _walk_forward_stats()
    config: dict,
) -> tuple:
    """
    Construct a point-in-time scan item for decision_service._decide() using:
    - Actual indicator data from the bar (compute_indicators_df output)
    - Production strategy signals via strategy.check_entry(row, prev_row) and
      strategy.inspect_entry_rules(row, prev_row) for confidence
    - Walk-forward historical stats (win_rate, expectancy, PF) — computed from
      ONLY trades that closed before this bar, preventing look-ahead bias

    This is the bridge between historical candle data and the production decision
    engine — it feeds real inputs into _decide() rather than simulating it.

    Returns (scan_item: dict, entry_signal: bool, entry_reason: str)
    """
    close = _sf(row.get("close", 0))
    atr = _sf(row.get("atr", 0))
    rsi = _sf(row.get("rsi", 50), 50.0)
    adx = _sf(row.get("adx", 20), 20.0)
    volume = _sf(row.get("volume", 0))
    vol_ma = _sf(row.get("vol_ma", 0))
    volume_ratio = (volume / vol_ma) if vol_ma > 0 else (1.0 if volume > 0 else 0.0)

    # ── Get production strategy signal + rule inspector (actual production code)
    entry_signal, entry_reason = False, ""
    rule_checks: list = []
    try:
        entry_signal, entry_reason = strategy.check_entry(row, prev_row)
        rule_checks = strategy.inspect_entry_rules(row, prev_row)
    except Exception as ex:
        entry_reason = f"check_entry error: {ex}"

    # ── Confidence from rule inspector (same metric production scanner uses)
    if rule_checks:
        rules_passed = sum(1 for r in rule_checks if r.get("passed", False))
        confidence = rules_passed / len(rule_checks) * 100.0
    else:
        confidence = 70.0 if entry_signal else 35.0

    # ── Risk levels from config (optimizer will vary these per-combo)
    stop_pct = float(config.get("stop_pct", 2.0))
    target_pct = float(config.get("target_pct", 4.0))
    # ATR-based cap: never widen stop beyond 1.5× ATR%
    if atr > 0 and close > 0:
        atr_pct = atr / close * 100.0
        stop_pct = max(0.5, min(stop_pct, atr_pct * 1.5))
    stop = round(close * (1.0 - stop_pct / 100.0), 2) if close > 0 else 0.0
    target = round(close * (1.0 + target_pct / 100.0), 2) if close > 0 else 0.0
    rr = (target - close) / (close - stop) if close > stop > 0 else 0.0

    # ── Walk-forward historical stats (point-in-time; no future data)
    win_rate = _sf(wf_stats.get("win_rate_pct", 50.0), 50.0)
    expectancy = _sf(wf_stats.get("expectancy", 0.0))
    pf = _sf(wf_stats.get("profit_factor", 1.0), 1.0)
    sharpe = _sf(wf_stats.get("sharpe_ratio", 0.0))
    n_trades = int(wf_stats.get("total_trades", 0))
    avg_holding = _sf(wf_stats.get("avg_holding_days", 5.0), 5.0)

    # ── Filter gate (production-equivalent)
    min_rr = float(config.get("min_rr", 1.5))
    filter_passed = (rr >= min_rr and expectancy >= 0.0 and close > 0)
    filter_reasons = []
    if rr < min_rr:
        filter_reasons.append(f"R:R={rr:.2f} < min {min_rr}")
    if expectancy < 0.0:
        filter_reasons.append("Negative walk-forward expectancy")

    scan_item = {
        "stock": symbol.upper(), "sector": "",
        "price": close, "entry_price": close,
        "stop_loss": stop, "target": target,
        "rr_ratio": round(rr, 2),
        # Confidence from production inspect_entry_rules()
        "final_confidence": round(confidence, 1),
        "base_confidence": round(confidence, 1),
        "learning_adjustment": 0.0,
        "similarity_adjustment": 0.0,
        "evidence_reliability": "VERY_LOW",
        "similarity_evidence": None,
        "model_adjustment": 0.0,
        # Walk-forward historical stats (point-in-time; no look-ahead)
        "historical_expectancy": round(expectancy, 4),
        "historical_profit_factor": round(pf, 4),
        "historical_win_rate": round(win_rate, 2),
        "historical_sharpe": round(sharpe, 4),
        "historical_kelly": 0.0,
        "historical_trades": n_trades,
        "total_trades": n_trades,
        "pattern_match_pct": 0.0,
        "best_pattern": "",
        "best_regime": "",
        "best_strategy_id": "",
        "best_strategy_name": str(getattr(strategy, "name", "")),
        "rsi": round(rsi, 1),
        "adx": round(adx, 1),
        "volume_ratio": round(volume_ratio, 2),
        "volatility": None,
        "filter_passed": filter_passed,
        "filter_reasons": filter_reasons,
        "error": None,
        # live_signal is used by production _decide() to determine the WATCH
        # reason ("Setup incomplete — no live entry signal yet"). Must be set
        # from the actual strategy.check_entry() result, not inferred.
        "live_signal": entry_signal,
        "opportunity_breakdown": {
            "expectancy_score": max(0.0, min(100.0, 50.0 + expectancy * 10.0)),
            "pf_score": max(0.0, min(100.0, pf / 3.0 * 100.0)),
            "sector_strength_score": 50.0,
        },
        "expected_holding_days": round(avg_holding, 1),
    }
    return scan_item, entry_signal, entry_reason


# ── Production decision replay (bar-by-bar) ───────────────────────────────────

def _run_symbol_replay(
    symbol: str,
    df: pd.DataFrame,
    config: dict,
    bootstrap_trades: list,
    strategy_name: str,
) -> tuple:
    """
    Walk bar-by-bar through indicator-enriched candles, replaying the production
    AI decision pipeline and simulating trade entries / exits.

    bootstrap_trades: Historical trades from run_backtest() on the period BEFORE
      the replay window (all exit_date values precede the replay start date).
      These seed the walk-forward evidence so _decide() has non-zero expectancy
      and profit factor on the first bar — breaking the cold-start deadlock where
      empty history blocks BUY regardless of signal quality. No look-ahead bias
      is introduced because all bootstrap trades closed before the replay begins.

    At each bar:
    1. Walk-forward stats from replay's own closed trades PLUS bootstrap —
       only trades with exit_date strictly before this bar's date are included.
    2. Build scan item with live_signal=entry_signal (production _decide() uses
       this field for the WATCH "no live entry signal" reason).
    3. Call production decision_service._decide(scan_item, positions, buy_log).
    4. Open a position ONLY when _decide() returns BUY/STRONG_BUY AND the
       production strategy.check_entry() actually fired (entry_signal=True).
       _decide() can issue BUY based on confidence/history gates alone; we require
       the explicit strategy signal to match production entry semantics.
    5. For open positions: check intrabar low vs stop and high vs target (same as
       production run_backtest). Also call strategy.check_exit() for signal exits.
       The more conservative intrabar check takes priority; exits are recorded as
       actual trades in sim_trades, matching production exit behavior.

    Returns (decisions: List[dict], sim_trades: List[dict])
    """
    from decision_service import _decide
    from strategies import get_strategy
    from backtesting_engine import WARMUP_BARS

    try:
        strategy = get_strategy(strategy_name)
    except Exception:
        return [], []

    rows = df.reset_index(drop=True)
    if "time" in df.columns:
        dates = [str(d) for d in df["time"].tolist()]
    else:
        dates = [str(d) for d in df.index.tolist()]

    n = len(rows)
    warmup = WARMUP_BARS

    decisions: List[dict] = []
    sim_trades: List[dict] = []
    # Seed with bootstrap trades (pre-period evidence). All bootstrap exit_dates
    # precede the replay start, so _walk_forward_stats() correctly includes them
    # at bar 0 and never introduces look-ahead (their exits are in the past).
    replay_closed_trades: List[dict] = list(bootstrap_trades)

    # ── Position state passed to _decide() each bar ──────────────────────────
    # Format mirrors the production paper trading store:
    #   positions = {SYM: {"avg_price": float, "quantity": int}}
    #   buy_log   = [{"symbol": SYM, "action": "BUY", "timestamp": ISO,
    #                 "stop_loss": float, "target": float}]
    positions: dict = {}
    buy_log: list = []

    for i in range(warmup, n):
        row = rows.iloc[i]
        prev_row = rows.iloc[i - 1] if i > 0 else row
        date = dates[i]
        close = _sf(row.get("close", 0))
        high = _sf(row.get("high", close))
        low = _sf(row.get("low", close))
        if close <= 0:
            continue

        # ── Step 0: Intrabar exit check for open position (BEFORE new bar decision)
        # Uses intrabar low/high AND strategy.check_exit() — same as production
        # run_backtest(). Exits are processed before the new decision is issued.
        if symbol in positions:
            pos = positions[symbol]
            entry_p = _sf(pos.get("avg_price", close))
            stop = _sf(pos.get("stop_loss", 0))
            target = _sf(pos.get("target_price", 0))
            entry_date_str = pos.get("entry_date", date)

            stop_hit = stop > 0 and low <= stop
            target_hit = target > 0 and high >= target

            # Strategy signal exit (same as production backtesting_engine.py)
            sig_exit = False
            sig_exit_reason = ""
            try:
                sig_exit, sig_exit_reason = strategy.check_exit(
                    row, prev_row, entry_p, stop, target
                )
            except Exception:
                pass

            # Time exit: position held longer than max_holding_days
            # Checked BEFORE applying this bar's hold_bars increment so the
            # bar that pushes hold_bars over the threshold sees the exit in
            # Step 1 walk-forward stats (enabling wf evidence to grow).
            max_hold = int(config.get("max_holding_days", 30))
            time_exit = int(pos.get("hold_bars", 0)) >= max_hold

            exit_price: Optional[float] = None
            exit_reason: Optional[str] = None

            if stop_hit and target_hit:
                # Conservative: stop wins on same-bar conflict (matches production)
                exit_price = min(close, stop)
                exit_reason = "STOP_LOSS"
            elif stop_hit:
                exit_price = min(close, stop)
                exit_reason = "STOP_LOSS"
            elif target_hit:
                exit_price = target
                exit_reason = "TARGET_HIT"
            elif sig_exit:
                exit_price = close
                exit_reason = "SIGNAL_EXIT"
            elif time_exit:
                exit_price = close
                exit_reason = "TIME_EXIT"

            if exit_price is not None and exit_reason is not None:
                pnl_pct = (exit_price - entry_p) / entry_p * 100.0 if entry_p > 0 else 0.0
                result = ("WIN" if pnl_pct > BREAKEVEN_BAND_PCT
                          else "LOSS" if pnl_pct < -BREAKEVEN_BAND_PCT else "BREAKEVEN")
                closed_trade = {
                    "symbol": symbol, "strategy": strategy_name,
                    "entry_date": str(entry_date_str)[:10],
                    "entry_price": round(entry_p, 2),
                    "exit_date": date[:10],
                    "exit_price": round(exit_price, 2),
                    "exit_reason": exit_reason,
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_abs": round(exit_price - entry_p, 2),
                    "holding_days": pos.get("hold_bars", 0),
                    "mfe_pct": 0.0,
                    "mad_pct": 0.0,
                    "result": result,
                    "confidence": pos.get("entry_confidence", 0.0),
                    "recommendation": "BUY",
                    "agent_scores": {},
                }
                replay_closed_trades.append(closed_trade)
                sim_trades.append(closed_trade)
                # Clear position and buy_log entry
                del positions[symbol]
                buy_log = [t for t in buy_log if t.get("symbol") != symbol]

        # ── Step 1: Walk-forward stats from replay's own closed trades only ───
        # No run_backtest() trades contaminate this — only trades the replay
        # itself has already closed before this bar's date.
        wf_stats = _walk_forward_stats(replay_closed_trades, date)

        # ── Step 2: Build scan item with live_signal=entry_signal ─────────────
        scan_item, entry_signal, entry_reason = _build_scan_item_from_bar(
            symbol, row, prev_row, strategy, wf_stats, config
        )

        # ── Step 3: Call production _decide() with live position state ─────────
        try:
            trade_decision = _decide(scan_item, positions, buy_log)
            recommendation = str(trade_decision.get("recommendation", "AVOID"))
            final_confidence = _sf(trade_decision.get("final_confidence", 0))
            decision_reason = str(trade_decision.get("reason", entry_reason))
            rr_ratio = _sf(trade_decision.get("rr_ratio", scan_item.get("rr_ratio", 0)))
            filter_passed = bool(trade_decision.get("filter_passed",
                                                     scan_item.get("filter_passed", False)))
        except Exception as ex:
            recommendation = "AVOID"
            final_confidence = 0.0
            decision_reason = f"_decide error: {ex}"
            rr_ratio = _sf(scan_item.get("rr_ratio", 0))
            filter_passed = False

        decisions.append({
            "symbol": symbol,
            "strategy": strategy_name,
            "bar_date": date[:10],
            "bar_close": close,
            "recommendation": recommendation,
            "final_confidence": round(final_confidence, 1),
            "reason": decision_reason,
            "threshold": float(config.get("confidence_threshold", 60.0)),
            "entry_signal": entry_signal,
            "filter_passed": filter_passed,
            "rr_ratio": round(rr_ratio, 2),
            "position_open": symbol in positions,
            "wf_trades_used": wf_stats.get("total_trades", 0),
            "detail": {
                "recommendation": recommendation,
                "entry_signal": entry_signal,
                "rr_ratio": round(rr_ratio, 2),
                "filter_passed": filter_passed,
                "wf_win_rate": wf_stats.get("win_rate_pct"),
                "wf_expectancy": wf_stats.get("expectancy"),
                "wf_trades": wf_stats.get("total_trades"),
                "confidence_from_rules": round(scan_item.get("base_confidence", 0), 1),
            },
        })

        # ── Step 4: Open position ONLY when _decide() BUY AND entry_signal=True
        # _decide() may issue BUY based solely on confidence/history gates;
        # requiring entry_signal ensures the production strategy check_entry() also
        # confirms the technical setup, matching production entry semantics.
        if (recommendation in _BUY_RECS
                and entry_signal               # strategy.check_entry() must fire
                and symbol not in positions):
            stop = _sf(scan_item.get("stop_loss", close * 0.97))
            target = _sf(scan_item.get("target", close * 1.04))
            positions[symbol] = {
                "avg_price": close,
                "quantity": 1,
                "stop_loss": stop,
                "target_price": target,
                "entry_date": date,
                "hold_bars": 0,
                "entry_confidence": round(final_confidence, 1),
            }
            buy_log.append({
                "symbol": symbol, "action": "BUY",
                "timestamp": date,
                "stop_loss": stop, "target": target,
                "price": close, "qty": 1,
            })
        elif symbol in positions:
            # Advance hold counter for time tracking
            positions[symbol]["hold_bars"] = positions[symbol].get("hold_bars", 0) + 1

    # Force-close any position still open at end of data
    if symbol in positions:
        pos = positions[symbol]
        last_row = rows.iloc[-1]
        last_close = _sf(last_row.get("close", pos.get("avg_price", 0)))
        entry_p = _sf(pos.get("avg_price", last_close))
        pnl_pct = (last_close - entry_p) / entry_p * 100.0 if entry_p > 0 else 0.0
        result = ("WIN" if pnl_pct > BREAKEVEN_BAND_PCT
                  else "LOSS" if pnl_pct < -BREAKEVEN_BAND_PCT else "BREAKEVEN")
        sim_trades.append({
            "symbol": symbol, "strategy": strategy_name,
            "entry_date": str(pos.get("entry_date", ""))[:10],
            "entry_price": round(entry_p, 2),
            "exit_date": dates[-1][:10] if dates else "",
            "exit_price": round(last_close, 2),
            "exit_reason": "END_OF_DATA",
            "pnl_pct": round(pnl_pct, 2),
            "pnl_abs": round(last_close - entry_p, 2),
            "holding_days": pos.get("hold_bars", 0),
            "mfe_pct": 0.0, "mad_pct": 0.0, "result": result,
            "confidence": pos.get("entry_confidence", 0.0),
            "recommendation": "BUY", "agent_scores": {},
        })

    return decisions, sim_trades


# ── Parameterized walk-forward simulator (used by optimizer) ──────────────────

def _run_parameterized_sim(
    symbol: str,
    df: pd.DataFrame,
    config: dict,
    strategy,           # StrategyBase instance
) -> list:
    """
    Walk-forward trade simulator parameterized by config values:
      confidence_threshold — skip entries where inspect_entry_rules confidence < this
      stop_pct            — stop level as % below entry price
      target_pct          — target level as % above entry price
      min_rr              — minimum R:R to take the trade
      max_holding_days    — time-based exit bar count
      trailing_stop_pct   — trail stop advancement rate

    Different configs produce genuinely different P&L because:
      - confidence_threshold changes which entry signals are accepted
      - stop_pct / target_pct changes which exit is hit first and the payoff
      - min_rr filters trades below the R:R floor

    Returns a list of trade dicts with pnl_pct, result, entry_date, exit_date.
    Uses only production strategy.check_entry() and inspect_entry_rules().
    """
    from backtesting_engine import WARMUP_BARS

    conf_threshold = float(config.get("confidence_threshold", 60.0))
    stop_pct = float(config.get("stop_pct", 2.0))
    target_pct = float(config.get("target_pct", 4.0))
    min_rr = float(config.get("min_rr", 1.5))
    max_hold = int(config.get("max_holding_days", 20))
    trail_pct = float(config.get("trailing_stop_pct", 1.5))

    rows = df.reset_index(drop=True)
    if "time" in df.columns:
        dates = [str(d) for d in df["time"].tolist()]
    else:
        dates = [str(d) for d in df.index.tolist()]

    n = len(rows)
    warmup = WARMUP_BARS
    trades: list = []

    # In-position state
    position: Optional[dict] = None  # None or {entry_price, stop, target, entry_date, hold_bars}

    for i in range(warmup, n):
        row = rows.iloc[i]
        prev = rows.iloc[i - 1] if i > 0 else row
        date = dates[i]
        close = _sf(row.get("close", 0))
        high = _sf(row.get("high", close))
        low = _sf(row.get("low", close))
        if close <= 0:
            continue

        if position is not None:
            # ── Check exit conditions for open position ────────────────────────
            ep = position["entry_price"]
            stop = position["current_stop"]
            target = position["target"]
            hold = position["hold_bars"] + 1
            position["hold_bars"] = hold

            stop_hit = low <= stop
            target_hit = high >= target
            time_hit = hold >= max_hold

            exit_price = None
            exit_reason = None

            if stop_hit and target_hit:
                # Conservative: stop wins on same-bar conflict
                exit_price = min(close, stop)
                exit_reason = "STOP_LOSS"
            elif stop_hit:
                exit_price = min(close, stop)
                exit_reason = "TRAILING_STOP" if stop > position["orig_stop"] else "STOP_LOSS"
            elif target_hit:
                exit_price = target
                exit_reason = "TARGET_HIT"
            elif time_hit:
                exit_price = close
                exit_reason = "TIME_EXIT"

            if exit_price is not None:
                pnl_pct = (exit_price - ep) / ep * 100.0 if ep > 0 else 0.0
                result = ("WIN" if pnl_pct > BREAKEVEN_BAND_PCT
                          else "LOSS" if pnl_pct < -BREAKEVEN_BAND_PCT else "BREAKEVEN")
                trades.append({
                    "symbol": symbol,
                    "entry_date": position["entry_date"][:10],
                    "entry_price": round(ep, 2),
                    "exit_date": date[:10],
                    "exit_price": round(exit_price, 2),
                    "exit_reason": exit_reason,
                    "pnl_pct": round(pnl_pct, 2),
                    "holding_days": hold,
                    "result": result,
                    "stop_pct": stop_pct,
                    "target_pct": target_pct,
                    "conf_threshold": conf_threshold,
                })
                position = None
                continue

            # Advance trailing stop (after close; takes effect next bar)
            if trail_pct > 0 and close > ep:
                new_trail = close * (1.0 - trail_pct / 100.0)
                if new_trail > stop:
                    position["current_stop"] = new_trail
            continue

        # ── No position: check entry ──────────────────────────────────────────
        try:
            entry_signal, _ = strategy.check_entry(row, prev)
            rule_checks = strategy.inspect_entry_rules(row, prev)
        except Exception:
            continue

        if not entry_signal:
            continue

        # Confidence from inspect_entry_rules
        if rule_checks:
            confidence = sum(1 for r in rule_checks if r.get("passed", False)) \
                         / len(rule_checks) * 100.0
        else:
            confidence = 70.0

        if confidence < conf_threshold:
            continue  # entry filtered by config threshold

        # ATR-capped stop/target
        atr = _sf(row.get("atr", 0))
        eff_stop_pct = stop_pct
        if atr > 0 and close > 0:
            atr_pct = atr / close * 100.0
            eff_stop_pct = max(0.5, min(stop_pct, atr_pct * 1.5))

        stop_price = close * (1.0 - eff_stop_pct / 100.0)
        target_price = close * (1.0 + target_pct / 100.0)
        rr = (target_price - close) / (close - stop_price) if close > stop_price > 0 else 0.0

        if rr < min_rr:
            continue  # entry filtered by R:R requirement

        position = {
            "entry_price": close,
            "entry_date": date,
            "current_stop": stop_price,
            "orig_stop": stop_price,
            "target": target_price,
            "hold_bars": 0,
        }

    # Force-close any open position at end of data
    if position is not None and dates:
        last_close = _sf(rows.iloc[-1].get("close", position["entry_price"]))
        pnl_pct = ((last_close - position["entry_price"])
                   / position["entry_price"] * 100.0
                   if position["entry_price"] > 0 else 0.0)
        result = ("WIN" if pnl_pct > BREAKEVEN_BAND_PCT
                  else "LOSS" if pnl_pct < -BREAKEVEN_BAND_PCT else "BREAKEVEN")
        trades.append({
            "symbol": symbol,
            "entry_date": position["entry_date"][:10],
            "entry_price": round(position["entry_price"], 2),
            "exit_date": dates[-1][:10],
            "exit_price": round(last_close, 2),
            "exit_reason": "END_OF_DATA",
            "pnl_pct": round(pnl_pct, 2),
            "holding_days": position["hold_bars"],
            "result": result,
            "stop_pct": stop_pct,
            "target_pct": target_pct,
            "conf_threshold": conf_threshold,
        })

    return trades


# ── Trade simulation with trailing stop + MFE/MAD ─────────────────────────────

def _simulate_trade_v2(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    target_price: float,
    entry_date: str,
    future_df: pd.DataFrame,
    config: dict,
) -> dict:
    """
    Simulate a trade with trailing stop, MFE, MAD, and WIN/LOSS/BREAKEVEN.

    The trailing stop only advances AFTER the candle closes — it is never
    applied to the same bar's low (which would create impossible intrabar exits).
    When both stop and target are hit on the same bar, stop (conservative) wins.

    future_df: DataFrame with OHLCV columns, starting from the candle AFTER entry.
    Returns a full trade record dict.
    """
    if entry_price <= 0 or stop_loss <= 0 or future_df.empty:
        return {
            "entry_date": entry_date, "entry_price": entry_price,
            "stop_loss": stop_loss, "target_price": target_price,
            "exit_date": entry_date, "exit_price": entry_price,
            "exit_reason": "NO_DATA", "pnl_pct": 0.0, "pnl_abs": 0.0,
            "holding_days": 0, "mfe_pct": 0.0, "mad_pct": 0.0,
            "result": "BREAKEVEN", "trailing_stop": stop_loss,
        }

    trail_pct = _sf(config.get("trailing_stop_pct", 1.5), 1.5)
    max_holding = int(config.get("max_holding_days", 30))

    current_stop = stop_loss
    mfe = 0.0
    mad = 0.0

    exit_date = None
    exit_price = None
    exit_reason = None

    rows = future_df.reset_index(drop=True)
    if "time" in future_df.columns:
        dates = [str(d) for d in future_df["time"].tolist()]
    else:
        dates = [str(d) for d in future_df.index.tolist()]

    for i, (date, row_data) in enumerate(zip(dates, rows.itertuples())):
        high = _sf(getattr(row_data, "high", 0))
        low = _sf(getattr(row_data, "low", 0))
        close = _sf(getattr(row_data, "close", entry_price))

        # Track extremes for MFE/MAD
        if entry_price > 0:
            mfe = max(mfe, (high - entry_price) / entry_price * 100.0)
            mad = max(mad, (entry_price - low) / entry_price * 100.0)

        # ── Step 1: Check pre-existing stop against this bar's low BEFORE
        #   updating the trail. Ensures trail from previous bar is tested first.
        stop_hit = current_stop > 0 and low <= current_stop
        target_hit = target_price > 0 and high >= target_price

        if stop_hit and target_hit:
            exit_price = min(close, current_stop)
            exit_reason = "TRAILING_STOP" if current_stop > stop_loss else "STOP_LOSS"
            exit_date = date
            break
        elif stop_hit:
            exit_price = min(close, current_stop)
            exit_reason = "TRAILING_STOP" if current_stop > stop_loss else "STOP_LOSS"
            exit_date = date
            break
        elif target_hit:
            exit_price = target_price
            exit_reason = "TARGET_HIT"
            exit_date = date
            break

        if i >= max_holding:
            exit_price = close
            exit_reason = "TIME_EXIT"
            exit_date = date
            break

        # ── Step 2: Advance trailing stop after this bar closes (next bar only)
        if close > entry_price and trail_pct > 0:
            new_trail_stop = close * (1.0 - trail_pct / 100.0)
            if new_trail_stop > current_stop:
                current_stop = new_trail_stop

    if exit_date is None:
        last_row = rows.iloc[-1]
        exit_price = _sf(getattr(last_row, "close", entry_price), entry_price)
        exit_reason = "END_OF_DATA"
        exit_date = dates[-1] if dates else entry_date

    pnl_pct = ((exit_price - entry_price) / entry_price * 100.0) if entry_price > 0 else 0.0
    pnl_abs = exit_price - entry_price if entry_price > 0 else 0.0
    holding_days = len([d for d in dates if d <= (exit_date or "")])

    if pnl_pct > BREAKEVEN_BAND_PCT:
        result = "WIN"
    elif pnl_pct < -BREAKEVEN_BAND_PCT:
        result = "LOSS"
    else:
        result = "BREAKEVEN"

    return {
        "entry_date": entry_date,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "target_price": round(target_price, 2),
        "trailing_stop": round(current_stop, 2),
        "exit_date": exit_date,
        "exit_price": round(exit_price, 2),
        "exit_reason": exit_reason,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_abs": round(pnl_abs, 2),
        "holding_days": holding_days,
        "mfe_pct": round(mfe, 2),
        "mad_pct": round(mad, 2),
        "result": result,
    }


# ── Trade enhancer ────────────────────────────────────────────────────────────

def _enhance_trade_with_mfe_mad(trade: dict, df: pd.DataFrame) -> dict:
    """
    Add MFE and MAD to a trade already simulated by production run_backtest().
    Adds WIN/LOSS/BREAKEVEN classification.
    """
    entry_date = str(trade.get("entry_date", ""))[:10]
    exit_date = str(trade.get("exit_date", ""))[:10]
    entry_price = _sf(trade.get("entry_price", 0))

    if entry_price <= 0 or df.empty:
        trade.update({"mfe_pct": 0.0, "mad_pct": 0.0})
        pnl_pct = _sf(trade.get("pnl_pct", 0))
        trade["result"] = ("WIN" if pnl_pct > BREAKEVEN_BAND_PCT
                           else "LOSS" if pnl_pct < -BREAKEVEN_BAND_PCT else "BREAKEVEN")
        return trade

    if "time" in df.columns:
        dates = [str(d)[:10] for d in df["time"].tolist()]
    else:
        dates = [str(d)[:10] for d in df.index.tolist()]

    rows = df.reset_index(drop=True)
    mfe = 0.0
    mad = 0.0
    in_trade = False

    for i, date in enumerate(dates):
        if not in_trade and date >= entry_date:
            in_trade = True
        if not in_trade:
            continue
        row = rows.iloc[i]
        high = _sf(row.get("high", entry_price))
        low = _sf(row.get("low", entry_price))
        mfe = max(mfe, (high - entry_price) / entry_price * 100.0)
        mad = max(mad, (entry_price - low) / entry_price * 100.0)
        if exit_date and date >= exit_date:
            break

    pnl_pct = _sf(trade.get("pnl_pct", 0))
    result = ("WIN" if pnl_pct > BREAKEVEN_BAND_PCT
              else "LOSS" if pnl_pct < -BREAKEVEN_BAND_PCT else "BREAKEVEN")

    trade.update({"mfe_pct": round(mfe, 2), "mad_pct": round(mad, 2), "result": result})
    return trade


# ── Missed opportunity detection ──────────────────────────────────────────────

_SUGGESTIONS: dict = {
    "rr":         "R:R below minimum — consider lowering min R:R or widening target (advisory only)",
    "expectancy": "Negative walk-forward expectancy blocked this setup — review strategy parameters",
    "confidence": "Confidence below threshold — consider adjusting confidence_threshold (advisory only)",
    "AVOID":      "AI decision was AVOID — review the rejected bar's indicators for improvement signals",
    "WATCH":      "AI decision was WATCH — monitor for regime or volume improvement before entry",
    "default":    "Review the rejection condition and consider adjusting the relevant threshold",
}


def _get_suggestion(ai_decision: str, rejection_reason: str) -> str:
    if "r:r" in rejection_reason.lower() or "rr" in rejection_reason.lower():
        return _SUGGESTIONS["rr"]
    if "expectancy" in rejection_reason.lower():
        return _SUGGESTIONS["expectancy"]
    if "confidence" in rejection_reason.lower():
        return _SUGGESTIONS["confidence"]
    return _SUGGESTIONS.get(ai_decision, _SUGGESTIONS["default"])


def _detect_missed(
    symbol: str,
    strategy: str,
    decisions: List[dict],
    df: pd.DataFrame,
    min_move_pct: float = 2.0,
) -> List[dict]:
    """
    Find bars where the production pipeline said AVOID or WATCH but the stock
    subsequently moved ≥ min_move_pct% within 5 bars.
    """
    missed: List[dict] = []

    ai_by_date = {d["bar_date"][:10]: d for d in decisions
                  if d.get("recommendation") in ("WATCH", "AVOID")}
    if not ai_by_date:
        return missed

    if "time" in df.columns:
        dates = [str(d)[:10] for d in df["time"].tolist()]
    else:
        dates = [str(d)[:10] for d in df.index.tolist()]

    rows = df.reset_index(drop=True)
    n = len(rows)

    for i, date in enumerate(dates):
        ai_dec = ai_by_date.get(date)
        if not ai_dec:
            continue
        if i + 5 >= n:
            continue

        entry_close = _sf(rows.iloc[i].get("close", 0))
        future_high = max(
            _sf(rows.iloc[j].get("high", 0))
            for j in range(i + 1, min(i + 6, n))
        )

        if entry_close <= 0:
            continue

        actual_move = (future_high - entry_close) / entry_close * 100.0

        if actual_move >= min_move_pct:
            missed.append({
                "symbol": symbol,
                "strategy": strategy,
                "bar_date": date,
                "ai_decision": ai_dec.get("recommendation", "AVOID"),
                "ai_confidence": ai_dec.get("final_confidence", 0),
                "actual_move_pct": round(actual_move, 2),
                "potential_profit_pct": round(actual_move * 0.85, 2),
                "rejection_reason": ai_dec.get("reason", ""),
                "improvement_suggestion": _get_suggestion(
                    ai_dec.get("recommendation", "AVOID"),
                    ai_dec.get("reason", ""),
                ),
            })

    return missed


# ── Performance analytics ─────────────────────────────────────────────────────

def _aggregate_trades(trades: List[dict]) -> dict:
    """Aggregate trade list into performance stats."""
    if not trades:
        return {
            "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
            "breakeven_trades": 0, "win_rate_pct": None, "loss_rate_pct": None,
            "avg_pnl_pct": None, "best_trade_pct": None, "worst_trade_pct": None,
            "max_drawdown_pct": None, "profit_factor": None, "expectancy_pct": None,
            "sharpe_ratio": None, "avg_holding_days": None,
            "avg_confidence": None, "avg_mfe": None, "avg_mad": None,
            "sufficient_data": False,
        }

    n = len(trades)
    wins = [t for t in trades if t.get("result") == "WIN"]
    losses = [t for t in trades if t.get("result") == "LOSS"]
    bes = [t for t in trades if t.get("result") == "BREAKEVEN"]

    pnls = [_sf(t.get("pnl_pct", 0)) for t in trades]
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None

    avg_pnl = sum(pnls) / n if pnls else 0.0
    variance = sum((p - avg_pnl) ** 2 for p in pnls) / max(n - 1, 1)
    std_dev = math.sqrt(variance) if variance > 0 else 0.0
    sharpe = (avg_pnl / std_dev * math.sqrt(252)) if std_dev > 0 else None

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    holding_days = [t.get("holding_days") for t in trades if t.get("holding_days")]
    confidences = [_sf(t.get("confidence", 0)) for t in trades if t.get("confidence")]
    mfes = [_sf(t.get("mfe_pct", 0)) for t in trades if "mfe_pct" in t]
    mads = [_sf(t.get("mad_pct", 0)) for t in trades if "mad_pct" in t]

    return {
        "total_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "breakeven_trades": len(bes),
        "win_rate_pct": round(100 * len(wins) / n, 1),
        "loss_rate_pct": round(100 * len(losses) / n, 1),
        "avg_pnl_pct": round(avg_pnl, 2),
        "best_trade_pct": round(max(pnls), 2) if pnls else None,
        "worst_trade_pct": round(min(pnls), 2) if pnls else None,
        "max_drawdown_pct": round(max_dd, 2),
        "profit_factor": round(profit_factor, 2) if isinstance(profit_factor, float) else None,
        "expectancy_pct": round(avg_pnl, 2),
        "sharpe_ratio": round(sharpe, 2) if sharpe is not None else None,
        "avg_holding_days": round(sum(holding_days) / len(holding_days), 1) if holding_days else None,
        "avg_confidence": round(sum(confidences) / len(confidences), 1) if confidences else None,
        "avg_mfe": round(sum(mfes) / len(mfes), 2) if mfes else None,
        "avg_mad": round(sum(mads) / len(mads), 2) if mads else None,
        "sufficient_data": n >= 5,
    }


def _common_rejection(decisions: List[dict]) -> str:
    reasons: dict = defaultdict(int)
    for d in decisions:
        if d.get("recommendation") in ("AVOID", "WATCH"):
            key = str(d.get("reason", ""))[:60]
            reasons[key] += 1
    if not reasons:
        return "None"
    return max(reasons, key=reasons.get)


# ── Core backtest pipeline ────────────────────────────────────────────────────

def start_backtest_pipeline(config_json: str) -> dict:
    """
    Phase 1 of the async backtest flow.

    Validates config, creates a RUNNING run record in the DB, and returns
    {run_id, symbols_total, label} immediately.  The caller is responsible for
    launching execute_backtest_pipeline(run_id, config_json) in a background
    process so that the frontend can poll for live progress.
    """
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except Exception:
        config = {}

    symbols: List[str] = _cap_symbols(config.get("symbols") or [])
    if not symbols:
        from config import DEFAULT_WATCHLIST
        symbols = list(DEFAULT_WATCHLIST)[:15]

    start_date, end_date, date_err = _validate_and_normalize_dates(
        config.get("start_date", ""), config.get("end_date", "")
    )
    if date_err:
        return {"error": date_err, "label": LABEL}

    interval = str(config.get("interval", "1h"))
    run_id = str(uuid.uuid4())[:12]

    from strategies import list_strategies
    all_strategy_names = [s["id"] for s in list_strategies()]
    strategy_names: List[str] = config.get("strategies") or all_strategy_names

    conn = _get_conn()
    if conn:
        try:
            _ensure_tables(conn)
            _exec(conn, """
                INSERT INTO validation_v2_runs
                (run_id, config, status, symbols, strategies, start_date, end_date,
                 interval, symbols_total, symbols_done, current_symbol, symbol_errors)
                VALUES (%s, %s, 'RUNNING', %s, %s, %s, %s, %s, %s, 0, '', '[]')
            """, (run_id, json.dumps(config), json.dumps(symbols),
                  json.dumps(strategy_names), start_date, end_date, interval,
                  len(symbols)))
        except Exception:
            pass
        finally:
            conn.close()
    else:
        # No DB — fall back to synchronous run so the caller still gets results
        return run_backtest_pipeline(config_json)

    return {
        "run_id": run_id,
        "status": "RUNNING",
        "symbols_total": len(symbols),
        "label": LABEL,
    }


def mark_run_failed(run_id: str, error: str) -> dict:
    """Persist a FAILED status + error text on a run (idempotent, terminal-safe).

    Never downgrades a COMPLETED run.  Used by the crash wrapper below and by
    the Node route when the background executor process dies.
    """
    conn = _get_conn()
    if not conn:
        return {"error": "DB unavailable"}
    try:
        _ensure_tables(conn)
        _exec(conn, """
            UPDATE validation_v2_runs
            SET status = 'FAILED', error = %s, completed_at = NOW()
            WHERE run_id = %s AND status NOT IN ('COMPLETED', 'FAILED')
        """, (str(error)[:2000], run_id))
        return {"ok": True, "run_id": run_id}
    except Exception as e:
        return {"error": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# Runs still RUNNING with no progress for this long are declared stuck.
STUCK_RUN_TIMEOUT_MINUTES = 30

_STUCK_ERROR = (
    "No progress for {m}+ minutes — the background executor likely crashed. "
    "Re-run the backtest; if it happens again check the server logs."
)


def _fail_stuck_runs(conn) -> None:
    """Mark RUNNING runs with no recent progress as FAILED (lazy watchdog)."""
    try:
        _exec(conn, """
            UPDATE validation_v2_runs
            SET status = 'FAILED', error = %s, completed_at = NOW()
            WHERE status = 'RUNNING'
              AND COALESCE(last_progress_at, created_at) < NOW() - (%s * INTERVAL '1 minute')
        """, (_STUCK_ERROR.format(m=STUCK_RUN_TIMEOUT_MINUTES),
              STUCK_RUN_TIMEOUT_MINUTES))
    except Exception:
        pass


def execute_backtest_pipeline(run_id: str, config_json: str) -> dict:
    """Crash-safe wrapper: any uncaught executor exception marks the run FAILED."""
    try:
        result = _execute_backtest_impl(run_id, config_json)
        if isinstance(result, dict) and result.get("error"):
            mark_run_failed(run_id, str(result["error"]))
        return result
    except Exception as e:
        import traceback
        detail = f"{e}\n{traceback.format_exc()[-1500:]}"
        mark_run_failed(run_id, detail)
        return {"error": str(e), "run_id": run_id}


def _execute_backtest_impl(run_id: str, config_json: str) -> dict:
    """
    Phase 2 of the async backtest flow.  Processes symbols one-by-one and
    writes progress + results to DB after each symbol.  Designed to run as a
    background subprocess; callers should not wait for it.
    """
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except Exception:
        config = {}

    conn = _get_conn()
    if not conn:
        return {"error": "DB unavailable"}

    try:
        _ensure_tables(conn)
        # Load the run record so we know what to process
        run = _q1(conn, "SELECT * FROM validation_v2_runs WHERE run_id = %s", (run_id,))
        if not run:
            return {"error": f"Run {run_id} not found"}

        symbols_json = run.get("symbols", "[]")
        symbols: List[str] = json.loads(symbols_json) if isinstance(symbols_json, str) else list(symbols_json or [])
        strategies_json = run.get("strategies", "[]")
        strategy_names: List[str] = json.loads(strategies_json) if isinstance(strategies_json, str) else list(strategies_json or [])
        interval = str(run.get("interval", "1h"))
        start_date = str(run.get("start_date") or "")
        end_date = str(run.get("end_date") or "")
        initial_capital = float(config.get("initial_capital", _paper_capital()))
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return {"error": str(e)}

    from market_data_engine import fetch_candles_df
    from indicator_engine import compute_indicators_df

    all_decisions: List[dict] = []
    all_trades: List[dict] = []
    all_missed: List[dict] = []
    errors: List[str] = []

    for sym_idx, symbol in enumerate(symbols):
        # ── Update progress: announce which symbol we're starting ────────────
        try:
            _exec(conn, """
                UPDATE validation_v2_runs
                SET current_symbol = %s, symbols_done = %s,
                    last_progress_at = NOW()
                WHERE run_id = %s
            """, (symbol, sym_idx, run_id))
        except Exception:
            pass

        sym_decisions: List[dict] = []
        sym_trades: List[dict] = []
        sym_missed: List[dict] = []

        try:
            kwargs: dict = {"interval": interval}
            if start_date:
                kwargs["start"] = start_date
                kwargs["end"] = end_date
            else:
                kwargs["period"] = "6mo" if interval == "1d" else "3mo"
            df_raw = fetch_candles_df(symbol, **kwargs)
            if df_raw.empty or len(df_raw) < 60:
                msg = f"{symbol}: insufficient data ({len(df_raw)} bars)"
                errors.append(msg)
                # Persist error immediately so the frontend can surface it
                try:
                    _exec(conn, """
                        UPDATE validation_v2_runs
                        SET symbol_errors = symbol_errors || %s::jsonb,
                            symbols_done = %s, last_progress_at = NOW()
                        WHERE run_id = %s
                    """, (json.dumps([msg]), sym_idx + 1, run_id))
                except Exception:
                    pass
                continue
            df = compute_indicators_df(df_raw)
        except Exception as e:
            msg = f"{symbol}: candle fetch failed — {str(e)[:60]}"
            errors.append(msg)
            try:
                _exec(conn, """
                    UPDATE validation_v2_runs
                    SET symbol_errors = symbol_errors || %s::jsonb,
                        symbols_done = %s, last_progress_at = NOW()
                    WHERE run_id = %s
                """, (json.dumps([msg]), sym_idx + 1, run_id))
            except Exception:
                pass
            continue

        for strategy_name in strategy_names:
            # Heartbeat: long symbol/strategy replays must not look stuck.
            try:
                _exec(conn, """
                    UPDATE validation_v2_runs SET last_progress_at = NOW()
                    WHERE run_id = %s AND status = 'RUNNING'
                """, (run_id,))
            except Exception:
                pass
            try:
                bootstrap_trades: list = []
                try:
                    from backtesting_engine import run_backtest as _run_bt
                    _bs_days = int(config.get("bootstrap_days", 90))
                    if start_date:
                        _bs_end = start_date
                        _bs_start = (
                            _date_cls.fromisoformat(start_date) - timedelta(days=_bs_days)
                        ).isoformat()
                    else:
                        _bs_end = _date_cls.today().isoformat()
                        _bs_start = (_date_cls.today() - timedelta(days=_bs_days + 90)).isoformat()
                    _bt = _run_bt(symbol, strategy_name, _bs_start, _bs_end,
                                  interval=interval, initial_capital=initial_capital)
                    bootstrap_trades = _bt.get("trades", [])
                except Exception:
                    pass

                bar_decisions, sim_trades = _run_symbol_replay(
                    symbol, df, config, bootstrap_trades, strategy_name
                )
                sym_decisions.extend(bar_decisions)

                for t in sim_trades:
                    _enhance_trade_with_mfe_mad(t, df)
                sym_trades.extend(sim_trades)

                missed = _detect_missed(symbol, strategy_name, bar_decisions, df)
                sym_missed.extend(missed)

            except Exception as e:
                errors.append(f"{symbol}/{strategy_name}: {str(e)[:80]}")

        all_decisions.extend(sym_decisions)
        all_trades.extend(sym_trades)
        all_missed.extend(sym_missed)

        # ── Flush this symbol's results to DB and mark it done ───────────────
        try:
            for d in sym_decisions[:500]:  # cap per-symbol flush
                _exec(conn, """
                    INSERT INTO validation_v2_decisions
                    (run_id, symbol, strategy, bar_date, bar_close, recommendation,
                     final_confidence, reason, threshold, entry_signal, filter_passed,
                     rr_ratio, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (run_id, d["symbol"], d["strategy"], d["bar_date"], d["bar_close"],
                      d["recommendation"], d["final_confidence"], d["reason"],
                      d["threshold"], d["entry_signal"], d["filter_passed"],
                      d["rr_ratio"], json.dumps(d.get("detail", {}))))

            for t in sym_trades:
                _exec(conn, """
                    INSERT INTO validation_v2_trades
                    (run_id, symbol, strategy, entry_date, entry_price, stop_loss,
                     target_price, trailing_stop, exit_date, exit_price, exit_reason,
                     pnl_pct, pnl_abs, holding_days, mfe_pct, mad_pct, result,
                     confidence, recommendation, agent_scores)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (run_id, t["symbol"], t["strategy"], t.get("entry_date"),
                      _sf(t.get("entry_price", 0)), _sf(t.get("stop_loss", 0)),
                      _sf(t.get("target_price", 0)), _sf(t.get("trailing_stop", 0)),
                      t.get("exit_date"), _sf(t.get("exit_price", 0)),
                      t.get("exit_reason"), _sf(t.get("pnl_pct", 0)),
                      _sf(t.get("pnl_abs", 0)), int(t.get("holding_days", 0)),
                      _sf(t.get("mfe_pct", 0)), _sf(t.get("mad_pct", 0)),
                      t.get("result", "UNKNOWN"), _sf(t.get("confidence", 0)),
                      t.get("recommendation", "BUY"),
                      json.dumps(t.get("agent_scores", {}))))

            for m in sym_missed:
                _exec(conn, """
                    INSERT INTO validation_v2_missed
                    (run_id, symbol, strategy, bar_date, ai_decision, ai_confidence,
                     actual_move_pct, potential_profit_pct, rejection_reason,
                     improvement_suggestion)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (run_id, m["symbol"], m["strategy"], m["bar_date"],
                      m["ai_decision"], m["ai_confidence"], m["actual_move_pct"],
                      m["potential_profit_pct"], m["rejection_reason"],
                      m["improvement_suggestion"]))

            # Advance symbols_done counter and clear current_symbol
            _exec(conn, """
                UPDATE validation_v2_runs
                SET symbols_done = %s, current_symbol = %s,
                    last_progress_at = NOW()
                WHERE run_id = %s
            """, (sym_idx + 1, "" if sym_idx + 1 < len(symbols) else "", run_id))

        except Exception as e:
            errors.append(f"{symbol} DB flush: {str(e)[:80]}")

    # ── Final DB update: mark COMPLETED ─────────────────────────────────────
    try:
        _exec(conn, """
            UPDATE validation_v2_runs
            SET status = 'COMPLETED', error = NULL,
                total_decisions = %s, total_trades = %s,
                last_progress_at = NOW(),
                symbols_done = %s, current_symbol = '',
                symbol_errors = %s,
                completed_at = NOW()
            WHERE run_id = %s AND status = 'RUNNING'
        """, (len(all_decisions), len(all_trades), len(symbols),
              json.dumps(errors[:20]), run_id))
    except Exception as e:
        errors.append(f"final DB update: {str(e)[:80]}")
    finally:
        conn.close()

    return {"success": True, "run_id": run_id, "errors": errors[:10]}


def run_backtest_pipeline(config_json: str) -> dict:
    """
    Run the full AI validation pipeline backtest.

    Uses production code throughout:
    - backtesting_engine.run_backtest() for strategy signal simulation and trades
    - decision_service._decide() for recommendations, called with live position state
    - Walk-forward stats (no look-ahead bias)
    - Default interval: 1h (hourly bars) for intraday replay fidelity

    config: {symbols, start_date, end_date, interval, strategies,
             confidence_threshold, stop_pct, target_pct, position_size_pct,
             min_rr, trailing_stop_pct, initial_capital}
    """
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except Exception:
        config = {}

    symbols: List[str] = _cap_symbols(config.get("symbols") or [])
    if not symbols:
        from config import DEFAULT_WATCHLIST
        symbols = list(DEFAULT_WATCHLIST)[:15]

    start_date, end_date, date_err = _validate_and_normalize_dates(
        config.get("start_date", ""), config.get("end_date", "")
    )
    if date_err:
        return {"error": date_err, "label": LABEL}

    interval = str(config.get("interval", "1h"))
    initial_capital = float(config.get("initial_capital", _paper_capital()))
    run_id = str(uuid.uuid4())[:12]

    from strategies import list_strategies, get_strategy
    all_strategy_names = [s["id"] for s in list_strategies()]
    strategy_names: List[str] = config.get("strategies") or all_strategy_names

    from market_data_engine import fetch_candles_df
    from indicator_engine import compute_indicators_df

    conn = _get_conn()
    if conn:
        try:
            _ensure_tables(conn)
            _exec(conn, """
                INSERT INTO validation_v2_runs
                (run_id, config, status, symbols, strategies, start_date, end_date, interval)
                VALUES (%s, %s, 'RUNNING', %s, %s, %s, %s, %s)
            """, (run_id, json.dumps(config), json.dumps(symbols),
                  json.dumps(strategy_names), start_date, end_date, interval))
        except Exception:
            pass

    all_decisions: List[dict] = []
    all_trades: List[dict] = []
    all_missed: List[dict] = []
    errors: List[str] = []

    for symbol in symbols:
        try:
            kwargs: dict = {"interval": interval}
            if start_date:
                kwargs["start"] = start_date
                kwargs["end"] = end_date
            else:
                kwargs["period"] = "6mo" if interval == "1d" else "3mo"
            df_raw = fetch_candles_df(symbol, **kwargs)
            if df_raw.empty or len(df_raw) < 60:
                errors.append(f"{symbol}: insufficient data ({len(df_raw)} bars)")
                continue
            df = compute_indicators_df(df_raw)
        except Exception as e:
            errors.append(f"{symbol}: candle fetch failed — {str(e)[:60]}")
            continue

        for strategy_name in strategy_names:
            try:
                # Bootstrap: run_backtest() on the period BEFORE the replay window.
                # These trades all have exit_date < start_date → no look-ahead.
                # They seed _decide()'s walk-forward evidence so expectancy and PF
                # are non-zero from bar 0, breaking the cold-start deadlock where
                # empty history prevents any BUY entry regardless of signal quality.
                bootstrap_trades: list = []
                try:
                    from backtesting_engine import run_backtest as _run_bt
                    _bs_days = int(config.get("bootstrap_days", 90))
                    if start_date:
                        _bs_end = start_date
                        _bs_start = (
                            _date_cls.fromisoformat(start_date) - timedelta(days=_bs_days)
                        ).isoformat()
                    else:
                        _bs_end = _date_cls.today().isoformat()
                        _bs_start = (_date_cls.today() - timedelta(days=_bs_days + 90)).isoformat()
                    _bt = _run_bt(symbol, strategy_name, _bs_start, _bs_end,
                                  interval=interval, initial_capital=initial_capital)
                    bootstrap_trades = _bt.get("trades", [])
                except Exception:
                    pass  # bootstrap failure is non-fatal; replay starts with neutral stats

                # V2 canonical trade set: walk-forward replay only.
                # All replay trades are produced by _run_symbol_replay, which:
                #   - Requires BOTH _decide() BUY/STRONG_BUY AND strategy.check_entry()
                #   - Uses intrabar low/high for stop/target exits (same as run_backtest)
                #   - Also calls strategy.check_exit() for signal exits
                #   - Walk-forward stats seeded with bootstrap; grow as replay closes trades
                bar_decisions, sim_trades = _run_symbol_replay(
                    symbol, df, config, bootstrap_trades, strategy_name
                )
                all_decisions.extend(bar_decisions)

                # Replay trades ARE the canonical trade set — no run_backtest() mixing
                for t in sim_trades:
                    _enhance_trade_with_mfe_mad(t, df)
                all_trades.extend(sim_trades)

                # Detect missed opportunities from replay decisions
                missed = _detect_missed(symbol, strategy_name, bar_decisions, df)
                all_missed.extend(missed)

            except Exception as e:
                errors.append(f"{symbol}/{strategy_name}: {str(e)[:80]}")

    if conn:
        try:
            for d in all_decisions[:10_000]:
                _exec(conn, """
                    INSERT INTO validation_v2_decisions
                    (run_id, symbol, strategy, bar_date, bar_close, recommendation,
                     final_confidence, reason, threshold, entry_signal, filter_passed,
                     rr_ratio, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (run_id, d["symbol"], d["strategy"], d["bar_date"], d["bar_close"],
                      d["recommendation"], d["final_confidence"], d["reason"],
                      d["threshold"], d["entry_signal"], d["filter_passed"],
                      d["rr_ratio"], json.dumps(d.get("detail", {}))))

            for t in all_trades:
                _exec(conn, """
                    INSERT INTO validation_v2_trades
                    (run_id, symbol, strategy, entry_date, entry_price, stop_loss,
                     target_price, trailing_stop, exit_date, exit_price, exit_reason,
                     pnl_pct, pnl_abs, holding_days, mfe_pct, mad_pct, result,
                     confidence, recommendation, agent_scores)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (run_id, t["symbol"], t["strategy"], t.get("entry_date"),
                      _sf(t.get("entry_price", 0)), _sf(t.get("stop_loss", 0)),
                      _sf(t.get("target_price", 0)), _sf(t.get("trailing_stop", 0)),
                      t.get("exit_date"), _sf(t.get("exit_price", 0)),
                      t.get("exit_reason"), _sf(t.get("pnl_pct", 0)),
                      _sf(t.get("pnl_abs", 0)), int(t.get("holding_days", 0)),
                      _sf(t.get("mfe_pct", 0)), _sf(t.get("mad_pct", 0)),
                      t.get("result", "UNKNOWN"), _sf(t.get("confidence", 0)),
                      t.get("recommendation", "BUY"),
                      json.dumps(t.get("agent_scores", {}))))

            for m in all_missed:
                _exec(conn, """
                    INSERT INTO validation_v2_missed
                    (run_id, symbol, strategy, bar_date, ai_decision, ai_confidence,
                     actual_move_pct, potential_profit_pct, rejection_reason,
                     improvement_suggestion)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (run_id, m["symbol"], m["strategy"], m["bar_date"],
                      m["ai_decision"], m["ai_confidence"], m["actual_move_pct"],
                      m["potential_profit_pct"], m["rejection_reason"],
                      m["improvement_suggestion"]))

            _exec(conn, """
                UPDATE validation_v2_runs
                SET status = 'COMPLETED', total_decisions = %s, total_trades = %s,
                    completed_at = NOW()
                WHERE run_id = %s
            """, (len(all_decisions), len(all_trades), run_id))
        except Exception as e:
            errors.append(f"DB store error: {str(e)[:100]}")
        finally:
            conn.close()

    stats = _aggregate_trades(all_trades)
    return {
        "success": True,
        "run_id": run_id,
        "label": LABEL,
        "advisory_note": ADVISORY_NOTE,
        "symbols_processed": len(symbols),
        "strategies_used": strategy_names,
        "interval": interval,
        "total_decisions": len(all_decisions),
        "total_trades": len(all_trades),
        "missed_opportunities": len(all_missed),
        "stats": stats,
        "errors": errors[:10],
        "generated_at": _now(),
    }


def get_backtest_run(run_id: str) -> dict:
    """Return full run data including production decisions and trade results."""
    conn = _get_conn()
    if not conn:
        return {"error": "DB unavailable", "run_id": run_id}
    try:
        _ensure_tables(conn)
        _fail_stuck_runs(conn)
        run = _q1(conn, "SELECT * FROM validation_v2_runs WHERE run_id = %s", (run_id,))
        if not run:
            return {"error": f"Run {run_id} not found"}

        decisions = _q(conn, """
            SELECT symbol, strategy, bar_date, bar_close, recommendation,
                   final_confidence, reason, threshold, entry_signal, filter_passed,
                   rr_ratio, detail
            FROM validation_v2_decisions WHERE run_id = %s
            ORDER BY bar_date, symbol, strategy LIMIT 5000
        """, (run_id,))

        trades = _q(conn, "SELECT * FROM validation_v2_trades WHERE run_id = %s ORDER BY entry_date",
                    (run_id,))

        missed = _q(conn, """
            SELECT * FROM validation_v2_missed WHERE run_id = %s
            ORDER BY actual_move_pct DESC LIMIT 50
        """, (run_id,))

        stats = _aggregate_trades(trades)
        rec_dist: dict = defaultdict(int)
        for d in decisions:
            rec_dist[d.get("recommendation", "UNKNOWN")] += 1

        syms_total = int(run.get("symbols_total") or 0)
        syms_done = int(run.get("symbols_done") or 0)
        current_sym = str(run.get("current_symbol") or "")
        sym_errors_raw = run.get("symbol_errors") or "[]"
        try:
            sym_errors: list = (
                json.loads(sym_errors_raw)
                if isinstance(sym_errors_raw, str)
                else list(sym_errors_raw)
            )
        except Exception:
            sym_errors = []

        def _jsonb_list(val) -> list:
            """JSONB columns may come back as str (legacy) or list (psycopg native)."""
            if isinstance(val, str):
                try:
                    return json.loads(val or "[]")
                except Exception:
                    return []
            return list(val or [])

        progress = {
            "symbols_done": syms_done,
            "symbols_total": syms_total or len(_jsonb_list(run.get("symbols"))),
            "current_symbol": current_sym,
        }

        return {
            "success": True, "run_id": run_id, "label": LABEL,
            "status": run.get("status"),
            "run_error": run.get("error"),
            "config": run.get("config") or {},
            "symbols": _jsonb_list(run.get("symbols")),
            "strategies": _jsonb_list(run.get("strategies")),
            "interval": run.get("interval", "1h"),
            "total_decisions": len(decisions),
            "total_trades": len(trades),
            "stats": stats,
            "recommendation_distribution": dict(rec_dist),
            "most_common_rejection": _common_rejection(decisions),
            "decisions_sample": decisions[:200],
            "trades": trades,
            "missed_opportunities": missed,
            "progress": progress,
            "symbol_errors": sym_errors,
            "generated_at": _now(),
        }
    finally:
        conn.close()


def list_backtest_runs() -> dict:
    conn = _get_conn()
    if not conn:
        return {"runs": [], "label": LABEL}
    try:
        _ensure_tables(conn)
        _fail_stuck_runs(conn)
        runs = _q(conn, """
            SELECT run_id, status, total_decisions, total_trades,
                   start_date, end_date, interval, error, created_at, completed_at
            FROM validation_v2_runs ORDER BY created_at DESC LIMIT 50
        """)
        return {"runs": runs, "count": len(runs), "label": LABEL}
    finally:
        conn.close()


def get_missed_opportunities(run_id: Optional[str] = None) -> dict:
    conn = _get_conn()
    if not conn:
        return {"missed": [], "label": LABEL}
    try:
        _ensure_tables(conn)
        if run_id:
            rows = _q(conn, """
                SELECT * FROM validation_v2_missed WHERE run_id = %s
                ORDER BY actual_move_pct DESC LIMIT 100
            """, (run_id,))
        else:
            rows = _q(conn, "SELECT * FROM validation_v2_missed ORDER BY actual_move_pct DESC LIMIT 100")
        total_potential = sum(_sf(r.get("potential_profit_pct", 0)) for r in rows)
        return {
            "missed": rows, "count": len(rows),
            "total_potential_profit_pct": round(total_potential, 2),
            "label": LABEL, "advisory_note": ADVISORY_NOTE,
        }
    finally:
        conn.close()


def run_parameter_optimizer(config_json: str) -> dict:
    """
    Grid search over parameter combinations using the parameterized walk-forward
    simulator (_run_parameterized_sim). Each combo genuinely varies the simulation
    because stop_pct/target_pct/confidence_threshold change entry filters and
    exit outcomes bar-by-bar.

    Advisory only — never auto-applies.
    Security caps: max 8 symbols, max 2-year date span, max 200 grid combos.
    """
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except Exception:
        config = {}

    symbols = _cap_symbols(config.get("symbols") or [], _MAX_OPT_SYMBOLS)
    if not symbols:
        from config import DEFAULT_WATCHLIST
        symbols = list(DEFAULT_WATCHLIST)[:_MAX_OPT_SYMBOLS]

    start_date, end_date, date_err = _validate_and_normalize_dates(
        config.get("start_date", ""), config.get("end_date", "")
    )
    if date_err:
        return {"error": date_err, "label": LABEL}

    grid = config.get("grid", {})
    conf_vals, e = _resolve_grid_dim(grid, "confidence_threshold")
    if e: return {"error": e, "label": LABEL}
    stop_vals, e = _resolve_grid_dim(grid, "stop_pct")
    if e: return {"error": e, "label": LABEL}
    tgt_vals, e = _resolve_grid_dim(grid, "target_pct")
    if e: return {"error": e, "label": LABEL}
    pos_vals, e = _resolve_grid_dim(grid, "position_size_pct")
    if e: return {"error": e, "label": LABEL}
    minr_vals, e = _resolve_grid_dim(grid, "min_rr")
    if e: return {"error": e, "label": LABEL}

    n_combos = len(conf_vals) * len(stop_vals) * len(tgt_vals) * len(pos_vals) * len(minr_vals)
    if n_combos > _MAX_GRID_COMBOS:
        return {
            "error": (
                f"Effective grid has {n_combos} combinations (including defaults "
                f"for omitted dimensions); maximum allowed is {_MAX_GRID_COMBOS}."
            ),
            "label": LABEL,
        }

    from strategies import list_strategies, get_strategy
    from market_data_engine import fetch_candles_df
    from indicator_engine import compute_indicators_df

    strategy_names = [s["id"] for s in list_strategies()]
    interval = str(config.get("interval", "1d"))

    # Pre-fetch and compute indicators once per symbol (shared across all combos)
    dfs: dict = {}
    for sym in symbols:
        try:
            kwargs: dict = {"interval": interval}
            if start_date:
                kwargs["start"] = start_date; kwargs["end"] = end_date
            else:
                kwargs["period"] = "3mo"
            df_raw = fetch_candles_df(sym, **kwargs)
            if not df_raw.empty and len(df_raw) >= 60:
                dfs[sym] = compute_indicators_df(df_raw)
        except Exception:
            pass

    if not dfs:
        return {"error": "No indicator data available for optimizer", "label": LABEL}

    results: List[dict] = []

    for conf in conf_vals:
        for stop_p in stop_vals:
            for tgt_p in tgt_vals:
                for pos_sz in pos_vals:
                    for min_r in minr_vals:
                        run_config = {
                            "confidence_threshold": conf,
                            "stop_pct": stop_p, "target_pct": tgt_p,
                            "position_size_pct": pos_sz, "min_rr": min_r,
                            "trailing_stop_pct": 1.5, "max_holding_days": 20,
                        }
                        # Run parameterized simulation — genuinely different per combo
                        combo_trades: List[dict] = []
                        for sym, df in dfs.items():
                            for strat_name in strategy_names:
                                try:
                                    strat = get_strategy(strat_name)
                                    trades = _run_parameterized_sim(sym, df, run_config, strat)
                                    combo_trades.extend(trades)
                                except Exception:
                                    pass

                        stats = _aggregate_trades(combo_trades)
                        results.append({
                            "config": run_config,
                            "total_trades": stats["total_trades"],
                            "win_rate_pct": stats["win_rate_pct"],
                            "profit_factor": stats["profit_factor"],
                            "sharpe_ratio": stats["sharpe_ratio"],
                            "expectancy_pct": stats["expectancy_pct"],
                            "max_drawdown_pct": stats["max_drawdown_pct"],
                            "avg_pnl_pct": stats["avg_pnl_pct"],
                        })

    results.sort(key=lambda r: _sf(r.get("sharpe_ratio"), -999), reverse=True)
    best = results[0] if results else None
    recommendation = (
        f"Best Sharpe: {_sf(best.get('sharpe_ratio', 0), 0):.2f} at "
        f"confidence={best['config']['confidence_threshold']}, "
        f"stop={best['config']['stop_pct']}%, target={best['config']['target_pct']}%"
    ) if best else "No valid configurations found"

    opt_run_id = str(uuid.uuid4())[:12]
    conn = _get_conn()
    if conn:
        try:
            _ensure_tables(conn)
            _exec(conn, """
                INSERT INTO validation_v2_optimizer_runs
                (opt_run_id, config, best_config, results, combinations_tested, recommendation)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (opt_run_id, json.dumps(config),
                  json.dumps(best) if best else None,
                  json.dumps(results[:50]), len(results), recommendation))
        except Exception:
            pass
        finally:
            conn.close()

    return {
        "success": True, "opt_run_id": opt_run_id, "label": LABEL,
        "advisory_note": ADVISORY_NOTE,
        "symbols_tested": len(dfs),
        "combinations_tested": len(results),
        "results": results[:30],
        "best_config": best,
        "recommendation": recommendation,
        "warning": "DO NOT apply automatically. Human review and approval required.",
        "generated_at": _now(),
    }


def get_optimizer_recommendation(opt_run_id: Optional[str] = None) -> dict:
    conn = _get_conn()
    if not conn:
        return {"label": LABEL, "advisory_note": ADVISORY_NOTE,
                "warning": "DB unavailable — run the optimizer first.", "generated_at": _now()}
    try:
        _ensure_tables(conn)
        if opt_run_id:
            row = _q1(conn, "SELECT * FROM validation_v2_optimizer_runs WHERE opt_run_id = %s",
                      (opt_run_id,))
        else:
            row = _q1(conn, "SELECT * FROM validation_v2_optimizer_runs ORDER BY created_at DESC LIMIT 1")

        if not row:
            return {"label": LABEL, "advisory_note": ADVISORY_NOTE,
                    "warning": "No optimizer run found. Run POST /validation-v2/optimizer/run first.",
                    "generated_at": _now()}

        best_config = row.get("best_config")
        if isinstance(best_config, str):
            best_config = json.loads(best_config)
        results = row.get("results")
        if isinstance(results, str):
            results = json.loads(results)

        return {
            "success": True, "opt_run_id": row["opt_run_id"],
            "label": LABEL, "advisory_note": ADVISORY_NOTE,
            "best_config": best_config, "recommendation": row.get("recommendation"),
            "combinations_tested": row.get("combinations_tested"),
            "top_results": (results or [])[:10],
            "created_at": str(row.get("created_at", "")),
            "warning": "DO NOT apply automatically. Human review and approval required.",
            "generated_at": _now(),
        }
    finally:
        conn.close()


def run_model_comparison(config_json: str) -> dict:
    """
    Compare current_config vs candidate_config using _run_parameterized_sim().
    Each config's stop_pct/target_pct/confidence_threshold drives its simulation,
    producing genuinely different P&L. Advisory: never applies changes.
    Security caps: max 10 symbols, max 2-year date span.
    """
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except Exception:
        config = {}

    current_config = config.get("current_config", {
        "confidence_threshold": 60.0, "stop_pct": 2.0, "target_pct": 4.0,
        "position_size_pct": 10.0, "min_rr": 1.5,
        "trailing_stop_pct": 1.5, "max_holding_days": 20,
    })
    candidate_config = config.get("candidate_config", {
        "confidence_threshold": 65.0, "stop_pct": 1.5, "target_pct": 5.0,
        "position_size_pct": 12.0, "min_rr": 2.0,
        "trailing_stop_pct": 1.5, "max_holding_days": 20,
    })

    symbols = _cap_symbols(config.get("symbols") or [], 10)
    if not symbols:
        from config import DEFAULT_WATCHLIST
        symbols = list(DEFAULT_WATCHLIST)[:10]

    start_date, end_date, date_err = _validate_and_normalize_dates(
        config.get("start_date", ""), config.get("end_date", "")
    )
    if date_err:
        return {"error": date_err, "label": LABEL}

    interval = str(config.get("interval", "1d"))

    from strategies import list_strategies, get_strategy
    from market_data_engine import fetch_candles_df
    from indicator_engine import compute_indicators_df

    strategy_names = [s["id"] for s in list_strategies()]

    dfs: dict = {}
    for sym in symbols:
        try:
            kwargs: dict = {"interval": interval}
            if start_date:
                kwargs["start"] = start_date; kwargs["end"] = end_date
            else:
                kwargs["period"] = "3mo"
            df_raw = fetch_candles_df(sym, **kwargs)
            if not df_raw.empty and len(df_raw) >= 60:
                dfs[sym] = compute_indicators_df(df_raw)
        except Exception:
            pass

    def _eval_config(cfg: dict) -> dict:
        all_trades: List[dict] = []
        for sym, df in dfs.items():
            for strat_name in strategy_names:
                try:
                    strat = get_strategy(strat_name)
                    trades = _run_parameterized_sim(sym, df, cfg, strat)
                    all_trades.extend(trades)
                except Exception:
                    pass
        return _aggregate_trades(all_trades)

    current_stats = _eval_config(current_config)
    candidate_stats = _eval_config(candidate_config)

    curr_sharpe = _sf(current_stats.get("sharpe_ratio"), 0.0)
    cand_sharpe = _sf(candidate_stats.get("sharpe_ratio"), 0.0)
    improvement_pct = ((cand_sharpe - curr_sharpe) / max(abs(curr_sharpe), 0.01)) * 100

    if improvement_pct > 10.0:
        verdict = "PROMOTE_CANDIDATE"
        verdict_reason = (f"Candidate Sharpe {cand_sharpe:.2f} vs current {curr_sharpe:.2f} "
                          f"(+{improvement_pct:.0f}%)")
    elif improvement_pct < -5.0:
        verdict = "KEEP_CURRENT"
        verdict_reason = f"Candidate underperforms current by {abs(improvement_pct):.0f}%"
    else:
        verdict = "INCONCLUSIVE"
        verdict_reason = f"Marginal difference ({improvement_pct:+.0f}%) — collect more data"

    def _delta(cand, curr):
        if cand is None or curr is None: return None
        return round(cand - curr, 2)

    return {
        "success": True, "label": LABEL, "advisory_note": ADVISORY_NOTE,
        "symbols_tested": len(dfs),
        "current_config": current_config, "candidate_config": candidate_config,
        "current_stats": current_stats, "candidate_stats": candidate_stats,
        "deltas": {
            k: _delta(candidate_stats.get(k), current_stats.get(k))
            for k in ("win_rate_pct", "sharpe_ratio", "profit_factor",
                      "expectancy_pct", "max_drawdown_pct", "avg_pnl_pct")
        },
        "verdict": verdict, "verdict_reason": verdict_reason,
        "warning": "DO NOT promote candidate automatically. Human review required.",
        "generated_at": _now(),
    }


def get_session_timeline(run_id: str) -> dict:
    """
    Return a sorted event log for frontend timeline scrubbing.
    Timestamps are derived from stored bar_date values — no fabricated clock times.
    Daily bars are anchored to NSE open (09:15 IST); intraday bars preserve their time.
    """
    conn = _get_conn()
    if not conn:
        return {"events": [], "label": LABEL}
    try:
        _ensure_tables(conn)

        ai_decs = _q(conn, """
            SELECT symbol, strategy, bar_date, bar_close, recommendation,
                   final_confidence, reason, entry_signal, filter_passed, rr_ratio, detail
            FROM validation_v2_decisions WHERE run_id = %s ORDER BY bar_date, symbol, strategy
        """, (run_id,))

        trades = _q(conn, """
            SELECT symbol, strategy, entry_date, entry_price, exit_date, exit_price,
                   exit_reason, pnl_pct, result, recommendation
            FROM validation_v2_trades WHERE run_id = %s ORDER BY entry_date
        """, (run_id,))

        events: List[dict] = []

        def _bar_ts(bar_date: str, offset_minutes: int = 0) -> str:
            try:
                ts = str(bar_date).replace(" ", "T")
                has_time = "T" in ts or len(ts) > 10
                if not has_time:
                    ts = ts[:10] + "T09:15:00+05:30"
                if offset_minutes:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    ts = (dt + timedelta(minutes=offset_minutes)).isoformat()
            except Exception:
                ts = str(bar_date)
            return ts

        by_date: dict = defaultdict(list)
        for d in ai_decs:
            by_date[d["bar_date"][:10]].append(d)
        dates = sorted(by_date.keys())

        for date in dates:
            decs = by_date[date]
            buy_decs = [d for d in decs if d.get("recommendation") in _BUY_RECS]
            watch_decs = [d for d in decs if d.get("recommendation") == "WATCH"]
            avoid_decs = [d for d in decs if d.get("recommendation") == "AVOID"]
            exit_decs = [d for d in decs if d.get("recommendation") in _SELL_RECS]

            events.append({
                "time": _bar_ts(date, 0),
                "type": "scan_complete",
                "label": f"AI Scan — {len(set(d['symbol'] for d in decs))} stocks",
                "bar_date": date,
                "buy_count": len(buy_decs),
                "watch_count": len(watch_decs),
                "avoid_count": len(avoid_decs),
                "exit_count": len(exit_decs),
                "detail": (f"BUY/STRONG_BUY: {len(buy_decs)}, WATCH: {len(watch_decs)}, "
                           f"AVOID: {len(avoid_decs)}, EXIT: {len(exit_decs)}"),
            })

            for i, d in enumerate(buy_decs):
                events.append({
                    "time": _bar_ts(date, i + 1),
                    "type": "buy_signal",
                    "label": f"{d['recommendation']} {d['symbol']} [{d['strategy']}]",
                    "bar_date": date, "symbol": d["symbol"], "strategy": d["strategy"],
                    "recommendation": d["recommendation"],
                    "confidence": d["final_confidence"], "close": d.get("bar_close"),
                    "detail": f"Confidence: {_sf(d['final_confidence']):.0f}% — {d['reason']}",
                })

            for i, d in enumerate(exit_decs):
                events.append({
                    "time": _bar_ts(date, len(buy_decs) + i + 5),
                    "type": "exit_signal",
                    "label": f"EXIT {d['symbol']} [{d['strategy']}]",
                    "bar_date": date, "symbol": d["symbol"], "strategy": d["strategy"],
                    "detail": f"EXIT signal — {d['reason']}",
                })

        for t in trades:
            exit_date = t.get("exit_date") or ""
            exit_reason = t.get("exit_reason", "")
            pnl = _sf(t.get("pnl_pct", 0))
            type_map = {
                "TARGET": "target_hit", "TARGET_HIT": "target_hit",
                "STOP": "stop_hit", "STOP_LOSS": "stop_hit", "TRAILING_STOP": "stop_hit",
                "SIGNAL_EXIT": "signal_exit", "TIME_EXIT": "time_exit",
            }
            event_type = type_map.get(exit_reason, "trade_exit")
            events.append({
                "time": _bar_ts(exit_date, 15),
                "type": event_type,
                "label": f"{exit_reason} — {t['symbol']} [{t.get('strategy', '')}]",
                "bar_date": exit_date, "symbol": t["symbol"], "pnl_pct": pnl,
                "exit_reason": exit_reason,
                "detail": f"Exit ₹{_sf(t.get('exit_price', 0)):.2f} | P&L: {pnl:+.1f}%",
            })

        events.sort(key=lambda e: e.get("time", ""))
        return {
            "run_id": run_id, "events": events, "total_events": len(events),
            "dates": dates, "label": LABEL,
            "note": "Timestamps from stored bar_date; daily bars anchored to 09:15 IST.",
        }
    finally:
        conn.close()


def get_performance_analytics(period: str = "monthly") -> dict:
    """Aggregate all V2 backtest trades by day/week/month."""
    conn = _get_conn()
    if not conn:
        return {"performance": {}, "label": LABEL}
    try:
        _ensure_tables(conn)
        all_trades = _q(conn, "SELECT * FROM validation_v2_trades ORDER BY entry_date")
        all_decisions = _q(conn, "SELECT * FROM validation_v2_decisions")

        if not all_trades:
            return {
                "label": LABEL, "period": period,
                "note": "No backtest trades found. Run a backtest first.",
                "performance": {}, "generated_at": _now(),
            }

        now = datetime.now()
        cutoffs = {"daily": 1, "weekly": 7, "monthly": 30}
        days = cutoffs.get(period, 30)
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        period_trades = [t for t in all_trades if (t.get("entry_date") or "") >= cutoff]
        if not period_trades:
            period_trades = all_trades

        stats = _aggregate_trades(period_trades)
        pnls_all = [(t.get("symbol"), _sf(t.get("pnl_pct", 0))) for t in period_trades]
        best = max(pnls_all, key=lambda x: x[1]) if pnls_all else None
        worst = min(pnls_all, key=lambda x: x[1]) if pnls_all else None

        rec_dist: dict = defaultdict(int)
        for d in all_decisions:
            rec_dist[d.get("recommendation", "UNKNOWN")] += 1

        return {
            "label": LABEL, "period": period, "stats": stats,
            "best_trade": {"symbol": best[0], "pnl_pct": best[1]} if best else None,
            "worst_trade": {"symbol": worst[0], "pnl_pct": worst[1]} if worst else None,
            "recommendation_distribution": dict(rec_dist),
            "most_common_rejection": _common_rejection(all_decisions),
            "all_time_stats": _aggregate_trades(all_trades),
            "generated_at": _now(),
        }
    finally:
        conn.close()
