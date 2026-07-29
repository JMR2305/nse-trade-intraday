"""
ai_performance/shared_services.py — Stable shared service interface.

THIS IS THE CANONICAL ENTRY POINT for Phase 5D.5 (Executive Dashboard).

Phase 5D.5 MUST import from this module instead of recalculating AI metrics.

Stable public API (do not rename without versioning):

  get_ai_summary()           → dict   (all top-level KPIs in one call)
  get_confidence_data()      → dict
  get_calibration_data()     → dict
  get_prediction_data()      → dict
  get_recommendation_data()  → dict
  get_learning_data()        → dict
  get_health_score()         → dict   (AIHealthScore for embedding in executive view)
  get_ai_snapshot()          → dict   (minimal flat dict for executive dashboard tile)

All functions check is_enabled() first and return disabled_response() when off.
All functions are read-only and advisory-only.
"""
from __future__ import annotations

from typing import Dict, Any

from .ai_models import (
    is_enabled, disabled_response, _LABEL, AIHealthScore, health_label,
    CONFIDENCE_THRESHOLD,
)

import statistics as _stats


def _compute_all() -> Dict[str, Any]:
    """
    Full computation pipeline — called once per request.

    1. Load AI signal records (wraps 5D.3 ClosedTrade FIFO data)
    2. Compute all AI-specific analytics
    3. Return a single dict with all sub-module results
    """
    from .ai_engine            import load_all_data
    from .confidence_analysis  import compute_confidence_distribution, compute_confidence_vs_regime, compute_confidence_vs_sector
    from .calibration          import compute_calibration
    from .prediction_analysis  import compute_prediction_metrics
    from .recommendation_analysis import compute_recommendation_analysis
    from .learning_analysis    import compute_learning_analysis

    data     = load_all_data()
    signals  = data["signals"]
    profiles = data["profiles"]

    conf_dist  = compute_confidence_distribution(signals)
    conf_regime = compute_confidence_vs_regime(signals)
    conf_sector = compute_confidence_vs_sector(signals)
    calibration = compute_calibration(signals)
    pred        = compute_prediction_metrics(signals)
    rec_analysis = compute_recommendation_analysis(signals)
    learning     = compute_learning_analysis(signals)

    health = _compute_health_score(signals, pred, calibration, rec_analysis, profiles)

    return {
        "signals":       signals,
        "profiles":      profiles,
        "conf_dist":     conf_dist,
        "conf_regime":   conf_regime,
        "conf_sector":   conf_sector,
        "calibration":   calibration,
        "pred":          pred,
        "rec_analysis":  rec_analysis,
        "learning":      learning,
        "health":        health,
    }


def _compute_health_score(signals, pred, calibration, rec_analysis, profiles) -> AIHealthScore:
    """
    AI Health Score (0–100) using weighted components.

    Prediction Accuracy  25% — balanced_accuracy * 100
    Calibration Quality  20% — reliability_score (already 0–100)
    Consistency          20% — stdev of daily win rates → converted to score
    Execution Outcome    15% — avg quality_score across signals
    Risk Awareness       10% — % of trades that hit TARGET (vs SL / other)
    Recommendation       10% — accepted strategies' win rate vs overall
    """
    h = AIHealthScore()

    n = len(signals)
    if n == 0:
        h.label = health_label(0.0)
        return h

    # 1. Prediction Accuracy (25%)
    h.prediction_accuracy = round(pred.balanced_accuracy * 100, 2)

    # 2. Calibration Quality (20%)
    h.calibration_quality = round(calibration.reliability_score, 2)

    # 3. Consistency (20%) — lower stdev in daily accuracies = more consistent
    from .learning_analysis import compute_learning_analysis
    learning = compute_learning_analysis(signals)
    daily = [d["accuracy"] for d in learning["daily"] if d["count"] > 0]
    if len(daily) >= 2:
        stdev = _stats.stdev(daily)
        # stdev of 0 = 100 points; stdev of 50 = 0 points
        h.consistency = round(max(0.0, 100.0 - stdev * 2), 2)
    elif len(daily) == 1:
        h.consistency = round(daily[0], 2)   # single day = no variance data
    else:
        h.consistency = 50.0  # neutral when no daily data

    # 4. Execution Outcome (15%) — avg quality score (already 0–100)
    scores = [s.quality_score for s in signals if s.quality_score > 0]
    h.execution_outcome = round(_stats.mean(scores), 2) if scores else 50.0

    # 5. Risk Awareness (10%) — % of trades exiting via TARGET_HIT
    target_hits = sum(1 for s in signals if s.exit_type in ("TARGET_HIT", "TARGET"))
    h.risk_awareness = round(target_hits / n * 100, 2)

    # 6. Recommendation Quality (10%) — accepted strategies' win rate normalised
    h.recommendation_quality = round(
        min(rec_analysis.get("accepted_win_rate", 50.0), 100.0), 2
    )

    # Weighted composite
    weights = (0.25, 0.20, 0.20, 0.15, 0.10, 0.10)
    components = (
        h.prediction_accuracy,
        h.calibration_quality,
        h.consistency,
        h.execution_outcome,
        h.risk_awareness,
        h.recommendation_quality,
    )
    h.total_score = round(sum(c * w for c, w in zip(components, weights)), 1)
    h.label = health_label(h.total_score)
    return h


# ── Stable public API ─────────────────────────────────────────────────────────

def get_ai_summary() -> dict:
    """All top-level KPIs in one call — primary endpoint for the dashboard."""
    if not is_enabled():
        return disabled_response()
    try:
        d = _compute_all()
        signals  = d["signals"]
        n        = len(signals)
        winners  = sum(1 for s in signals if s.is_winner)
        high_conf = sum(1 for s in signals if s.is_high_confidence)

        return {
            "status":              "ENABLED",
            "label":               _LABEL,
            "total_signals":       n,
            "executed_signals":    n,                  # all closed trades = executed
            "ignored_signals":     0,                  # not observable from trade history
            "successful_signals":  winners,
            "failed_signals":      n - winners,
            "signal_success_rate": round(winners / n * 100, 2) if n > 0 else 0.0,
            "high_confidence_pct": round(high_conf / n * 100, 2) if n > 0 else 0.0,
            "avg_confidence":      round(_stats.mean(s.signal_confidence for s in signals), 4) if n > 0 else 0.0,
            "health_score":        d["health"].to_dict(),
            "prediction":          d["pred"].to_dict(),
            "calibration_ece":     round(d["calibration"].ece, 4),
            "calibration_reliability": round(d["calibration"].reliability_score, 2),
            "trend_direction":     d["learning"]["trend_direction"],
            "accuracy_delta":      d["learning"]["accuracy_delta"],
            "recent_accuracy":     d["learning"]["recent_accuracy"],
            "confidence_distribution": d["conf_dist"],
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_confidence_data() -> dict:
    """Confidence distribution + cross-analyses."""
    if not is_enabled():
        return disabled_response()
    try:
        d = _compute_all()
        return {
            "status":           "ENABLED",
            "label":            _LABEL,
            "distribution":     d["conf_dist"],
            "vs_regime":        d["conf_regime"],
            "vs_sector":        d["conf_sector"],
            "confidence_threshold": CONFIDENCE_THRESHOLD,
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_calibration_data() -> dict:
    """Calibration curve + metrics."""
    if not is_enabled():
        return disabled_response()
    try:
        d = _compute_all()
        return {
            "status":  "ENABLED",
            "label":   _LABEL,
            **d["calibration"].to_dict(),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_prediction_data() -> dict:
    """Binary classification metrics (precision, recall, F1, MCC…)."""
    if not is_enabled():
        return disabled_response()
    try:
        d = _compute_all()
        return {
            "status": "ENABLED",
            "label":  _LABEL,
            **d["pred"].to_dict(),
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "classification_note":  (
                "TP = high_confidence + winner, FP = high_confidence + loser, "
                "TN = low_confidence + loser, FN = low_confidence + winner. "
                f"Threshold = {CONFIDENCE_THRESHOLD:.0%}."
            ),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_recommendation_data() -> dict:
    """Recommendation success/failure analysis."""
    if not is_enabled():
        return disabled_response()
    try:
        d = _compute_all()
        return {
            "status": "ENABLED",
            "label":  _LABEL,
            **d["rec_analysis"],
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_learning_data() -> dict:
    """Learning / improvement trend analysis."""
    if not is_enabled():
        return disabled_response()
    try:
        d = _compute_all()
        return {
            "status": "ENABLED",
            "label":  _LABEL,
            **d["learning"],
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_health_score() -> dict:
    """AI Health Score (0–100) with component breakdown."""
    if not is_enabled():
        return disabled_response()
    try:
        d = _compute_all()
        return {
            "status": "ENABLED",
            "label":  _LABEL,
            **d["health"].to_dict(),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_ai_snapshot() -> dict:
    """
    Minimal flat dict for Phase 5D.5 Executive Dashboard tile.
    Single call, no fan-out needed from the executive view.
    """
    if not is_enabled():
        return disabled_response()
    try:
        d = _compute_all()
        h = d["health"]
        p = d["pred"]
        return {
            "status":               "ENABLED",
            "label":                _LABEL,
            "health_score":         h.total_score,
            "health_label":         h.label,
            "prediction_accuracy":  round(p.accuracy * 100, 2),
            "balanced_accuracy":    round(p.balanced_accuracy * 100, 2),
            "precision":            round(p.precision * 100, 2),
            "recall":               round(p.recall * 100, 2),
            "f1_score":             round(p.f1_score, 4),
            "avg_confidence":       round(
                _stats.mean(s.signal_confidence for s in d["signals"]) * 100, 2
            ) if d["signals"] else 0.0,
            "calibration_ece":      d["calibration"].ece,
            "trend_direction":      d["learning"]["trend_direction"],
            "accuracy_delta":       d["learning"]["accuracy_delta"],
            "total_signals":        len(d["signals"]),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}
