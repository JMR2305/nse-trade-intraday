"""
api.py — Phase 5D.5 HTTP facade functions.

Three endpoints:
  GET /api/executive/summary  — full dashboard
  GET /api/executive/health   — system health only
  GET /api/executive/widgets  — all widget data (no executive score)

PAPER TRADING / ADVISORY ONLY.
No mutations of any kind.
"""
from __future__ import annotations
from .shared_services import get_executive_summary, get_system_health, get_all_widgets


def get_summary() -> dict:
    return get_executive_summary()


def get_health() -> dict:
    return get_system_health()


def get_widgets() -> dict:
    return get_all_widgets()
