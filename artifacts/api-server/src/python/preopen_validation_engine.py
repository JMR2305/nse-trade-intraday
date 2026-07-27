"""
preopen_validation_engine.py — Phase 5B Pre-Open Validation top-level orchestrator.

All public functions return {"status":"DISABLED"} when PREOPEN_VALIDATION_ENABLED is off.
None of these functions submit orders, modify risk limits, alter strategy weights,
or change the Phase 5A scoring formula.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

_ENABLED_VAR = "PREOPEN_VALIDATION_ENABLED"
_IST = timezone(timedelta(hours=5, minutes=30))


def _is_enabled() -> bool:
    return os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


def _disabled_response(extra: Optional[dict] = None) -> dict:
    resp = {
        "status":       "DISABLED",
        "feature_flag": _ENABLED_VAR,
        "message":      f"Pre-Open Validation is disabled. Set {_ENABLED_VAR}=true to enable.",
        "label":        "PAPER / ADVISORY ONLY",
    }
    if extra:
        resp.update(extra)
    return resp


def _today_ist() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


# ── Status ────────────────────────────────────────────────────────────────────

def get_status() -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        import preopen_validation_db as db
        from preopen_validation_scheduler import get_scheduler_status
        sessions = db.get_validation_sessions(limit=5)
        return {
            "status":         "ENABLED",
            "feature_flag":   _ENABLED_VAR,
            "trading_date":   _today_ist(),
            "sessions_count": len(sessions),
            "latest_session": sessions[0] if sessions else None,
            "scheduler":      get_scheduler_status(),
            "label":          "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "label": "PAPER / ADVISORY ONLY"}


# ── Daily data ────────────────────────────────────────────────────────────────

def get_daily(trading_date: Optional[str] = None) -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        import preopen_validation_db as db
        date = trading_date or _today_ist()
        sessions = db.get_validation_sessions(limit=30)
        reports  = db.get_daily_reports(limit=10)
        session  = next((s for s in sessions if s.get("trading_date") == date), None)
        report   = next((r for r in reports  if r.get("trading_date") == date), None)
        metrics  = report.get("metrics_json") if report else None
        return {
            "success":      True,
            "trading_date": date,
            "session":      session,
            "metrics":      metrics,
            "sessions_available": [s.get("trading_date") for s in sessions],
            "label":        "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Candidate outcomes ────────────────────────────────────────────────────────

def get_candidates(trading_date: Optional[str] = None, limit: int = 200) -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        import preopen_validation_db as db
        date = trading_date or _today_ist()
        candidates = db.get_candidate_outcomes(date, limit=limit)
        return {
            "success":      True,
            "trading_date": date,
            "candidates":   candidates,
            "count":        len(candidates),
            "label":        "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_symbol(symbol: str, trading_date: Optional[str] = None) -> dict:
    if not _is_enabled():
        return _disabled_response({"symbol": symbol})
    try:
        import preopen_validation_db as db
        date = trading_date or _today_ist()
        rec  = db.get_candidate_outcome_symbol(date, symbol.upper())
        if not rec:
            return {"success": False, "error": f"No validation record for {symbol} on {date}"}
        return {"success": True, "trading_date": date, "symbol": symbol.upper(),
                "record": rec, "label": "PAPER / ADVISORY ONLY"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Score bands ───────────────────────────────────────────────────────────────

def get_score_bands(trading_date: Optional[str] = None) -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        import preopen_validation_db as db
        date  = trading_date or _today_ist()
        bands = db.get_score_band_metrics(date)
        return {
            "success":      True,
            "trading_date": date,
            "score_bands":  bands,
            "label":        "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Factor metrics ────────────────────────────────────────────────────────────

def get_factors(trading_date: Optional[str] = None) -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        import preopen_validation_db as db
        date    = trading_date or _today_ist()
        factors = db.get_factor_metrics(date)
        return {
            "success":      True,
            "trading_date": date,
            "factors":      factors,
            "note":         "Low sample sizes are marked inconclusive.",
            "label":        "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Sector breakdown ──────────────────────────────────────────────────────────

def get_sectors(trading_date: Optional[str] = None) -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        import preopen_validation_db as db
        from preopen_validation_model import ValidationRecord, DataQualityStatus, ValidationStatus
        from preopen_validation_metrics import calculate_sector_breakdown
        date       = trading_date or _today_ist()
        candidates = db.get_candidate_outcomes(date, limit=500)
        records    = [_dict_to_record(c) for c in candidates]
        sectors    = calculate_sector_breakdown(records)
        return {
            "success":      True,
            "trading_date": date,
            "sectors":      sectors,
            "label":        "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Full report ───────────────────────────────────────────────────────────────

def get_report(trading_date: Optional[str] = None) -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        import preopen_validation_db as db
        date    = trading_date or _today_ist()
        reports = db.get_daily_reports(limit=30)
        report  = next((r for r in reports if r.get("trading_date") == date), None)
        if not report:
            return {
                "success":      False,
                "error":        f"No report found for {date}",
                "trading_date": date,
                "label":        "PAPER / ADVISORY ONLY",
            }
        return {
            "success":      True,
            "trading_date": date,
            "report":       report,
            "label":        "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Run validation (POST) ─────────────────────────────────────────────────────

def run_validation() -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        from preopen_validation_scheduler import run_validation_cycle_now
        return run_validation_cycle_now()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── 5-day report ──────────────────────────────────────────────────────────────

def get_5day_report() -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        import preopen_validation_db as db
        from preopen_validation_model import ValidationRecord
        from preopen_validation_reports import generate_5day_report

        daily_reports = db.get_daily_reports(limit=10)
        daily_records: Dict[str, list] = {}

        for dr in daily_reports:
            date       = dr.get("trading_date", "")
            candidates = db.get_candidate_outcomes(date, limit=500)
            records    = [_dict_to_record(c) for c in candidates]
            if records:
                daily_records[date] = records

        if not daily_records:
            return {
                "success": False,
                "error":   "No completed validation sessions found",
                "label":   "PAPER / ADVISORY ONLY",
            }

        report = generate_5day_report(daily_records)
        return {"success": True, "report": report, "label": "PAPER / ADVISORY ONLY"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Helper ────────────────────────────────────────────────────────────────────

def _dict_to_record(d: dict):
    from preopen_validation_model import ValidationRecord
    r = ValidationRecord()
    for k, v in d.items():
        if hasattr(r, k):
            try:
                setattr(r, k, v)
            except Exception:
                pass
    return r
