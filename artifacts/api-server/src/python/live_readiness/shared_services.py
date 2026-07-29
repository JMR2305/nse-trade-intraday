"""
shared_services.py — Phase 6.5
Stable public interface for live_readiness.

READ-ONLY. ADVISORY-ONLY.
This module NEVER enables live trading, places orders, or modifies any
trading engine, portfolio, strategies, signals, AI models, or risk parameters.
"""
from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .readiness_models import (
    is_enabled, disabled_response,
    compute_readiness_score, compute_category_score,
    health_grade, go_no_go, PASS, WARN, FAIL,
    READY, READY_WARN, NOT_READY,
)


# ---------------------------------------------------------------------------
# GET /api/readiness/summary
# ---------------------------------------------------------------------------

def get_summary() -> dict:
    """
    Unified Operational Readiness Score + GO/NO-GO assessment.
    Aggregates all sub-checkers into one top-level dashboard.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .system_health_checker import check_system_health
        from .data_quality_checker   import check_data_quality
        from .recovery_checker       import check_recovery
        from .security_checker       import check_security
        from .config_checker         import check_config
        from .api_health_checker     import check_api_health

        sys_h  = check_system_health()
        data_q = check_data_quality()
        rec    = check_recovery()
        sec    = check_security()
        cfg    = check_config()
        api_h  = check_api_health()

        cat_scores = {
            "SystemHealth": sys_h["score"],
            "DataQuality":  data_q["score"],
            "Recovery":     rec["score"],
            "Security":     sec["score"],
            "Config":       cfg["score"],
            "APIHealth":    api_h["score"],
        }
        score = compute_readiness_score(cat_scores)
        grade = health_grade(score)
        critical = sec.get("critical_failures", 0)
        verdict  = go_no_go(score, critical)

        # Trend: stable — future enhancement with historical score storage
        trend = "STABLE"

        # Strengths / weaknesses
        strengths    = [cat for cat, s in cat_scores.items() if s >= 80]
        weaknesses   = [cat for cat, s in cat_scores.items() if s < 60]
        observations = [cat for cat, s in cat_scores.items() if 60 <= s < 80]

        # All critical (required=True, status=FAIL) checks across all categories
        all_checks = (
            sys_h["checks"] + data_q["checks"] + rec["checks"] +
            sec["checks"] + cfg["checks"] + api_h["checks"]
        )
        blocking = [c for c in all_checks if c["required"] and c["status"] == FAIL]
        warnings = [c for c in all_checks if c["status"] == WARN]

        return {
            "status": "ENABLED",
            "readiness_score": score,
            "grade": grade,
            "trend": trend,
            "verdict": verdict,
            "verdict_short": _verdict_short(verdict),
            "category_scores": cat_scores,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "observations": observations,
            "blocking_issues": [c["label"] + ": " + c["detail"] for c in blocking[:5]],
            "warning_count": len(warnings),
            "critical_failure_count": len(blocking),
            "total_checks": len(all_checks),
            "passed_checks": sum(1 for c in all_checks if c["status"] == PASS),
            # Phase 6.x snapshot summary
            "phase6x_snapshot": _get_phase6x_snapshot(),
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/readiness/system
# ---------------------------------------------------------------------------

def get_system() -> dict:
    """System health + broker readiness + performance metrics."""
    if not is_enabled():
        return disabled_response()
    try:
        from .system_health_checker import check_system_health
        from .config_checker import check_config

        sys_h = check_system_health()
        cfg   = check_config()
        broker = _get_broker_status()

        return {
            "status": "ENABLED",
            "system_health": sys_h,
            "broker_readiness": broker,
            "feature_flags": cfg.get("feature_flags", {}),
            "config_checksum": cfg.get("config_checksum", ""),
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/readiness/data
# ---------------------------------------------------------------------------

def get_data() -> dict:
    """Data quality checks + API health."""
    if not is_enabled():
        return disabled_response()
    try:
        from .data_quality_checker import check_data_quality
        from .api_health_checker   import check_api_health

        dq   = check_data_quality()
        api_h = check_api_health()

        return {
            "status": "ENABLED",
            "data_quality": dq,
            "api_health": api_h,
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/readiness/recovery
# ---------------------------------------------------------------------------

def get_recovery() -> dict:
    """Recovery capability checks."""
    if not is_enabled():
        return disabled_response()
    try:
        from .recovery_checker import check_recovery
        rec = check_recovery()
        return {
            "status": "ENABLED",
            **rec,
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/readiness/security
# ---------------------------------------------------------------------------

def get_security() -> dict:
    """Security readiness + config validation."""
    if not is_enabled():
        return disabled_response()
    try:
        from .security_checker import check_security
        from .config_checker   import check_config

        sec = check_security()
        cfg = check_config()

        return {
            "status": "ENABLED",
            "security": sec,
            "configuration": cfg,
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/readiness/report
# ---------------------------------------------------------------------------

def get_report() -> dict:
    """
    Full consolidated readiness report — all categories + GO/NO-GO + recommendations.
    """
    if not is_enabled():
        return disabled_response()
    try:
        summary = get_summary()
        system  = get_system()
        data    = get_data()
        rec     = get_recovery()
        sec     = get_security()

        recommendations = _build_recommendations(summary, system, data, rec, sec)

        # Future CI/CD integration hook
        cicd_hook = {
            "enabled": False,
            "note": (
                "CI/CD integration is a future-ready hook. When enabled, this report "
                "can be consumed by a deployment pipeline to gate production releases. "
                "Set CI_CD_READINESS_GATE=true to activate."
            ),
            "deployment_checklist_stub": [
                "All required checks PASS",
                "Security score ≥ 85",
                "Data quality score ≥ 75",
                "No FAIL on advisory-only flags",
                "Config checksum matches expected value",
            ],
        }

        return {
            "status": "ENABLED",
            "generated_at": _now_iso(),
            "summary": summary,
            "system_health": system.get("system_health", {}),
            "data_quality": data.get("data_quality", {}),
            "api_health": data.get("api_health", {}),
            "recovery": rec,
            "security": sec.get("security", {}),
            "configuration": sec.get("configuration", {}),
            "recommendations": recommendations,
            "cicd_integration": cicd_hook,
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
        exclude = {"status", "category_scores", "phase6x_snapshot", "advisory_only",
                   "available", "strengths", "weaknesses", "observations",
                   "blocking_issues"}
        keys = [k for k in summary if k not in exclude and not isinstance(summary[k], (dict, list))]
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
        return json.dumps(get_report(), indent=2, default=str)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Flat snapshot for downstream phases
# ---------------------------------------------------------------------------

def get_readiness_snapshot() -> dict:
    """Flat KPI dict for Executive Dashboard / super-aggregators. Never raises."""
    try:
        from .system_health_checker import check_system_health
        from .data_quality_checker   import check_data_quality
        from .security_checker       import check_security
        from .config_checker         import check_config
        from .api_health_checker     import check_api_health
        from .recovery_checker       import check_recovery

        sys_h  = check_system_health()
        data_q = check_data_quality()
        sec    = check_security()
        cfg    = check_config()
        api_h  = check_api_health()
        rec    = check_recovery()

        cat_scores = {
            "SystemHealth": sys_h["score"],
            "DataQuality":  data_q["score"],
            "Recovery":     rec["score"],
            "Security":     sec["score"],
            "Config":       cfg["score"],
            "APIHealth":    api_h["score"],
        }
        score   = compute_readiness_score(cat_scores)
        verdict = go_no_go(score, sec.get("critical_failures", 0))

        return {
            "readiness_score": score,
            "grade": health_grade(score),
            "verdict": verdict,
            "verdict_short": _verdict_short(verdict),
        }
    except Exception:
        return {
            "readiness_score": 0.0,
            "grade": "D",
            "verdict": NOT_READY,
            "verdict_short": "NOT READY",
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_broker_status() -> dict:
    """Check broker connectivity — advisory paper trading only. Never places orders."""
    has_key    = bool(os.environ.get("ZERODHA_API_KEY"))
    has_secret = bool(os.environ.get("ZERODHA_API_SECRET"))
    connected  = False
    detail     = "Credentials not present."

    if has_key and has_secret:
        try:
            # Only check if the kiteconnect module is importable — never authenticate
            import kiteconnect
            detail = "kiteconnect module available; credentials present. Paper trading only."
            connected = True
        except ImportError:
            detail = "Credentials present but kiteconnect not installed."

    return {
        "credentials_present": has_key and has_secret,
        "module_available": connected,
        "detail": detail,
        "paper_trading_only": True,
        "live_orders_never_placed": True,
        "advisory": "This platform is paper-trading only. Live orders are never placed.",
    }


def _get_phase6x_snapshot() -> dict:
    """Collect flat snapshots from all Phase 6.x modules without raising."""
    snapshot: dict = {}
    try:
        from paper_trading_validation.shared_services import get_validation_snapshot
        snapshot["phase_6_1"] = get_validation_snapshot()
    except Exception:
        snapshot["phase_6_1"] = {}
    try:
        from strategy_optimisation.shared_services import get_optimisation_snapshot
        snapshot["phase_6_2"] = get_optimisation_snapshot()
    except Exception:
        snapshot["phase_6_2"] = {}
    try:
        from ai_optimisation.shared_services import get_ai_optimisation_snapshot
        snapshot["phase_6_3"] = get_ai_optimisation_snapshot()
    except Exception:
        snapshot["phase_6_3"] = {}
    try:
        from risk_optimisation.shared_services import get_risk_optimisation_snapshot
        snapshot["phase_6_4"] = get_risk_optimisation_snapshot()
    except Exception:
        snapshot["phase_6_4"] = {}
    return snapshot


def _build_recommendations(summary, system, data, rec, sec) -> list:
    recs = []
    score = summary.get("readiness_score", 0)
    verdict = summary.get("verdict", NOT_READY)

    for issue in summary.get("blocking_issues", []):
        recs.append({
            "priority": "HIGH",
            "category": "Blocking",
            "action": f"Resolve: {issue}",
            "advisory_only": True,
        })

    cat_scores = summary.get("category_scores", {})
    if cat_scores.get("Security", 100) < 70:
        recs.append({
            "priority": "HIGH",
            "category": "Security",
            "action": "Review and resolve security check failures before extended paper trading.",
            "advisory_only": True,
        })
    if cat_scores.get("Config", 100) < 70:
        recs.append({
            "priority": "HIGH",
            "category": "Configuration",
            "action": "Configure all missing environment variables and enable Phase 6.x feature flags.",
            "advisory_only": True,
        })
    if cat_scores.get("DataQuality", 100) < 70:
        recs.append({
            "priority": "MEDIUM",
            "category": "DataQuality",
            "action": "Resolve data quality issues — review trade journal for duplicates or missing fields.",
            "advisory_only": True,
        })
    if cat_scores.get("Recovery", 100) < 70:
        recs.append({
            "priority": "MEDIUM",
            "category": "Recovery",
            "action": "Verify portfolio state recovery and session restoration are working correctly.",
            "advisory_only": True,
        })
    if score >= 80 and verdict == READY:
        recs.append({
            "priority": "INFO",
            "category": "ReadinessStatus",
            "action": "Platform is operationally ready for extended paper trading. Continue monitoring.",
            "advisory_only": True,
        })

    return recs


def _verdict_short(verdict: str) -> str:
    if verdict == READY:      return "READY"
    if verdict == READY_WARN: return "READY (with observations)"
    return "NOT READY"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
