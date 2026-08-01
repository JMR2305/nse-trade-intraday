"""
models.py — Phase 8.5
Dataclasses, enums, and helpers for the Operational Control Centre.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── Feature flag ───────────────────────────────────────────────────────────────
_FLAG = "OPERATIONS_CENTER_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":        "DISABLED",
        "available":     False,
        "advisory_only": True,
        "message":       f"Set {_FLAG}=true to enable the Operational Control Centre.",
    }


# ── Grade / trend helpers ──────────────────────────────────────────────────────

def ops_grade(score: float) -> str:
    if score >= 92: return "A+"
    if score >= 80: return "A"
    if score >= 68: return "B"
    if score >= 50: return "C"
    return "D"


def trend_label(current: float, previous: float) -> str:
    if current > previous + 2: return "IMPROVING"
    if current < previous - 2: return "DEGRADING"
    return "STABLE"


# ── Status constants ───────────────────────────────────────────────────────────
STATUS_OPERATIONAL = "OPERATIONAL"
STATUS_DEGRADED    = "DEGRADED"
STATUS_DOWN        = "DOWN"
STATUS_UNKNOWN     = "UNKNOWN"
STATUS_DISABLED    = "DISABLED"

SEV_CRITICAL = "CRITICAL"
SEV_WARNING  = "WARNING"
SEV_INFO     = "INFO"


# ── Checklist categories ───────────────────────────────────────────────────────
CHECKLIST_MORNING    = "MORNING"
CHECKLIST_PREOPEN    = "PRE_OPEN"
CHECKLIST_MARKET_OPEN = "MARKET_OPEN"
CHECKLIST_MID_SESSION = "MID_SESSION"
CHECKLIST_CLOSING    = "CLOSING"
CHECKLIST_EOD        = "END_OF_DAY"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ist() -> datetime:
    """Return current time in IST (UTC+5:30)."""
    from datetime import timedelta
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def checklist_phase() -> str:
    """Return which checklist phase applies right now (IST)."""
    ist = _now_ist()
    h, m = ist.hour, ist.minute
    total_minutes = h * 60 + m
    if total_minutes < 9 * 60:
        return CHECKLIST_MORNING
    if total_minutes < 9 * 60 + 15:
        return CHECKLIST_PREOPEN
    if total_minutes < 9 * 60 + 30:
        return CHECKLIST_MARKET_OPEN
    if total_minutes < 14 * 60:
        return CHECKLIST_MID_SESSION
    if total_minutes < 15 * 60 + 30:
        return CHECKLIST_CLOSING
    return CHECKLIST_EOD


# ── Known feature flags ────────────────────────────────────────────────────────
KNOWN_FLAGS: list[dict] = [
    {"name": "OPERATIONS_CENTER_ENABLED",       "category": "core",         "description": "Phase 8.5 Operational Control Centre"},
    {"name": "OBSERVABILITY_CENTER_ENABLED",     "category": "core",         "description": "Phase 8.1 Production Monitoring"},
    {"name": "DATA_QUALITY_ENABLED",             "category": "core",         "description": "Phase 8.3 Data Quality Framework"},
    {"name": "RISK_VALIDATION_ENABLED",          "category": "core",         "description": "Phase 8.4 Risk Validation Framework"},
    {"name": "PAPER_TRADING_MODE",               "category": "trading",      "description": "Paper trading (not live execution)"},
    {"name": "ZERODHA_ENABLED",                  "category": "trading",      "description": "Live Zerodha broker connection"},
    {"name": "MARKET_INTELLIGENCE_HUB_ENABLED",  "category": "intelligence", "description": "Phase 7.1 Market Intelligence Hub"},
    {"name": "EVENT_INTELLIGENCE_ENABLED",       "category": "intelligence", "description": "Phase 7 Event Intelligence"},
    {"name": "MACRO_INTELLIGENCE_ENABLED",       "category": "intelligence", "description": "Phase 7 Macro Intelligence"},
    {"name": "EXECUTIVE_DASHBOARD_ENABLED",      "category": "analytics",    "description": "Executive Dashboard aggregator"},
    {"name": "LIVE_READINESS_ENABLED",           "category": "analytics",    "description": "Phase 6.5 Live Readiness score"},
    {"name": "STRATEGY_INTELLIGENCE_ENABLED",    "category": "analytics",    "description": "Phase 5D.3 Strategy Intelligence"},
    {"name": "AI_PERFORMANCE_ENABLED",           "category": "analytics",    "description": "Phase 5D.4 AI Performance Intelligence"},
    {"name": "PORTFOLIO_PERFORMANCE_ENABLED",    "category": "analytics",    "description": "Phase 5D.2 Portfolio Performance"},
    {"name": "RISK_OPTIMISATION_ENABLED",        "category": "analytics",    "description": "Phase 6.4 Risk Optimisation"},
    {"name": "STRATEGY_OPTIMISATION_ENABLED",    "category": "analytics",    "description": "Phase 6.2 Strategy Optimisation"},
    {"name": "EXPLAINABLE_AI_ENABLED",           "category": "ai",           "description": "Explainable AI module"},
    {"name": "RESEARCH_LAB_ENABLED",             "category": "ai",           "description": "Research Lab module"},
    {"name": "AUTO_PAPER_ENABLED",               "category": "experimental", "description": "Automated paper trade entries"},
    {"name": "PUSH_NOTIFICATIONS_ENABLED",       "category": "experimental", "description": "Mobile push alerts"},
]


@dataclass
class OpsAlert:
    alert_id:    str
    severity:    str
    source:      str
    title:       str
    detail:      str
    generated_at: str = field(default_factory=_now_iso)
    acknowledged: bool = False
    resolved:    bool = False

    def to_dict(self) -> dict:
        return {
            "alert_id":     self.alert_id,
            "severity":     self.severity,
            "source":       self.source,
            "title":        self.title,
            "detail":       self.detail,
            "generated_at": self.generated_at,
            "acknowledged": self.acknowledged,
            "resolved":     self.resolved,
        }


@dataclass
class TimelineEvent:
    event_id:   str
    category:   str
    title:      str
    detail:     str
    timestamp:  str
    severity:   str = SEV_INFO

    def to_dict(self) -> dict:
        return {
            "event_id":  self.event_id,
            "category":  self.category,
            "title":     self.title,
            "detail":    self.detail,
            "timestamp": self.timestamp,
            "severity":  self.severity,
        }


@dataclass
class ChecklistItem:
    item_id:     str
    title:       str
    description: str
    status:      str   # OK / WARNING / UNKNOWN
    detail:      str = ""

    def to_dict(self) -> dict:
        return {
            "item_id":     self.item_id,
            "title":       self.title,
            "description": self.description,
            "status":      self.status,
            "detail":      self.detail,
        }
