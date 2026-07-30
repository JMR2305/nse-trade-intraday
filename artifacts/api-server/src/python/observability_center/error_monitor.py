"""
error_monitor.py — Phase 8.1
Application error aggregation and tracking.
Maintains an in-process circular error buffer and derives error analytics.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
import traceback
from datetime import datetime, timezone
from collections import defaultdict
from .models import STATUS_HEALTHY, STATUS_DEGRADED

# In-process error log: circular buffer
_error_log: list[dict] = []
_MAX_ERRORS = 200


def record_error(
    source: str,
    error_type: str,
    message: str,
    exc: BaseException | None = None,
    context: dict | None = None,
) -> None:
    """
    Record an error observation. Advisory-only — does not affect error propagation.
    Call from route handlers or background jobs to populate the error monitor.
    """
    global _error_log
    entry = {
        "error_id":   f"{source}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "source":     source,
        "error_type": error_type,
        "message":    str(message)[:300],
        "traceback":  (traceback.format_exc() if exc else None),
        "context":    context or {},
        "ts":         datetime.now(timezone.utc).isoformat(),
    }
    _error_log.append(entry)
    if len(_error_log) > _MAX_ERRORS:
        _error_log = _error_log[-_MAX_ERRORS:]


def _error_frequency(errors: list[dict]) -> dict:
    """Count errors by type and source."""
    by_type:   dict = defaultdict(int)
    by_source: dict = defaultdict(int)
    for e in errors:
        by_type[e["error_type"]] += 1
        by_source[e["source"]]   += 1
    return {
        "by_type":   dict(sorted(by_type.items(),   key=lambda x: -x[1])),
        "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1])),
    }


def _error_rate_per_hour(errors: list[dict]) -> float:
    """Estimate error rate per hour from the in-process log window."""
    if len(errors) < 2:
        return 0.0
    try:
        first_ts = datetime.fromisoformat(errors[0]["ts"])
        last_ts  = datetime.fromisoformat(errors[-1]["ts"])
        span_h   = max(0.01, (last_ts - first_ts).total_seconds() / 3600)
        return round(len(errors) / span_h, 2)
    except Exception:
        return 0.0


def get_error_monitor() -> dict:
    """Return error analytics from the in-process error log."""
    errors   = list(_error_log)          # snapshot
    total    = len(errors)
    recent   = errors[-20:]              # most recent 20
    freq     = _error_frequency(errors)
    rate_h   = _error_rate_per_hour(errors)

    status = (STATUS_DEGRADED if total > 10 or rate_h > 5 else STATUS_HEALTHY)
    health_score = max(0.0, round(100 - min(total, 100) - rate_h * 2, 1))

    # Categorise by type
    app_errors  = [e for e in errors if "Exception" in e.get("error_type", "") or
                   "Error"     in e.get("error_type", "")]
    api_errors  = [e for e in errors if e.get("source", "").startswith("api")]
    val_errors  = [e for e in errors if "validation" in e.get("error_type", "").lower() or
                   "parse"     in e.get("error_type", "").lower()]

    return {
        "available":        True,
        "advisory_only":    True,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "status":           status,
        "health_score":     health_score,
        "total_errors":     total,
        "app_errors":       len(app_errors),
        "api_errors":       len(api_errors),
        "validation_errors": len(val_errors),
        "error_rate_per_h": rate_h,
        "recent_errors":    recent,
        "frequency":        freq,
        "buffer_capacity":  _MAX_ERRORS,
        "note": (
            "Error log reflects errors recorded in this Python process session only. "
            "Node.js / Express errors are logged separately via pino."
        ),
    }
