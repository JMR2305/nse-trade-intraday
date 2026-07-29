"""
api.py — Phase 6.3
HTTP façade functions for the 5 ai-optimisation endpoints.
"""
from __future__ import annotations
from .shared_services import (
    get_summary,
    get_calibration,
    get_drift,
    get_recommendations,
    get_history,
)


def cmd_summary()         -> dict: return get_summary()
def cmd_calibration()     -> dict: return get_calibration()
def cmd_drift()           -> dict: return get_drift()
def cmd_recommendations() -> dict: return get_recommendations()
def cmd_history()         -> dict: return get_history()
