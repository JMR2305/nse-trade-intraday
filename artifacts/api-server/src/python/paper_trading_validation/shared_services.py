"""
shared_services.py — Phase 6.1
Stable public interface for paper_trading_validation.
All future phases and super-dashboards call these functions.

READ-ONLY. Never modifies trades, portfolio, strategies, orders, or signals.
"""
from __future__ import annotations
import sys, os
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .validation_models import is_enabled, disabled_response


# ---------------------------------------------------------------------------
# GET /api/validation/session
# Today's session: metadata + today's trades + daily metrics
# ---------------------------------------------------------------------------

def get_session() -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .validation_collector import collect_all_trade_records, collect_session_metadata
        from .metrics_engine import compute_daily_metrics
        from datetime import date

        records = collect_all_trade_records()
        session = collect_session_metadata()
        today_metrics = compute_daily_metrics(records, date.today())

        today_str = date.today().isoformat()
        today_trades = [r.to_dict() for r in records if r.timestamp.startswith(today_str)]

        return {
            "status": "ENABLED",
            "session": session.to_dict(),
            "today_metrics": today_metrics.to_dict(),
            "today_trades": today_trades,
            "trade_count_today": len(today_trades),
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/validation/history
# Historical performance: daily rows + all period roll-ups + dataset growth
# ---------------------------------------------------------------------------

def get_history() -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .validation_collector import collect_all_trade_records
        from .metrics_engine import compute_history, compute_dataset_growth

        records = collect_all_trade_records()
        history = compute_history(records)
        growth = compute_dataset_growth(records)

        return {
            "status": "ENABLED",
            "history": history,
            "growth": growth,
            "total_completed_trades": len(records),
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/validation/quality
# Data quality report over all collected records
# ---------------------------------------------------------------------------

def get_quality() -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .validation_collector import collect_all_trade_records
        from .data_quality import run_quality_checks

        records = collect_all_trade_records()
        report = run_quality_checks(records)

        return {
            "status": "ENABLED",
            "quality": report.to_dict(),
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/validation/statistics
# Overall validation statistics
# ---------------------------------------------------------------------------

def get_statistics() -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .validation_collector import collect_all_trade_records
        from .metrics_engine import compute_statistics

        records = collect_all_trade_records()
        stats = compute_statistics(records)

        return {
            "status": "ENABLED",
            "statistics": stats,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_records_csv() -> str:
    """Return CSV string of all trade records. Empty string if disabled."""
    if not is_enabled():
        return ""
    try:
        from .validation_collector import collect_all_trade_records
        from .export_service import export_csv
        return export_csv(collect_all_trade_records())
    except Exception:
        return ""


def export_records_json() -> str:
    """Return JSON string of all trade records. Empty string if disabled."""
    if not is_enabled():
        return ""
    try:
        from .validation_collector import collect_all_trade_records
        from .export_service import export_json
        return export_json(collect_all_trade_records())
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Flat snapshot — for future super-dashboards
# ---------------------------------------------------------------------------

def get_validation_snapshot() -> dict:
    """
    Flat KPI dict for use by executive dashboard or future phases.
    Returns zeros/UNKNOWN when data is unavailable — never raises.
    """
    try:
        from .validation_collector import collect_all_trade_records
        from .metrics_engine import compute_statistics
        records = collect_all_trade_records()
        stats = compute_statistics(records)
        return {
            "total_validated_trades": stats.get("total_trades", 0),
            "validation_win_rate": stats.get("win_rate", 0.0),
            "validation_net_pnl": stats.get("net_pnl", 0.0),
            "avg_ai_confidence": stats.get("avg_ai_confidence", 0.0),
            "avg_execution_score": stats.get("avg_execution_score", 0.0),
            "max_drawdown": stats.get("max_drawdown", 0.0),
        }
    except Exception:
        return {
            "total_validated_trades": 0,
            "validation_win_rate": 0.0,
            "validation_net_pnl": 0.0,
            "avg_ai_confidence": 0.0,
            "avg_execution_score": 0.0,
            "max_drawdown": 0.0,
        }
