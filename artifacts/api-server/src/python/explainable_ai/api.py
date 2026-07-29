"""Phase 7.4 – Command dispatch adapter for main.py (return-dict pattern)."""
from __future__ import annotations
import sys


def _symbol_arg() -> str:
    """Return symbol from sys.argv[2] if provided, else empty string."""
    return sys.argv[2] if len(sys.argv) > 2 else ""


# ── dispatch functions — each RETURNS a dict (main.py handles JSON serialisation) ─

def cmd_summary() -> dict:
    from .shared_services import get_summary
    return get_summary()


def cmd_decision() -> dict:
    from .shared_services import get_decision
    return get_decision(_symbol_arg())


def cmd_contributions() -> dict:
    from .shared_services import get_contributions
    return get_contributions(_symbol_arg())


def cmd_confidence() -> dict:
    from .shared_services import get_confidence
    return get_confidence(_symbol_arg())


def cmd_scenarios() -> dict:
    from .shared_services import get_scenarios
    return get_scenarios(_symbol_arg())


def cmd_history() -> dict:
    from .shared_services import get_history
    return get_history(_symbol_arg())


def cmd_snapshot() -> dict:
    from .shared_services import get_explainable_ai_snapshot
    return get_explainable_ai_snapshot()


def cmd_export() -> dict:
    import json as _json
    from .shared_services import export_csv, export_json
    fmt = _symbol_arg() or "json"
    if fmt == "csv":
        return {"format": "csv", "content": export_csv()}
    return {"format": "json", "content": _json.loads(export_json())}
