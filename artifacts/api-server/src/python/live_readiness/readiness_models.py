"""
readiness_models.py — Phase 6.5
Feature flag, scoring helpers, and dataclasses.

READ-ONLY. ADVISORY-ONLY.
This module NEVER enables live trading, places orders, or modifies any
trading engine, portfolio, strategies, signals, AI models, or risk parameters.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return os.environ.get("READINESS_VALIDATION_ENABLED", "false").lower() == "true"


def disabled_response() -> dict:
    return {
        "status": "DISABLED",
        "message": "Set READINESS_VALIDATION_ENABLED=true to enable.",
    }


# ---------------------------------------------------------------------------
# Severity / status constants
# ---------------------------------------------------------------------------

PASS   = "PASS"
WARN   = "WARN"
FAIL   = "FAIL"

READY       = "READY FOR EXTENDED PAPER TRADING"
READY_WARN  = "READY WITH OBSERVATIONS"
NOT_READY   = "NOT READY"


# ---------------------------------------------------------------------------
# ReadinessCheck dataclass
# ---------------------------------------------------------------------------

@dataclass
class ReadinessCheck:
    name: str            # machine-readable key
    label: str           # human-readable label
    status: str          # PASS / WARN / FAIL
    required: bool       # required = blocks READY if FAIL; advisory = WARN only
    detail: str          # explanation
    category: str        # SystemHealth / DataQuality / Config / Security / Recovery / APIHealth / Broker

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "required": self.required,
            "detail": self.detail,
            "category": self.category,
        }


# ---------------------------------------------------------------------------
# Score helpers
# ---------------------------------------------------------------------------

def compute_category_score(checks: List[ReadinessCheck]) -> float:
    """
    Category score 0–100.
    PASS = 1.0, WARN = 0.5, FAIL = 0.0 per check.
    """
    if not checks:
        return 50.0
    total = sum(1.0 if c.status == PASS else 0.5 if c.status == WARN else 0.0 for c in checks)
    return round((total / len(checks)) * 100.0, 2)


def compute_readiness_score(category_scores: dict) -> float:
    """
    Weighted Operational Readiness Score 0–100.
    System Health 20%, Data Quality 20%, API Health 15%,
    Config 15%, Security 15%, Recovery 15%.
    """
    weights = {
        "SystemHealth": 0.20,
        "DataQuality":  0.20,
        "APIHealth":    0.15,
        "Config":       0.15,
        "Security":     0.15,
        "Recovery":     0.15,
    }
    score = sum(category_scores.get(cat, 50.0) * w for cat, w in weights.items())
    return round(min(max(score, 0.0), 100.0), 2)


def health_grade(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 65: return "B"
    if score >= 50: return "C"
    return "D"


def go_no_go(score: float, critical_failures: int) -> str:
    if critical_failures > 0:
        return NOT_READY
    if score >= 80:
        return READY
    if score >= 60:
        return READY_WARN
    return NOT_READY
