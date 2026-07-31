"""
risk_validation/api.py — Phase 8.4
Thin command-handler wrappers called from main.py dispatch.
READ-ONLY · ADVISORY-ONLY.
"""
from .shared_services import (
    get_summary, get_portfolio_data, get_sector_data, get_correlation_data,
    get_stress_data, get_tail_risk_data, get_execution_data,
    get_market_risk_data, get_drift_data, get_alerts_data,
    get_export_json, get_export_csv, get_risk_validation_snapshot,
)
from .models import is_enabled, disabled_response

def cmd_summary()     -> dict: return get_summary()
def cmd_portfolio()   -> dict: return get_portfolio_data()
def cmd_sector()      -> dict: return get_sector_data()
def cmd_correlation() -> dict: return get_correlation_data()
def cmd_stress()      -> dict: return get_stress_data()
def cmd_tail()        -> dict: return get_tail_risk_data()
def cmd_execution()   -> dict: return get_execution_data()
def cmd_market()      -> dict: return get_market_risk_data()
def cmd_drift()       -> dict: return get_drift_data()
def cmd_alerts()      -> dict: return get_alerts_data()
def cmd_snapshot()    -> dict: return get_risk_validation_snapshot()
def cmd_export_json() -> dict: return get_export_json()

def cmd_export_csv() -> dict:
    if not is_enabled():
        return disabled_response()
    return {
        "status":       "ENABLED",
        "advisory_only": True,
        "csv":           get_export_csv(),
    }
