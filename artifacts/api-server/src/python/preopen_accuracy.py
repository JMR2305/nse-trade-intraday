"""
preopen_accuracy.py — Phase 5A Post-Open Accuracy Report.

Reads reconciliation records from the preopen_reconciliation table and
computes session accuracy metrics:
  - Mean Absolute Error %: how close indicative prices were to actual opens
  - Hit Rate %: correct direction calls (gap direction held at 09:20)
  - Confirmation Rate %: watchlist candidates confirmed at open
  - False Positive Rate %: watchlist candidates that reversed

Called after 09:30 IST once actual open prices are available in the DB.

READ-ONLY. ADVISORY-ONLY. PAPER TRADING.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

_ENABLED_VAR = "PREOPEN_INTELLIGENCE_ENABLED"


def _is_enabled() -> bool:
    return os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


# ── Metric computation ────────────────────────────────────────────────────────

def _compute_metrics(records: List[dict]) -> Dict[str, Any]:
    """Aggregate reconciliation records into accuracy metrics."""
    total = len(records)
    if total == 0:
        return {
            "available": False,
            "symbols_reconciled": 0,
            "message": "No reconciliation data available. Run a pre-open session first.",
        }

    # Mean Absolute Error %
    with_error = [r for r in records if r.get("indicative_to_open_error") is not None]
    mae_pct = (
        round(sum(float(r["indicative_to_open_error"]) for r in with_error) / len(with_error), 4)
        if with_error else None
    )

    # Hit Rate: gap direction held at 09:20 (opening_continuation)
    with_direction = [r for r in records if r.get("opening_continuation") is not None]
    continuations = [r for r in with_direction if r["opening_continuation"] is True]
    hit_rate_pct = (
        round(len(continuations) / len(with_direction) * 100, 2)
        if with_direction else None
    )

    # Confirmation Rate: watchlist candidates confirmed
    wl_total = [r for r in records if r.get("was_in_watchlist")]
    wl_confirmed = [r for r in wl_total if r.get("watchlist_confirmed") is True]
    confirmation_rate_pct = (
        round(len(wl_confirmed) / len(wl_total) * 100, 2)
        if wl_total else None
    )

    # False Positive Rate: watchlist candidates that reversed
    wl_reversals = [r for r in wl_total if r.get("opening_reversal") is True]
    false_positive_rate_pct = (
        round(len(wl_reversals) / len(wl_total) * 100, 2)
        if wl_total else None
    )

    # Opening continuation and reversal rates over all symbols
    reversals = [r for r in with_direction if r.get("opening_reversal") is True]
    continuation_rate_pct = (
        round(len(continuations) / len(with_direction) * 100, 2)
        if with_direction else None
    )
    reversal_rate_pct = (
        round(len(reversals) / len(with_direction) * 100, 2)
        if with_direction else None
    )

    # Accuracy grade
    if mae_pct is not None and hit_rate_pct is not None:
        if mae_pct < 0.3 and hit_rate_pct >= 70:
            grade, grade_label = "A", "Excellent"
        elif mae_pct < 0.6 and hit_rate_pct >= 55:
            grade, grade_label = "B", "Good"
        elif mae_pct < 1.0 and hit_rate_pct >= 45:
            grade, grade_label = "C", "Fair"
        else:
            grade, grade_label = "D", "Poor"
    else:
        grade, grade_label = "N/A", "Insufficient data"

    return {
        "available": True,
        "symbols_reconciled": total,
        "with_error_count": len(with_error),
        "with_direction_count": len(with_direction),
        "watchlist_total": len(wl_total),
        "watchlist_confirmed_count": len(wl_confirmed),
        "avg_indicative_to_open_error_pct": mae_pct,
        "hit_rate_pct": hit_rate_pct,
        "confirmation_rate_pct": confirmation_rate_pct,
        "false_positive_rate_pct": false_positive_rate_pct,
        "continuation_rate_pct": continuation_rate_pct,
        "reversal_rate_pct": reversal_rate_pct,
        "grade": grade,
        "grade_label": grade_label,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def get_accuracy(trading_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Get accuracy metrics for a trading date (defaults to latest available).
    Returns metrics + per-symbol reconciliation records.
    """
    if not _is_enabled():
        return {
            "status": "DISABLED",
            "available": False,
            "message": f"Set {_ENABLED_VAR}=true to enable pre-open intelligence",
        }

    try:
        import preopen_db as db

        records = db.get_reconciliation(trading_date)
        metrics = _compute_metrics(records)

        trading_date_out = records[0].get("trading_date") if records else trading_date
        session_id = records[0].get("session_id") if records else None
        reconciled_at = (
            max(str(r.get("reconciled_at") or "") for r in records)
            if records else None
        )

        # Per-symbol summary (lightweight, no binary fields)
        symbol_rows = [
            {
                "symbol": r.get("symbol"),
                "indicative_price": r.get("indicative_equilibrium_price"),
                "actual_open": r.get("actual_open_price"),
                "price_at_0920": r.get("price_at_0920"),
                "price_at_0930": r.get("price_at_0930"),
                "error_pct": r.get("indicative_to_open_error"),
                "direction_correct": r.get("opening_continuation"),
                "was_in_watchlist": r.get("was_in_watchlist"),
                "watchlist_confirmed": r.get("watchlist_confirmed"),
            }
            for r in records
        ]

        return {
            "success": True,
            "trading_date": trading_date_out,
            "session_id": session_id,
            "reconciled_at": reconciled_at,
            **metrics,
            "symbols": symbol_rows,
            "label": "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e), "available": False}


def get_accuracy_history(n_sessions: int = 5) -> Dict[str, Any]:
    """Get accuracy summary across the last N sessions."""
    if not _is_enabled():
        return {
            "status": "DISABLED",
            "available": False,
            "message": f"Set {_ENABLED_VAR}=true to enable pre-open intelligence",
        }

    try:
        import preopen_db as db

        dates = db.get_reconciliation_dates(n_sessions)
        sessions = []
        for date in dates:
            records = db.get_reconciliation(date)
            metrics = _compute_metrics(records)
            if metrics.get("available"):
                session_id = records[0].get("session_id") if records else None
                sessions.append({
                    "trading_date": date,
                    "session_id": session_id,
                    **{
                        k: v for k, v in metrics.items()
                        if k not in ("available", "message")
                    },
                })

        return {
            "success": True,
            "sessions": sessions,
            "label": "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e), "sessions": []}
