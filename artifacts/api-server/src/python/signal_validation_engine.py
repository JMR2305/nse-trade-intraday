"""
signal_validation_engine.py — Phase 5C API facade.

All API endpoints call functions here.
When SIGNAL_VALIDATION_ENABLED=false every function returns a DISABLED response.
No order submission, no broker call, no strategy modification.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from signal_validation_model import (
    is_enabled, SignalValidationRecord, LifecycleState, OutcomeClass,
    _ENABLED_VAR,
)

_IST = timezone(timedelta(hours=5, minutes=30))
_RATE_LIMIT: Dict[str, float] = {}
_RATE_LIMIT_SECONDS = 30


def _disabled() -> dict:
    return {
        "status":       "DISABLED",
        "feature_flag": _ENABLED_VAR,
        "message":      f"Set {_ENABLED_VAR}=true to enable Phase 5C signal validation.",
        "label":        "PAPER TRADING / ADVISORY ONLY",
    }


def _today_ist() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _now_ist() -> str:
    return datetime.now(_IST).isoformat()


def _rate_limit_check(key: str) -> bool:
    """Returns True if the action is rate-limited (too soon)."""
    import time
    last = _RATE_LIMIT.get(key, 0)
    now  = time.monotonic()
    if now - last < _RATE_LIMIT_SECONDS:
        return True
    _RATE_LIMIT[key] = now
    return False


# ── Status ─────────────────────────────────────────────────────────────────────

def get_status() -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        from signal_validation_tick import get_tick_status
        session = db.get_latest_session()
        ts      = get_tick_status()
        return {
            "status":        "ENABLED",
            "feature_flag":  _ENABLED_VAR,
            "trading_date":  _today_ist(),
            "label":         "PAPER TRADING / ADVISORY ONLY",
            "latest_session": session,
            "scheduler": {
                "registered":  True,
                "auto_tick":   True,
                "enabled":     ts.get("enabled"),
                "trading_day": ts.get("trading_day"),
                "ist_time":    ts.get("ist_time"),
                "active_phase": ts.get("active_phase"),
                "next_phase":  ts.get("next_phase"),
                "phases_done": ts.get("phases_done", []),
                "all_phases":  ts.get("all_phases", []),
                "session_id":  ts.get("session_id"),
            },
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "label": "PAPER TRADING / ADVISORY ONLY"}


# ── Summary ────────────────────────────────────────────────────────────────────

def get_summary(trading_date: Optional[str] = None) -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        from signal_validation_attribution import calculate_summary, calculate_funnel
        td   = trading_date or _today_ist()
        raws = db.get_records(trading_date=td, limit=None)
        recs = [SignalValidationRecord.from_dict(r) for r in raws]
        return {
            "trading_date":   td,
            "freshness":      _now_ist(),
            "sample_size":    len(recs),
            "data_complete":  all(r.outcome_class for r in recs),
            "summary":        calculate_summary(recs),
            "funnel":         calculate_funnel(recs),
            "label":          "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Signals list ───────────────────────────────────────────────────────────────

def get_signals(
    trading_date: Optional[str] = None,
    strategy_id:  Optional[str] = None,
    symbol:       Optional[str] = None,
    validation_status: Optional[str] = None,
    outcome_class: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    if not is_enabled():
        return _disabled()
    limit  = min(max(1, limit), 500)
    offset = max(0, offset)
    try:
        import signal_validation_db as db
        td   = trading_date or _today_ist()
        rows = db.get_records(
            trading_date=td, strategy_id=strategy_id,
            symbol=symbol, validation_status=validation_status,
            outcome_class=outcome_class, limit=limit, offset=offset,
        )
        return {
            "trading_date":   td,
            "count":          len(rows),
            "limit":          limit,
            "offset":         offset,
            "freshness":      _now_ist(),
            "data_complete":  len(rows) == limit,
            "signals":        [_serialize_row(r) for r in rows],
            "label":          "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def get_signal_detail(signal_id: str, trading_date: Optional[str] = None) -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        td  = trading_date or _today_ist()
        rec = db.get_record_by_signal_id(signal_id, td)
        if not rec:
            return {"status": "NOT_FOUND", "signal_id": signal_id}
        events     = db.get_lifecycle_events(rec["validation_id"])
        checkpoints = db.get_price_checkpoints(rec["validation_id"])
        return {
            "signal":         _serialize_row(rec),
            "timeline":       events,
            "price_checkpoints": checkpoints,
            "freshness":      _now_ist(),
            "label":          "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Funnel ─────────────────────────────────────────────────────────────────────

def get_funnel(trading_date: Optional[str] = None) -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        from signal_validation_attribution import calculate_funnel
        td   = trading_date or _today_ist()
        rows = db.get_records(trading_date=td, limit=None)
        recs = [SignalValidationRecord.from_dict(r) for r in rows]
        return {
            "trading_date": td,
            "freshness":    _now_ist(),
            "sample_size":  len(recs),
            "funnel":       calculate_funnel(recs),
            "label":        "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Strategies ─────────────────────────────────────────────────────────────────

def get_strategies(trading_date: Optional[str] = None) -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        from signal_validation_attribution import (
            calculate_strategy_attribution, _confidence_label,
        )
        td   = trading_date or _today_ist()
        rows = db.get_records(trading_date=td, limit=None)
        recs = [SignalValidationRecord.from_dict(r) for r in rows]
        metrics = calculate_strategy_attribution(recs, td, "")
        return {
            "trading_date": td,
            "freshness":    _now_ist(),
            "sample_size":  len(recs),
            "strategies":   metrics,
            "min_signals_for_comparison": 20,
            "min_trades_for_comparison":  10,
            "label":        "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── AI attribution ─────────────────────────────────────────────────────────────

def get_ai_attribution(trading_date: Optional[str] = None) -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        from signal_validation_attribution import calculate_ai_attribution
        td   = trading_date or _today_ist()
        rows = db.get_records(trading_date=td, limit=None)
        recs = [SignalValidationRecord.from_dict(r) for r in rows]
        return {
            "trading_date":   td,
            "freshness":      _now_ist(),
            "sample_size":    len(recs),
            "ai_attribution": calculate_ai_attribution(recs, td, ""),
            "advisory_note":  "AI remains advisory only. Phase 5C does not change AI thresholds.",
            "label":          "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Pre-open attribution ───────────────────────────────────────────────────────

def get_preopen_attribution(trading_date: Optional[str] = None) -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        from signal_validation_attribution import calculate_preopen_attribution
        td   = trading_date or _today_ist()
        rows = db.get_records(trading_date=td, limit=None)
        recs = [SignalValidationRecord.from_dict(r) for r in rows]
        valid_5b = db.count_valid_sessions()
        return {
            "trading_date":             td,
            "freshness":                _now_ist(),
            "sample_size":              len(recs),
            "preopen_attribution":      calculate_preopen_attribution(recs, td, "", valid_5b),
            "predictive_value_declared": valid_5b >= 5,
            "valid_phase5b_sessions":   valid_5b,
            "observation_note":         "Observational attribution only. Pre-open scores do not connect to Trade Decisions.",
            "label":                    "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Risk attribution ───────────────────────────────────────────────────────────

def get_risk_attribution(trading_date: Optional[str] = None) -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        from signal_validation_attribution import _confidence_label
        td   = trading_date or _today_ist()
        rows = db.get_records(trading_date=td, limit=None)
        recs = [SignalValidationRecord.from_dict(r) for r in rows]
        rejected = [r for r in recs if r.validation_status == LifecycleState.RISK_REJECTED]
        reasons: Dict[str, int] = {}
        for r in rejected:
            k = r.risk_rejection_reason or "unknown"
            reasons[k] = reasons.get(k, 0) + 1
        with_hyp = [r for r in rejected if r.hyp_rejection_justified is not None]
        just_rate = (sum(1 for r in with_hyp if r.hyp_rejection_justified) / len(with_hyp)
                     if with_hyp else None)
        return {
            "trading_date":             td,
            "freshness":                _now_ist(),
            "total_rejected":           len(rejected),
            "rejection_reasons":        reasons,
            "rejection_justified_rate": just_rate,
            "with_hypothetical_data":   len(with_hyp),
            "confidence":               _confidence_label(len(rejected)),
            "label":                    "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Regimes ────────────────────────────────────────────────────────────────────

def get_regimes(trading_date: Optional[str] = None) -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        from signal_validation_attribution import calculate_regime_attribution
        td   = trading_date or _today_ist()
        rows = db.get_records(trading_date=td, limit=None)
        recs = [SignalValidationRecord.from_dict(r) for r in rows]
        return {
            "trading_date":       td,
            "freshness":          _now_ist(),
            "regime_attribution": calculate_regime_attribution(recs, td, ""),
            "note":               "Uses RC-10 regime classification unchanged.",
            "label":              "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Missed opportunities ───────────────────────────────────────────────────────

def get_missed_opportunities(trading_date: Optional[str] = None,
                             limit: int = 50) -> dict:
    if not is_enabled():
        return _disabled()
    limit = min(max(1, limit), 200)
    try:
        import signal_validation_db as db
        td   = trading_date or _today_ist()
        rows = db.get_records(trading_date=td,
                              validation_status=LifecycleState.MISSED, limit=limit)
        rejected = db.get_records(trading_date=td,
                                  validation_status=LifecycleState.RISK_REJECTED,
                                  limit=limit)
        combined = rows + rejected
        return {
            "trading_date":        td,
            "freshness":           _now_ist(),
            "sample_size":         len(combined),
            "missed_count":        len(rows),
            "rejected_count":      len(rejected),
            "missed_opportunities": [_serialize_row(r) for r in combined],
            "hypothetical_label":  "HYPOTHETICAL — NOT A TRADE",
            "note":                "Hypothetical P&L is excluded from paper portfolio statistics.",
            "label":               "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Report ─────────────────────────────────────────────────────────────────────

def get_report(trading_date: Optional[str] = None) -> dict:
    if not is_enabled():
        return _disabled()
    try:
        import signal_validation_db as db
        td  = trading_date or _today_ist()
        rep = db.get_daily_report(td)
        if not rep:
            return {
                "status":       "NOT_READY",
                "trading_date": td,
                "message":      "Daily report will be generated after market close (15:25 IST).",
            }
        return {
            "trading_date": td,
            "freshness":    _now_ist(),
            "report":       rep,
            "label":        "PAPER TRADING / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Manual run ─────────────────────────────────────────────────────────────────

def run_now(trading_date: Optional[str] = None) -> dict:
    """Manually trigger signal ingestion and reconciliation. Rate-limited."""
    if not is_enabled():
        return _disabled()
    if _rate_limit_check("run_now"):
        return {
            "status":  "RATE_LIMITED",
            "message": f"Manual run is rate-limited to once per {_RATE_LIMIT_SECONDS}s.",
        }
    try:
        td = trading_date or _today_ist()
        from signal_validation_tick import run_tick as _tick
        return _tick()
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def reconcile_now(trading_date: Optional[str] = None) -> dict:
    """Manually trigger EOD reconciliation. Rate-limited."""
    if not is_enabled():
        return _disabled()
    if _rate_limit_check("reconcile"):
        return {
            "status":  "RATE_LIMITED",
            "message": f"Reconciliation is rate-limited to once per {_RATE_LIMIT_SECONDS}s.",
        }
    try:
        import signal_validation_db as db
        from signal_validation_model import SignalValidationRecord
        td      = trading_date or _today_ist()
        session = db.get_latest_session(td)
        sid     = session.get("session_id") if session else f"sv-{td}-manual"
        from signal_validation_tick import _run_eod_close
        return _run_eod_close(sid, td)
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _serialize_row(row: dict) -> dict:
    """Convert Decimal/date types for JSON serialization."""
    out = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
