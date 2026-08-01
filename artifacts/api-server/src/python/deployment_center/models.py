"""
models.py — Phase 8.8
Dataclasses, constants, and helpers for the Deployment & Disaster Recovery Centre.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── Feature flag ───────────────────────────────────────────────────────────────
_FLAG = "DEPLOYMENT_CENTER_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":        "DISABLED",
        "available":     False,
        "advisory_only": True,
        "read_only":     True,
        "message":       f"Set {_FLAG}=true to enable the Deployment & Disaster Recovery Centre.",
    }


# ── Grade / trend helpers ──────────────────────────────────────────────────────

def dr_grade(score: float) -> str:
    if score >= 92: return "A+"
    if score >= 80: return "A"
    if score >= 68: return "B"
    if score >= 50: return "C"
    return "D"


def dr_trend(scores: list) -> str:
    if len(scores) < 2:
        return "STABLE"
    delta = float(scores[-1]) - float(scores[0])
    if delta > 3:   return "IMPROVING"
    if delta < -3:  return "DEGRADING"
    return "STABLE"


# ── Status / severity constants ────────────────────────────────────────────────
STATUS_READY     = "READY"
STATUS_DEGRADED  = "DEGRADED"
STATUS_NOT_READY = "NOT_READY"
STATUS_UNKNOWN   = "UNKNOWN"
STATUS_DISABLED  = "DISABLED"

SEV_CRITICAL = "CRITICAL"
SEV_WARNING  = "WARNING"
SEV_INFO     = "INFO"

# ── Thresholds ─────────────────────────────────────────────────────────────────
BACKUP_MAX_AGE_HOURS         = 24
ROLLBACK_PKG_MAX_AGE_DAYS    = 7
RESTORE_TIME_ESTIMATE_MIN    = 30
ROLLBACK_TIME_ESTIMATE_MIN   = 15
CONTINUITY_CRITICAL_SVC_COUNT = 5

# ── Required environment variables ────────────────────────────────────────────
REQUIRED_ENV_VARS: list[dict] = [
    {"name": "DATABASE_URL",        "description": "PostgreSQL connection string",      "critical": True},
    {"name": "SESSION_SECRET",      "description": "Express session signing secret",    "critical": True},
    {"name": "PORT",                "description": "API server listen port",            "critical": True},
    {"name": "NODE_ENV",            "description": "Node environment",                  "critical": False},
    {"name": "ZERODHA_API_KEY",     "description": "Zerodha Kite API key",              "critical": False},
    {"name": "ZERODHA_API_SECRET",  "description": "Zerodha Kite API secret",           "critical": False},
    {"name": "PYTHON_BIN",          "description": "Python binary path",                "critical": False},
]

# ── Required feature flags ─────────────────────────────────────────────────────
REQUIRED_FEATURE_FLAGS: list[str] = [
    "DEPLOYMENT_CENTER_ENABLED",
    "OBSERVABILITY_CENTER_ENABLED",
    "OPERATIONS_CENTER_ENABLED",
    "SECURITY_CENTER_ENABLED",
    "PERFORMANCE_CENTER_ENABLED",
    "DATA_QUALITY_ENABLED",
    "RISK_VALIDATION_ENABLED",
]

# ── Critical services for business continuity ─────────────────────────────────
CRITICAL_SERVICES = [
    {"id": "api_server",    "name": "API Server",          "tier": 1},
    {"id": "database",      "name": "PostgreSQL Database",  "tier": 1},
    {"id": "scheduler",     "name": "Scan Scheduler",       "tier": 1},
    {"id": "python_engine", "name": "Python Analytics Engine", "tier": 1},
    {"id": "cache",         "name": "In-process Cache",     "tier": 2},
    {"id": "notifications", "name": "Push Notifications",   "tier": 2},
    {"id": "email_alerts",  "name": "Email Alerts",         "tier": 2},
]

# ── Future multi-agent readiness table ────────────────────────────────────────
FUTURE_AGENTS = [
    {"id": "deploy-validator",   "role": "Validates deployment packages before apply"},
    {"id": "backup-verifier",    "role": "Verifies backup integrity on a schedule"},
    {"id": "rollback-executor",  "role": "Executes rollback after operator two-step confirm"},
    {"id": "config-auditor",     "role": "Continuous configuration drift detection"},
    {"id": "infra-monitor",      "role": "Infrastructure health monitoring agent"},
    {"id": "continuity-planner", "role": "Business continuity scenario tester"},
    {"id": "restore-tester",     "role": "Dry-runs restore procedures in isolation"},
    {"id": "incident-responder", "role": "Auto-escalates P0 incidents to operators"},
    {"id": "dr-coordinator",     "role": "Coordinates multi-site recovery procedures"},
    {"id": "sla-guardian",       "role": "Enforces SLA thresholds and pages on-call"},
]


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class DrRecommendation:
    category:      str
    severity:      str
    message:       str
    action:        str
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return {
            "category":      self.category,
            "severity":      self.severity,
            "message":       self.message,
            "action":        self.action,
            "advisory_only": self.advisory_only,
        }


@dataclass
class EnvVarCheck:
    name:        str
    description: str
    critical:    bool
    present:     bool
    detail:      str

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "critical":    self.critical,
            "present":     self.present,
            "detail":      self.detail,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
