"""
signal_validation_tick.py — Phase 5C IST checkpoint tick handler.

Called by the Node.js market-hours scheduler every minute via:
    python3 main.py signal_validation_tick

Checkpoint windows (IST):
  09:00–09:30  →  ingest_signals  (ingest today's signals from signals_cache)
  09:25–09:35  →  checkpoint_5m   (5-minute price checkpoints for active signals)
  09:35–09:45  →  checkpoint_15m  (15-minute checkpoints)
  09:45–10:05  →  checkpoint_30m  (30-minute checkpoints)
  10:15–10:45  →  checkpoint_60m  (60-minute checkpoints)
  15:25–15:50  →  eod_close       (EOD prices, classify, daily report)

Checkpoints marked once_only=False (ingest_signals) run every tick in window
so new signals generated throughout the session are captured.
All others run once per trading date (idempotent).

PAPER TRADING / ADVISORY ONLY.
No order submission, no broker call, no strategy modification.
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from signal_validation_model import is_enabled, LifecycleState, SignalValidationRecord

_IST        = timezone(timedelta(hours=5, minutes=30))
_ENABLED_VAR = "SIGNAL_VALIDATION_ENABLED"
_STATE_FILE  = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".signal_validation_tick_state.json",
)

_PHASES = [
    # (name,            window_start, window_end, once_only)
    # ingest_signals runs every tick throughout market hours (09:00–15:25) so
    # signals generated at any point during the session are captured, not just
    # those available at open.  once_only=False + DB idempotency = no duplicates.
    ("ingest_signals",  (9,  0),  (15, 25), False),
    ("checkpoint_5m",   (9, 25),  (9, 35),  True),
    ("checkpoint_15m",  (9, 35),  (9, 45),  True),
    ("checkpoint_30m",  (9, 45),  (10, 5),  True),
    ("checkpoint_60m",  (10,15),  (10,45),  True),
    ("eod_close",       (15,25),  (15,50),  True),
]


def _now_ist() -> datetime:
    return datetime.now(_IST)


def _today_ist() -> str:
    return _now_ist().strftime("%Y-%m-%d")


def _is_trading_day() -> bool:
    try:
        from market_hours import is_trading_day
        return is_trading_day(_now_ist().date())
    except Exception:
        return _now_ist().weekday() < 5


def _active_phase(now: datetime) -> Optional[tuple]:
    """
    Return the most appropriate phase for the current time.
    When multiple phases overlap (ingest_signals covers full market hours
    and checkpoints sit inside it), once-only checkpoint phases take priority
    over the continuous ingest phase so they are not starved.
    ingest_signals is run unconditionally by run_tick whenever in window.
    """
    hm = now.hour * 60 + now.minute
    active = [p for p in _PHASES
              if p[1][0] * 60 + p[1][1] <= hm <= p[2][0] * 60 + p[2][1]]
    if not active:
        return None
    # Prefer once-only phases (checkpoints, eod_close) over continuous ingest
    once_only = [p for p in active if p[3]]
    return once_only[0] if once_only else active[0]
    return None


def _next_phase_label(now: datetime) -> Optional[str]:
    hm = now.hour * 60 + now.minute
    for name, (wh, wm), _, _ in _PHASES:
        if hm < wh * 60 + wm:
            return f"{name} at {wh:02d}:{wm:02d} IST"
    return None


# ── State persistence ──────────────────────────────────────────────────────────

def _load_state(trading_date: str) -> dict:
    try:
        if not os.path.exists(_STATE_FILE):
            return {}
        with open(_STATE_FILE) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
        return data if data.get("trading_date") == trading_date else {}
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


# ── Phase implementations ──────────────────────────────────────────────────────

def _load_paper_trades_today(trading_date: str) -> list:
    """
    Load today's paper trades for lifecycle correlation.
    Returns an empty list on any error — callers must tolerate absence.
    """
    try:
        import portfolio_store
        all_trades = portfolio_store.load_all_trades_any() or []
        return [t for t in all_trades
                if str(t.get("timestamp") or t.get("trade_ts") or "").startswith(trading_date)]
    except Exception:
        pass
    try:
        import paper_portfolio_store
        all_trades = paper_portfolio_store.load_all_trades() or []
        return [t for t in all_trades
                if str(t.get("timestamp") or t.get("trade_ts") or "").startswith(trading_date)]
    except Exception:
        return []


def _run_ingest_signals(session_id: str, trading_date: str) -> dict:
    """
    Ingest signals from signals_cache for today, then advance each record
    through AI/RISK/FILL lifecycle states using available metadata.
    """
    try:
        import signals_store
        signals = signals_store.load_signals() or []
        today_sigs = [s for s in signals
                      if str(s.get("time") or s.get("timestamp") or "").startswith(trading_date)]
        if not today_sigs:
            # Fall back to signal_snapshots if available
            try:
                snaps = signals_store.load_signal_snapshots() or []
                today_sigs = [s for s in snaps
                              if str(s.get("time") or "").startswith(trading_date)]
            except Exception:
                pass
    except Exception:
        today_sigs = []

    if not today_sigs:
        return {"ingested": 0, "skipped": 0, "errors": 0, "note": "no_signals_found"}

    # Load paper trades once — used for both new ingestion AND re-advancement
    paper_trades = _load_paper_trades_today(trading_date)

    # Build a single shared claimed_trade_ids set for the entire tick.
    # Pre-seeded from ALL today's DB records that already hold a paper_order_id
    # so that neither the new-ingest pass nor the re-advance pass can claim a
    # trade that was matched in a previous tick or the other pass in this tick.
    import signal_validation_db as db_mod
    shared_claimed: set = {
        r["paper_order_id"]
        for r in (db_mod.get_records(trading_date=trading_date, limit=None) or [])
        if r.get("paper_order_id")
    }

    from signal_validation_lifecycle import ingest_signal_batch
    result = ingest_signal_batch(
        today_sigs, session_id, trading_date,
        paper_trades=paper_trades,
        claimed_trade_ids=shared_claimed,
    )

    # Re-advance existing stuck records that have not yet been correlated with
    # a paper trade. Paper trades can arrive minutes after signal ingestion, so
    # records can be stuck at APPROVED/PAPER_ORDER_CREATED/PAPER_ORDER_FILLED.
    # Pass the same shared_claimed set so this pass cannot double-claim a trade
    # already taken by the new-ingest pass above.
    re_advanced = _re_advance_stuck_records(trading_date, paper_trades,
                                            claimed_trade_ids=shared_claimed)
    result["re_advanced"] = re_advanced
    return result


def _re_advance_stuck_records(
    trading_date: str,
    paper_trades: list,
    claimed_trade_ids: Optional[set] = None,
) -> int:
    """
    Load records stuck at APPROVED or PAPER_ORDER_CREATED (no paper trade yet
    correlated) and attempt to advance them using the current paper trade list.
    Also step PAPER_ORDER_FILLED records to OPEN_POSITION if they missed that.

    claimed_trade_ids — shared set from the caller (pre-seeded with trades
    already matched this tick and in previous ticks).  Trades this pass claims
    are added to the set so the caller retains full claim visibility.

    Returns the count of records that were successfully advanced.
    """
    if not paper_trades:
        return 0

    import signal_validation_db as db
    from signal_validation_lifecycle import advance_lifecycle_from_signal
    from signal_validation_model import SignalValidationRecord

    # Use caller-supplied set or create a local one (standalone call path)
    if claimed_trade_ids is None:
        claimed_trade_ids = set()

    # Collect records that should have paper trades but don't yet
    stuck_statuses = [
        LifecycleState.APPROVED,
        LifecycleState.PAPER_ORDER_CREATED,
        LifecycleState.PAPER_ORDER_FILLED,
    ]

    stuck_recs = []
    for status in stuck_statuses:
        stuck_recs.extend(
            db.get_records(trading_date=trading_date, validation_status=status, limit=None)
        )

    if not stuck_recs:
        return 0

    # Re-advance each stuck record
    advanced = 0
    for raw in stuck_recs:
        if raw.get("validation_status") in (
                LifecycleState.PAPER_ORDER_CREATED, LifecycleState.PAPER_ORDER_FILLED):
            # Already has a trade match; just step through to OPEN_POSITION
            rec = SignalValidationRecord.from_dict(raw)
            start = rec.validation_status
            if rec.validation_status == LifecycleState.PAPER_ORDER_CREATED and \
                    LifecycleState.is_valid_transition(
                        LifecycleState.PAPER_ORDER_CREATED, LifecycleState.PAPER_ORDER_FILLED):
                from signal_validation_lifecycle import transition
                transition(rec, LifecycleState.PAPER_ORDER_FILLED,
                           reason="Re-advance: fill confirmed on later tick",
                           source_component="signal_validation_tick._re_advance_stuck_records",
                           persist=is_enabled())
            if rec.validation_status == LifecycleState.PAPER_ORDER_FILLED and \
                    LifecycleState.is_valid_transition(
                        LifecycleState.PAPER_ORDER_FILLED, LifecycleState.OPEN_POSITION):
                from signal_validation_lifecycle import transition
                transition(rec, LifecycleState.OPEN_POSITION,
                           reason="Re-advance: position opened on later tick",
                           source_component="signal_validation_tick._re_advance_stuck_records",
                           persist=is_enabled())
            if rec.validation_status != start:
                advanced += 1
        else:
            # APPROVED — attempt trade correlation
            rec = SignalValidationRecord.from_dict(raw)
            start = rec.validation_status
            # Reconstruct minimal signal dict for advance function
            sig_stub = {
                "id":              rec.signal_id,
                "stock":           rec.symbol,
                "signal":          rec.signal_direction or "BUY",
                "signal_timestamp_ist": rec.signal_timestamp_ist,
                "risk_decision":   rec.risk_decision or "APPROVED",
            }
            advance_lifecycle_from_signal(
                rec, sig_stub,
                paper_trades=paper_trades,
                claimed_trade_ids=claimed_trade_ids,
            )
            if rec.validation_status != start:
                advanced += 1

    return advanced


def _run_price_checkpoint(session_id: str, trading_date: str,
                          checkpoint_type: str, minutes: int) -> dict:
    """Fetch LTP for all active validation records and record a price checkpoint."""
    import signal_validation_db as db

    records = db.get_records(trading_date=trading_date,
                             validation_status=LifecycleState.OPEN_POSITION,
                             limit=None)
    if not records:
        # Also check approved / filled states
        records = []
        for st in (LifecycleState.APPROVED, LifecycleState.PAPER_ORDER_FILLED,
                   LifecycleState.PAPER_ORDER_CREATED):
            records.extend(db.get_records(trading_date=trading_date,
                                          validation_status=st, limit=None))

    if not records:
        return {"checkpointed": 0, "note": "no_active_records"}

    symbols = list({r["symbol"] for r in records if r.get("symbol")})
    prices: Dict[str, float] = {}
    try:
        from market_data import get_multiple_ltp
        raw = get_multiple_ltp(symbols)
        prices = {sym: float(p) for sym, p in raw.items() if p is not None}
    except Exception:
        pass

    updated = 0
    from decimal import Decimal
    for rec in records:
        sym = rec.get("symbol")
        price = prices.get(sym)
        if price is None:
            continue
        entry = rec.get("entry_price")
        ret_pct = None
        if entry:
            try:
                ep = float(entry)
                direction = rec.get("signal_direction") or "BUY"
                if direction in ("BUY", "STRONG_BUY"):
                    ret_pct = (price - ep) / ep * 100
                else:
                    ret_pct = (ep - price) / ep * 100
            except Exception:
                pass

        db.upsert_price_checkpoint({
            "validation_id":   rec["validation_id"],
            "checkpoint_type": checkpoint_type,
            "price":           price,
            "timestamp_ist":   _now_ist().isoformat(),
            "source":          "live_quote",
            "is_hypothetical": False,
            "return_pct":      ret_pct,
        })

        # Update the record's price field
        field_map = {
            "5m": "price_5m", "15m": "price_15m",
            "30m": "price_30m", "60m": "price_60m",
        }
        field = field_map.get(checkpoint_type)
        if field:
            from signal_validation_model import SignalValidationRecord
            r = SignalValidationRecord.from_dict(rec)
            setattr(r, field, Decimal(str(price)))
            # Update MFE/MAE
            if entry:
                ep = Decimal(str(float(entry)))
                diff = Decimal(str(price)) - ep
                if r.signal_direction in ("BUY", "STRONG_BUY"):
                    if r.max_favourable_excursion is None or diff > r.max_favourable_excursion:
                        r.max_favourable_excursion = diff
                    if r.max_adverse_excursion is None or diff < r.max_adverse_excursion:
                        r.max_adverse_excursion = diff
            db.upsert_record(r.to_dict())
        updated += 1

    return {"checkpointed": updated, "symbols_queried": len(symbols)}


def _run_eod_close(session_id: str, trading_date: str) -> dict:
    """EOD: collect closing prices, classify outcomes, generate reports."""
    import signal_validation_db as db

    # 1. Fetch EOD prices for all records today
    records_raw = db.get_records(trading_date=trading_date, limit=None)
    if not records_raw:
        return {"classified": 0, "note": "no_records"}

    symbols = list({r["symbol"] for r in records_raw if r.get("symbol")})
    eod_prices: Dict[str, Dict] = {}
    try:
        import yfinance as yf
        tickers = [f"{s}.NS" for s in symbols]
        data = yf.download(tickers, period="1d", interval="1d",
                           group_by="ticker", progress=False, auto_adjust=True)
        for sym, ticker in zip(symbols, tickers):
            try:
                df = data[ticker] if len(tickers) > 1 else data
                if df is None or df.empty:
                    continue
                row = df.iloc[-1]
                eod_prices[sym] = {
                    "close": float(row["Close"]) if "Close" in row else None,
                    "high":  float(row["High"])  if "High"  in row else None,
                    "low":   float(row["Low"])   if "Low"   in row else None,
                }
            except Exception:
                continue
    except Exception:
        pass

    from signal_validation_model import SignalValidationRecord
    from decimal import Decimal

    # Do not mutate outcome/history rows on an incomplete EOD data pass.  A
    # session can only be COMPLETE when every record is terminal; in
    # particular, live paper positions require both an exit price and entry
    # price to close safely.
    active_raw = [
        raw for raw in records_raw
        if not LifecycleState.is_terminal(raw.get("validation_status"))
    ]
    closable_states = (LifecycleState.OPEN_POSITION, LifecycleState.PAPER_ORDER_FILLED)
    blocked = [
        raw for raw in active_raw
        if raw.get("validation_status") not in closable_states
    ]
    missing_close = [
        raw for raw in active_raw
        if raw.get("validation_status") in closable_states
        and (not eod_prices.get(raw.get("symbol"), {}).get("close")
             or not raw.get("entry_price"))
    ]
    if blocked or missing_close:
        db.upsert_session({
            "session_id": session_id, "trading_date": trading_date,
            "status": "EOD_RETRY_REQUIRED",
        })
        return {
            "classified": 0,
            "session_status": "EOD_RETRY_REQUIRED",
            "retry_required": True,
            "non_terminal_records": len(active_raw),
            "missing_close_records": len(missing_close),
            "blocked_lifecycle_records": len(blocked),
            "note": "EOD close data/lifecycle is incomplete; no record history was rewritten",
        }

    from signal_validation_outcomes import classify_and_update
    classified = 0
    for rec_raw in records_raw:
        rec = SignalValidationRecord.from_dict(rec_raw)
        sym = rec.symbol
        eod = eod_prices.get(sym, {})

        if eod.get("close"):
            rec.end_of_day_price = Decimal(str(eod["close"]))
            # Update MFE/MAE from EOD
            if eod.get("high") and rec.entry_price and rec.signal_direction in ("BUY", "STRONG_BUY"):
                mfe = Decimal(str(eod["high"])) - rec.entry_price
                if rec.max_favourable_excursion is None or mfe > rec.max_favourable_excursion:
                    rec.max_favourable_excursion = mfe
            if eod.get("low") and rec.entry_price and rec.signal_direction in ("BUY", "STRONG_BUY"):
                mae = Decimal(str(eod["low"])) - rec.entry_price
                if rec.max_adverse_excursion is None or mae < rec.max_adverse_excursion:
                    rec.max_adverse_excursion = mae

        # Close open positions at EOD using the audited lifecycle helper
        if rec.validation_status in (LifecycleState.OPEN_POSITION, LifecycleState.PAPER_ORDER_FILLED):
            if rec.end_of_day_price and rec.entry_price:
                from signal_validation_lifecycle import close_position
                close_position(rec, rec.end_of_day_price, exit_reason="EOD_CLOSE",
                               source_component="signal_validation_tick._run_eod_close")

        # Compute hypothetical returns for missed/rejected signals
        if rec.validation_status in (LifecycleState.RISK_REJECTED, LifecycleState.MISSED):
            _compute_hypothetical(rec, eod)
            rec.is_hypothetical    = True
            rec.hypothetical_label = "HYPOTHETICAL — NOT A TRADE"

        classify_and_update(rec)
        db.upsert_record(rec.to_dict())
        classified += 1

    # Verify post-write lifecycle state from persistence before finalising.
    # This protects against a failed/invalid transition being masked by a
    # COMPLETE session stamp.
    recs_obj = [SignalValidationRecord.from_dict(r) for r in db.get_records(
        trading_date=trading_date, limit=None)]
    non_terminal = [
        r for r in recs_obj if not LifecycleState.is_terminal(r.validation_status)
    ]
    if non_terminal:
        db.upsert_session({
            "session_id": session_id, "trading_date": trading_date,
            "status": "EOD_RETRY_REQUIRED",
        })
        return {
            "classified": classified,
            "session_status": "EOD_RETRY_REQUIRED",
            "retry_required": True,
            "non_terminal_records": len(non_terminal),
            "note": "EOD classification did not terminally resolve every record",
        }

    # 2. Compute attribution metrics
    from signal_validation_attribution import (
        calculate_strategy_attribution, calculate_ai_attribution,
        calculate_preopen_attribution, calculate_regime_attribution, calculate_summary
    )
    strat_m  = calculate_strategy_attribution(recs_obj, trading_date, session_id)
    ai_m     = calculate_ai_attribution(recs_obj, trading_date, session_id)
    preo_m   = calculate_preopen_attribution(recs_obj, trading_date, session_id)
    regime_m = calculate_regime_attribution(recs_obj, trading_date, session_id)
    summary  = calculate_summary(recs_obj)

    db.save_strategy_metrics(strat_m)
    db.save_ai_metrics(ai_m)
    db.save_preopen_metrics(preo_m)

    # 3. Update session
    db.upsert_session({
        "session_id":            session_id,
        "trading_date":          trading_date,
        "status":                "COMPLETE",
        "signals_generated":     summary["signals_generated"],
        "signals_approved":      summary["signals_approved"],
        "paper_trades":          summary["paper_trades"],
        "risk_rejections":       summary["risk_rejections"],
        "win_rate":              summary.get("win_rate"),
        "expectancy":            summary.get("expectancy"),
        "false_positives":       summary.get("false_positives"),
        "missed_opportunities":  summary.get("missed_opportunities"),
        "data_completeness_pct": summary.get("data_completeness_pct"),
    })

    # 4. Generate daily report
    from signal_validation_reports import generate_daily_report
    report = generate_daily_report(trading_date, session_id, recs_obj)
    db.upsert_session({"session_id": session_id, "trading_date": trading_date,
                       "daily_report_path": report.get("report_json_path")})

    # 5. Check five-day gate
    valid_sessions = db.count_valid_sessions()
    five_day_result = None
    if valid_sessions >= 5:
        five_day_result = _try_five_day_report()

    return {
        "classified":          classified,
        "report_path":         report.get("report_json_path"),
        "five_day_triggered":  five_day_result is not None,
        "valid_sessions":      valid_sessions,
    }


def _compute_hypothetical(rec: SignalValidationRecord, eod: dict) -> None:
    """Fill hypothetical return fields for missed/rejected signals. Labelled NOT A TRADE."""
    close = eod.get("close")
    if close is None or rec.signal_price is None:
        return
    from decimal import Decimal
    sp = float(rec.signal_price)
    if sp == 0:
        return
    if rec.signal_direction in ("BUY", "STRONG_BUY"):
        ret = (close - sp) / sp * 100
    else:
        ret = (sp - close) / sp * 100
    rec.hyp_return_60m = Decimal(str(round(ret, 4)))
    if eod.get("high"):
        mfe = ((eod["high"] - sp) / sp * 100 if rec.signal_direction in ("BUY", "STRONG_BUY")
               else (sp - eod["high"]) / sp * 100)
        rec.hyp_mfe = Decimal(str(round(mfe, 4)))
    if eod.get("low"):
        mae = ((eod["low"] - sp) / sp * 100 if rec.signal_direction in ("BUY", "STRONG_BUY")
               else (sp - eod["low"]) / sp * 100)
        rec.hyp_mae = Decimal(str(round(mae, 4)))
    # Classify rejection validity
    if rec.hyp_return_60m and rec.hyp_return_60m >= Decimal("2.0"):
        rec.hyp_rejection_justified = False  # signal would have succeeded
    elif rec.hyp_return_60m and rec.hyp_return_60m < 0:
        rec.hyp_rejection_justified = True   # rejection was correct


def _try_five_day_report() -> Optional[dict]:
    """Attempt to generate the five-day consolidated report."""
    try:
        import signal_validation_db as db
        from signal_validation_model import SignalValidationRecord
        from signal_validation_reports import generate_five_day_report

        sessions = db.get_sessions(limit=10)
        valid = [s for s in sessions if (s.get("paper_trades") or 0) > 0][:5]
        if len(valid) < 5:
            return None

        records_by_date: Dict[str, List[SignalValidationRecord]] = {}
        for s in valid:
            date = str(s.get("trading_date", ""))[:10]
            raw = db.get_records(trading_date=date, limit=None)
            records_by_date[date] = [SignalValidationRecord.from_dict(r) for r in raw]

        result = generate_five_day_report(valid, records_by_date)
        db.save_daily_report({
            "trading_date":        valid[-1].get("trading_date"),
            "session_id":          valid[-1].get("session_id"),
            "five_day_report_json": result.get("report"),
            "five_day_verdict":    result.get("verdict"),
        })
        return result
    except Exception:
        return None


# ── Main tick ──────────────────────────────────────────────────────────────────

def run_tick() -> Dict[str, Any]:
    """
    Entry point — called by the Node scheduler every minute. Never raises.
    """
    now          = _now_ist()
    trading_date = now.strftime("%Y-%m-%d")

    base = {
        "ran":           False,
        "phase":         None,
        "trading_date":  trading_date,
        "session_id":    None,
        "next_phase":    _next_phase_label(now),
        "enabled":       is_enabled(),
        "auto_tick":     True,
    }

    if not is_enabled():
        return {**base, "reason": f"{_ENABLED_VAR} is false — tick is a no-op"}

    if not _is_trading_day():
        return {**base, "reason": f"{trading_date} is not a valid NSE trading day"}

    active = _active_phase(now)
    if active is None:
        return {**base, "reason": f"No phase window active at {now.strftime('%H:%M')} IST"}

    phase_name, _, _, once_only = active

    state = _load_state(trading_date)
    if not state:
        state = {
            "trading_date":  trading_date,
            "session_id":    f"sv-{trading_date}-{uuid.uuid4().hex[:6]}",
            "phases_done":   {},
            "ingest_count":  0,
        }

    session_id = state["session_id"]
    base["session_id"] = session_id

    if once_only and phase_name in state.get("phases_done", {}):
        return {**base, "reason": f"Phase '{phase_name}' already completed today"}

    try:
        import signal_validation_db as db
        db.upsert_session({
            "session_id":   session_id,
            "trading_date": trading_date,
            "status":       "ACTIVE",
        })
    except Exception:
        pass

    try:
        if phase_name == "ingest_signals":
            detail = _run_ingest_signals(session_id, trading_date)
            state["ingest_count"] = state.get("ingest_count", 0) + 1
        elif phase_name == "checkpoint_5m":
            detail = _run_price_checkpoint(session_id, trading_date, "5m", 5)
        elif phase_name == "checkpoint_15m":
            detail = _run_price_checkpoint(session_id, trading_date, "15m", 15)
        elif phase_name == "checkpoint_30m":
            detail = _run_price_checkpoint(session_id, trading_date, "30m", 30)
        elif phase_name == "checkpoint_60m":
            detail = _run_price_checkpoint(session_id, trading_date, "60m", 60)
        elif phase_name == "eod_close":
            detail = _run_eod_close(session_id, trading_date)
        else:
            detail = {"error": f"Unknown phase: {phase_name}"}
    except Exception as e:
        return {**base, "reason": f"Phase '{phase_name}' raised unexpectedly: {e}"}

    # Retry-required EOD outcomes intentionally remain eligible for another
    # invocation in the EOD window.  Recording them as done would turn a
    # transient provider gap into a permanent incomplete session.
    if once_only and not detail.get("retry_required", False):
        state.setdefault("phases_done", {})[phase_name] = {
            "ts": now.isoformat(), **detail,
        }

    _save_state(state)

    return {
        **base,
        "ran":    True,
        "phase":  phase_name,
        "reason": f"Phase '{phase_name}' executed",
        **{k: v for k, v in detail.items() if k not in ("phase",)},
    }


def get_tick_status() -> Dict[str, Any]:
    now          = _now_ist()
    trading_date = now.strftime("%Y-%m-%d")
    state        = _load_state(trading_date)
    active       = _active_phase(now)

    return {
        "auto_tick":      True,
        "registered":     True,
        "enabled":        is_enabled(),
        "trading_day":    _is_trading_day(),
        "ist_time":       now.strftime("%H:%M:%S"),
        "trading_date":   trading_date,
        "active_phase":   active[0] if active else None,
        "next_phase":     _next_phase_label(now),
        "session_id":     state.get("session_id"),
        "ingest_count":   state.get("ingest_count", 0),
        "phases_done":    list(state.get("phases_done", {}).keys()),
        "all_phases":     [p[0] for p in _PHASES],
        "active":         is_enabled() and _is_trading_day(),
    }
