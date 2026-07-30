"""
audit_tracker.py — Phase 8.1
Audit log and timeline for operator actions and configuration changes.
In-process circular audit buffer — advisory and read-only.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
import hashlib
from datetime import datetime, timezone
from .models import AuditEntry

# In-process audit log
_audit_log: list[AuditEntry] = []
_MAX_AUDIT  = 500


def record_audit(
    action:   str,
    actor:    str   = "system",
    detail:   str   = "",
    category: str   = "SYSTEM",
) -> None:
    """Record an audit entry. Advisory only — does not enforce policy."""
    global _audit_log
    entry_id = hashlib.sha1(
        f"{action}{actor}{datetime.now(timezone.utc).isoformat()}".encode()
    ).hexdigest()[:10]
    entry = AuditEntry(
        entry_id = entry_id,
        action   = action,
        actor    = actor,
        detail   = str(detail)[:300],
        category = category,
    )
    _audit_log.append(entry)
    if len(_audit_log) > _MAX_AUDIT:
        _audit_log = _audit_log[-_MAX_AUDIT:]


def _seed_startup_audit() -> None:
    """Seed the audit log with startup facts if empty."""
    if _audit_log:
        return
    env = os.environ.get("NODE_ENV", "development")
    flags_enabled = [
        k for k in (
            "MARKET_INTELLIGENCE_HUB_ENABLED", "EVENT_INTELLIGENCE_ENABLED",
            "MACRO_INTELLIGENCE_ENABLED", "EXPLAINABLE_AI_ENABLED",
            "RESEARCH_LAB_ENABLED", "OBSERVABILITY_CENTER_ENABLED",
        )
        if os.environ.get(k, "false").lower() == "true"
    ]
    record_audit("PLATFORM_START",  "system",
                 f"Environment: {env}", "DEPLOYMENT")
    for flag in flags_enabled:
        record_audit("FEATURE_FLAG_ENABLED", "system",
                     f"{flag}=true at startup", "CONFIGURATION")


def get_audit_timeline() -> dict:
    """Return the audit trail and timeline statistics."""
    _seed_startup_audit()

    entries   = list(_audit_log)
    recent    = entries[-50:]
    total     = len(entries)

    # Category breakdown
    cat_counts: dict = {}
    for e in entries:
        cat_counts[e.category] = cat_counts.get(e.category, 0) + 1

    # Actor breakdown
    actor_counts: dict = {}
    for e in entries:
        actor_counts[e.actor] = actor_counts.get(e.actor, 0) + 1

    # Timeline: last 10 entries formatted
    timeline = [
        {
            "ts":      e.timestamp,
            "action":  e.action,
            "actor":   e.actor,
            "category": e.category,
            "detail":  e.detail[:100],
        }
        for e in reversed(recent)
    ]

    return {
        "available":       True,
        "advisory_only":   True,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "total_entries":   total,
        "session_entries": len(entries),
        "category_counts": cat_counts,
        "actor_counts":    actor_counts,
        "timeline":        timeline,
        "recent_entries":  [e.to_dict() for e in reversed(recent[:20])],
        "buffer_capacity": _MAX_AUDIT,
        "note": "Audit log reflects this process session only. Persistent audit requires external log storage.",
    }
