"""
Trade Evaluator — Version 2.0 Adaptive Self-Evaluation Engine (Module 1).

For every paper trade:
  1. On BUY  — permanently store the complete prediction snapshot
               (what the bot believed at entry).
  2. On SELL — evaluate the completed trade: actual vs predicted outcome,
               MFE/MAE, stop/target hits, prediction error, calibration
               error, and outcome classification. Failure/success causes
               are assigned by failure_analyzer.

PAPER TRADING ONLY — research tool. Never places real orders.
Evaluation NEVER changes strategy logic. Trades executed on synthetic /
mock price data are stored but flagged learn_eligible = 0 so the learning
layer can never learn from them.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta

import trade_intelligence as _ti

# Tests may monkeypatch this to point at a temp DB.
DB_PATH = _ti.DB_PATH

_DIR = os.path.dirname(os.path.abspath(__file__))

_SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction_snapshots (
    trade_id            TEXT PRIMARY KEY,
    symbol              TEXT NOT NULL,
    sector              TEXT,
    entry_time          TEXT,
    strategy_id         TEXT,
    strategy_name       TEXT,
    recommendation      TEXT,
    base_confidence     REAL,
    learning_adjustment REAL,
    final_confidence    REAL,
    expected_return     REAL,
    expected_holding_days REAL,
    expected_rr         REAL,
    entry_price         REAL,
    stop_loss           REAL,
    target              REAL,
    market_regime       TEXT,
    sector_strength     REAL,
    volatility_regime   TEXT,
    volatility          REAL,
    data_source         TEXT,
    data_quality        TEXT,
    indicators          TEXT,   -- JSON: ema9..volume_ratio
    pattern_matched     TEXT,
    pattern_rank        REAL,
    historical_matches  INTEGER,
    historical_win_rate REAL,
    historical_expectancy REAL,
    historical_profit_factor REAL,
    reliability_level   TEXT,
    model_version       INTEGER,
    created_at          TEXT
);
"""

_EVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_evaluations (
    trade_id            TEXT PRIMARY KEY,   -- SELL trade id
    buy_trade_id        TEXT,
    symbol              TEXT NOT NULL,
    sector              TEXT,
    entry_time          TEXT,
    exit_time           TEXT,
    entry_price         REAL,
    exit_price          REAL,
    quantity            INTEGER,
    exit_type           TEXT,
    actual_return       REAL,
    actual_holding_days REAL,
    mfe                 REAL,
    mae                 REAL,
    max_gap_pct         REAL,
    stop_hit            INTEGER,
    target_hit          INTEGER,
    direction_correct   INTEGER,
    expected_return     REAL,
    prediction_error    REAL,
    predicted_confidence REAL,
    calibration_error   REAL,
    outcome_class       TEXT,
    failure_causes      TEXT,   -- JSON list
    success_factors     TEXT,   -- JSON list
    lesson              TEXT,
    learn_eligible      INTEGER,
    data_source         TEXT,
    model_version       INTEGER,
    evaluated_at        TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_SNAPSHOT_SCHEMA)
    conn.execute(_EVAL_SCHEMA)
    conn.commit()
    return conn


def _f(v, default=None):
    try:
        x = float(v)
        return x if x == x else default   # NaN guard
    except (TypeError, ValueError):
        return default


# ── Prediction snapshot (spec §2) ─────────────────────────────────────────────

def _scan_item_for(symbol: str) -> dict:
    """Best-effort lookup of the latest scanner item for `symbol` from the
    opportunity cache — used to enrich the snapshot with historical evidence.
    Missing cache simply yields an empty dict (fields stay None)."""
    sym = symbol.upper()
    for fname in ("opportunity_cache.json", "intelligence_cache.json"):
        path = os.path.join(_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict) and str(
                    it.get("stock", it.get("symbol", ""))).upper() == sym:
                return it
    return {}


def _reliability_level(n) -> str:
    n = int(n or 0)
    if n >= 30:
        return "high"
    if n >= 15:
        return "medium"
    return "low"


def store_prediction_snapshot(buy_trade: dict, sector: str = "",
                              scan_item: dict | None = None) -> dict:
    """Permanently store the complete prediction state at entry.
    Called from paper_trader.execute_buy — must never raise into the caller.
    Returns the stored snapshot dict."""
    sym = str(buy_trade.get("symbol", "")).upper()

    try:
        from market_data_engine import get_last_source
        data_source = get_last_source(sym)
    except Exception:
        data_source = "unknown"

    if not sector:
        try:
            from market_scanner import _sector_of
            sector = _sector_of(sym)
        except Exception:
            sector = ""

    item = scan_item if scan_item is not None else _scan_item_for(sym)

    entry_price = _f(buy_trade.get("price"), 0.0) or 0.0
    target = _f(buy_trade.get("target"), 0.0) or 0.0
    stop = _f(buy_trade.get("stop_loss"), 0.0) or 0.0
    expected_return = round((target - entry_price) / entry_price * 100.0, 2) \
        if (entry_price > 0 and target > 0) else None

    final_conf = _f(buy_trade.get("signal_confidence"))
    base_conf = _f(item.get("base_confidence"), final_conf)
    learn_adj = _f(item.get("learning_adjustment"), 0.0)
    n_hist = int(item.get("historical_trades", 0) or 0)

    volatility = _f(buy_trade.get("volatility_at_entry"))
    vol_regime = ("high" if (volatility or 0) >= 22.0
                  else "low" if (volatility or 99) <= 8.0 else "normal") \
        if volatility is not None else None

    try:
        model_version = _active_model_version()
    except Exception:
        model_version = 0

    snapshot = {
        "trade_id": str(buy_trade.get("id", "")),
        "symbol": sym,
        "sector": sector,
        "entry_time": buy_trade.get("timestamp", ""),
        "strategy_id": buy_trade.get("strategy_id", "ai_scan"),
        "strategy_name": buy_trade.get("strategy_name", "AI Scan"),
        "recommendation": buy_trade.get("ai_decision", "BUY"),
        "base_confidence": base_conf,
        "learning_adjustment": learn_adj,
        "final_confidence": final_conf,
        "expected_return": expected_return,
        "expected_holding_days": _f(item.get("expected_holding_days")),
        "expected_rr": _f(buy_trade.get("rr_ratio")),
        "entry_price": entry_price,
        "stop_loss": stop,
        "target": target,
        "market_regime": buy_trade.get("market_regime_at_entry",
                                       buy_trade.get("regime", "")),
        "sector_strength": _f((item.get("opportunity_breakdown") or {})
                              .get("sector_strength_score")),
        "volatility_regime": vol_regime,
        "volatility": volatility,
        "data_source": data_source,
        "data_quality": "ok" if data_source == "yfinance" else "fallback",
        "indicators": json.dumps(buy_trade.get("indicators_at_entry") or {}),
        "pattern_matched": (
            f"{buy_trade.get('strategy_name', '')} · {sector} · "
            f"{buy_trade.get('market_regime_at_entry', buy_trade.get('regime', ''))}"
        ),
        "pattern_rank": _f(item.get("opportunity_score")),
        "historical_matches": n_hist,
        "historical_win_rate": _f(item.get("historical_win_rate")),
        "historical_expectancy": _f(item.get("historical_expectancy")),
        "historical_profit_factor": _f(item.get("historical_profit_factor")),
        "reliability_level": _reliability_level(n_hist),
        "model_version": model_version,
        "created_at": datetime.now().isoformat(),
    }

    conn = _connect()
    try:
        cols = list(snapshot.keys())
        conn.execute(
            f"INSERT OR REPLACE INTO prediction_snapshots ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})",
            [snapshot[c] for c in cols],
        )
        conn.commit()
    finally:
        conn.close()
    return snapshot


def _active_model_version() -> int:
    from model_versioning import get_active_version
    return int(get_active_version().get("version", 0))


def get_snapshot(trade_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM prediction_snapshots WHERE trade_id = ?",
            (trade_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── Excursions (MFE / MAE / overnight gaps) ──────────────────────────────────

def _excursions(symbol: str, entry_time: str, exit_time: str,
                entry_price: float) -> tuple[float | None, float | None, float | None, str]:
    """(mfe %, mae %, max overnight gap %, data_source) between entry and exit.
    Uses daily candles; returns Nones when live data is unavailable."""
    try:
        from market_data import fetch_ohlcv
        from market_data_engine import get_last_source

        start = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00")).replace(tzinfo=None)
        end = datetime.fromisoformat(str(exit_time).replace("Z", "+00:00")).replace(tzinfo=None)
        span_days = max(5, (end - start).days + 5)
        period = "1mo" if span_days <= 25 else ("3mo" if span_days <= 85 else "1y")

        df = fetch_ohlcv(symbol, period=period, interval="1d")
        source = get_last_source(symbol)
        if source != "yfinance" or df is None or df.empty or entry_price <= 0:
            return None, None, None, source

        df = df.copy()
        idx = df.index.tz_localize(None) if getattr(df.index, "tz", None) is not None else df.index
        mask = (idx >= start.replace(hour=0, minute=0, second=0, microsecond=0)) & \
               (idx <= end + timedelta(days=1))
        window = df.loc[mask]
        if window.empty:
            return None, None, None, source

        high = float(window["High"].max())
        low = float(window["Low"].min())
        mfe = round((high - entry_price) / entry_price * 100.0, 2)
        mae = round((low - entry_price) / entry_price * 100.0, 2)

        max_gap = 0.0
        closes = window["Close"].tolist()
        opens = window["Open"].tolist()
        for i in range(1, len(window)):
            prev_close = float(closes[i - 1])
            if prev_close > 0:
                gap = abs(float(opens[i]) - prev_close) / prev_close * 100.0
                max_gap = max(max_gap, gap)
        return mfe, mae, round(max_gap, 2), source
    except Exception:
        return None, None, None, "unknown"


# ── Evaluation of a completed trade (spec §3) ────────────────────────────────

def evaluate_closed_trade(buy_trade: dict, sell_trade: dict,
                          sector: str = "") -> dict | None:
    """Evaluate a completed BUY→SELL round trip and store the result.
    Returns the evaluation dict, or None when inputs are unusable."""
    if not buy_trade or not sell_trade:
        return None
    sym = str(sell_trade.get("symbol", "")).upper()
    entry_price = _f(buy_trade.get("price"), 0.0) or 0.0
    exit_price = _f(sell_trade.get("price"), 0.0) or 0.0
    if entry_price <= 0 or exit_price <= 0:
        return None

    if not sector:
        try:
            from market_scanner import _sector_of
            sector = _sector_of(sym)
        except Exception:
            sector = ""

    snapshot = get_snapshot(str(buy_trade.get("id", ""))) or {}
    if not snapshot:
        # Backfill path: build a best-effort snapshot from the BUY record.
        try:
            snapshot = store_prediction_snapshot(buy_trade, sector=sector)
        except Exception:
            snapshot = {}

    entry_time = buy_trade.get("timestamp", "")
    exit_time = sell_trade.get("timestamp", "")

    actual_return = round((exit_price - entry_price) / entry_price * 100.0, 2)
    try:
        t0 = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00")).replace(tzinfo=None)
        t1 = datetime.fromisoformat(str(exit_time).replace("Z", "+00:00")).replace(tzinfo=None)
        holding_days = round(max(0.0, (t1 - t0).total_seconds() / 86400.0), 1)
    except Exception:
        holding_days = 0.0

    mfe, mae, max_gap, live_source = _excursions(sym, entry_time, exit_time, entry_price)

    stop = _f(buy_trade.get("stop_loss"), 0.0) or 0.0
    target = _f(buy_trade.get("target"), 0.0) or 0.0
    exit_type = str(sell_trade.get("exit_type", "SIGNAL_EXIT"))
    stop_hit = exit_type == "STOP_HIT" or (stop > 0 and exit_price <= stop * 1.005)
    target_hit = exit_type == "TARGET_HIT" or (target > 0 and exit_price >= target * 0.995)

    direction_correct = actual_return > 0   # long-only system predicts UP

    expected_return = _f(snapshot.get("expected_return"))
    prediction_error = round(actual_return - expected_return, 2) \
        if expected_return is not None else None

    predicted_conf = _f(snapshot.get("final_confidence"),
                        _f(buy_trade.get("signal_confidence")))
    calibration_error = round(predicted_conf - (100.0 if direction_correct else 0.0), 1) \
        if predicted_conf is not None else None

    from analytics_engine import classify_outcome
    outcome_class = classify_outcome(actual_return)

    # SAFETY (spec invariant): NEVER learn from mock/unverified data — the
    # gate covers the FULL trade lifecycle, not just the BUY snapshot:
    #   1. snapshot_source — data source when the BUY prediction was made
    #   2. sell_source     — data source of the most recent fetch for this
    #                        symbol (the SELL price when called from
    #                        execute_sell; "unknown" for old backfills, which
    #                        are then conservatively excluded)
    #   3. live_source     — source of the evaluation-time excursion
    #                        verification fetch (MFE/MAE window)
    # If ANY of them is not verified live yfinance data, the trade is stored
    # for transparency but flagged learn_eligible = 0.
    snapshot_source = snapshot.get("data_source", "unknown")
    try:
        from market_data_engine import get_last_source
        sell_source = get_last_source(sym)
    except Exception:
        sell_source = "unknown"
    eval_source = live_source or "unknown"
    learn_eligible = 1 if (snapshot_source == "yfinance"
                           and sell_source == "yfinance"
                           and eval_source == "yfinance") else 0
    # Surface the offending source so the UI can show WHY it was excluded.
    if snapshot_source != "yfinance":
        data_source = snapshot_source
    elif sell_source != "yfinance":
        data_source = sell_source
    else:
        data_source = eval_source

    evaluation = {
        "trade_id": str(sell_trade.get("id", "")),
        "buy_trade_id": str(buy_trade.get("id", "")),
        "symbol": sym,
        "sector": sector,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": int(sell_trade.get("quantity", 0) or 0),
        "exit_type": exit_type,
        "actual_return": actual_return,
        "actual_holding_days": holding_days,
        "mfe": mfe,
        "mae": mae,
        "max_gap_pct": max_gap,
        "stop_hit": 1 if stop_hit else 0,
        "target_hit": 1 if target_hit else 0,
        "direction_correct": 1 if direction_correct else 0,
        "expected_return": expected_return,
        "prediction_error": prediction_error,
        "predicted_confidence": predicted_conf,
        "calibration_error": calibration_error,
        "outcome_class": outcome_class,
        "learn_eligible": learn_eligible,
        "data_source": data_source,
        "model_version": int(snapshot.get("model_version") or 0),
        "evaluated_at": datetime.now().isoformat(),
    }

    # Failure / success analysis (spec §4, §5)
    try:
        from failure_analyzer import analyze_trade
        causes, factors, lesson = analyze_trade(snapshot, evaluation)
    except Exception:
        causes, factors, lesson = [], [], ""
    evaluation["failure_causes"] = json.dumps(causes)
    evaluation["success_factors"] = json.dumps(factors)
    evaluation["lesson"] = lesson

    conn = _connect()
    try:
        cols = list(evaluation.keys())
        conn.execute(
            f"INSERT OR REPLACE INTO trade_evaluations ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})",
            [evaluation[c] for c in cols],
        )
        conn.commit()
    finally:
        conn.close()

    evaluation["failure_causes"] = causes
    evaluation["success_factors"] = factors
    return evaluation


# ── Backfill + queries ────────────────────────────────────────────────────────

def backfill_evaluations() -> dict:
    """Evaluate every completed BUY→SELL round trip that has no evaluation
    yet (FIFO pairing per symbol, same as Trade Replay)."""
    from paper_trader import _load_state
    state = _load_state()
    trades = state.get("trades", [])

    conn = _connect()
    try:
        existing = {r[0] for r in conn.execute(
            "SELECT trade_id FROM trade_evaluations")}
    finally:
        conn.close()

    open_buys: dict[str, list[dict]] = {}
    evaluated, skipped = 0, 0
    for tr in trades:
        sym = tr.get("symbol", "")
        if tr.get("action") == "BUY":
            open_buys.setdefault(sym, []).append(tr)
        elif tr.get("action") == "SELL" and open_buys.get(sym):
            buy = open_buys[sym].pop(0)
            if str(tr.get("id", "")) in existing:
                skipped += 1
                continue
            if evaluate_closed_trade(buy, tr):
                evaluated += 1
    return {"evaluated": evaluated, "already_evaluated": skipped}


def get_evaluations(limit: int = 200) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM trade_evaluations ORDER BY exit_time DESC LIMIT ?",
            (int(limit),)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("failure_causes", "success_factors"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except Exception:
                d[k] = []
        out.append(d)
    return out


def get_evaluation_with_snapshot(limit: int = 200) -> list[dict]:
    """Evaluations joined with their prediction snapshots (for review UIs
    and the learning aggregator)."""
    evals = get_evaluations(limit)
    conn = _connect()
    try:
        snaps = {r["trade_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM prediction_snapshots")}
    finally:
        conn.close()
    for e in evals:
        snap = snaps.get(e.get("buy_trade_id"), {})
        if snap.get("indicators"):
            try:
                snap = {**snap, "indicators": json.loads(snap["indicators"])}
            except Exception:
                pass
        e["snapshot"] = snap
    return evals
