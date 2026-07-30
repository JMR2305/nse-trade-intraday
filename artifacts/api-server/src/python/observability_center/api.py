"""
api.py — Phase 8.1
Command dispatch for main.py.
Each cmd_* function returns a dict (never prints).

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from .shared_services import (
    get_summary, get_system, get_performance,
    get_errors, get_alerts, get_audit,
    get_observability_snapshot, export_csv, export_json,
)


def cmd_summary()      -> dict: return get_summary()
def cmd_system()       -> dict: return get_system()
def cmd_performance()  -> dict: return get_performance()
def cmd_errors()       -> dict: return get_errors()
def cmd_alerts()       -> dict: return get_alerts()
def cmd_audit()        -> dict: return get_audit()
def cmd_snapshot()     -> dict: return get_observability_snapshot()
def cmd_export_csv()   -> dict: return {"csv": export_csv(), "status": "ENABLED"}
def cmd_export_json()  -> dict: return export_json()
