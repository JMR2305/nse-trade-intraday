"""
dashboard_models.py — Data models and feature flag for Phase 5D.5.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Any

_LABEL = "PAPER TRADING / ADVISORY ONLY"
_FLAG  = "EXECUTIVE_DASHBOARD_ENABLED"


def is_enabled() -> bool:
    return os.getenv(_FLAG, "false").lower() in {"true", "1", "yes"}


def disabled_response() -> dict:
    return {"status": "DISABLED", "feature_flag": _FLAG, "label": _LABEL}


# ---------------------------------------------------------------------------
# Executive Score weights (must sum to 1.0)
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {
    "portfolio_health":   0.25,
    "ai_health":          0.20,
    "strategy_health":    0.20,
    "execution_quality":  0.15,
    "risk":               0.10,
    "system_health":      0.10,
}


def score_label(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    if score >= 40:
        return "Poor"
    return "Critical"


@dataclass
class ExecutiveScore:
    portfolio_health:   float = 50.0
    ai_health:          float = 50.0
    strategy_health:    float = 50.0
    execution_quality:  float = 50.0
    risk:               float = 50.0
    system_health:      float = 50.0

    @property
    def total(self) -> float:
        return round(
            self.portfolio_health  * SCORE_WEIGHTS["portfolio_health"]
            + self.ai_health       * SCORE_WEIGHTS["ai_health"]
            + self.strategy_health * SCORE_WEIGHTS["strategy_health"]
            + self.execution_quality * SCORE_WEIGHTS["execution_quality"]
            + self.risk            * SCORE_WEIGHTS["risk"]
            + self.system_health   * SCORE_WEIGHTS["system_health"],
            1,
        )

    @property
    def label(self) -> str:
        return score_label(self.total)

    def to_dict(self) -> dict:
        return {
            "total":              self.total,
            "label":              self.label,
            "components": {
                "portfolio_health":  round(self.portfolio_health, 1),
                "ai_health":         round(self.ai_health, 1),
                "strategy_health":   round(self.strategy_health, 1),
                "execution_quality": round(self.execution_quality, 1),
                "risk":              round(self.risk, 1),
                "system_health":     round(self.system_health, 1),
            },
            "weights": SCORE_WEIGHTS,
        }
