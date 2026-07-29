"""
api.py — Phase 7.2
Command dispatch adapter for main.py.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations


def cmd_summary() -> dict:
    from .shared_services import get_summary
    return get_summary()


def cmd_corporate() -> dict:
    from .shared_services import get_corporate
    return get_corporate()


def cmd_regulatory() -> dict:
    from .shared_services import get_regulatory
    return get_regulatory()


def cmd_news() -> dict:
    from .shared_services import get_news
    return get_news()


def cmd_timeline() -> dict:
    from .shared_services import get_timeline
    return get_timeline()


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
