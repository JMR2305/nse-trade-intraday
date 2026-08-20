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
import os
import sys
import time
from datetime import datetime, timedelta, date, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

import backtest_portfolio as bp
import historical_data_engine as hde
from pipeline_events import emit, emit_many

WARMUP_DAILY_DAYS = 270          # calendar days of daily history for indicators
DEFAULT_SETTINGS = {             # same knobs phase20 uses
    "fill_model": "NEXT_QUOTE",
    "slippage_pct": 0.15,
    "charges_pct": 0.12,
}

# Settings-driven position sizing (Capital Deployment Fix).
# Defaults preserve historical behaviour EXACTLY: 1% risk, 25% cap,
# scale-in disabled → one open position per symbol.
DEFAULT_SIZING = {
    "risk_per_trade_pct": 1.0,             # % of current cash risked per trade
    "max_position_cap_pct": 25.0,          # max % of cash in one tranche
    "max_symbol_exposure_pct": 25.0,       # total cost basis per symbol vs portfolio
    "max_total_exposure_pct": 80.0,        # total open cost basis vs portfolio
    "scale_in_enabled": False,             # OFF by default — no behaviour change
    "max_scale_in_count": 2,               # extra tranches allowed per symbol
    "scale_in_min_confidence": 60.0,
    "scale_in_min_rr": 1.5,
    "scale_in_min_unrealized_profit_pct": -1.0,  # existing position not deeply negative
}

# Minimum prior sessions with data at the same time-of-day before the
# time-normalized intraday volume ratio is trusted (Task 4 fallback rule).
VOL_CURVE_MIN_DAYS = 5


# Safe bounds per numeric sizing knob: (min, max). Values outside the bound,
# non-finite (NaN/Inf) or non-numeric fall back to the default — fail-safe.
_SIZING_BOUNDS = {
    "risk_per_trade_pct": (0.01, 10.0),
    "max_position_cap_pct": (0.1, 100.0),
    "max_symbol_exposure_pct": (0.1, 100.0),
    "max_total_exposure_pct": (0.1, 100.0),
    "scale_in_min_confidence": (0.0, 100.0),
    "scale_in_min_rr": (0.0, 100.0),
    "scale_in_min_unrealized_profit_pct": (-100.0, 100.0),
}


def resolve_sizing(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge run-config sizing over safe defaults. Strictly validated:
    booleans must be real JSON booleans (strings like "false" are rejected),
    numbers must be finite and within safe bounds, otherwise the default is
    kept. Unknown keys are ignored. This is the last line of defence for
    unvalidated API payloads — never trust raw values in guard comparisons
    (NaN compares false and would silently bypass exposure caps).
    """
    raw = cfg.get("sizing") or {}
    out = dict(DEFAULT_SIZING)
    if not isinstance(raw, dict):
        return out
    for k in DEFAULT_SIZING:
        v = raw.get(k)
        if v is None:
            continue
        if k == "scale_in_enabled":
            if isinstance(v, bool):
                out[k] = v
        elif k == "max_scale_in_count":
            if isinstance(v, (int, float)) and not isinstance(v, bool) \
                    and math.isfinite(float(v)) and 0 <= int(v) <= 10:
                out[k] = int(v)
        else:
            lo, hi = _SIZING_BOUNDS[k]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                f = float(v)
                if math.isfinite(f) and lo <= f <= hi:
                    out[k] = f
    return out


# ── Universe resolution ──────────────────────────────────────────────────────

def _set_universe_resolution(
    cfg: Dict[str, Any],
    evidence: str,
    *,
    as_of_date: Optional[str] = None,
    snapshot_at: Optional[str] = None,
) -> None:
    """Persist a human-readable account of the membership evidence used."""
    source = (
        "IMMUTABLE_HISTORICAL_SNAPSHOT"
        if evidence == "HISTORICAL_SNAPSHOT"
        else "CURRENT_ACTIVE_LIST_FALLBACK"
        if evidence == "CURRENT_MEMBERSHIP_FALLBACK"
        else "HISTORICAL_SNAPSHOT_UNAVAILABLE"
    )
    cfg["universe_evidence"] = evidence
    cfg["universe_resolution"] = {
        "evidence": evidence,
        "source": source,
        "as_of_date": as_of_date,
        "snapshot_at": snapshot_at,
        "degraded": evidence == "CURRENT_MEMBERSHIP_FALLBACK",
    }


def resolve_universe(
    cfg: Dict[str, Any],
    universe_mode: Optional[str] = None,
    as_of_date: Optional[str] = None,
) -> List[str]:
    symbols = cfg.get("symbols")
    if symbols:
        return [str(s).upper() for s in symbols]
    universe = str(universe_mode or cfg.get("universe_mode") or cfg.get("universe") or "configured").lower()
    if universe in ("custom_low_price_sector", "custom-low-price-sector"):
        target_date = str(as_of_date or cfg.get("as_of_date") or cfg.get("end") or "")[:10]
        try:
            from custom_universe_store import (
                get_active_symbols,
                get_historical_universe_resolution,
            )
            historical = get_historical_universe_resolution(target_date)
            if historical.get("status") == "HISTORICAL_SNAPSHOT":
                _set_universe_resolution(
                    cfg,
                    "HISTORICAL_SNAPSHOT",
                    as_of_date=historical.get("as_of_date") or target_date,
                    snapshot_at=historical.get("snapshot_at"),
                )
                return list(historical.get("symbols") or [])
            # Current membership is future information for a historical run.
            # Keep the legacy fallback available only by an explicit operator
            # opt-in, and persist evidence quality in the run configuration.
            if (
                historical.get("status") == "HISTORICAL_SNAPSHOT_UNAVAILABLE"
                and cfg.get("allow_current_universe_fallback") is True
            ):
                _set_universe_resolution(
                    cfg,
                    "CURRENT_MEMBERSHIP_FALLBACK",
                    as_of_date=historical.get("as_of_date") or target_date,
                )
                logger = __import__("logging").getLogger(__name__)
                logger.warning(
                    "CUSTOM_LOW_PRICE_SECTOR has no snapshot on/before %s; "
                    "using explicitly opted-in current membership",
                    target_date or "unknown",
                )
                return get_active_symbols()
            _set_universe_resolution(
                cfg,
                "HISTORICAL_SNAPSHOT_UNAVAILABLE",
                as_of_date=historical.get("as_of_date") or target_date,
            )
            return []
        except Exception:
            _set_universe_resolution(
                cfg,
                "HISTORICAL_SNAPSHOT_UNAVAILABLE",
                as_of_date=target_date,
            )
            return []
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
                  ts: pd.Timestamp, interval: str,
                  vol_normalize: bool = False) -> Optional[pd.DataFrame]:
    """
    Build the OHLCV dataframe a live scan would have seen at moment `ts`:
      * daily interval: all daily bars with timestamp <= ts.
      * intraday: daily bars from days strictly BEFORE ts.date(), plus one
        partial "today" bar aggregated from intraday candles up to ts.
    Strictly no data after `ts` is included — this is the no-lookahead
    guarantee, and the validation engine re-derives it identically.

    vol_normalize (intraday only, opt-in per run): attach a time-of-day
    normalized volume ratio to df.attrs["intraday_vol_norm"] — session-so-far
    volume vs the AVERAGE session-to-date volume at the same time-of-day over
    prior sessions in the cache. Never fabricated: with fewer than
    VOL_CURVE_MIN_DAYS prior sessions it reports ok=False (insufficient
    evidence) and the pipeline falls back to the raw full-day ratio.
    Daily mode is never affected.
    """
    if daily is None or daily.empty:
        return None
    if interval == "1d":
        df = daily[daily.index <= ts]
        return df if not df.empty else None
    day_start = ts.normalize()
    df = daily[daily.index < day_start]
    session_vol: Optional[float] = None
    if intraday is not None and not intraday.empty:
        today = intraday[(intraday.index >= day_start) & (intraday.index <= ts)]
        if not today.empty:
            session_vol = float(today["volume"].sum())
            bar = pd.DataFrame(
                [{
                    "open": float(today["open"].iloc[0]),
                    "high": float(today["high"].max()),
                    "low": float(today["low"].min()),
                    "close": float(today["close"].iloc[-1]),
                    "volume": session_vol,
                }],
                index=[day_start],
            )
            df = pd.concat([df, bar])
    if df.empty:
        return None
    if vol_normalize and session_vol is not None:
        df.attrs["intraday_vol_norm"] = _time_of_day_volume_ratio(
            intraday, ts, day_start, session_vol)
    return df


def _time_of_day_volume_ratio(intraday: pd.DataFrame, ts: pd.Timestamp,
                              day_start: pd.Timestamp,
                              session_vol: float) -> Dict[str, Any]:
    """
    session_so_far_volume / average_session_to_date_volume_at_same_time,
    strictly from prior sessions ALREADY in the as-of window (< day_start —
    no look-ahead). Returns ok=False with a reason when evidence is
    insufficient; never fabricates a volume curve.
    """
    cutoff = ts.time()
    prior = intraday[intraday.index < day_start]
    cums: List[float] = []
    if not prior.empty:
        for day, grp in prior.groupby(prior.index.normalize()):
            v = float(grp[grp.index.time <= cutoff]["volume"].sum())
            if v > 0:
                cums.append(v)
    if len(cums) < VOL_CURVE_MIN_DAYS:
        return {"ok": False, "days": len(cums),
                "reason": (f"insufficient volume-curve evidence: "
                           f"{len(cums)} prior sessions < {VOL_CURVE_MIN_DAYS}")}
    avg = sum(cums) / len(cums)
    if avg <= 0:
        return {"ok": False, "days": len(cums),
                "reason": "prior session-to-date volumes are zero"}
    return {"ok": True, "ratio": round(session_vol / avg, 4),
            "days": len(cums), "cutoff": str(cutoff),
            "basis": "time_of_day_normalized"}


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

def _try_enter(run_id: str, scan_id: str, rec, cash: float, ts: str,
               sizing: Optional[Dict[str, Any]] = None,
               mark: Optional[float] = None) -> Tuple[float, Optional[str]]:
    """
    Enter a BUY-class recommendation into the backtest ledger.

    Sizing is settings-driven (resolve_sizing). Behaviour with default
    settings is IDENTICAL to the historical hardcoded 1% risk / 25% cap /
    one-open-position-per-symbol rule.

    Scale-in (only when sizing["scale_in_enabled"] is true): if an OPEN
    position already exists for the symbol, an additional tranche is allowed
    only when every scale-in guard passes; every attempt emits
    SCALE_IN_APPROVED / SCALE_IN_REJECTED (with the exact reason) and
    executed tranches additionally emit SCALE_IN_EXECUTED.
    """
    from phase20_executor import compute_fill, compute_charges
    s = sizing or DEFAULT_SIZING
    entry, stop = float(rec.entry_price), float(rec.stop_loss)
    per_share_risk = entry - stop
    if entry <= 0 or per_share_risk <= 0:
        if s.get("scale_in_enabled"):
            open_now = [t for t in bp.open_trades(run_id)
                        if str(t["symbol"]).upper() == str(rec.symbol).upper()]
            if open_now:
                emit("SCALE_IN_REJECTED", "EXECUTION", scan_id=scan_id,
                     symbol=rec.symbol, mode="BACKTEST", run_id=run_id,
                     payload={"reason": "Invalid stop-loss/target for scale-in"})
        return cash, None

    # Existing OPEN tranches for this symbol / whole run (for scale-in guards)
    sym = str(rec.symbol).upper()
    open_all = bp.open_trades(run_id)
    open_sym = [t for t in open_all if str(t["symbol"]).upper() == sym]
    tranche = 0
    scale_in = bool(open_sym)
    if scale_in:
        if not s.get("scale_in_enabled"):
            # Preserved historical behaviour: duplicate entry cancelled.
            emit("ORDER_CANCELLED", "EXECUTION", scan_id=scan_id, symbol=rec.symbol,
                 mode="BACKTEST", run_id=run_id,
                 payload={"reason": "Open backtest position already exists"})
            return cash, None
        ok, reject_reason, tranche = _scale_in_guards(
            rec, s, open_all, open_sym, cash, entry, mark)
        if not ok:
            emit("SCALE_IN_REJECTED", "EXECUTION", scan_id=scan_id,
                 symbol=rec.symbol, mode="BACKTEST", run_id=run_id,
                 payload={"reason": reject_reason,
                          "open_tranches": len(open_sym),
                          "cash": round(cash, 2)})
            return cash, None

    risk_amount = cash * float(s["risk_per_trade_pct"]) / 100.0
    qty = int(risk_amount / per_share_risk)
    max_qty = int(cash * float(s["max_position_cap_pct"]) / 100.0 / entry)
    qty = min(qty, max_qty)
    if qty < 1:
        ev = "SCALE_IN_REJECTED" if scale_in else "ORDER_REJECTED"
        emit(ev, "EXECUTION", scan_id=scan_id, symbol=rec.symbol,
             mode="BACKTEST", run_id=run_id,
             payload={"reason": "Position size < 1 share for available cash",
                      "cash": round(cash, 2)})
        return cash, None
    fill = compute_fill(entry, DEFAULT_SETTINGS, side="BUY")
    fill_price = fill["fill_price"]
    charges = compute_charges(fill_price * qty, DEFAULT_SETTINGS)
    cost = fill_price * qty + charges
    if cost > cash:
        ev = "SCALE_IN_REJECTED" if scale_in else "ORDER_REJECTED"
        emit(ev, "EXECUTION", scan_id=scan_id, symbol=rec.symbol,
             mode="BACKTEST", run_id=run_id,
             payload={"reason": "Insufficient cash", "cost": round(cost, 2),
                      "cash": round(cash, 2)})
        return cash, None
    if scale_in:
        # Exposure guards re-checked WITH the new tranche cost included.
        pv = cash + sum(float(t["fill_price"]) * int(t["quantity"])
                        for t in open_all)
        sym_cost = sum(float(t["fill_price"]) * int(t["quantity"])
                       for t in open_sym) + cost
        tot_cost = sum(float(t["fill_price"]) * int(t["quantity"])
                       for t in open_all) + cost
        if pv > 0 and sym_cost / pv * 100.0 > float(s["max_symbol_exposure_pct"]):
            emit("SCALE_IN_REJECTED", "EXECUTION", scan_id=scan_id,
                 symbol=rec.symbol, mode="BACKTEST", run_id=run_id,
                 payload={"reason": f"Symbol exposure {sym_cost / pv * 100.0:.1f}%"
                                    f" would exceed cap {s['max_symbol_exposure_pct']}%"})
            return cash, None
        if pv > 0 and tot_cost / pv * 100.0 > float(s["max_total_exposure_pct"]):
            emit("SCALE_IN_REJECTED", "EXECUTION", scan_id=scan_id,
                 symbol=rec.symbol, mode="BACKTEST", run_id=run_id,
                 payload={"reason": f"Total exposure {tot_cost / pv * 100.0:.1f}%"
                                    f" would exceed cap {s['max_total_exposure_pct']}%"})
            return cash, None
        emit("SCALE_IN_APPROVED", "EXECUTION", scan_id=scan_id,
             symbol=rec.symbol, mode="BACKTEST", run_id=run_id,
             payload={"tranche": tranche, "qty": qty,
                      "confidence": rec.calibrated_confidence,
                      "rr_ratio": rec.rr_ratio})

    emit("ORDER_SUBMITTED", "EXECUTION", scan_id=scan_id, symbol=rec.symbol,
         mode="BACKTEST", run_id=run_id,
         payload={"qty": qty, "signal_price": entry, "tranche": tranche,
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
        "tranche": tranche,
    })
    if trade_id is None:
        emit("ORDER_CANCELLED", "EXECUTION", scan_id=scan_id, symbol=rec.symbol,
             mode="BACKTEST", run_id=run_id,
             payload={"reason": "Open backtest position already exists"})
        return cash, None
    if scale_in:
        emit("SCALE_IN_EXECUTED", "EXECUTION", scan_id=scan_id,
             symbol=rec.symbol, mode="BACKTEST", run_id=run_id,
             payload={"trade_id": trade_id, "tranche": tranche,
                      "fill_price": fill_price, "qty": qty})
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


def _scale_in_guards(rec, s: Dict[str, Any], open_all: List[Dict[str, Any]],
                     open_sym: List[Dict[str, Any]], cash: float,
                     entry: float, mark: Optional[float]
                     ) -> Tuple[bool, str, int]:
    """
    Pre-sizing scale-in guards. Returns (ok, reject_reason, tranche_number).
    Exposure caps are re-checked after sizing (with the actual tranche cost).
    """
    # open_sym includes the initial tranche
    n_scale_ins = max(0, len(open_sym) - 1)
    if n_scale_ins >= int(s["max_scale_in_count"]):
        return False, (f"Scale-in count {n_scale_ins} at limit "
                       f"({int(s['max_scale_in_count'])})"), 0
    conf = float(rec.calibrated_confidence or 0.0)
    if conf < float(s["scale_in_min_confidence"]):
        return False, (f"Confidence {conf:.1f} below scale-in threshold "
                       f"{s['scale_in_min_confidence']}"), 0
    rr = float(rec.rr_ratio or 0.0)
    if rr < float(s["scale_in_min_rr"]):
        return False, (f"Risk/reward {rr:.2f} below scale-in threshold "
                       f"{s['scale_in_min_rr']}"), 0
    stop, target = float(rec.stop_loss), float(rec.target_price)
    if not (0 < stop < entry < target):
        return False, "Invalid stop-loss/target for scale-in", 0
    # Existing position must be profitable or not deeply negative.
    px = float(mark) if mark else entry
    cost = sum(float(t["fill_price"]) * int(t["quantity"]) for t in open_sym)
    qty = sum(int(t["quantity"]) for t in open_sym)
    if cost > 0 and qty > 0:
        unreal_pct = (px * qty - cost) / cost * 100.0
        if unreal_pct < float(s["scale_in_min_unrealized_profit_pct"]):
            return False, (f"Existing position unrealized {unreal_pct:.2f}% "
                           f"below scale-in floor "
                           f"{s['scale_in_min_unrealized_profit_pct']}%"), 0
    tranche = max(int(t.get("tranche") or 0) for t in open_sym) + 1
    return True, "", tranche


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


def _spawn_next_queued() -> None:
    """Promote the next QUEUED run to PENDING and spawn its worker process.

    Called after any run finishes (COMPLETED, FAILED, or checkpoint-CANCELLED)
    so the queue drains automatically.

    Before promoting, the watchdog sweep is run to convert any RUNNING runs
    whose worker process died silently (OOM kill, container restart) into FAILED.
    This frees concurrency slots so the queue is never permanently blocked by a
    ghost RUNNING row.

    On any spawn/log-open failure the promoted run is reverted to QUEUED
    *provided it is still PENDING* (i.e. no other process has already claimed
    it).  This prevents the run from waiting 30 minutes for the stale watchdog
    rather than retrying on the next sweep poll.

    Failures are always swallowed at the outermost level — this helper must
    never crash the finishing worker.
    """
    # Run the watchdog before checking the queue — clears ghost RUNNING slots.
    try:
        bp.sweep_watchdog_timeouts()
    except Exception:
        pass  # never block queue promotion on a watchdog failure

    next_rid = None
    try:
        next_rid = bp.promote_next_queued()
        if not next_rid:
            return
        import subprocess as _sub
        _main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
        log_path = f"/tmp/backtest_{next_rid}.log"
        with open(log_path, "ab") as _lf:
            _sub.Popen(
                [sys.executable, _main_py,
                 "backtest_exec", json.dumps({"run_id": next_rid})],
                stdout=_lf, stderr=_lf,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                start_new_session=True,
            )
    except Exception:
        # Revert to QUEUED only if the run is still PENDING (not RUNNING —
        # another process may have already claimed it).
        if next_rid is not None:
            try:
                bp.revert_pending_to_queued(next_rid)
            except Exception:
                pass


def execute_run(run_id: str) -> Dict[str, Any]:
    """
    Execute a backtest run created via backtest_portfolio.create_run().
    Long-running — meant to be launched in a detached process.
    """
    _perf_start = time.perf_counter()  # wall-clock start for telemetry
    run = bp.get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Unknown run {run_id}"}
    cfg = run.get("config") or {}
    interval = str(cfg.get("interval") or "1d")
    start = str(cfg.get("start"))[:10]
    end = str(cfg.get("end"))[:10]
    capital = float(cfg.get("capital") or 100000.0)
    universe = resolve_universe(cfg)
    if not universe:
        reason = (
            "No historical CUSTOM_LOW_PRICE_SECTOR snapshot exists on or "
            "before this run's as-of date. Choose a later date or explicitly "
            "opt in to current-membership fallback."
        )
        bp._emergency_mark_failed(run_id, reason)
        return {"ok": False, "run_id": run_id, "error": reason,
                "universe_evidence": cfg.get("universe_evidence")}

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
        mock_candle_symbols: List[str] = []

        def _has_mock(candles: List[Dict[str, Any]]) -> bool:
            """True when any candle is tagged source='mock'."""
            return any(str(c.get("source") or "").lower() == "mock"
                       for c in candles)

        for i, sym in enumerate(universe):
            d = hde.ensure_candles(sym, "1d", warm_start, end)
            if not d["ok"]:
                data_errors[sym] = d["error"]
                continue
            # Reject mock-sourced daily candles — these are synthetic fallback
            # data from market_data_engine (yfinance was rate-limited during
            # cache population).  Running decisions on mock prices produces
            # results that look real but are meaningless.
            if _has_mock(d["candles"]):
                mock_candle_symbols.append(sym)
                data_errors[sym] = (
                    f"{sym}: daily candles are synthetic (source='mock') — "
                    f"yfinance was rate-limited when the cache was populated. "
                    f"Clear the cache entry and retry after the rate limit clears."
                )
                emit("MOCK_DATA_WARNING", "SUPERVISOR", scan_id=run_id,
                     mode="BACKTEST", run_id=run_id, symbol=sym,
                     payload={"reason": "mock_candle_source",
                              "interval": "1d", "symbol": sym})
                continue
            daily_dfs[sym] = _to_df(d["candles"])
            if interval != "1d":
                r = hde.ensure_candles(sym, interval, start, end)
                if not r["ok"]:
                    data_errors[sym] = r["error"]
                    continue
                # Same check for intraday candles.
                if _has_mock(r["candles"]):
                    mock_candle_symbols.append(sym)
                    data_errors[sym] = (
                        f"{sym}: {interval} candles are synthetic "
                        f"(source='mock') — yfinance was rate-limited when "
                        f"the cache was populated. Clear the cache entry and "
                        f"retry after the rate limit clears."
                    )
                    emit("MOCK_DATA_WARNING", "SUPERVISOR", scan_id=run_id,
                         mode="BACKTEST", run_id=run_id, symbol=sym,
                         payload={"reason": "mock_candle_source",
                                  "interval": interval, "symbol": sym})
                    continue
                intraday_dfs[sym] = _to_df(r["candles"])
                per_symbol[sym] = [c for c in r["candles"]
                                   if start <= c["ts"][:10] <= end]
            else:
                intraday_dfs[sym] = None
                per_symbol[sym] = [c for c in d["candles"]
                                   if start <= c["ts"][:10] <= end]
            bp.update_run(run_id, progress={
                "phase": "DATA", "done": i + 1, "total": len(universe),
                "current_symbol": sym,
                "progress_updated_at": datetime.now(timezone.utc).isoformat()})
        emit("SCAN_FETCH_COMPLETED", "SUPERVISOR", scan_id=run_id,
             mode="BACKTEST", run_id=run_id,
             payload={"symbols_ok": len(per_symbol),
                      "symbols_failed": len(data_errors),
                      "mock_candle_symbols": mock_candle_symbols})
        if not per_symbol:
            mock_suffix = (
                f" Symbols with synthetic data: {mock_candle_symbols}."
                if mock_candle_symbols else ""
            )
            raise RuntimeError(
                f"No historical data for any symbol: "
                f"{json.dumps(data_errors)[:400]}{mock_suffix}"
            )

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
        sizing = resolve_sizing(cfg)
        vol_normalize = bool(cfg.get("volume_time_normalized")) and interval != "1d"

        # ── Performance: pre-build O(1) timestamp index for bar lookup ────────
        # Without this, each tick scans every candle of every symbol looking for
        # the matching timestamp — O(symbols × candles) per tick = ~1.5 M string
        # comparisons for a 5-symbol 15m 30-day run.
        per_symbol_ts_idx: Dict[str, Dict[str, Dict[str, float]]] = {
            sym: {c["ts"]: c for c in candles}
            for sym, candles in per_symbol.items()
        }

        # ── Performance: event buffer — batch DB writes every 5 ticks ─────────
        # Opening a new psycopg2 connection for each tick's emit_many() call
        # costs ~66 ms on Neon serverless.  Buffering events and flushing every
        # 5 ticks cuts 553 connections to ≤ 111 — saving ~29 s on a typical run.
        # Exit events (POSITION_CLOSED) from _check_exits are emitted promptly
        # (not buffered) to preserve their exact timing in the event stream.
        _evt_buf: List[Dict[str, Any]] = []

        # ── Telemetry accumulators (advisory, stored in metrics at completion) ─
        _tick_times: List[float] = []  # wall-clock ms per tick (avg / p95)
        _scan_ms    = 0.0              # cumulative _scan_one + indicator time
        _event_ms   = 0.0             # cumulative emit_many flush time
        _db_ms      = 0.0             # cumulative DB write time
        _progress_updates = 0         # heartbeat writes to backtest_runs
        _data_ms = (time.perf_counter() - _perf_start) * 1000  # DATA phase cost

        for tick_i, ts_iso in enumerate(timeline):
            _t0 = time.perf_counter()  # per-tick wall-clock start
            ts = pd.Timestamp(ts_iso)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            scan_id = f"{run_id}-T{tick_i:05d}"

            # O(1) bar lookup via pre-built timestamp index
            bars: Dict[str, Dict[str, float]] = {
                sym: idx[ts_iso]
                for sym, idx in per_symbol_ts_idx.items()
                if ts_iso in idx
            }

            # exits first (against the current candle, never the entry candle)
            _t_db = time.perf_counter()
            cash = _check_exits(run_id, scan_id, ts_iso, bars, cash)
            _db_ms += (time.perf_counter() - _t_db) * 1000
            if round(cash, 2) != cash_log[-1][1]:
                cash_log.append([tick_i, round(cash, 2)])

            # scan every symbol that has a bar at this timestamp
            recs = []
            _t_scan = time.perf_counter()
            for sym in bars:
                df = build_asof_df(daily_dfs.get(sym), intraday_dfs.get(sym),
                                   ts, interval, vol_normalize=vol_normalize)
                fr = _fetch_result(sym, df, ts_iso)
                recs.append(_scan_one(sym, fr, scan_id, ts_iso, cash))
            _scan_ms += (time.perf_counter() - _t_scan) * 1000
            # Buffer events — flushed every 5 ticks (see checkpoint block below)
            _evt_buf.extend(derive_symbol_events(recs, scan_id, mode="BACKTEST",
                                                 run_id=run_id))

            # enter BUY-class recommendations via the isolated ledger
            for rec in recs:
                if rec.error is None and rec.all_gates_passed \
                        and rec.final_action in ("BUY", "STRONG BUY"):
                    bar = bars.get(str(rec.symbol).upper())
                    cash, _tid = _try_enter(
                        run_id, scan_id, rec, cash, ts_iso, sizing=sizing,
                        mark=float(bar["close"]) if bar else None)

            # ── Every 5 ticks: flush events + cancel/stale check + heartbeat ──
            # Heartbeat MUST run every 5 ticks or the 30-min stale watchdog will
            # mark the run STALE.  Flushing events here keeps event latency ≤ 5
            # ticks (~75 min of 15m data) which is acceptable for backtest audit.
            if tick_i % 5 == 4 or tick_i == tick_count - 1:
                # Flush buffered scan events (one DB round-trip for ≤5 ticks)
                _t_evt = time.perf_counter()
                if _evt_buf:
                    emit_many(_evt_buf)
                    _evt_buf.clear()
                _event_ms += (time.perf_counter() - _t_evt) * 1000
                # Cancellation / stale checkpoint — one cheap DB read.
                # get_run_status() returns None on any DB error so a transient
                # Neon outage skips the check rather than crashing the run.
                try:
                    _cur_status = bp.get_run_status(run_id)
                except Exception:
                    _cur_status = None   # belt-and-suspenders: skip, not crash
                if _cur_status == "CANCEL_REQUESTED":
                    # Atomic: only writes CANCELLED if status is still
                    # CANCEL_REQUESTED (not yet STALE or otherwise terminal).
                    bp.cancel_checkpoint_run(run_id)
                    # Drain the queue: this slot is now free, so promote and
                    # spawn the next waiting run exactly like COMPLETED/FAILED.
                    _spawn_next_queued()
                    return {"ok": False, "run_id": run_id, "cancelled": True,
                            "ticks_completed": tick_i,
                            "message": "Run cancelled by operator at checkpoint"}
                if _cur_status == "STALE":
                    # Watchdog marked us stale (no heartbeat for 30+ min).
                    # Exit without overwriting the STALE status so operators
                    # see the correct audit state and can safely retry.
                    return {"ok": False, "run_id": run_id, "stale_exit": True,
                            "ticks_completed": tick_i,
                            "message": ("Run marked STALE by watchdog; "
                                        "worker exiting without overwriting state")}
                # Heartbeat: cheap progress write that resets the stale clock.
                _t_db = time.perf_counter()
                bp.update_run(run_id, progress={
                    "phase": "REPLAY", "done": tick_i + 1, "total": tick_count,
                    "ts": ts_iso, "cash": round(cash, 2),
                    "current_symbols": sorted(bars.keys()),
                    "progress_updated_at": datetime.now(timezone.utc).isoformat()})
                _db_ms += (time.perf_counter() - _t_db) * 1000
                _progress_updates += 1

            # ── Every 20 ticks: full portfolio snapshot ────────────────────────
            # More expensive than the heartbeat (reads all trades from DB).
            # 20-tick cadence keeps DB load low while still giving operators a
            # live equity curve at ~5 min resolution for 15m backtests.
            if tick_i % 20 == 0 or tick_i == tick_count - 1:
                snap_marks = {s: float(b["close"]) for s, b in bars.items()}
                _t_db = time.perf_counter()
                snap = bp.portfolio_snapshot(run_id, snap_marks)
                _db_ms += (time.perf_counter() - _t_db) * 1000
                # Buffer PORTFOLIO_UPDATED alongside the next scan-event flush;
                # a final immediate flush below handles the last-tick case.
                _evt_buf.append({
                    "event_type": "PORTFOLIO_UPDATED", "stage": "PORTFOLIO",
                    "scan_id": scan_id, "mode": "BACKTEST", "run_id": run_id,
                    "payload": {"cash": snap["cash"],
                                "portfolio_value": snap["portfolio_value"],
                                "open_positions": snap["open_positions_count"],
                                "realized_pnl": snap["realized_pnl"]}})
                # Flush immediately on the last tick so PORTFOLIO_UPDATED is
                # never left in the buffer after the loop exits.
                if tick_i == tick_count - 1 and _evt_buf:
                    _t_evt = time.perf_counter()
                    emit_many(_evt_buf)
                    _evt_buf.clear()
                    _event_ms += (time.perf_counter() - _t_evt) * 1000
            _tick_times.append((time.perf_counter() - _t0) * 1000)

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
        # Result-level provenance: consumers should not have to infer evidence
        # quality from a mutable-looking run configuration.
        metrics["universe_evidence"] = cfg.get("universe_evidence")
        metrics["universe_resolution"] = cfg.get("universe_resolution")
        # Always present — empty list means no mock data was detected.
        metrics["mock_candle_symbols"] = mock_candle_symbols
        # ── Performance telemetry (advisory — never changes decisions) ────────
        _total_s = time.perf_counter() - _perf_start
        _tt_sorted = sorted(_tick_times)
        _p95_idx = max(0, int(len(_tt_sorted) * 0.95) - 1) if _tt_sorted else 0
        metrics["perf"] = {
            "total_runtime_s":   round(_total_s, 1),
            "data_phase_s":      round(_data_ms / 1000, 1),
            "replay_phase_s":    round(_total_s - _data_ms / 1000, 1),
            "ticks_per_second":  round(
                len(_tick_times) / max(_total_s - _data_ms / 1000, 0.001), 2),
            "avg_ms_per_tick":   round(
                sum(_tick_times) / len(_tick_times), 1) if _tick_times else 0,
            "p95_ms_per_tick":   round(_tt_sorted[_p95_idx], 1) if _tt_sorted else 0,
            "max_ms_per_tick":   round(max(_tick_times), 1) if _tick_times else 0,
            "scan_ms_total":     round(_scan_ms),
            "event_ms_total":    round(_event_ms),
            "db_ms_total":       round(_db_ms),
            "progress_updates":  _progress_updates,
        }
        # Atomic: complete_run() writes COMPLETED only if status is still
        # RUNNING (single conditional UPDATE, rowcount-checked).  If a watchdog
        # marked the run STALE between the last checkpoint and here, the write
        # is a no-op and we exit without overwriting the watchdog's state.
        _written = bp.complete_run(
            run_id,
            config={**cfg, "cash_by_tick": cash_log,
                    "learning_fingerprint": learning_fp},
            metrics=metrics, missed=missed,
            progress={"phase": "DONE", "done": tick_count,
                      "total": tick_count},
        )
        if not _written:
            _cur = bp.get_run_status(run_id)
            return {"ok": False, "run_id": run_id, "fenced": True,
                    "message": (f"Run was marked {_cur!r} during finalization; "
                                "worker exits without overwriting watchdog state")}
        emit("SCAN_COMPLETED", "SUPERVISOR", scan_id=run_id, mode="BACKTEST",
             run_id=run_id, payload=metrics)
        _spawn_next_queued()   # promote + start next queued run if any
        return {"ok": True, "run_id": run_id, "metrics": metrics}
    except Exception as exc:
        # Classify DB connectivity failures with a clear, actionable message so
        # operators know immediately this is a Neon/Postgres issue, not a bug.
        raw_err = str(exc)
        if bp._is_connection_error(exc):
            err_str = (
                f"Database connection failed during backtest replay "
                f"({type(exc).__name__}: {raw_err[:200]}). "
                "This is typically a Neon/Postgres auth-timeout on a long run "
                "(>30 min with no DB activity during a warmup-data-fetch phase). "
                "Retry the run — the candle cache is warm and will resume faster."
            )[:500]
        else:
            err_str = raw_err[:500]
        # _emergency_mark_failed tries DB first (with retry), then file fallback.
        # Never raises — a second DB failure here must not leave the run RUNNING.
        bp._emergency_mark_failed(run_id, err_str)
        try:
            emit("SCAN_FAILED", "SUPERVISOR", scan_id=run_id, mode="BACKTEST",
                 run_id=run_id, payload={"error": err_str[:300]})
        except Exception:
            pass   # event emission is best-effort; never let it mask the FAILED write
        _spawn_next_queued()   # promote + start next queued run even on failure
        return {"ok": False, "run_id": run_id, "error": err_str}


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
    vol_normalize = bool(cfg.get("volume_time_normalized")) and interval != "1d"
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
        df = build_asof_df(daily_cache[sym], intra_cache[sym], ts, interval,
                           vol_normalize=vol_normalize)
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
