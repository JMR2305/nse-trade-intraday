"""
ai_performance/ai_models.py — Phase 5D.4 data models.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import os as _os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

_ENABLED_VAR = "AI_PERFORMANCE_ENABLED"
_LABEL = "PAPER TRADING / ADVISORY ONLY"

# ── Confidence classification threshold ──────────────────────────────────────
# Signals with confidence >= this are treated as "High confidence" (positive class).
CONFIDENCE_THRESHOLD = 0.60

# ── Confidence buckets ───────────────────────────────────────────────────────
CONFIDENCE_BUCKETS = [
    ("90–100", 0.90, 1.01),
    ("80–90",  0.80, 0.90),
    ("70–80",  0.70, 0.80),
    ("60–70",  0.60, 0.70),
    ("Below 60", 0.0, 0.60),
]

HEALTH_LABELS = [
    (90, "Excellent"),
    (75, "Good"),
    (60, "Fair"),
    (40, "Poor"),
    (0,  "Critical"),
]

TREND_IMPROVING = "Improving"
TREND_STABLE    = "Stable"
TREND_DECLINING = "Declining"


def is_enabled() -> bool:
    return _os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":       "DISABLED",
        "feature_flag": _ENABLED_VAR,
        "message":      f"Set {_ENABLED_VAR}=true to enable Phase 5D.4 AI performance intelligence.",
        "label":        _LABEL,
    }


def health_label(score: float) -> str:
    for threshold, label in HEALTH_LABELS:
        if score >= threshold:
            return label
    return "Critical"


@dataclass
class AISignalRecord:
    """
    One closed round-trip trade enriched with AI-specific classification fields.
    Built by ai_engine.py from strategy_intelligence.strategy_engine.ClosedTrade.
    """
    trade_id:           str   = ""
    symbol:             str   = ""
    sector:             str   = ""
    strategy_name:      str   = ""
    entry_ts:           str   = ""
    exit_ts:            str   = ""
    exit_date:          str   = ""   # YYYY-MM-DD (IST)
    exit_week:          str   = ""   # YYYY-Www
    exit_month:         str   = ""   # YYYY-MM

    pnl:                float = 0.0
    pnl_pct:            float = 0.0
    signal_confidence:  float = 0.0  # 0–1
    confidence_bucket:  str   = ""   # "90–100" etc.
    quality_score:      int   = 0
    market_regime:      str   = ""
    exit_type:          str   = ""
    stop_loss:          float = 0.0
    target:             float = 0.0
    entry_price:        float = 0.0
    exit_price:         float = 0.0

    # Binary classification (confidence threshold = 0.60)
    is_high_confidence: bool = False   # predicted "win"
    is_winner:          bool = False   # actual outcome
    is_tp:              bool = False   # True Positive
    is_fp:              bool = False   # False Positive
    is_tn:              bool = False   # True Negative
    is_fn:              bool = False   # False Negative

    # Recommendation from 5D.3 (if available)
    strategy_recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "trade_id":           self.trade_id,
            "symbol":             self.symbol,
            "sector":             self.sector,
            "strategy_name":      self.strategy_name,
            "exit_date":          self.exit_date,
            "pnl":                round(self.pnl, 2),
            "signal_confidence":  round(self.signal_confidence, 4),
            "confidence_bucket":  self.confidence_bucket,
            "quality_score":      self.quality_score,
            "market_regime":      self.market_regime,
            "is_high_confidence": self.is_high_confidence,
            "is_winner":          self.is_winner,
            "classification":     "TP" if self.is_tp else "FP" if self.is_fp else "TN" if self.is_tn else "FN",
        }


@dataclass
class ConfidenceBucketStats:
    """Stats for one confidence bucket."""
    bucket:     str   = ""
    count:      int   = 0
    winners:    int   = 0
    losers:     int   = 0
    win_rate:   float = 0.0   # actual win rate in this bucket
    avg_pnl:    float = 0.0
    net_pnl:    float = 0.0
    avg_confidence: float = 0.0  # actual avg confidence within bucket

    def to_dict(self) -> dict:
        return {
            "bucket":         self.bucket,
            "count":          self.count,
            "winners":        self.winners,
            "losers":         self.losers,
            "win_rate":       round(self.win_rate, 4),
            "avg_pnl":        round(self.avg_pnl, 2),
            "net_pnl":        round(self.net_pnl, 2),
            "avg_confidence": round(self.avg_confidence, 4),
        }


@dataclass
class CalibrationPoint:
    """One point on the calibration / reliability curve."""
    bucket:              str   = ""
    predicted_confidence: float = 0.0
    actual_success_rate: float = 0.0
    sample_count:        int   = 0
    calibration_error:   float = 0.0   # |predicted - actual|

    def to_dict(self) -> dict:
        return {
            "bucket":               self.bucket,
            "predicted_confidence": round(self.predicted_confidence, 4),
            "actual_success_rate":  round(self.actual_success_rate, 4),
            "sample_count":         self.sample_count,
            "calibration_error":    round(self.calibration_error, 4),
        }


@dataclass
class PredictionMetrics:
    """Binary classification metrics."""
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    precision:         float = 0.0
    recall:            float = 0.0   # True Positive Rate / Sensitivity
    accuracy:          float = 0.0
    false_positive_rate: float = 0.0
    false_negative_rate: float = 0.0
    true_positive_rate:  float = 0.0
    true_negative_rate:  float = 0.0
    f1_score:          float = 0.0
    mcc:               float = 0.0   # Matthews Correlation Coefficient
    balanced_accuracy: float = 0.0

    def to_dict(self) -> dict:
        return {
            "tp": self.tp, "fp": self.fp, "tn": self.tn, "fn": self.fn,
            "precision":           round(self.precision, 4),
            "recall":              round(self.recall, 4),
            "accuracy":            round(self.accuracy, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "false_negative_rate": round(self.false_negative_rate, 4),
            "true_positive_rate":  round(self.true_positive_rate, 4),
            "true_negative_rate":  round(self.true_negative_rate, 4),
            "f1_score":            round(self.f1_score, 4),
            "mcc":                 round(self.mcc, 4),
            "balanced_accuracy":   round(self.balanced_accuracy, 4),
        }


@dataclass
class CalibrationMetrics:
    """Full calibration analysis result."""
    ece:                 float = 0.0   # Expected Calibration Error (0–1, lower better)
    reliability_score:   float = 0.0   # 1 – ECE, scaled 0–100
    confidence_bias:     float = 0.0   # mean(predicted) – mean(actual); + = overconfident
    overconfidence_score: float = 0.0  # % of buckets where predicted > actual
    underconfidence_score: float = 0.0 # % of buckets where predicted < actual
    calibration_curve:   List[CalibrationPoint] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ece":                  round(self.ece, 4),
            "reliability_score":    round(self.reliability_score, 2),
            "confidence_bias":      round(self.confidence_bias, 4),
            "overconfidence_score": round(self.overconfidence_score, 2),
            "underconfidence_score": round(self.underconfidence_score, 2),
            "calibration_curve":    [p.to_dict() for p in self.calibration_curve],
        }


@dataclass
class AIHealthScore:
    """Composite AI Health Score 0–100."""
    total_score:          float = 0.0
    label:                str   = ""
    prediction_accuracy:  float = 0.0   # 25% weight
    calibration_quality:  float = 0.0   # 20% weight
    consistency:          float = 0.0   # 20% weight
    execution_outcome:    float = 0.0   # 15% weight
    risk_awareness:       float = 0.0   # 10% weight
    recommendation_quality: float = 0.0 # 10% weight

    def to_dict(self) -> dict:
        return {
            "total_score":           round(self.total_score, 1),
            "label":                 self.label,
            "components": {
                "prediction_accuracy":   round(self.prediction_accuracy, 1),
                "calibration_quality":   round(self.calibration_quality, 1),
                "consistency":           round(self.consistency, 1),
                "execution_outcome":     round(self.execution_outcome, 1),
                "risk_awareness":        round(self.risk_awareness, 1),
                "recommendation_quality": round(self.recommendation_quality, 1),
            },
            "weights": {
                "prediction_accuracy":   0.25,
                "calibration_quality":   0.20,
                "consistency":           0.20,
                "execution_outcome":     0.15,
                "risk_awareness":        0.10,
                "recommendation_quality": 0.10,
            },
        }
