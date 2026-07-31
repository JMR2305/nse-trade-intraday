"""
risk_validation/models.py — Phase 8.4
Core types and helpers for the Advanced Risk Validation Framework.
READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_FLAG = "RISK_VALIDATION_ENABLED"

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":       "DISABLED",
        "available":    False,
        "advisory_only": True,
        "message":      f"Set {_FLAG}=true to enable",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def risk_grade(score: float) -> str:
    if score >= 92: return "A+"
    if score >= 80: return "A"
    if score >= 68: return "B"
    if score >= 50: return "C"
    return "D"


def risk_trend(scores: list[float]) -> str:
    """Derive trend from ordered scores (oldest→newest). Needs ≥2 values."""
    if len(scores) < 2:
        return "Stable"
    delta = scores[-1] - scores[0]
    if delta > 5:  return "Improving"
    if delta < -5: return "Deteriorating"
    return "Stable"


@dataclass
class Issue:
    severity: str    # CRITICAL | WARNING | INFO
    check:    str    # machine-readable code
    field:    str    # affected field/dimension
    message:  str    # human-readable description
    value:    Optional[float] = None
    category: str             = ""

    def to_dict(self) -> dict:
        d: dict = {
            "severity": self.severity,
            "check":    self.check,
            "field":    self.field,
            "message":  self.message,
        }
        if self.value is not None: d["value"]    = self.value
        if self.category:          d["category"] = self.category
        return d


def domain_result(
    domain:       str,
    checks_run:   int,
    checks_passed: int,
    issues:       list[Issue],
    extra:        Optional[dict] = None,
) -> dict:
    checks_failed = checks_run - checks_passed
    score  = round(checks_passed / max(checks_run, 1) * 100, 1)
    result = {
        "status":        "ENABLED",
        "available":     True,
        "advisory_only": True,
        "domain":        domain,
        "score":         score,
        "grade":         risk_grade(score),
        "checks_run":    checks_run,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "pass_rate":     score,
        "critical_count": sum(1 for i in issues if i.severity == "CRITICAL"),
        "warning_count":  sum(1 for i in issues if i.severity == "WARNING"),
        "issues":        [i.to_dict() for i in issues],
        "generated_at":  _now_iso(),
    }
    if extra:
        result.update(extra)
    return result


def unavailable_result(domain: str, reason: str = "No data available") -> dict:
    return {
        "status":        "ENABLED",
        "available":     False,
        "advisory_only": True,
        "domain":        domain,
        "score":         0.0,
        "grade":         "D",
        "checks_run":    0,
        "checks_passed": 0,
        "checks_failed": 0,
        "critical_count": 0,
        "warning_count":  0,
        "issues":        [],
        "reason":        reason,
        "generated_at":  _now_iso(),
    }
