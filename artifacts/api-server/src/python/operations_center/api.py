"""
api.py — Phase 8.5
CLI command functions for the Operational Control Centre.

READ-ONLY. ADVISORY-ONLY.
All commands are invoked via main.py and return JSON to stdout.
"""
from operations_center.shared_services import (
    get_summary,
    get_market,
    get_risk,
    get_paper_trading,
    get_data_quality,
    get_observability,
    get_feature_flags,
    get_jobs,
    get_alerts,
    get_checklist,
    get_timeline,
    get_operations_snapshot,
    export_json,
    export_csv,
)

# ── Command functions (called by main.py dispatch) ─────────────────────────────

def cmd_summary()       -> dict: return get_summary()
def cmd_market()        -> dict: return get_market()
def cmd_risk()          -> dict: return get_risk()
def cmd_paper()         -> dict: return get_paper_trading()
def cmd_data_quality()  -> dict: return get_data_quality()
def cmd_observability() -> dict: return get_observability()
def cmd_flags()         -> dict: return get_feature_flags()
def cmd_jobs()          -> dict: return get_jobs()
def cmd_alerts()        -> dict: return get_alerts()
def cmd_checklist()     -> dict: return get_checklist()
def cmd_timeline()      -> dict: return get_timeline()
def cmd_snapshot()      -> dict: return get_operations_snapshot()
def cmd_export_json()   -> dict: return export_json()
def cmd_export_csv()    -> dict: return export_csv()
