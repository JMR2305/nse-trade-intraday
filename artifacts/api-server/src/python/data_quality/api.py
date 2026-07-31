"""
data_quality/api.py — Phase 8.3
Command-handler wrappers called from main.py command dispatch.

Each cmd_*() function is a thin one-liner that delegates to shared_services.
"""
from .shared_services import (
    get_summary, get_market, get_preopen, get_paper,
    get_portfolio, get_ai, get_signals, get_config,
    get_alerts, get_export_json, get_export_csv,
    get_data_quality_snapshot,
)
from .models import is_enabled, disabled_response

def cmd_summary()  -> dict: return get_summary()
def cmd_market()   -> dict: return get_market()
def cmd_preopen()  -> dict: return get_preopen()
def cmd_paper()    -> dict: return get_paper()
def cmd_portfolio()-> dict: return get_portfolio()
def cmd_ai()       -> dict: return get_ai()
def cmd_signals()  -> dict: return get_signals()
def cmd_config()   -> dict: return get_config()
def cmd_alerts()   -> dict: return get_alerts()
def cmd_snapshot() -> dict: return get_data_quality_snapshot()
def cmd_export_json() -> dict: return get_export_json()

def cmd_export_csv() -> dict:
    if not is_enabled():
        return disabled_response()
    return {
        "status":       "ENABLED",
        "advisory_only": True,
        "csv":          get_export_csv(),
    }
