"""
shared_services.py — Phase 6.4
Stable public interface for risk_optimisation.

All future phases call these functions — never sub-modules directly.

READ-ONLY. ADVISORY-ONLY.
No orders, portfolio, strategies, signals, risk engine, or position sizes
are ever modified by this module.
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .risk_models import (
    is_enabled, disabled_response, compute_risk_optimisation_score, health_grade,
)

DEFAULT_CAPITAL = 500_000.0


def _get_records() -> list:
    """Load FIFO-matched validated trade records from Phase 6.1."""
    try:
        from paper_trading_validation.validation_collector import collect_all_trade_records
        return collect_all_trade_records()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# GET /api/risk-optimisation/summary
# ---------------------------------------------------------------------------

def get_summary() -> dict:
    """
    Risk Optimisation summary:
    • Risk Optimisation Score (0–100) + grade + trend
    • Snapshot from all sub-analysers
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .capital_analyser import analyse_capital, analyse_position_sizing
        from .concentration_analyser import analyse_concentration
        from .drawdown_analyser import analyse_drawdown
        from .stop_loss_analyser import analyse_stop_loss
        from .target_analyser import analyse_targets

        records = _get_records()
        cap     = analyse_capital(records)
        pos     = analyse_position_sizing(records)
        conc    = analyse_concentration(records)
        dd      = analyse_drawdown(records)
        sl      = analyse_stop_loss(records)
        tgt     = analyse_targets(records)

        score = compute_risk_optimisation_score(
            diversification_score=conc["diversification_score"],
            drawdown_severity=dd["drawdown_severity"],
            capital_efficiency=cap["capital_efficiency"],
            position_sizing_score=pos["position_sizing_score"],
            stop_loss_score=sl["stop_loss_quality_score"],
        )
        grade = health_grade(score)

        # Trend from recent vs historical drawdown
        dd_sev = dd["drawdown_severity"]
        trend = "DECLINING" if dd_sev > 0.50 else "IMPROVING" if dd_sev < 0.15 else "STABLE"

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            "risk_optimisation_score": score,
            "grade": grade,
            "trend": trend,
            # Component scores
            "diversification_score": conc["diversification_score"],
            "drawdown_severity": dd["drawdown_severity"],
            "capital_efficiency": cap["capital_efficiency"],
            "position_sizing_score": pos["position_sizing_score"],
            "stop_loss_quality_score": sl["stop_loss_quality_score"],
            # Key metrics
            "max_drawdown": dd["max_drawdown"],
            "win_rate": tgt["win_rate"],
            "reward_risk_ratio": tgt["reward_risk_ratio"],
            "capital_utilisation_rate": cap["capital_utilisation_rate"],
            "correlation_risk": conc["correlation_risk"],
            "stop_loss_rate": sl["stop_loss_rate"],
            # Position sizing
            "avg_position_size": pos["avg_position_size"],
            "recommended_position_size": pos["recommended_position_size"],
            "max_safe_position": pos["max_safe_position"],
            # Supporting metrics
            "supporting_metrics": {
                "idle_capital": cap["idle_capital"],
                "kelly_fraction": cap["kelly_fraction"],
                "hhi_sector": conc["hhi_sector"],
                "hhi_strategy": conc["hhi_strategy"],
                "total_drawdown_periods": dd["total_drawdown_periods"],
                "avg_drawdown": dd["avg_drawdown"],
                "recovery_efficiency": dd["recovery_efficiency"],
                "target_hit_rate": tgt["target_hit_rate"],
                "sl_premature_exits": sl["premature_exits"],
                "sl_late_exits": sl["late_exits"],
            },
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/risk-optimisation/capital
# ---------------------------------------------------------------------------

def get_capital() -> dict:
    """
    Capital allocation + position sizing + concentration details.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .capital_analyser import analyse_capital, analyse_position_sizing
        from .concentration_analyser import analyse_concentration
        from .stop_loss_analyser import analyse_stop_loss
        from .target_analyser import analyse_targets

        records = _get_records()
        cap  = analyse_capital(records)
        pos  = analyse_position_sizing(records)
        conc = analyse_concentration(records)
        sl   = analyse_stop_loss(records)
        tgt  = analyse_targets(records)

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            "capital_allocation": cap,
            "position_sizing": pos,
            "portfolio_concentration": conc,
            "stop_loss_analysis": sl,
            "target_analysis": tgt,
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/risk-optimisation/drawdown
# ---------------------------------------------------------------------------

def get_drawdown() -> dict:
    """
    Drawdown analysis with equity curve, periods, and recovery metrics.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .drawdown_analyser import analyse_drawdown

        records = _get_records()
        dd = analyse_drawdown(records)

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            **dd,
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/risk-optimisation/stress
# ---------------------------------------------------------------------------

def get_stress() -> dict:
    """
    Advisory stress test simulation across 7 scenarios.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .stress_tester import run_stress_tests

        records = _get_records()
        stress = run_stress_tests(records)

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            **stress,
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/risk-optimisation/recommendations
# ---------------------------------------------------------------------------

def get_recommendations() -> dict:
    """
    Advisory risk optimisation recommendations across 8 dimensions.
    All carry advisory_only=True. Never auto-applied.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .capital_analyser import analyse_capital, analyse_position_sizing
        from .concentration_analyser import analyse_concentration
        from .drawdown_analyser import analyse_drawdown
        from .stop_loss_analyser import analyse_stop_loss
        from .target_analyser import analyse_targets
        from .recommendation_engine import generate_risk_recommendations

        records = _get_records()
        cap  = analyse_capital(records)
        pos  = analyse_position_sizing(records)
        conc = analyse_concentration(records)
        dd   = analyse_drawdown(records)
        sl   = analyse_stop_loss(records)
        tgt  = analyse_targets(records)

        recs = generate_risk_recommendations(cap, pos, conc, dd, sl, tgt)

        explanations = [
            {
                "category": r.category,
                "recommendation": r.recommendation,
                "reason": r.rationale,
                "supporting_metrics": {
                    "max_drawdown": dd["max_drawdown"],
                    "capital_utilisation": cap["capital_utilisation_rate"],
                    "diversification_score": conc["diversification_score"],
                    "reward_risk_ratio": tgt["reward_risk_ratio"],
                },
                "historical_evidence": f"Based on {len(records)} paper trade records.",
                "confidence": r.confidence,
                "suggested_action": r.suggested_value,
                "expected_benefit": r.expected_benefit,
                "risk_reduction": r.risk_reduction,
                "priority": r.priority,
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
            "high_priority": sum(1 for r in recs if r.priority == "HIGH"),
            "medium_priority": sum(1 for r in recs if r.priority == "MEDIUM"),
            "low_priority": sum(1 for r in recs if r.priority == "LOW"),
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
        keys = [k for k in summary if k not in exclude and not isinstance(summary[k], dict)]
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

def get_risk_optimisation_snapshot() -> dict:
    """Flat KPI dict for Executive Dashboard / super-aggregators. Never raises."""
    try:
        records = _get_records()
        from .capital_analyser import analyse_capital, analyse_position_sizing
        from .concentration_analyser import analyse_concentration
        from .drawdown_analyser import analyse_drawdown
        from .stop_loss_analyser import analyse_stop_loss

        cap  = analyse_capital(records)
        pos  = analyse_position_sizing(records)
        conc = analyse_concentration(records)
        dd   = analyse_drawdown(records)
        sl   = analyse_stop_loss(records)

        score = compute_risk_optimisation_score(
            diversification_score=conc["diversification_score"],
            drawdown_severity=dd["drawdown_severity"],
            capital_efficiency=cap["capital_efficiency"],
            position_sizing_score=pos["position_sizing_score"],
            stop_loss_score=sl["stop_loss_quality_score"],
        )
        return {
            "risk_optimisation_score": score,
            "grade": health_grade(score),
            "max_drawdown": dd["max_drawdown"],
            "capital_efficiency": cap["capital_efficiency"],
            "diversification_score": conc["diversification_score"],
            "correlation_risk": conc["correlation_risk"],
        }
    except Exception:
        return {
            "risk_optimisation_score": 0.0,
            "grade": "D",
            "max_drawdown": 0.0,
            "capital_efficiency": 0.0,
            "diversification_score": 0.0,
            "correlation_risk": "LOW",
        }
