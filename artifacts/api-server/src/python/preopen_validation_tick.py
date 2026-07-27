"""
preopen_validation_tick.py — Phase 5B IST checkpoint tick handler.

Called by the Node.js market-hours scheduler every minute via:
    python3 main.py preopen_validation_tick

This module owns all IST time-gating and checkpoint deduplication so the
Node scheduler needs no time-of-day awareness.

Checkpoint windows (IST, inclusive):
  09:18–09:26  →  actual_open + price_0920
  09:28–09:36  →  price_0930
  09:58–10:06  →  price_1000
  10:28–10:36  →  price_1030
  15:28–15:50  →  eod (high/low/close) → classify → daily report

State is persisted per trading date in a JSON sidecar file so:
  - No checkpoint is executed twice on the same day.
  - A hot-reload of the API server does not re-execute completed checkpoints.
  - The status endpoint can report which checkpoints are done.

PAPER TRADING / ADVISORY ONLY.
No order, execution, or trade-placement function exists in this module.
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_ENABLED_VAR = "PREOPEN_VALIDATION_ENABLED"
_STATE_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            ".preopen_validation_tick_state.json")

# ── Checkpoint definitions ────────────────────────────────────────────────────

_CHECKPOINTS = [
    # (name,          window_start_hhmm, window_end_hhmm,   fields_to_collect)
    ("open_0920",     (9, 18),           (9, 26),           ["actual_open", "price_0920"]),
    ("price_0930",    (9, 28),           (9, 36),           ["price_0930"]),
    ("price_1000",    (9, 58),           (10, 6),           ["price_1000"]),
    ("price_1030",    (10, 28),          (10, 36),          ["price_1030"]),
    ("eod_classify",  (15, 28),          (15, 50),          ["eod"]),
]


def _is_enabled() -> bool:
    return os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


def _now_ist() -> datetime:
    return datetime.now(IST)


def _today_ist() -> str:
    return _now_ist().strftime("%Y-%m-%d")


def _is_trading_day() -> bool:
    try:
        from market_hours import is_trading_day
        return is_trading_day(_now_ist().date())
    except Exception:
        # Fallback: not a weekend
        return _now_ist().weekday() < 5


def _current_checkpoint(now: datetime) -> Optional[tuple]:
    """Return the checkpoint tuple whose window the current IST time falls in, or None."""
    h, m = now.hour, now.minute
    for cp in _CHECKPOINTS:
        name, (wh, wm), (eh, em), fields = cp
        window_start = h * 60 + m >= wh * 60 + wm
        window_end   = h * 60 + m <= eh * 60 + em
        if window_start and window_end:
            return cp
    return None


# ── Persistent tick state ─────────────────────────────────────────────────────

def _load_state(trading_date: str) -> dict:
    try:
        if not os.path.exists(_STATE_FILE):
            return {}
        with open(_STATE_FILE) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
        if data.get("trading_date") == trading_date:
            return data
        return {}  # stale — new trading day
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(state, f, indent=2, default=str)
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, _STATE_FILE)
    except Exception:
        pass


def _state_add_checkpoint(state: dict, cp_name: str, detail: dict) -> dict:
    state.setdefault("checkpoints_done", {})[cp_name] = {
        "ts": _now_ist().isoformat(),
        **detail,
    }
    return state


# ── Price collection helpers ──────────────────────────────────────────────────

def _fetch_prices_for_symbols(symbols: List[str]) -> Dict[str, Optional[float]]:
    """Get current LTP for each symbol. Returns {} on error."""
    try:
        from market_data import get_multiple_ltp
        prices = get_multiple_ltp(symbols)
        return {sym: float(p) for sym, p in prices.items() if p is not None}
    except Exception:
        return {}


def _fetch_eod_for_symbols(symbols: List[str]) -> Dict[str, Dict]:
    """Get today's OHLCV for each symbol. Returns {} on error."""
    try:
        import yfinance as yf
        tickers = [f"{s}.NS" for s in symbols]
        data = yf.download(tickers, period="1d", interval="1d",
                           group_by="ticker", progress=False, auto_adjust=True)
        result: Dict[str, Dict] = {}
        for sym, ticker in zip(symbols, tickers):
            try:
                df = data[ticker] if len(tickers) > 1 else data
                if df is None or df.empty:
                    continue
                row = df.iloc[-1]
                result[sym] = {
                    "high":  float(row["High"])  if "High"  in row else None,
                    "low":   float(row["Low"])   if "Low"   in row else None,
                    "close": float(row["Close"]) if "Close" in row else None,
                    "open":  float(row["Open"])  if "Open"  in row else None,
                }
            except Exception:
                continue
        return result
    except Exception:
        return {}


# ── Candidate lifecycle ───────────────────────────────────────────────────────

def _ensure_candidates_initialised(session_id: str, trading_date: str,
                                    state: dict) -> List[Any]:
    """
    Load or create ValidationRecord stubs from today's Phase 5A snapshots.
    Returns the list of records currently in DB (dicts).
    """
    import preopen_validation_db as db

    existing = db.get_candidate_outcomes(trading_date, limit=500)
    if existing:
        return existing

    # Bootstrap from Phase 5A
    try:
        import preopen_db as p5a_db
        snaps = p5a_db.get_latest_snapshots(trading_date)
    except Exception:
        snaps = []

    if not snaps:
        return []

    from preopen_validation_model import ValidationRecord, ValidationStatus, DataQualityStatus
    records = []
    for i, snap in enumerate(snaps):
        r = ValidationRecord(
            trading_date=trading_date,
            session_id=session_id,
            symbol=snap.get("symbol", ""),
            sector=snap.get("sector", "Unknown"),
            preopen_rank=snap.get("volume_rank") or (i + 1),
            opportunity_score=float(snap.get("opportunity_score") or 0),
            classification=snap.get("classification", ""),
            previous_close=snap.get("previous_close"),
            indicative_price=snap.get("indicative_equilibrium_price"),
            final_preopen_price=snap.get("final_open_price"),
            buy_quantity=int(snap.get("total_buy_quantity") or 0),
            sell_quantity=int(snap.get("total_sell_quantity") or 0),
            imbalance_percent=float(snap.get("imbalance_percent") or 0),
            executed_quantity=int(snap.get("final_executed_quantity") or 0),
            liquidity_score=float(snap.get("liquidity_score") or 0),
            sector_score=float((snap.get("factor_scores") or {}).get("sector_confirmation") or 0),
            gap_percent=snap.get("gap_percent"),
            validation_status=ValidationStatus.PENDING,
            data_quality_status=DataQualityStatus.MISSING,
        )
        db.upsert_candidate_outcome(r.to_dict())
        records.append(r.to_dict())
    return records


def _collect_price_checkpoint(records: List[dict], fields: List[str],
                               trading_date: str) -> Dict[str, Any]:
    """Fetch prices and update records for the given field list."""
    import preopen_validation_db as db
    from preopen_validation_model import ValidationRecord

    symbols = [r["symbol"] for r in records if r.get("symbol")]
    if not symbols:
        return {"fetched": 0, "symbols": 0}

    if "eod" in fields:
        eod = _fetch_eod_for_symbols(symbols)
        updated = 0
        for rec in records:
            d = eod.get(rec["symbol"])
            if not d:
                continue
            r = ValidationRecord()
            for k, v in rec.items():
                if hasattr(r, k):
                    try:
                        setattr(r, k, v)
                    except Exception:
                        pass
            if r.actual_open is None and d.get("open"):
                r.actual_open = d["open"]
            if d.get("high"):
                r.intraday_high = d["high"]
            if d.get("low"):
                r.intraday_low = d["low"]
            if d.get("close"):
                r.closing_price = d["close"]
            r.update_returns()
            db.upsert_candidate_outcome(r.to_dict())
            updated += 1
        return {"fetched": len(eod), "symbols": len(symbols), "updated": updated}

    prices = _fetch_prices_for_symbols(symbols)
    updated = 0
    for rec in records:
        price = prices.get(rec["symbol"])
        if price is None:
            continue
        r = ValidationRecord()
        for k, v in rec.items():
            if hasattr(r, k):
                try:
                    setattr(r, k, v)
                except Exception:
                    pass
        for field in fields:
            if field != "eod":
                setattr(r, field, price)
        r.update_returns()
        db.upsert_candidate_outcome(r.to_dict())
        updated += 1
    return {"fetched": len(prices), "symbols": len(symbols), "updated": updated}


def _run_eod_classify_and_report(records: List[dict], session_id: str,
                                  trading_date: str) -> Dict[str, Any]:
    """Run EOD price collection, outcome classification, and daily report."""
    import preopen_validation_db as db
    from preopen_validation_model import ValidationRecord
    from preopen_validation_outcomes import classify_and_update
    from preopen_validation_metrics import (
        calculate_session_metrics, calculate_score_bands, calculate_factor_metrics,
    )
    from preopen_validation_reports import generate_daily_report

    # Convert dicts → records for classification
    vrecords = []
    for rec in records:
        r = ValidationRecord()
        for k, v in rec.items():
            if hasattr(r, k):
                try:
                    setattr(r, k, v)
                except Exception:
                    pass
        vrecords.append(r)

    classified = [classify_and_update(r) for r in vrecords]
    for r in classified:
        db.upsert_candidate_outcome(r.to_dict())

    score_bands = calculate_score_bands(classified)
    factor_met  = calculate_factor_metrics(classified)
    db.save_score_band_metrics(session_id, trading_date, score_bands)
    db.save_factor_metrics(session_id, trading_date, factor_met)

    report = generate_daily_report(trading_date, session_id, classified)

    m = calculate_session_metrics(classified)
    db.upsert_validation_session({
        "session_id":             session_id,
        "trading_date":           trading_date,
        "status":                 "COMPLETE",
        "total_candidates":       m.get("total_candidates", 0),
        "valid_candidates":       m.get("valid_candidates", 0),
        "excluded_candidates":    m.get("excluded_candidates", 0),
        "classified_candidates":  len(classified),
        "data_quality_pct":       m.get("data_completeness_pct", 0),
        "metrics_computed":       True,
        "daily_report_path":      report.get("report_json_path"),
    })

    return {
        "classified":        len(classified),
        "continuation_rate": m.get("continuation_rate"),
        "report_path":       report.get("report_json_path"),
    }


# ── Main tick function ────────────────────────────────────────────────────────

def run_tick() -> Dict[str, Any]:
    """
    Main entry point — called by the Node scheduler every minute.
    Returns a structured dict; never raises (safe to run in a fire-and-forget context).

    Return shape:
      {
        "ran":         bool,     # True when a checkpoint was executed
        "checkpoint":  str|None, # Name of checkpoint executed, or None
        "reason":      str,      # Human-readable reason for skip or action
        "session_id":  str,
        "trading_date":str,
        "candidates":  int,
        "checkpoints_done": [...],
        "next_checkpoint": str|None,
        "enabled":     bool,
        "auto_tick":   True,
      }
    """
    now          = _now_ist()
    trading_date = now.strftime("%Y-%m-%d")

    base = {
        "ran":              False,
        "checkpoint":       None,
        "trading_date":     trading_date,
        "session_id":       None,
        "candidates":       0,
        "checkpoints_done": [],
        "next_checkpoint":  _next_checkpoint_label(now),
        "enabled":          _is_enabled(),
        "auto_tick":        True,
    }

    if not _is_enabled():
        return {**base, "reason": f"{_ENABLED_VAR} is false — tick is a no-op"}

    if not _is_trading_day():
        return {**base, "reason": f"{trading_date} is not a valid NSE trading day"}

    cp = _current_checkpoint(now)
    if cp is None:
        return {**base, "reason": f"No checkpoint window active at {now.strftime('%H:%M')} IST"}

    cp_name, _, _, fields = cp

    # Load (or initialise) today's tick state
    state = _load_state(trading_date)
    if not state:
        state = {
            "trading_date": trading_date,
            "session_id":   f"val-{trading_date}-{uuid.uuid4().hex[:6]}",
            "checkpoints_done": {},
        }

    session_id = state["session_id"]
    base["session_id"] = session_id

    # Idempotency: skip if already done
    if cp_name in state.get("checkpoints_done", {}):
        done_list = list(state["checkpoints_done"].keys())
        base["checkpoints_done"] = done_list
        return {**base, "reason": f"Checkpoint '{cp_name}' already completed today"}

    # Ensure session row exists in DB
    try:
        import preopen_validation_db as db
        db.upsert_validation_session({
            "session_id":   session_id,
            "trading_date": trading_date,
            "status":       "COLLECTING",
        })
    except Exception:
        pass

    # Ensure candidate records exist
    try:
        records = _ensure_candidates_initialised(session_id, trading_date, state)
    except Exception as e:
        return {**base, "reason": f"Candidate initialisation failed: {e}"}

    base["candidates"] = len(records)

    if not records:
        detail = {"symbols": 0}
        state  = _state_add_checkpoint(state, cp_name, {**detail, "skipped": "no_candidates"})
        _save_state(state)
        base["checkpoints_done"] = list(state["checkpoints_done"].keys())
        return {**base, "reason": "No Phase 5A candidates found for today — checkpoint skipped"}

    # Execute the checkpoint
    try:
        if cp_name == "eod_classify":
            # Reload fresh records from DB (may have been updated by earlier checkpoints)
            records = db.get_candidate_outcomes(trading_date, limit=500)
            detail  = _run_eod_classify_and_report(records, session_id, trading_date)
        else:
            detail = _collect_price_checkpoint(records, fields, trading_date)
    except Exception as e:
        return {**base, "reason": f"Checkpoint '{cp_name}' failed: {e}"}

    state = _state_add_checkpoint(state, cp_name, detail)
    _save_state(state)

    done_list = list(state["checkpoints_done"].keys())
    return {
        **base,
        "ran":              True,
        "checkpoint":       cp_name,
        "reason":           f"Checkpoint '{cp_name}' completed successfully",
        "checkpoints_done": done_list,
        "next_checkpoint":  _next_checkpoint_label(now),
        **detail,
    }


def _next_checkpoint_label(now: datetime) -> Optional[str]:
    """Return the name of the next upcoming checkpoint, or None if all passed."""
    h, m = now.hour, now.minute
    current_min = h * 60 + m
    for cp_name, (wh, wm), _, _ in _CHECKPOINTS:
        if current_min < wh * 60 + wm:
            return f"{cp_name} at {wh:02d}:{wm:02d} IST"
    return None


def get_tick_status() -> Dict[str, Any]:
    """
    Returns scheduler registration status for the /status endpoint.
    Called by preopen_validation_engine.get_status().
    """
    now          = _now_ist()
    trading_date = now.strftime("%Y-%m-%d")
    state        = _load_state(trading_date)
    cp           = _current_checkpoint(now)

    return {
        "auto_tick":          True,
        "registered":         True,
        "enabled":            _is_enabled(),
        "trading_day":        _is_trading_day(),
        "ist_time":           now.strftime("%H:%M:%S"),
        "trading_date":       trading_date,
        "active_window":      cp[0] if cp else None,
        "next_checkpoint":    _next_checkpoint_label(now),
        "session_id":         state.get("session_id"),
        "checkpoints_done":   list(state.get("checkpoints_done", {}).keys()),
        "checkpoints_detail": state.get("checkpoints_done", {}),
        "all_checkpoints":    [cp[0] for cp in _CHECKPOINTS],
    }
