"""
data_quality/models.py — Phase 8.3
Feature flag, grade helpers, alert dataclasses, and shared constants.

READ-ONLY · ADVISORY-ONLY — never modifies any data source.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# ── Feature flag ──────────────────────────────────────────────────────────────
_FLAG = "DATA_QUALITY_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":        "DISABLED",
        "available":     False,
        "advisory_only": True,
        "message":       f"Set {_FLAG}=true to enable Data Quality.",
    }


# ── Grade helpers ─────────────────────────────────────────────────────────────
def quality_grade(score: float) -> str:
    if score >= 92: return "A+"
    if score >= 80: return "A"
    if score >= 68: return "B"
    if score >= 50: return "C"
    return "D"


# ── Alert severity ────────────────────────────────────────────────────────────
Severity = Literal["CRITICAL", "WARNING", "INFO", "DUPLICATE", "MISSING", "STALE"]

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "DUPLICATE": 2,
                  "MISSING": 3, "STALE": 4, "INFO": 5}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Validation issue ──────────────────────────────────────────────────────────
@dataclass
class Issue:
    severity:  str
    check:     str
    field:     str
    message:   str
    symbol:    str = ""
    value:     Any = None

    def to_dict(self) -> dict:
        d = {
            "severity": self.severity,
            "check":    self.check,
            "field":    self.field,
            "message":  self.message,
        }
        if self.symbol:
            d["symbol"] = self.symbol
        if self.value is not None:
            d["value"] = self.value
        return d


# ── Domain result builder ─────────────────────────────────────────────────────
def domain_result(
    domain:       str,
    checks_run:   int,
    checks_passed:int,
    issues:       list[Issue],
    *,
    available:    bool = True,
    extra:        dict | None = None,
) -> dict:
    """Standardised result dict for every validation domain."""
    pass_rate = round(checks_passed / checks_run * 100, 1) if checks_run else 0.0
    score     = pass_rate          # domain score == pass-rate for simplicity
    return {
        "domain":         domain,
        "status":         "ENABLED",
        "available":      available,
        "advisory_only":  True,
        "checks_run":     checks_run,
        "checks_passed":  checks_passed,
        "checks_failed":  checks_run - checks_passed,
        "pass_rate":      pass_rate,
        "score":          round(score, 1),
        "grade":          quality_grade(score),
        "issues":         [i.to_dict() for i in issues],
        "critical_count": sum(1 for i in issues if i.severity == "CRITICAL"),
        "warning_count":  sum(1 for i in issues if i.severity == "WARNING"),
        "generated_at":   _now_iso(),
        **(extra or {}),
    }


# ── Status constants ──────────────────────────────────────────────────────────
ADVISORY_LABEL = "DATA QUALITY / ADVISORY ONLY"
