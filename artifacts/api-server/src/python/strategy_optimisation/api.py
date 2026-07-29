"""
api.py — Phase 6.2
HTTP façade functions for the 4 optimisation endpoints.
"""
from __future__ import annotations
from .shared_services import get_summary, get_strategies, get_recommendations, get_patterns


def cmd_summary() -> dict:
    return get_summary()


def cmd_strategies() -> dict:
    return get_strategies()


def cmd_recommendations() -> dict:
    return get_recommendations()


def cmd_patterns() -> dict:
    return get_patterns()
