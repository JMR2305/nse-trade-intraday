"""
api.py — Phase 7.1
HTTP façade functions for the 5 market intelligence endpoints + exports.
"""
from __future__ import annotations
from .shared_services import (
    get_summary,
    get_sectors,
    get_watchlist,
    get_breadth,
    get_overview,
)


def cmd_summary()   -> dict: return get_summary()
def cmd_sectors()   -> dict: return get_sectors()
def cmd_watchlist() -> dict: return get_watchlist()
def cmd_breadth()   -> dict: return get_breadth()
def cmd_overview()  -> dict: return get_overview()
