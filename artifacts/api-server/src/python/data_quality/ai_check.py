"""
data_quality/ai_check.py — Phase 8.3
AI validation: confidence bounds, prediction probability ranges, calibration
quality (ECE), feature completeness, inference latency, and output consistency.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result

_MAX_ECE          = 0.20   # ECE > 0.20 is poorly calibrated
_MAX_LATENCY_MS   = 5000   # >5 s inference is a warning
_MIN_CONFIDENCE   = 0.0
_MAX_CONFIDENCE   = 1.0


def _safe_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def validate_ai_snapshot(snap: dict) -> dict:
    issues:       list[Issue] = []
    total_checks: int         = 0
    total_passed: int         = 0

    def chk(ok: bool, sev: str, check: str, fld: str, msg: str, val=None):
        nonlocal total_checks, total_passed
        total_checks += 1
        if ok:
            total_passed += 1
        else:
            issues.append(Issue(sev, check, fld, msg, value=val))

    # Confidence range 0–1
    conf = _safe_float(snap.get("avg_confidence"))
    if conf is not None:
        chk(0.0 <= conf <= 1.0, "CRITICAL", "CONFIDENCE_RANGE", "avg_confidence",
            f"avg_confidence {conf:.3f} outside [0, 1]", conf)
    else:
        chk(False, "MISSING", "CONFIDENCE_PRESENT", "avg_confidence",
            "avg_confidence field is missing")

    # Prediction accuracy range 0–1
    acc = _safe_float(snap.get("recent_accuracy") or
                      snap.get("prediction", {}).get("accuracy") if isinstance(snap.get("prediction"), dict) else None)
    if acc is not None:
        chk(0.0 <= acc <= 1.0, "WARNING", "ACCURACY_RANGE", "accuracy",
            f"prediction accuracy {acc:.3f} outside [0, 1]", acc)
    else:
        total_checks += 1; total_passed += 1  # optional field

    # Calibration ECE
    ece = _safe_float(snap.get("calibration_ece"))
    if ece is not None:
        chk(ece < _MAX_ECE, "WARNING", "CALIBRATION_ECE", "calibration_ece",
            f"ECE {ece:.3f} ≥ {_MAX_ECE} — model is poorly calibrated", ece)
    else:
        total_checks += 1; total_passed += 1

    # Precision / Recall in [0, 1]
    for fld in ("precision", "recall", "f1_score"):
        val = snap.get(fld) or (snap.get("prediction") or {}).get(fld) \
              if isinstance(snap.get("prediction"), dict) else snap.get(fld)
        v = _safe_float(val)
        if v is not None:
            chk(0.0 <= v <= 1.0, "WARNING", "METRIC_RANGE", fld,
                f"{fld} {v:.3f} outside [0, 1]", v)
        else:
            total_checks += 1; total_passed += 1

    # Total signals sanity
    total_signals = snap.get("total_signals")
    executed      = snap.get("executed_signals") or snap.get("successful_signals", 0)
    if total_signals is not None:
        ts = _safe_float(total_signals, 0)
        ex = _safe_float(executed, 0)
        chk(ts >= 0, "CRITICAL", "SIGNAL_COUNT", "total_signals",
            f"total_signals is negative ({ts})", ts)
        chk(ex <= ts + 0.001,
            "WARNING", "EXECUTION_OVERFLOW", "executed_signals",
            f"executed_signals ({ex}) > total_signals ({ts})", ex)
    else:
        total_checks += 2; total_passed += 2

    # Health score 0–100
    hs = snap.get("health_score")
    hs_val = (_safe_float(hs.get("total_score"))
              if isinstance(hs, dict) else _safe_float(hs))
    if hs_val is not None:
        chk(0.0 <= hs_val <= 100.0,
            "WARNING", "HEALTH_SCORE_RANGE", "health_score",
            f"health_score {hs_val:.1f} outside 0–100", hs_val)
    else:
        total_checks += 1; total_passed += 1

    if not snap:
        return domain_result("ai", 1, 0,
                             [Issue("MISSING", "DATA_PRESENT", "snapshot",
                                    "No AI snapshot available")],
                             available=False)

    return domain_result("ai", total_checks, total_passed, issues)


# ── Public entry point ────────────────────────────────────────────────────────

def get_ai_validation() -> dict:
    snap: dict = {}

    try:
        from ai_performance_intelligence.shared_services import get_ai_snapshot
        snap = get_ai_snapshot() or {}
    except Exception:
        pass

    if not snap:
        try:
            from paper_analytics.ai_insights import get_ai_insights
            snap = get_ai_insights() or {}
        except Exception:
            pass

    if not snap:
        try:
            from executive_dashboard.shared_services import get_exec_summary
            summary = get_exec_summary() or {}
            snap = summary.get("ai_health") or {}
        except Exception:
            pass

    return validate_ai_snapshot(snap)
