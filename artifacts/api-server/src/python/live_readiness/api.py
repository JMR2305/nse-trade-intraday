"""
api.py — Phase 6.5
HTTP façade functions for the 6 readiness endpoints.
"""
from __future__ import annotations
from .shared_services import (
    get_summary,
    get_system,
    get_data,
    get_recovery,
    get_security,
    get_report,
)


def cmd_summary()  -> dict: return get_summary()
def cmd_system()   -> dict: return get_system()
def cmd_data()     -> dict: return get_data()
def cmd_recovery() -> dict: return get_recovery()
def cmd_security() -> dict: return get_security()
def cmd_report()   -> dict: return get_report()
