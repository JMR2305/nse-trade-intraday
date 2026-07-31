"""
paper_analytics/api.py — Phase 8.2
Command dispatch for main.py.
Each cmd_* function returns a dict (never prints).

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations

from .shared_services import (
    get_summary, get_trades, get_strategies, get_risk,
    get_preopen, get_portfolio, get_learning,
    get_export_json, get_export_csv,
    get_paper_analytics_snapshot,
)


def cmd_summary()   -> dict: return get_summary()
def cmd_trades()    -> dict: return get_trades()
def cmd_strategies()-> dict: return get_strategies()
def cmd_risk()      -> dict: return get_risk()
def cmd_preopen()   -> dict: return get_preopen()
def cmd_portfolio() -> dict: return get_portfolio()
def cmd_learning()  -> dict: return get_learning()
def cmd_snapshot()  -> dict: return get_paper_analytics_snapshot()
def cmd_export_json()-> dict: return get_export_json()
def cmd_export_csv() -> dict:
    from .models import is_enabled, disabled_response
    if not is_enabled():
        return disabled_response()
    csv_data = get_export_csv()
    return {"csv": csv_data, "status": "ENABLED", "advisory_only": True}
