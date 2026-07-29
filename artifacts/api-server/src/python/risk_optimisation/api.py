"""
api.py — Phase 6.4
HTTP façade functions for the 5 risk-optimisation endpoints.
"""
from __future__ import annotations
from .shared_services import (
    get_summary,
    get_capital,
    get_drawdown,
    get_stress,
    get_recommendations,
)


def cmd_summary()         -> dict: return get_summary()
def cmd_capital()         -> dict: return get_capital()
def cmd_drawdown()        -> dict: return get_drawdown()
def cmd_stress()          -> dict: return get_stress()
def cmd_recommendations() -> dict: return get_recommendations()
