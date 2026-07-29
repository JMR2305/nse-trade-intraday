"""Phase 7.5 – Command dispatch adapter for main.py (return-dict pattern)."""
from __future__ import annotations
import json as _json


def cmd_summary() -> dict:
    from .shared_services import get_summary
    return get_summary()


def cmd_strategies() -> dict:
    from .shared_services import get_strategies
    return get_strategies()


def cmd_simulations() -> dict:
    from .shared_services import get_simulations
    return get_simulations()


def cmd_replay() -> dict:
    from .shared_services import get_replay
    return get_replay()


def cmd_benchmark() -> dict:
    from .shared_services import get_benchmark
    return get_benchmark()


def cmd_reports() -> dict:
    from .shared_services import get_reports
    return get_reports()


def cmd_snapshot() -> dict:
    from .shared_services import get_research_lab_snapshot
    return get_research_lab_snapshot()


def cmd_export() -> dict:
    import sys
    fmt = sys.argv[2] if len(sys.argv) > 2 else "json"
    if fmt == "csv":
        from .shared_services import export_csv
        return {"format": "csv", "content": export_csv()}
    from .shared_services import export_json
    return {"format": "json", "content": _json.loads(export_json())}
