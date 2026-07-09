"""
historical_knowledge_builder.py
Sprint 3 — Module 2A: Historical Knowledge Base.

Builds a large historical training dataset by simulating ALL existing
strategies over NIFTY 50 stocks using Yahoo Finance daily data.

Rules:
  - Existing strategy logic is NOT modified (strategies are imported and
    called exactly as the backtesting engine does).
  - Yahoo Finance data ONLY. If a symbol's download fails the symbol is
    skipped and logged — mock data is never used here.
  - Paper/research only. No orders. No lookahead: indicator snapshots are
    taken on the entry bar, market context uses only data up to entry date.

Storage: table `historical_knowledge_trades` in trade_intelligence.db.
Duplicates prevented via UNIQUE(symbol, strategy, entry_date, exit_date).
"""

import json
import math
import os
import sqlite3
from datetime import datetime
from typing import Optional

import pandas as pd

from config import NIFTY_50, INITIAL_CAPITAL, MAX_RISK_PCT
from indicator_engine import compute_indicators_df
from market_data_engine import _fetch_yfinance
from market_scanner import _sector_of
from strategies import get_strategy, LAB_STRATEGY_IDS

DB_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_intelligence.db")
STATUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historical_knowledge_status.json")

WARMUP_BARS = 55   # same warmup as backtesting_engine — indicators need history

RESEARCH_WARNING = (
    "This is historical simulation using Yahoo Finance data. "
    "It is for research only and not investment advice."
)

_PERIOD_MAP = {1: "1y", 3: "3y", 5: "5y"}


# ── DB ─────────────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_table() -> None:
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS historical_knowledge_trades (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol            TEXT NOT NULL,
            sector            TEXT,
            strategy          TEXT NOT NULL,
            entry_date        TEXT NOT NULL,
            exit_date         TEXT NOT NULL,
            holding_days      INTEGER,
            entry_price       REAL,
            exit_price        REAL,
            quantity          INTEGER,
            profit_loss       REAL,
            return_percent    REAL,
            winning           INTEGER,
            exit_reason       TEXT,
            market_regime     TEXT,
            nifty_trend       TEXT,
            banknifty_trend   TEXT,
            volatility_regime TEXT,
            ema9              REAL, ema20 REAL, ema50 REAL, ema200 REAL,
            rsi               REAL,
            macd              REAL, macd_signal REAL,
            vwap              REAL, atr REAL, adx REAL,
            supertrend        REAL,
            volume_ratio      REAL,
            opportunity_score REAL,
            trade_quality     REAL,
            confidence        REAL,
            risk_reward       REAL,
            created_at        TEXT,
            UNIQUE(symbol, strategy, entry_date, exit_date)
        )
    """)
    conn.commit()
    conn.close()


# ── Status file (progress reporting for the UI) ────────────────────────────────

def _write_status(s: dict) -> None:
    try:
        with open(STATUS_PATH, "w") as f:
            json.dump(s, f)
    except Exception:
        pass


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def read_status() -> dict:
    try:
        with open(STATUS_PATH) as f:
            status = json.load(f)
    except Exception:
        return {"status": "idle", "logs": []}
    # Reconcile stale "running" states: if the builder process is gone,
    # mark the build as failed so the UI never shows a permanent spinner.
    if status.get("status") == "running" and not _pid_alive(status.get("pid")):
        status["status"] = "failed"
        status["error"] = "Build process exited unexpectedly."
        status.setdefault("logs", []).append("ERROR: build process exited unexpectedly.")
        _write_status(status)
    return status


def is_build_running() -> bool:
    return read_status().get("status") == "running"


# ── Market context (precomputed, no lookahead) ────────────────────────────────

def _index_context_frame(yf_symbol: str, period: str) -> Optional[pd.DataFrame]:
    """
    Fetch an index and precompute per-date context columns.
    EWM/rolling values at date t use only candles up to t → no lookahead.
    """
    try:
        df = _fetch_yfinance(yf_symbol, "1d", period, None, None)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    close = df["close"]
    out = pd.DataFrame(index=df.index.date)
    out["ema20"]  = close.ewm(span=20, adjust=False).mean().values
    out["ema50"]  = close.ewm(span=50, adjust=False).mean().values
    out["close"]  = close.values
    out["ret5"]   = close.pct_change(5).values * 100.0
    out["annvol"] = (close.pct_change().rolling(20).std() * (252 ** 0.5) * 100.0).values
    out = out[~out.index.duplicated(keep="last")]
    return out


def _trend_label(row) -> str:
    """Same thresholds as market_regime._classify_trend (UP/DOWN/SIDEWAYS)."""
    try:
        if row["ema20"] > row["ema50"] * 1.005 and row["ret5"] > 0.5:
            return "UP"
        if row["ema20"] < row["ema50"] * 0.995 and row["ret5"] < -0.5:
            return "DOWN"
    except Exception:
        pass
    return "SIDEWAYS"


def _regime_label(row) -> str:
    """Same thresholds as trade_intelligence.classify_regime (7 categories)."""
    try:
        ann_vol = row["annvol"]
        if not math.isnan(ann_vol):
            if ann_vol >= 22.0:
                return "High Volatility"
            if ann_vol <= 8.0:
                return "Low Volatility"
        ema20, ema50, ret5 = row["ema20"], row["ema50"], row["ret5"]
        if ema20 > ema50 and ret5 > 2.0:
            return "Strong Bullish"
        if ema20 > ema50 and ret5 > 0.5:
            return "Bullish"
        if ema20 > ema50:
            return "Neutral"
        if ret5 < -2.0:
            return "Strong Bearish"
        if ema20 < ema50:
            return "Bearish"
    except Exception:
        pass
    return "Neutral"


def _vol_regime_label(row) -> str:
    try:
        v = row["annvol"]
        if not math.isnan(v):
            if v >= 22.0:
                return "HIGH"
            if v <= 8.0:
                return "LOW"
            return "NORMAL"
    except Exception:
        pass
    return "NORMAL"


class MarketContext:
    """Date → (market_regime, nifty_trend, banknifty_trend, volatility_regime)."""

    def __init__(self, period: str):
        self.nifty = _index_context_frame("^NSEI", period)
        self.banknifty = _index_context_frame("^NSEBANK", period)

    def _row_asof(self, frame: Optional[pd.DataFrame], d):
        if frame is None or frame.empty:
            return None
        idx = frame.index
        # last row with date <= d (as-of lookup, no lookahead)
        try:
            pos = idx.searchsorted(d, side="right") - 1  # type: ignore[arg-type]
        except Exception:
            return None
        if pos < 0:
            return None
        return frame.iloc[pos]

    def context_for(self, entry_date_str: str) -> dict:
        try:
            d = datetime.fromisoformat(entry_date_str[:10]).date()
        except Exception:
            d = None
        n = self._row_asof(self.nifty, d) if d else None
        b = self._row_asof(self.banknifty, d) if d else None
        return {
            "market_regime":     _regime_label(n) if n is not None else "Neutral",
            "nifty_trend":       _trend_label(n) if n is not None else "SIDEWAYS",
            "banknifty_trend":   _trend_label(b) if b is not None else "SIDEWAYS",
            "volatility_regime": _vol_regime_label(n) if n is not None else "NORMAL",
        }


# ── Entry-time decision metrics (research snapshot; additive, not strategy logic)

def _sf(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _decision_metrics(row: pd.Series, entry_price: float, stop: float, target: float) -> dict:
    """
    Deterministic, entry-bar-only metrics (no lookahead, no external fetches).
      risk_reward       : (target-entry)/(entry-stop)
      trade_quality     : 0-100 composite of trend / momentum / volume / risk
      confidence        : 0-100 = count of favorable conditions
      opportunity_score : 0-100 blend of quality, confidence and RR
    """
    risk = entry_price - stop
    rr = round((target - entry_price) / risk, 2) if risk > 0 else 0.0

    ema9, ema20, ema50 = _sf(row.get("ema9")), _sf(row.get("ema20")), _sf(row.get("ema50"))
    ema200 = _sf(row.get("ema200"))
    rsi = _sf(row.get("rsi"), 50.0)
    macd_line, macd_sig = _sf(row.get("macd_line")), _sf(row.get("macd_signal"))
    adx = _sf(row.get("adx"))
    vol_ratio = _sf(row.get("volume_ratio"), 1.0)
    close = _sf(row.get("close"))

    # trend 0-100
    if ema9 > ema20 > ema50 > ema200 > 0:
        trend = 100.0
    elif ema9 > ema20 > ema50:
        trend = 80.0
    elif ema9 > ema20:
        trend = 60.0
    elif ema9 < ema20 < ema50:
        trend = 20.0
    else:
        trend = 40.0

    # momentum 0-100
    momentum = 50.0
    if macd_line > macd_sig:
        momentum += 20
    if 45 <= rsi <= 65:
        momentum += 15
    elif rsi > 70 or rsi < 30:
        momentum -= 15
    if adx >= 25:
        momentum += 15
    momentum = max(0.0, min(100.0, momentum))

    # volume 0-100
    volume = max(0.0, min(100.0, 50.0 + (vol_ratio - 1.0) * 50.0))

    # risk 0-100 from RR
    if rr >= 3.0:   risk_s = 90.0
    elif rr >= 2.0: risk_s = 70.0
    elif rr >= 1.5: risk_s = 50.0
    elif rr >= 1.0: risk_s = 35.0
    else:           risk_s = 20.0

    quality = round(trend * 0.30 + momentum * 0.30 + volume * 0.15 + risk_s * 0.25, 1)

    favorable = sum([
        ema9 > ema20,
        ema20 > ema50,
        close > ema200 > 0,
        macd_line > macd_sig,
        40 <= rsi <= 70,
        adx >= 20,
        vol_ratio >= 1.0,
        rr >= 1.5,
    ])
    confidence = round(favorable / 8 * 100, 1)

    opp = round(quality * 0.5 + confidence * 0.3 + max(0.0, min(100.0, rr / 3.0 * 100.0)) * 0.2, 1)

    return {
        "risk_reward": rr,
        "trade_quality": quality,
        "confidence": confidence,
        "opportunity_score": opp,
    }


# ── Position sizing (same 1% risk rule as backtesting_engine) ─────────────────

def _compute_qty(entry_price: float, stop_loss: float, capital: float) -> int:
    stop_dist = entry_price - stop_loss
    if stop_dist <= 0 or capital < entry_price:
        return 0
    risk_amount = capital * MAX_RISK_PCT
    qty_risk = max(1, math.floor(risk_amount / stop_dist))
    qty_afford = math.floor(capital / entry_price)
    return max(0, min(qty_risk, qty_afford))


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Compute indicators and expose the datetime index as a `time` column."""
    enriched = compute_indicators_df(df)
    enriched = enriched.reset_index()
    first_col = enriched.columns[0]
    if "time" not in enriched.columns:
        enriched = enriched.rename(columns={first_col: "time"})
    return enriched


# ── Simulation (mirrors backtesting_engine walk-forward, unmodified rules) ─────

def _simulate(symbol: str, sector: str, strategy_id: str,
              rows: pd.DataFrame, ctx: MarketContext) -> list[dict]:
    strategy = get_strategy(strategy_id)
    trades: list[dict] = []
    position: Optional[dict] = None
    n = len(rows)

    for i in range(WARMUP_BARS, n):
        row, prev = rows.iloc[i], rows.iloc[i - 1]
        cur_high  = _sf(row.get("high"))
        cur_low   = _sf(row.get("low"))
        cur_close = _sf(row.get("close"))
        cur_time  = str(row.get("time", ""))[:10]
        if cur_close <= 0:
            continue

        if position is not None:
            exit_price = exit_reason = None
            if cur_low <= position["stop"]:
                exit_price, exit_reason = position["stop"], "STOP"
            elif cur_high >= position["target"]:
                exit_price, exit_reason = position["target"], "TARGET"
            else:
                sig_exit, _ = strategy.check_exit(
                    row, prev, position["entry_price"], position["stop"], position["target"])
                if sig_exit:
                    exit_price, exit_reason = cur_close, "SIGNAL_EXIT"

            if exit_price is not None:
                qty = position["quantity"]
                pnl = round((exit_price - position["entry_price"]) * qty, 2)
                ret_pct = round((exit_price - position["entry_price"]) / position["entry_price"] * 100, 2)
                try:
                    hold = (datetime.fromisoformat(cur_time)
                            - datetime.fromisoformat(position["entry_date"])).days
                except Exception:
                    hold = i - position["entry_bar"]
                trades.append({
                    "symbol": symbol, "sector": sector, "strategy": strategy_id,
                    "entry_date": position["entry_date"], "exit_date": cur_time,
                    "holding_days": max(0, hold),
                    "entry_price": position["entry_price"],
                    "exit_price": round(float(exit_price), 2),
                    "quantity": qty, "profit_loss": pnl,
                    "return_percent": ret_pct, "winning": 1 if pnl > 0 else 0,
                    "exit_reason": exit_reason,
                    **position["context"], **position["snapshot"], **position["metrics"],
                })
                position = None
            continue  # do not enter on an exit bar (same as engine ordering)

        entry_signal, _reason = strategy.check_entry(row, prev)
        if not entry_signal:
            continue
        entry_price = cur_close
        stop = strategy.compute_stop_loss(row, entry_price)
        target = strategy.compute_target(entry_price, stop)
        qty = _compute_qty(entry_price, stop, INITIAL_CAPITAL)
        if qty <= 0 or stop <= 0 or stop >= entry_price:
            continue

        snapshot = {
            "ema9": _sf(row.get("ema9")), "ema20": _sf(row.get("ema20")),
            "ema50": _sf(row.get("ema50")), "ema200": _sf(row.get("ema200")),
            "rsi": _sf(row.get("rsi")),
            "macd": _sf(row.get("macd_line")), "macd_signal": _sf(row.get("macd_signal")),
            "vwap": _sf(row.get("vwap")), "atr": _sf(row.get("atr")),
            "adx": _sf(row.get("adx")), "supertrend": _sf(row.get("supertrend")),
            "volume_ratio": _sf(row.get("volume_ratio")),
        }
        position = {
            "entry_date": cur_time, "entry_bar": i,
            "entry_price": round(entry_price, 2),
            "stop": round(stop, 2), "target": round(target, 2),
            "quantity": qty,
            "snapshot": snapshot,
            "context": ctx.context_for(cur_time),
            "metrics": _decision_metrics(row, entry_price, stop, target),
        }
    # open position at end of data is discarded (incomplete trade — not stored)
    return trades


# ── Build orchestration ────────────────────────────────────────────────────────

def build_knowledge_base(years: int = 5) -> dict:
    """Run the full build. Writes progress to the status file as it goes."""
    # Durable single-build lock: refuse to start if another build is running.
    if is_build_running():
        return {"error": "A build is already running", "status": "running"}

    period = _PERIOD_MAP.get(int(years), "5y")
    ensure_table()

    logs: list[str] = []
    skipped: list[str] = []
    status = {
        "status": "running", "started_at": datetime.now().isoformat(),
        "pid": os.getpid(),
        "years": int(years), "period": period,
        "stocks_total": len(NIFTY_50), "stocks_processed": 0,
        "strategies": LAB_STRATEGY_IDS, "trades_generated": 0,
        "skipped_symbols": skipped, "logs": logs, "warning": RESEARCH_WARNING,
    }
    _write_status(status)

    try:
        return _run_build(status, period, logs, skipped)
    except Exception as e:
        # Crash-safe finalization: never leave the status stuck at "running".
        status["status"] = "failed"
        status["error"] = str(e)
        status["finished_at"] = datetime.now().isoformat()
        logs.append(f"ERROR: build failed ({e})")
        _write_status(status)
        return status


def _run_build(status: dict, period: str, logs: list[str], skipped: list[str]) -> dict:
    ctx = MarketContext(period)
    if ctx.nifty is None:
        logs.append("WARNING: NIFTY index data unavailable — market context defaults used.")
    if ctx.banknifty is None:
        logs.append("WARNING: BANKNIFTY index data unavailable — trend defaults used.")

    total_inserted = 0
    conn = _connect()
    cols = ["symbol", "sector", "strategy", "entry_date", "exit_date", "holding_days",
            "entry_price", "exit_price", "quantity", "profit_loss", "return_percent",
            "winning", "exit_reason", "market_regime", "nifty_trend", "banknifty_trend",
            "volatility_regime", "ema9", "ema20", "ema50", "ema200", "rsi", "macd",
            "macd_signal", "vwap", "atr", "adx", "supertrend", "volume_ratio",
            "opportunity_score", "trade_quality", "confidence", "risk_reward", "created_at"]
    insert_sql = (f"INSERT OR IGNORE INTO historical_knowledge_trades "
                  f"({','.join(cols)}) VALUES ({','.join('?' * len(cols))})")

    for symbol in NIFTY_50:
        sym_trades = 0
        try:
            df = _fetch_yfinance(symbol, "1d", period, None, None)
        except Exception as e:
            skipped.append(symbol)
            logs.append(f"SKIP {symbol}: Yahoo download failed ({e})")
            status["stocks_processed"] += 1
            _write_status(status)
            continue

        if df is None or df.empty or len(df) < WARMUP_BARS + 5:
            skipped.append(symbol)
            logs.append(f"SKIP {symbol}: insufficient data ({0 if df is None else len(df)} bars)")
            status["stocks_processed"] += 1
            _write_status(status)
            continue

        try:
            enriched = _enrich(df)
        except Exception as e:
            skipped.append(symbol)
            logs.append(f"SKIP {symbol}: indicator computation failed ({e})")
            status["stocks_processed"] += 1
            _write_status(status)
            continue

        sector = _sector_of(symbol)
        now = datetime.now().isoformat()
        for sid in LAB_STRATEGY_IDS:
            try:
                trades = _simulate(symbol, sector, sid, enriched, ctx)
            except Exception as e:
                logs.append(f"ERROR {symbol}/{sid}: strategy simulation failed ({e})")
                continue
            if trades:
                rows = [tuple(t.get(c) if c != "created_at" else now for c in cols) for t in trades]
                cur = conn.executemany(insert_sql, rows)
                conn.commit()
                total_inserted += cur.rowcount if cur.rowcount > 0 else 0
                sym_trades += len(trades)

        logs.append(f"OK {symbol}: {sym_trades} trades generated")
        status["stocks_processed"] += 1
        status["trades_generated"] = total_inserted
        _write_status(status)

    conn.close()
    status["status"] = "completed"
    status["finished_at"] = datetime.now().isoformat()
    status["trades_generated"] = total_inserted
    _write_status(status)
    return status


# ── Summary & queries ──────────────────────────────────────────────────────────

def _group_best_worst(conn: sqlite3.Connection, col: str) -> tuple[Optional[dict], Optional[dict]]:
    rows = conn.execute(f"""
        SELECT {col} AS name, COUNT(*) AS trades,
               ROUND(AVG(winning) * 100, 1) AS win_rate,
               ROUND(AVG(return_percent), 2) AS avg_return,
               ROUND(SUM(profit_loss), 2) AS net_pnl
        FROM historical_knowledge_trades
        WHERE {col} IS NOT NULL AND {col} != ''
        GROUP BY {col} HAVING COUNT(*) >= 5
        ORDER BY avg_return DESC
    """).fetchall()
    if not rows:
        return None, None
    keys = ["name", "trades", "win_rate", "avg_return", "net_pnl"]
    return dict(zip(keys, rows[0])), dict(zip(keys, rows[-1]))


def knowledge_summary() -> dict:
    ensure_table()
    conn = _connect()
    row = conn.execute("""
        SELECT COUNT(*),
               COALESCE(SUM(winning), 0),
               COALESCE(AVG(return_percent), 0),
               COALESCE(SUM(CASE WHEN profit_loss > 0 THEN profit_loss ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN profit_loss < 0 THEN -profit_loss ELSE 0 END), 0),
               COUNT(DISTINCT symbol), COUNT(DISTINCT strategy)
        FROM historical_knowledge_trades
    """).fetchone()
    total, wins, avg_ret, gross_win, gross_loss = row[0], row[1], row[2], row[3], row[4]
    n_symbols, n_strategies = row[5], row[6]
    losses = total - wins
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.99 if gross_win > 0 else 0.0)

    best_strat, worst_strat = _group_best_worst(conn, "strategy")
    best_sector, worst_sector = _group_best_worst(conn, "sector")
    conn.close()

    return {
        "build": read_status(),
        "total_trades": total,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": round(wins / total * 100, 1) if total else 0.0,
        "average_return": round(avg_ret, 2),
        "profit_factor": pf,
        "stocks_covered": n_symbols,
        "strategies_covered": n_strategies,
        "best_strategy": best_strat, "worst_strategy": worst_strat,
        "best_sector": best_sector, "worst_sector": worst_sector,
        "warning": RESEARCH_WARNING,
    }


def knowledge_trades(limit: int = 100, offset: int = 0,
                     symbol: Optional[str] = None, strategy: Optional[str] = None) -> dict:
    ensure_table()
    conn = _connect()
    conn.row_factory = sqlite3.Row
    where, params = [], []
    if symbol:
        where.append("symbol = ?"); params.append(symbol.upper())
    if strategy:
        where.append("strategy = ?"); params.append(strategy)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM historical_knowledge_trades {where_sql}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM historical_knowledge_trades {where_sql} "
        f"ORDER BY entry_date DESC, symbol LIMIT ? OFFSET ?",
        params + [max(1, min(500, int(limit))), max(0, int(offset))]).fetchall()
    conn.close()
    return {"total": total, "trades": [dict(r) for r in rows], "warning": RESEARCH_WARNING}
