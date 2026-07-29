"""
api.py — Phase 7.3
Command dispatch adapter for main.py.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations


def cmd_summary() -> dict:
    from .shared_services import get_summary
    return get_summary()


def cmd_calendar() -> dict:
    from .shared_services import get_calendar
    return get_calendar()


def cmd_global() -> dict:
    from .shared_services import get_global
    return get_global()


def cmd_flows() -> dict:
    from .shared_services import get_flows
    return get_flows()


def cmd_commodities() -> dict:
    from .shared_services import get_commodities
    return get_commodities()


def cmd_brief() -> dict:
    from .shared_services import get_brief
    return get_brief()


def cmd_export_csv() -> dict:
    from .shared_services import export_csv
    csv_str = export_csv()
    return {"csv": csv_str, "status": "ENABLED" if csv_str else "DISABLED"}


def cmd_export_json() -> dict:
    from .shared_services import export_json
    json_str = export_json()
    return {"json": json_str, "status": "ENABLED" if json_str else "DISABLED"}
