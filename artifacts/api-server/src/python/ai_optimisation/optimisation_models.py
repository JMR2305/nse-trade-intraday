"""
optimisation_models.py — Phase 6.3
Feature flag, scoring helpers, and dataclasses.

READ-ONLY. ADVISORY-ONLY.
No AI models, trading engine, orders, portfolio, signals, risk engine,
or strategies are ever modified by this module.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return os.environ.get("AI_OPTIMISATION_ENABLED", "false").lower() == "true"


def disabled_response() -> dict:
    return {
        "status": "DISABLED",
        "message": "Set AI_OPTIMISATION_ENABLED=true to enable.",
    }


# ---------------------------------------------------------------------------
# Health score helpers
# ---------------------------------------------------------------------------

def health_grade(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def compute_ai_optimisation_score(
    accuracy: float,         # 0–1
    ece: float,              # expected calibration error 0–1 (lower = better)
    false_signal_rate: float, # 0–1 (lower = better)
    learning_velocity: float, # -1 to +1
    drift_severity: float,    # 0–1 (lower = better)
) -> float:
    """
    Weighted AI Optimisation Score 0–100.
    Accuracy 30%, Calibration 20%, False signal 20%, Learning 15%, Drift 15%.
    """
    cal_score = max(0.0, 1.0 - ece * 2.0)          # ECE penalty amplified
    false_score = max(0.0, 1.0 - false_signal_rate)
    learn_score = (learning_velocity + 1.0) / 2.0   # normalise -1..+1 → 0..1
    drift_score = max(0.0, 1.0 - drift_severity)

    raw = (
        accuracy * 30.0
        + cal_score * 20.0
        + false_score * 20.0
        + learn_score * 15.0
        + drift_score * 15.0
    )
    return round(min(max(raw, 0.0), 100.0), 2)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ConfidenceBand:
    band: str              # e.g. "60–80%"
    min_conf: float
    max_conf: float
    trades: int
    win_rate: float
    avg_return_pct: float
    avg_risk: float
    prediction_error: float   # |confidence − win_rate|

    def to_dict(self) -> dict:
        return {
            "band": self.band,
            "min_conf": self.min_conf,
            "max_conf": self.max_conf,
            "trades": self.trades,
            "win_rate": round(self.win_rate, 4),
            "avg_return_pct": round(self.avg_return_pct, 4),
            "avg_risk": round(self.avg_risk, 4),
            "prediction_error": round(self.prediction_error, 4),
        }


@dataclass
class FalseSignal:
    signal_type: str       # FALSE_BUY / FALSE_SELL / LATE / EARLY / HIGH_CONF_LOSS / LOW_CONF_WIN
    count: int
    pct_of_total: float
    avg_loss_pct: float
    description: str
    examples: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type,
            "count": self.count,
            "pct_of_total": round(self.pct_of_total, 4),
            "avg_loss_pct": round(self.avg_loss_pct, 4),
            "description": self.description,
            "examples": self.examples[:3],
        }


@dataclass
class DriftMetric:
    dimension: str         # Prediction / Confidence / Strategy / Regime / Sector / Performance
    baseline: float
    recent: float
    drift: float           # recent - baseline (signed)
    severity: str          # LOW / MEDIUM / HIGH
    advisory: str

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "baseline": round(self.baseline, 4),
            "recent": round(self.recent, 4),
            "drift": round(self.drift, 4),
            "severity": self.severity,
            "advisory": self.advisory,
        }


@dataclass
class OptimisationRecommendation:
    category: str          # ConfidenceThreshold / SignalFilter / RegimeSelection / etc.
    recommendation: str
    rationale: str
    current_value: str
    suggested_value: str
    confidence: str        # HIGH / MEDIUM / LOW
    expected_benefit: str
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "current_value": self.current_value,
            "suggested_value": self.suggested_value,
            "confidence": self.confidence,
            "expected_benefit": self.expected_benefit,
            "advisory_only": True,
        }
