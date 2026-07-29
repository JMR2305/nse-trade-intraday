"""
api.py — Phase 6.1
HTTP façade functions for the 4 validation endpoints.
Called by main.py command dispatcher.
"""
from __future__ import annotations
from .shared_services import get_session, get_history, get_quality, get_statistics


def cmd_session() -> dict:
    return get_session()


def cmd_history() -> dict:
    return get_history()


def cmd_quality() -> dict:
    return get_quality()


def cmd_statistics() -> dict:
    return get_statistics()
