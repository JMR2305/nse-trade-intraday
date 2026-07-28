"""
execution_quality/api.py — Public API facade for Phase 5D.1.

Every function checks is_enabled() first and returns disabled_response() when off.
PAPER TRADING / ADVISORY ONLY.
No order submission, no broker call, no strategy modification.
"""
from __future__ import annotations

from .models import is_enabled, disabled_response

_LABEL = "PAPER TRADING / ADVISORY ONLY"


def get_summary(date: str | None = None) -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .metrics import build_execution_records, compute_summary
        records = build_execution_records()
        if date:
            records = [r for r in records if (r.entry_ts or "").startswith(date)]
        summary = compute_summary(records)
        summary["label"] = _LABEL
        summary["status"] = "ENABLED"
        return summary
    except Exception as exc:
        return {"error": str(exc), "label": _LABEL}


def get_trades(date: str | None = None, limit: int = 200, offset: int = 0) -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .metrics import build_execution_records
        records = build_execution_records()
        if date:
            records = [r for r in records if (r.entry_ts or "").startswith(date)]
        records = records[offset: offset + limit]
        return {
            "status": "ENABLED",
            "label":  _LABEL,
            "count":  len(records),
            "trades": [r.to_dict() for r in records],
        }
    except Exception as exc:
        return {"error": str(exc), "label": _LABEL}


def get_slippage(date: str | None = None) -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .metrics import build_execution_records
        from .slippage import compute_slippage_stats
        records = build_execution_records()
        if date:
            records = [r for r in records if (r.entry_ts or "").startswith(date)]
        stats = compute_slippage_stats(records)
        stats["status"] = "ENABLED"
        stats["label"]  = _LABEL
        return stats
    except Exception as exc:
        return {"error": str(exc), "label": _LABEL}


def get_fills(date: str | None = None) -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .metrics import build_execution_records
        from .fill_analysis import compute_fill_stats
        records = build_execution_records()
        if date:
            records = [r for r in records if (r.entry_ts or "").startswith(date)]
        stats = compute_fill_stats(records)
        stats["status"] = "ENABLED"
        stats["label"]  = _LABEL
        return stats
    except Exception as exc:
        return {"error": str(exc), "label": _LABEL}
