"""
models.py — Phase 9.1
Constants, feature flag, and helpers for the Unified Command Centre.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

_FLAG = "COMMAND_CENTER_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":        "DISABLED",
        "available":     False,
        "advisory_only": True,
        "read_only":     True,
        "message":       f"Set {_FLAG}=true to enable the Unified Command Centre.",
    }


# ── Platform health grade ──────────────────────────────────────────────────────
def platform_grade(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 78: return "A"
    if score >= 65: return "B"
    if score >= 50: return "C"
    return "D"


def platform_status(score: float) -> str:
    if score >= 80: return "HEALTHY"
    if score >= 60: return "DEGRADED"
    return "CRITICAL"


# ── Alert severity constants ───────────────────────────────────────────────────
SEV_CRITICAL = "CRITICAL"
SEV_WARNING  = "WARNING"
SEV_INFO     = "INFO"

# ── Quick-action navigation shortcuts ─────────────────────────────────────────
QUICK_ACTIONS = [
    {"label": "Market Intelligence",  "href": "/market-intelligence", "icon": "TrendingUp"},
    {"label": "Paper Analytics",      "href": "/paper-analytics",     "icon": "BarChart2"},
    {"label": "Risk Validation",      "href": "/risk-validation",     "icon": "Shield"},
    {"label": "AI Performance",       "href": "/ai-performance",      "icon": "Brain"},
    {"label": "Research Lab",         "href": "/research-lab",        "icon": "FlaskConical"},
    {"label": "Operations Centre",    "href": "/operations-center",   "icon": "Monitor"},
    {"label": "Performance Centre",   "href": "/performance-center",  "icon": "Zap"},
    {"label": "Deployment & DR",      "href": "/deployment-center",   "icon": "Rocket"},
]

# ── System health module list (for Section 7 aggregation) ─────────────────────
SYSTEM_MODULES = [
    {"id": "observability", "label": "Observability",   "score_key": "observability_score",  "grade_key": "grade"},
    {"id": "operations",    "label": "Operations",      "score_key": "operations_score",     "grade_key": "grade"},
    {"id": "data_quality",  "label": "Data Quality",    "score_key": "quality_score",        "grade_key": "grade"},
    {"id": "security",      "label": "Security",        "score_key": "security_score",       "grade_key": "grade"},
    {"id": "performance",   "label": "Performance",     "score_key": "performance_score",    "grade_key": "grade"},
    {"id": "deployment",    "label": "Deployment & DR", "score_key": "dr_score",             "grade_key": "grade"},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_display() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
