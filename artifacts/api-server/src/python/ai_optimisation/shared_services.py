"""
shared_services.py — Phase 6.3
Stable public interface for ai_optimisation.

All future phases call these functions — never sub-modules directly.

READ-ONLY. ADVISORY-ONLY.
No AI models, trading engine, orders, portfolio, signals, risk engine,
or strategies are ever modified by this module.
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .optimisation_models import (
    is_enabled, disabled_response, compute_ai_optimisation_score, health_grade
)


def _get_records() -> list:
    """Load FIFO-matched validated trade records from Phase 6.1."""
    try:
        from paper_trading_validation.validation_collector import collect_all_trade_records
        return collect_all_trade_records()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# GET /api/ai-optimisation/summary
# ---------------------------------------------------------------------------

def get_summary() -> dict:
    """
    AI Optimisation summary:
    • AI Optimisation Score (0–100) + grade + trend
    • Snapshot of prediction quality
    • Snapshot of calibration
    • Snapshot of false signals
    • Snapshot of drift
    • Snapshot of learning progress
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .performance_analyser import analyse_prediction_quality
        from .calibration_analyser import analyse_calibration
        from .false_signal_analyser import analyse_false_signals
        from .drift_analyser import analyse_drift
        from .learning_analyser import analyse_learning

        records = _get_records()
        perf   = analyse_prediction_quality(records)
        cal    = analyse_calibration(records)
        false_s = analyse_false_signals(records)
        drift  = analyse_drift(records)
        learn  = analyse_learning(records)

        score = compute_ai_optimisation_score(
            accuracy=perf["accuracy"],
            ece=perf["ece"],
            false_signal_rate=false_s["false_signal_rate"],
            learning_velocity=learn["learning_velocity"],
            drift_severity=drift["drift_score"],
        )
        grade = health_grade(score)

        # Trend from learning velocity
        lv = learn["learning_velocity"]
        trend = "IMPROVING" if lv > 0.1 else "DECLINING" if lv < -0.1 else "STABLE"

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            "ai_optimisation_score": score,
            "grade": grade,
            "trend": trend,
            # Prediction quality snapshot
            "accuracy": perf["accuracy"],
            "precision": perf["precision"],
            "recall": perf["recall"],
            "f1_score": perf["f1_score"],
            "avg_confidence": perf["avg_confidence"],
            "ece": perf["ece"],
            "calibration_score": perf["calibration_score"],
            # False signal snapshot
            "false_signal_rate": false_s["false_signal_rate"],
            # Drift snapshot
            "drift_severity": drift["overall_drift_severity"],
            "drift_score": drift["drift_score"],
            # Learning snapshot
            "learning_velocity": learn["learning_velocity"],
            "adaptive_trend": learn["adaptive_trend"],
            # Explainability: supporting metrics
            "supporting_metrics": {
                "prediction_stability": perf["prediction_stability"],
                "recommendation_consistency": perf["recommendation_consistency"],
                "improvement_rate": learn["improvement_rate"],
                "regression_rate": learn["regression_rate"],
            },
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/ai-optimisation/calibration
# ---------------------------------------------------------------------------

def get_calibration() -> dict:
    """
    Confidence band analysis (5 bands) + threshold recommendation.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .calibration_analyser import analyse_calibration
        from .performance_analyser import analyse_prediction_quality

        records = _get_records()
        cal  = analyse_calibration(records)
        perf = analyse_prediction_quality(records)

        # Version comparison stub (future-ready, disabled by default)
        version_comparison = {
            "enabled": False,
            "note": "Version comparison available in future ML retraining integration.",
            "versions": [],
        }

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            **cal,
            "ece": perf["ece"],
            "version_comparison": version_comparison,
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/ai-optimisation/drift
# ---------------------------------------------------------------------------

def get_drift() -> dict:
    """
    Drift analysis across 6 dimensions + false signal analysis.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .drift_analyser import analyse_drift
        from .false_signal_analyser import analyse_false_signals
        from .performance_analyser import analyse_prediction_quality

        records = _get_records()
        drift  = analyse_drift(records)
        false_s = analyse_false_signals(records)
        perf   = analyse_prediction_quality(records)

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            **drift,
            "false_signal_analysis": false_s,
            "prediction_quality": {
                "accuracy": perf["accuracy"],
                "f1_score": perf["f1_score"],
                "prediction_stability": perf["prediction_stability"],
            },
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/ai-optimisation/recommendations
# ---------------------------------------------------------------------------

def get_recommendations() -> dict:
    """
    Advisory optimisation recommendations across 8 dimensions.
    All carry advisory_only=True. Never auto-applied.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .recommendation_engine import generate_recommendations
        from .calibration_analyser import analyse_calibration
        from .performance_analyser import analyse_prediction_quality
        from .learning_analyser import analyse_learning

        records = _get_records()
        cal    = analyse_calibration(records)
        perf   = analyse_prediction_quality(records)
        learn  = analyse_learning(records)

        recs = generate_recommendations(records, cal)

        # Explainable AI — attach context to each recommendation
        explanations = [
            {
                "category": r.category,
                "recommendation": r.recommendation,
                "reason": r.rationale,
                "supporting_metrics": {
                    "accuracy": perf["accuracy"],
                    "calibration_score": perf["calibration_score"],
                    "learning_velocity": learn["learning_velocity"],
                },
                "historical_evidence": f"Based on {len(records)} paper trade records.",
                "confidence": r.confidence,
                "suggested_action": r.suggested_value,
                "expected_benefit": r.expected_benefit,
                "advisory_only": True,
            }
            for r in recs
        ]

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            "recommendations": [r.to_dict() for r in recs],
            "explanations": explanations,
            "total_recommendations": len(recs),
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/ai-optimisation/history
# ---------------------------------------------------------------------------

def get_history() -> dict:
    """
    Rolling learning progress and historical trend.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .learning_analyser import analyse_learning
        from .performance_analyser import analyse_prediction_quality

        records = _get_records()
        learn = analyse_learning(records)
        perf  = analyse_prediction_quality(records)

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            **learn,
            "prediction_quality": {
                "accuracy": perf["accuracy"],
                "f1_score": perf["f1_score"],
                "avg_confidence": perf["avg_confidence"],
            },
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_summary_csv() -> str:
    if not is_enabled():
        return ""
    try:
        import csv, io
        summary = get_summary()
        if summary.get("status") != "ENABLED":
            return ""
        output = io.StringIO()
        exclude = {"status", "supporting_metrics", "advisory_only", "available"}
        keys = [k for k in summary if k not in exclude]
        writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerow({k: summary[k] for k in keys})
        return output.getvalue()
    except Exception:
        return ""


def export_full_json() -> str:
    if not is_enabled():
        return ""
    try:
        import json
        return json.dumps(get_recommendations(), indent=2, default=str)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Flat snapshot for downstream phases
# ---------------------------------------------------------------------------

def get_ai_optimisation_snapshot() -> dict:
    """Flat KPI dict for Executive Dashboard / super-aggregators. Never raises."""
    try:
        records = _get_records()
        from .performance_analyser import analyse_prediction_quality
        from .learning_analyser import analyse_learning
        from .false_signal_analyser import analyse_false_signals

        perf  = analyse_prediction_quality(records)
        learn = analyse_learning(records)
        false_s = analyse_false_signals(records)

        score = compute_ai_optimisation_score(
            accuracy=perf["accuracy"],
            ece=perf["ece"],
            false_signal_rate=false_s["false_signal_rate"],
            learning_velocity=learn["learning_velocity"],
            drift_severity=0.0,
        )
        return {
            "ai_optimisation_score": score,
            "grade": health_grade(score),
            "accuracy": perf["accuracy"],
            "f1_score": perf["f1_score"],
            "false_signal_rate": false_s["false_signal_rate"],
            "adaptive_trend": learn["adaptive_trend"],
        }
    except Exception:
        return {
            "ai_optimisation_score": 0.0,
            "grade": "D",
            "accuracy": 0.0,
            "f1_score": 0.0,
            "false_signal_rate": 0.0,
            "adaptive_trend": "INSUFFICIENT_DATA",
        }
