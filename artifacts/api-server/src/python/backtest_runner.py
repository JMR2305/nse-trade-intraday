"""
Phase 23 Part 2B/C/F/I — Historical Backtest Engine.

ARCHITECTURE RULE (from the Phase 23 directive): historical replay calls the
SAME production pipeline. There is no second decision engine here.

  * Per-symbol analysis = live_scan_engine._scan_one()  — the exact function
    LIVE scans use (indicators → research → market intelligence → monitoring
    → strategy → risk gates → AI decision).
  * Event derivation   = live_scan_engine.derive_symbol_events() — the exact
    function LIVE scans use, with mode='BACKTEST' + run_id.
  * Fill/charges model = phase20_executor.compute_fill / compute_charges.

The ONLY differences vs LIVE:
  1. Market data source: cached historical candles (historical_data_engine),
     truncated strictly as-of each replay timestamp (no look-ahead).
  2. Ledger: the isolated backtest ledger (backtest_portfolio) — the live
     phase20 paper ledger is NEVER touched.

Modes: single day / week / month / custom range; custom symbol list,
Nifty-50 universe or the configured trading universe; intervals 5m/10m/15m/1d.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, date, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

import backtest_portfolio as bp
import historical_data_engine as hde
from pipeline_events import emit, emit_many

WARMUP_DAILY_DAYS = 270          # calendar days of daily history for indicators
RISK_PER_TRADE_PCT = 1.0         # % of current cash risked per trade
MAX_POSITION_PCT = 25.0          # max % of cash in one position
DEFAULT_SETTINGS = {             # same knobs phase20 uses
    "fill_model": "NEXT_QUOTE",
    "slippage_pct": 0.15,
    "charges_pct": 0.12,
}


# ── Universe resolution ──────────────────────────────────────────────────────

def resolve_universe(cfg: Dict[str, Any]) -> List[str]:
    symbols = cfg.get("symbols")
    if symbols:
        return [str(s).upper() for s in symbols]
    universe = str(cfg.get("universe") or "configured").lower()
    if universe in ("nifty50", "nifty_50", "nifty"):
        try:
            from config import NIFTY_50
            return list(NIFTY_50)
        except Exception:
            pass
    # configured trading universe (watchlist with fallback)
    try:
        from watchlist_store import get_watchlist
        wl = get_watchlist()
        if wl:
            return [str(s).upper() for s in wl]
    except Exception:
        pass
    from config import DEFAULT_WATCHLIST
    return list(DEFAULT_WATCHLIST)


# ── As-of data construction (the no-lookahead core) ──────────────────────────

def _to_df(candles: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    df = df.set_index("ts").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def build_asof_df(daily: pd.DataFrame, intraday: Optional[pd.DataFrame],
                  ts: pd.Timestamp, interval: str) -> Optional[pd.DataFrame]:
    """
    Build the OHLCV dataframe a live scan would have seen at moment `ts`:
      * daily interval: all daily bars with timestamp <= ts.
      * intraday: daily bars from days strictly BEFORE ts.date(), plus one
        partial "today" bar aggregated from intraday candles up to ts.
    Strictly no data after `ts` is included — this is the no-lookahead
    guarantee, and the validation engine re-derives it identically.
    """
    if daily is None or daily.empty:
        return None
    if interval == "1d":
        df = daily[daily.index <= ts]
        return df if not df.empty else None
    day_start = ts.normalize()
    df = daily[daily.index < day_start]
    if intraday is not None and not intraday.empty:
        today = intraday[(intraday.index >= day_start) & (intraday.index <= ts)]
        if not today.empty:
            bar = pd.DataFrame(
                [{
                    "open": float(today["open"].iloc[0]),
                    "high": float(today["high"].max()),
                    "low": float(today["low"].min()),
                    "close": float(today["close"].iloc[-1]),
                    "volume": float(today["volume"].sum()),
                }],
                index=[day_start],
            )
            df = pd.concat([df, bar])
    return df if not df.empty else None


def _fetch_result(symbol: str, df: Optional[pd.DataFrame], ts: str):
    """Wrap an as-of dataframe in the SymbolFetchResult _scan_one expects."""
    from live_data_provider import SymbolFetchResult, DataQuality
    if df is None or df.empty:
        return SymbolFetchResult(
            symbol=symbol, success=False, df=None, latest_date=None,
            data_age_days=None, data_quality=DataQuality.UNAVAILABLE,
            data_source="backtest_cache", fetch_ts=ts, fetch_latency_ms=0,
            retries_used=0, error="No cached candles as of this timestamp",
            bars=0)
    return SymbolFetchResult(
        symbol=symbol, success=True, df=df,
        latest_date=str(df.index[-1].date()),
        data_age_days=0.0,                      # as-of data IS current data
        data_quality=DataQuality.LIVE,          # historically "live" at ts
        data_source="backtest_cache", fetch_ts=ts, fetch_latency_ms=0,
        retries_used=0, error=None, bars=len(df))


# ── Execution against the isolated backtest ledger ──────────────────────────

def _try_enter(run_id: str, scan_id: str, rec, cash: float, ts: str) -> Tuple[float, Optional[str]]:
    """Enter a BUY-class recommendation into the backtest ledger."""
    from phase20_executor import compute_fill, compute_charges
    entry, stop = float(rec.entry_price), float(rec.stop_loss)
    per_share_risk = entry - stop
    if entry <= 0 or per_share_risk <= 0:
        return cash, None
    risk_amount = cash * RISK_PER_TRADE_PCT / 100.0
    qty = int(risk_amount / per_share_risk)
    max_qty = int(cash * MAX_POSITION_PCT / 100.0 / entry)
    qty = min(qty, max_qty)
    if qty < 1:
        emit("ORDER_REJECTED", "EXECUTION", scan_id=scan_id, symbol=rec.symbol,
             mode="BACKTEST", run_id=run_id,
             payload={"reason": "Position size < 1 share for available cash",
                      "cash": round(cash, 2)})
        return cash, None
    fill = compute_fill(entry, DEFAULT_SETTINGS, side="BUY")
    fill_price = fill["fill_price"]
    charges = compute_charges(fill_price * qty, DEFAULT_SETTINGS)
    cost = fill_price * qty + charges
    if cost > cash:
        emit("ORDER_REJECTED", "EXECUTION", scan_id=scan_id, symbol=rec.symbol,
             mode="BACKTEST", run_id=run_id,
             payload={"reason": "Insufficient cash", "cost": round(cost, 2),
                      "cash": round(cash, 2)})
        return cash, None

    emit("ORDER_SUBMITTED", "EXECUTION", scan_id=scan_id, symbol=rec.symbol,
         mode="BACKTEST", run_id=run_id,
         payload={"qty": qty, "signal_price": entry,
                  "fill_model": DEFAULT_SETTINGS["fill_model"]})
    trade_id = bp.open_trade({
        "run_id": run_id, "scan_id": scan_id, "symbol": rec.symbol,
        "strategy_id": rec.strategy_id, "strategy_name": rec.strategy_name,
        "side": "BUY", "signal_ts": ts, "fill_ts": ts,
        "signal_price": entry, "fill_price": fill_price, "quantity": qty,
        "stop_loss": stop, "target": float(rec.target_price),
        "est_charges": charges, "slippage": fill["slippage"],
        "confidence": rec.calibrated_confidence,
        "opportunity_score": rec.opportunity_score, "regime": rec.regime,
    })
    if trade_id is None:
        emit("ORDER_CANCELLED", "EXECUTION", scan_id=scan_id, symbol=rec.symbol,
             mode="BACKTEST", run_id=run_id,
             payload={"reason": "Open backtest position already exists"})
        return cash, None
    emit_many([
        {"event_type": "ORDER_EXECUTED", "stage": "EXECUTION",
         "scan_id": scan_id, "symbol": rec.symbol, "mode": "BACKTEST",
         "run_id": run_id,
         "payload": {"trade_id": trade_id, "fill_price": fill_price,
                     "qty": qty, "charges": charges,
                     "slippage": fill["slippage"]}},
        {"event_type": "POSITION_OPENED", "stage": "PORTFOLIO",
         "scan_id": scan_id, "symbol": rec.symbol, "mode": "BACKTEST",
         "run_id": run_id,
         "payload": {"trade_id": trade_id, "stop_loss": stop,
                     "target": float(rec.target_price),
                     "strategy": rec.strategy_name}},
    ])
    return cash - cost, trade_id


def _check_exits(run_id: str, scan_id: str, ts_iso: str,
                 bars: Dict[str, Dict[str, float]], cash: float) -> float:
    """
    Exit open backtest positions against the CURRENT candle of each symbol.
    Stop-loss has priority over target (conservative intrabar assumption —
    identical to the production backtesting engine's convention).
    Positions opened at this same timestamp are skipped (no same-bar exits).
    """
    for t in bp.open_trades(run_id):
        sym = str(t["symbol"]).upper()
        bar = bars.get(sym)
        if bar is None or t.get("fill_ts") == ts_iso:
            continue
        exit_price = exit_rule = None
        if float(bar["low"]) <= float(t["stop_loss"]):
            exit_price, exit_rule = float(t["stop_loss"]), "STOP_LOSS"
        elif float(bar["high"]) >= float(t["target"]):
            exit_price, exit_rule = float(t["target"]), "TARGET"
        if exit_price is None:
            continue
        closed = bp.close_trade(t["trade_id"], ts_iso, exit_price, exit_rule)
        if not closed:
            continue
        cash += exit_price * int(t["quantity"])
        emit_many([
            {"event_type": "POSITION_CLOSED", "stage": "PORTFOLIO",
             "scan_id": scan_id, "symbol": sym, "mode": "BACKTEST",
             "run_id": run_id,
             "payload": {"trade_id": t["trade_id"], "exit_rule": exit_rule,
                         "exit_price": exit_price,
                         "realized_pnl": closed.get("realized_pnl")}},
            {"event_type": "SELL_GENERATED", "stage": "AI_DECISION",
             "scan_id": scan_id, "symbol": sym, "mode": "BACKTEST",
             "run_id": run_id,
             "payload": {"reason": exit_rule, "trade_id": t["trade_id"]}},
        ])
    return cash


# ── Timeline ─────────────────────────────────────────────────────────────────

def _replay_timestamps(interval: str, per_symbol_candles: Dict[str, List[Dict[str, Any]]]
                       ) -> List[str]:
    """Sorted union of all candle timestamps across the universe."""
    ts: set = set()
    for candles in per_symbol_candles.values():
        for c in candles:
            ts.add(c["ts"])
    return sorted(ts)


# ── Main runner ──────────────────────────────────────────────────────────────

def _learning_fingerprint() -> str:
    """
    Fingerprint of the adaptive-learning knowledge base the pipeline consults
    (_scan_one → adaptive_learning.get_item_adjustment). Stored at run time so
    validation can detect that live learning state changed — in which case a
    decision diff is INDETERMINATE, not proof of a pipeline bug.
    """
    try:
        from trade_intelligence import DB_PATH
        st = os.stat(DB_PATH)
        return f"{st.st_size}:{int(st.st_mtime)}"
    except Exception:
        return "absent"


def execute_run(run_id: str) -> Dict[str, Any]:
    """
    Execute a backtest run created via backtest_portfolio.create_run().
    Long-running — meant to be launched in a detached process.
    """
    run = bp.get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Unknown run {run_id}"}
    cfg = run.get("config") or {}
    interval = str(cfg.get("interval") or "1d")
    start = str(cfg.get("start"))[:10]
    end = str(cfg.get("end"))[:10]
    capital = float(cfg.get("capital") or 100000.0)
    universe = resolve_universe(cfg)

    # Atomic PENDING→RUNNING claim: a duplicate or retried backtest_exec must
    # never replay the same run twice (would corrupt trades/metrics/events).
    if not bp.claim_run(run_id):
        return {"ok": False, "run_id": run_id,
                "error": "Run is not PENDING — already claimed, running or "
                         "finished; refusing to execute twice"}
    emit("SCAN_STARTED", "SUPERVISOR", scan_id=run_id, mode="BACKTEST",
         run_id=run_id, payload={"interval": interval, "start": start,
                                 "end": end, "universe": len(universe)})

    try:
        # 1. Ensure candle cache (replay interval + daily warmup history).
        warm_start = (date.fromisoformat(start)
                      - timedelta(days=WARMUP_DAILY_DAYS)).isoformat()
        per_symbol: Dict[str, List[Dict[str, Any]]] = {}
        daily_dfs: Dict[str, pd.DataFrame] = {}
        intraday_dfs: Dict[str, Optional[pd.DataFrame]] = {}
        data_errors: Dict[str, str] = {}
        for i, sym in enumerate(universe):
            d = hde.ensure_candles(sym, "1d", warm_start, end)
            if not d["ok"]:
                data_errors[sym] = d["error"]
                continue
            daily_dfs[sym] = _to_df(d["candles"])
            if interval != "1d":
                r = hde.ensure_candles(sym, interval, start, end)
                if not r["ok"]:
                    data_errors[sym] = r["error"]
                    continue
                intraday_dfs[sym] = _to_df(r["candles"])
                per_symbol[sym] = [c for c in r["candles"]
                                   if start <= c["ts"][:10] <= end]
            else:
                intraday_dfs[sym] = None
                per_symbol[sym] = [c for c in d["candles"]
                                   if start <= c["ts"][:10] <= end]
            bp.update_run(run_id, progress={
                "phase": "DATA", "done": i + 1, "total": len(universe)})
        emit("SCAN_FETCH_COMPLETED", "SUPERVISOR", scan_id=run_id,
             mode="BACKTEST", run_id=run_id,
             payload={"symbols_ok": len(per_symbol),
                      "symbols_failed": len(data_errors)})
        if not per_symbol:
            raise RuntimeError(
                f"No historical data for any symbol: {json.dumps(data_errors)[:400]}")

        # 2. Candle-by-candle replay through the PRODUCTION pipeline.
        from live_scan_engine import _scan_one, derive_symbol_events
        timeline = _replay_timestamps(interval, per_symbol)
        cash = capital
        tick_count = len(timeline)
        # Persist exact replay inputs so validate_run can reproduce them:
        # cash at scan time per tick (change-compressed) + the adaptive
        # learning state fingerprint the pipeline consulted.
        cash_log: List[List[Any]] = [[0, round(capital, 2)]]
        learning_fp = _learning_fingerprint()
        for tick_i, ts_iso in enumerate(timeline):
            ts = pd.Timestamp(ts_iso)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            scan_id = f"{run_id}-T{tick_i:05d}"

            # current bars per symbol (only symbols with a candle at this ts)
            bars: Dict[str, Dict[str, float]] = {}
            for sym, candles in per_symbol.items():
                for c in candles:
                    if c["ts"] == ts_iso:
                        bars[sym] = c
                        break

            # exits first (against the current candle, never the entry candle)
            cash = _check_exits(run_id, scan_id, ts_iso, bars, cash)
            if round(cash, 2) != cash_log[-1][1]:
                cash_log.append([tick_i, round(cash, 2)])

            # scan every symbol that has a bar at this timestamp
            recs = []
            for sym in bars:
                df = build_asof_df(daily_dfs.get(sym), intraday_dfs.get(sym),
                                   ts, interval)
                fr = _fetch_result(sym, df, ts_iso)
                recs.append(_scan_one(sym, fr, scan_id, ts_iso, cash))
            emit_many(derive_symbol_events(recs, scan_id, mode="BACKTEST",
                                           run_id=run_id))

            # enter BUY-class recommendations via the isolated ledger
            for rec in recs:
                if rec.error is None and rec.all_gates_passed \
                        and rec.final_action in ("BUY", "STRONG BUY"):
                    cash, _tid = _try_enter(run_id, scan_id, rec, cash, ts_iso)

            if tick_i % 5 == 0 or tick_i == tick_count - 1:
                snap_marks = {s: float(b["close"]) for s, b in bars.items()}
                snap = bp.portfolio_snapshot(run_id, snap_marks)
                emit("PORTFOLIO_UPDATED", "PORTFOLIO", scan_id=scan_id,
                     mode="BACKTEST", run_id=run_id,
                     payload={"cash": snap["cash"],
                              "portfolio_value": snap["portfolio_value"],
                              "open_positions": snap["open_positions_count"],
                              "realized_pnl": snap["realized_pnl"]})
                bp.update_run(run_id, progress={
                    "phase": "REPLAY", "done": tick_i + 1, "total": tick_count,
                    "ts": ts_iso, "cash": round(cash, 2)})

        # 3. Close whatever is still open at the final candle close.
        last_close: Dict[str, float] = {}
        for sym, candles in per_symbol.items():
            if candles:
                last_close[sym] = float(candles[-1]["close"])
        final_ts = timeline[-1] if timeline else end
        for t in bp.open_trades(run_id):
            px = last_close.get(str(t["symbol"]).upper(),
                                float(t["fill_price"]))
            closed = bp.close_trade(t["trade_id"], final_ts, px,
                                    "END_OF_BACKTEST")
            if closed:
                cash += px * int(t["quantity"])
                emit("POSITION_CLOSED", "PORTFOLIO", scan_id=run_id,
                     symbol=t["symbol"], mode="BACKTEST", run_id=run_id,
                     payload={"trade_id": t["trade_id"],
                              "exit_rule": "END_OF_BACKTEST",
                              "exit_price": px,
                              "realized_pnl": closed.get("realized_pnl")})

        # 4. Final snapshot + analytics.
        snap = bp.portfolio_snapshot(run_id, last_close)
        missed = analyze_missed_opportunities(run_id, per_symbol, interval)
        metrics = {k: snap[k] for k in
                   ("starting_capital", "cash", "realized_pnl",
                    "net_return_pct", "win_rate", "wins", "losses",
                    "max_drawdown_pct", "portfolio_value", "total_trades")}
        metrics["ticks"] = tick_count
        metrics["symbols"] = len(per_symbol)
        metrics["data_errors"] = data_errors
        bp.update_run(run_id, status="COMPLETED",
                      completed_at=datetime.now(timezone.utc),
                      config={**cfg, "cash_by_tick": cash_log,
                              "learning_fingerprint": learning_fp},
                      metrics=metrics, missed=missed,
                      progress={"phase": "DONE", "done": tick_count,
                                "total": tick_count})
        emit("SCAN_COMPLETED", "SUPERVISOR", scan_id=run_id, mode="BACKTEST",
             run_id=run_id, payload=metrics)
        return {"ok": True, "run_id": run_id, "metrics": metrics}
    except Exception as exc:
        bp.update_run(run_id, status="FAILED", error=str(exc)[:500],
                      completed_at=datetime.now(timezone.utc))
        emit("SCAN_FAILED", "SUPERVISOR", scan_id=run_id, mode="BACKTEST",
             run_id=run_id, payload={"error": str(exc)[:300]})
        return {"ok": False, "run_id": run_id, "error": str(exc)[:500]}


# ── Part F: Missed Opportunity Analyzer ──────────────────────────────────────

def analyze_missed_opportunities(run_id: str,
                                 per_symbol: Dict[str, List[Dict[str, Any]]],
                                 interval: str,
                                 horizon_bars: int = 10) -> List[Dict[str, Any]]:
    """
    For every RISK_REJECTED / WATCH decision in the run, compute what the
    symbol actually did over the following `horizon_bars` candles.
    Advisory only — NEVER changes any strategy.
    """
    from pipeline_events import query_events
    rejected = query_events(run_id=run_id, mode="BACKTEST",
                            event_type="RISK_REJECTED", limit=5000)
    watches = query_events(run_id=run_id, mode="BACKTEST",
                           event_type="WATCH_GENERATED", limit=5000)
    timeline = _replay_timestamps(interval, per_symbol)
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for ev in rejected + watches:
        sym = str(ev.get("symbol") or "").upper()
        scan_id = ev.get("scan_id") or ""
        key = (sym, scan_id, ev["event_type"])
        if not sym or key in seen:
            continue
        seen.add(key)
        candles = per_symbol.get(sym) or []
        # map the scan tick to the symbol's candle BY TIMESTAMP (symbols can
        # have gaps, so tick index != per-symbol candle index)
        try:
            tick_i = int(scan_id.rsplit("-T", 1)[1])
        except Exception:
            continue
        if tick_i >= len(timeline):
            continue
        tick_ts = timeline[tick_i]
        base_idx = next((i for i, c in enumerate(candles)
                         if c["ts"] == tick_ts), None)
        if base_idx is None:
            continue
        payload = ev.get("payload") or {}
        failed_gates = payload.get("failed_gates") or {}
        reason = (
            "; ".join(f"{k}: {(v or {}).get('reason', 'failed')}"
                      for k, v in failed_gates.items())
            if failed_gates else
            payload.get("reason") or ev["event_type"]
        )
        base_price = float(candles[base_idx]["close"])
        future = candles[base_idx + 1: base_idx + 1 + horizon_bars]
        if not future or base_price <= 0:
            continue
        max_up = max(float(c["high"]) for c in future)
        end_close = float(future[-1]["close"])
        potential = round((max_up - base_price) / base_price * 100.0, 2)
        realized = round((end_close - base_price) / base_price * 100.0, 2)
        relax_hint = None
        if len(failed_gates) == 1:
            gate = next(iter(failed_gates))
            relax_hint = (f"Only the '{gate}' gate failed — relaxing it alone "
                          f"would have allowed this entry (advisory only).")
        out.append({
            "symbol": sym, "scan_id": scan_id,
            "decision": ("RISK_REJECTED" if ev["event_type"] == "RISK_REJECTED"
                         else "WATCH"),
            "reason": reason,
            "base_price": base_price,
            "potential_return_pct": potential,
            "return_at_horizon_pct": realized,
            "would_have_been_profitable": realized > 0,
            "horizon_bars": len(future),
            "single_rule_relax_hint": relax_hint,
        })
    out.sort(key=lambda m: m["potential_return_pct"], reverse=True)
    return out[:100]


# ── Part I: Historical Validation Engine ─────────────────────────────────────

def validate_run(run_id: str, sample: int = 25) -> Dict[str, Any]:
    """
    Prove replay ≡ pipeline: re-build the exact as-of dataframe for a sample
    of recorded decisions and re-run _scan_one. Any difference in
    final_action / strategy / confidence is logged as a mismatch with
    symbol, time, expected vs actual and reason.
    """
    from pipeline_events import query_events
    from live_scan_engine import _scan_one

    run = bp.get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Unknown run {run_id}"}
    cfg = run.get("config") or {}
    interval = str(cfg.get("interval") or "1d")
    start = str(cfg.get("start"))[:10]
    end = str(cfg.get("end"))[:10]
    warm_start = (date.fromisoformat(start)
                  - timedelta(days=WARMUP_DAILY_DAYS)).isoformat()

    decisions = [e for e in query_events(run_id=run_id, mode="BACKTEST",
                                         stage="AI_DECISION", limit=5000)
                 if e["event_type"] in ("BUY_GENERATED", "WATCH_GENERATED",
                                        "IGNORE_GENERATED")]
    if not decisions:
        return {"ok": True, "checked": 0, "skipped": 0, "mismatches": [],
                "verdict": "NO_DECISIONS"}
    step = max(1, len(decisions) // sample)
    picked = decisions[::step][:sample]

    # exact replay inputs recorded by execute_run
    capital = float(cfg.get("capital") or 100000.0)
    cash_log = cfg.get("cash_by_tick") or [[0, capital]]
    learning_fp = cfg.get("learning_fingerprint")
    learning_changed = (learning_fp is not None
                        and _learning_fingerprint() != learning_fp)

    def cash_at(tick_i: int) -> float:
        c = capital
        for entry in cash_log:
            if int(entry[0]) <= tick_i:
                c = float(entry[1])
            else:
                break
        return c

    daily_cache: Dict[str, pd.DataFrame] = {}
    intra_cache: Dict[str, Optional[pd.DataFrame]] = {}
    mismatches: List[Dict[str, Any]] = []
    all_ts: Optional[List[str]] = None
    checked = 0
    skipped = 0
    for ev in picked:
        sym = str(ev.get("symbol") or "").upper()
        scan_id = ev.get("scan_id") or ""
        if not sym:
            skipped += 1
            continue
        try:
            tick_i = int(scan_id.rsplit("-T", 1)[1])
        except Exception:
            skipped += 1
            continue
        if sym not in daily_cache:
            daily_cache[sym] = _to_df(hde.get_candles(sym, "1d", warm_start, end))
            intra_cache[sym] = (_to_df(hde.get_candles(sym, interval, start, end))
                                if interval != "1d" else None)
        # validation uses the same candle cache the run used — determinism
        src = (hde.get_candles(sym, interval, start, end) if interval != "1d"
               else hde.get_candles(sym, "1d", start, end))
        if all_ts is None:
            all_ts = _validation_timeline(run_id, cfg)
        if tick_i >= len(all_ts):
            skipped += 1
            continue
        ts_iso = all_ts[tick_i]
        if ts_iso not in {c["ts"] for c in src}:
            skipped += 1
            continue
        ts = pd.Timestamp(ts_iso)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        df = build_asof_df(daily_cache[sym], intra_cache[sym], ts, interval)
        fr = _fetch_result(sym, df, ts_iso)
        rec = _scan_one(sym, fr, scan_id, ts_iso, cash_at(tick_i))
        checked += 1
        payload = ev.get("payload") or {}
        expected_action = payload.get("action")
        expected_conf = payload.get("confidence")
        diffs = []
        if rec.final_action != expected_action:
            diffs.append(f"action {expected_action} → {rec.final_action}")
        if isinstance(expected_conf, (int, float)) and \
                rec.calibrated_confidence is not None and \
                abs(float(rec.calibrated_confidence) - float(expected_conf)) > 0.51:
            diffs.append(f"confidence {expected_conf} → "
                         f"{rec.calibrated_confidence}")
        if diffs:
            mismatches.append({
                "symbol": sym, "time": ts_iso, "scan_id": scan_id,
                "expected_decision": expected_action,
                "actual_decision": rec.final_action,
                "reason": ("Re-running the production pipeline on the "
                           "identical as-of data differed: "
                           + "; ".join(diffs)
                           + ("; NOTE: adaptive learning state changed since "
                              "the run, so this may be environmental, not a "
                              "pipeline bug" if learning_changed else "")),
            })
    if checked == 0:
        verdict = "INDETERMINATE"
    elif mismatches:
        verdict = ("INDETERMINATE" if learning_changed else "MISMATCH")
    else:
        verdict = "MATCH"
    result = {
        "ok": True, "run_id": run_id, "checked": checked, "skipped": skipped,
        "mismatches": mismatches,
        "learning_state_changed": learning_changed,
        "verdict": verdict,
        "note": ("Validation re-runs live_scan_engine._scan_one on the exact "
                 "as-of candle data AND the recorded per-tick cash the replay "
                 "used. Verdict is INDETERMINATE when nothing could be "
                 "checked or when the adaptive-learning state changed since "
                 "the run."),
    }
    bp.update_run(run_id, validation=result)
    return result


def _validation_timeline(run_id: str, cfg: Dict[str, Any]) -> List[str]:
    """Rebuild the run's union replay timeline from the candle cache."""
    interval = str(cfg.get("interval") or "1d")
    start = str(cfg.get("start"))[:10]
    end = str(cfg.get("end"))[:10]
    universe = resolve_universe(cfg)
    ts: set = set()
    for sym in universe:
        src = hde.get_candles(sym, interval if interval != "1d" else "1d",
                              start, end)
        for c in src:
            ts.add(c["ts"])
    return sorted(ts)


# ── Decision tree (Part E backend) ───────────────────────────────────────────

def decision_tree(run_or_scan_id: str, symbol: str,
                  mode: str = "BACKTEST") -> Dict[str, Any]:
    """
    Complete decision tree for one symbol in one run/scan, straight from the
    canonical event store: every stage, every gate, every rejection with the
    exact rule, confidence and indicator values. No hidden logic.
    """
    from pipeline_events import query_events, STAGES
    kwargs: Dict[str, Any] = {"symbol": symbol.upper(), "mode": mode,
                              "limit": 2000}
    if mode == "BACKTEST":
        kwargs["run_id"] = run_or_scan_id
    else:
        kwargs["scan_id"] = run_or_scan_id
    events = query_events(**kwargs)
    by_stage: Dict[str, List[Dict[str, Any]]] = {s: [] for s in STAGES}
    for e in events:
        by_stage.setdefault(e["stage"], []).append(e)
    ledger = ([t for t in bp.trades(run_or_scan_id)
               if str(t["symbol"]).upper() == symbol.upper()]
              if mode == "BACKTEST" else [])
    return {
        "id": run_or_scan_id, "symbol": symbol.upper(), "mode": mode,
        "stages": [{"stage": s, "events": by_stage.get(s, [])}
                   for s in STAGES],
        "trades": ledger,
        "total_events": len(events),
    }
