"""
models.py — Phase 8.1
Dataclasses, enums, and helpers for the Production Monitoring & Observability Center.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── Feature flag ──────────────────────────────────────────────────────────────
_FLAG = "OBSERVABILITY_CENTER_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() == "true"


def disabled_response() -> dict:
    return {
        "status":       "DISABLED",
        "available":    False,
        "advisory_only": True,
        "message":      f"Set {_FLAG}=true to enable the Observability Center.",
    }


# ── Grade / trend helpers ─────────────────────────────────────────────────────

def obs_grade(score: float) -> str:
    if score >= 92: return "A+"
    if score >= 80: return "A"
    if score >= 68: return "B"
    if score >= 50: return "C"
    return "D"


def trend_label(current: float, previous: float) -> str:
    if current > previous + 2: return "IMPROVING"
    if current < previous - 2: return "DEGRADING"
    return "STABLE"


# ── Status constants ──────────────────────────────────────────────────────────
STATUS_HEALTHY  = "HEALTHY"
STATUS_DEGRADED = "DEGRADED"
STATUS_DOWN     = "DOWN"
STATUS_UNKNOWN  = "UNKNOWN"

# Alert severity
SEV_CRITICAL = "CRITICAL"
SEV_WARNING  = "WARNING"
SEV_INFO     = "INFO"

# Alert categories
CAT_SYSTEM      = "SYSTEM"
CAT_API         = "API"
CAT_DATABASE    = "DATABASE"
CAT_CACHE       = "CACHE"
CAT_JOB         = "JOB"
CAT_ERROR       = "ERROR"
CAT_PERFORMANCE = "PERFORMANCE"
CAT_AVAILABILITY = "AVAILABILITY"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ObsAlert:
    alert_id:   str
    severity:   str          # CRITICAL / WARNING / INFO
    category:   str
    title:      str
    detail:     str
    generated_at: str = field(default_factory=_now_iso)
    acknowledged: bool = False
    resolved:   bool = False

    def to_dict(self) -> dict:
        return {
            "alert_id":    self.alert_id,
            "severity":    self.severity,
            "category":    self.category,
            "title":       self.title,
            "detail":      self.detail,
            "generated_at": self.generated_at,
            "acknowledged": self.acknowledged,
            "resolved":    self.resolved,
        }


@dataclass
class AuditEntry:
    entry_id:   str
    action:     str
    actor:      str
    detail:     str
    timestamp:  str = field(default_factory=_now_iso)
    category:   str = "SYSTEM"

    def to_dict(self) -> dict:
        return {
            "entry_id":  self.entry_id,
            "action":    self.action,
            "actor":     self.actor,
            "detail":    self.detail,
            "timestamp": self.timestamp,
            "category":  self.category,
        }
