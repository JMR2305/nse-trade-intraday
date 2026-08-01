"""
models.py — Phase 8.6
Dataclasses, enums, and helpers for the Security & Compliance Centre.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── Feature flag ───────────────────────────────────────────────────────────────
_FLAG = "SECURITY_CENTER_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":        "DISABLED",
        "available":     False,
        "advisory_only": True,
        "read_only":     True,
        "message":       f"Set {_FLAG}=true to enable the Security & Compliance Centre.",
    }


# ── Grade helpers ──────────────────────────────────────────────────────────────

def sec_grade(score: float) -> str:
    if score >= 92: return "A+"
    if score >= 80: return "A"
    if score >= 68: return "B"
    if score >= 50: return "C"
    return "D"


def risk_level(score: float) -> str:
    if score >= 80: return "LOW"
    if score >= 60: return "MEDIUM"
    if score >= 40: return "HIGH"
    return "CRITICAL"


# ── Status / severity constants ────────────────────────────────────────────────
STATUS_SECURE   = "SECURE"
STATUS_DEGRADED = "DEGRADED"
STATUS_AT_RISK  = "AT_RISK"
STATUS_UNKNOWN  = "UNKNOWN"
STATUS_DISABLED = "DISABLED"

SEV_CRITICAL = "CRITICAL"
SEV_WARNING  = "WARNING"
SEV_INFO     = "INFO"

PRESENCE_PRESENT = "PRESENT"
PRESENCE_MISSING = "MISSING"
PRESENCE_WEAK    = "WEAK"


# ── Known required secrets (presence-check only — never expose values) ─────────
REQUIRED_SECRETS: list[dict] = [
    {
        "name":        "SESSION_SECRET",
        "description": "Express session signing secret",
        "category":    "authentication",
        "min_length":  32,
        "critical":    True,
    },
    {
        "name":        "ZERODHA_API_KEY",
        "description": "Zerodha Kite API key for broker connectivity",
        "category":    "broker",
        "min_length":  8,
        "critical":    False,
    },
    {
        "name":        "ZERODHA_API_SECRET",
        "description": "Zerodha Kite API secret",
        "category":    "broker",
        "min_length":  8,
        "critical":    False,
    },
    {
        "name":        "DATABASE_URL",
        "description": "PostgreSQL connection string",
        "category":    "database",
        "min_length":  10,
        "critical":    True,
    },
]

# ── Known required configuration keys ─────────────────────────────────────────
REQUIRED_CONFIG: list[dict] = [
    {"name": "NODE_ENV",                    "description": "Node environment",           "expected_values": ["production", "development"]},
    {"name": "SECURITY_CENTER_ENABLED",     "description": "Phase 8.6 feature flag",     "expected_values": ["true", "1", "yes"]},
    {"name": "OPERATIONS_CENTER_ENABLED",   "description": "Phase 8.5 feature flag",     "expected_values": None},
    {"name": "OBSERVABILITY_CENTER_ENABLED","description": "Phase 8.1 feature flag",     "expected_values": None},
    {"name": "DATA_QUALITY_ENABLED",        "description": "Phase 8.3 feature flag",     "expected_values": None},
    {"name": "RISK_VALIDATION_ENABLED",     "description": "Phase 8.4 feature flag",     "expected_values": None},
    {"name": "PORT",                        "description": "API server port",             "expected_values": None},
]

# ── Known weak/default secret patterns (names, not values) ────────────────────
# We flag if a secret value matches a known-insecure length or pattern.
# We NEVER log or return the actual value.
WEAK_SECRET_INDICATORS = {
    "SESSION_SECRET": {"min_length": 32, "common_weak": ["secret", "password", "changeme", "default"]},
}

# ── Known vulnerable Python package name prefixes (advisory only) ─────────────
KNOWN_VULNERABLE_PACKAGES: list[dict] = [
    {"name": "urllib3",     "vulnerable_below": "1.26.5",  "advisory": "HTTP client vulnerability (CVE-2021-33503)"},
    {"name": "pillow",      "vulnerable_below": "9.0.0",   "advisory": "Image parsing vulnerability"},
    {"name": "requests",    "vulnerable_below": "2.27.0",  "advisory": "Proxy header injection (CVE-2023-32681)"},
    {"name": "cryptography","vulnerable_below": "41.0.0",  "advisory": "OpenSSL binding updates required"},
    {"name": "setuptools",  "vulnerable_below": "65.5.1",  "advisory": "Path traversal (CVE-2022-40897)"},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SecAlert:
    alert_id:    str
    severity:    str
    category:    str
    title:       str
    detail:      str
    generated_at: str = field(default_factory=_now_iso)
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return {
            "alert_id":    self.alert_id,
            "severity":    self.severity,
            "category":    self.category,
            "title":       self.title,
            "detail":      self.detail,
            "generated_at":self.generated_at,
            "advisory_only": self.advisory_only,
        }


@dataclass
class SecretCheck:
    name:        str
    description: str
    category:    str
    presence:    str   # PRESENT | MISSING | WEAK
    critical:    bool
    detail:      str = ""

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "category":    self.category,
            "presence":    self.presence,
            "critical":    self.critical,
            "detail":      self.detail,
            # NEVER include the actual secret value
        }


@dataclass
class ConfigCheck:
    name:      str
    description: str
    status:    str   # OK | MISSING | INVALID
    detail:    str = ""

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "status":      self.status,
            "detail":      self.detail,
        }
