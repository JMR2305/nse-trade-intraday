"""
decision_lineage.py — Phase 10E
End-to-end decision lineage for recommendations.

READ-ONLY · ADVISORY-ONLY
No model retraining. No parameter tuning. No automatic optimisation.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_call(fn_path: str) -> Optional[Dict[str, Any]]:
    """Import and call a shared_services function, returning None on failure."""
    try:
        parts  = fn_path.rsplit(".", 1)
        mod    = __import__(parts[0], fromlist=[parts[1]])
        fn     = getattr(mod, parts[1])
        return fn()
    except Exception:
        return None


def build_decision_lineage() -> Dict[str, Any]:
    """
    Reconstruct the end-to-end lineage for the most recent recommendation.
    Aggregates contributions from all 10 agents in the pipeline.
    """
    t0 = time.perf_counter()

    # Pull current snapshots from each layer
    market_snap  = _safe_call("market_data_agent.shared_services.get_market_data_snapshot")
    research_snap = _safe_call("research_agent.shared_services.get_research_snapshot")
    mi_snap      = _safe_call("market_intelligence_agent.shared_services.get_market_intelligence_agent_snapshot")
    monitoring_snap = _safe_call("stock_monitoring_agent.shared_services.get_stock_monitoring_snapshot")
    strategy_snap = _safe_call("strategy_agent.shared_services.get_strategy_snapshot")
    risk_snap    = _safe_call("risk_agent.shared_services.get_risk_snapshot")
    decision_snap = _safe_call("ai_decision_agent.shared_services.get_ai_decision_snapshot")
    execution_snap = _safe_call("execution_agent.shared_services.get_execution_snapshot")
    learning_snap = _safe_call("learning_agent.shared_services.get_learning_snapshot")
    knowledge_snap = _safe_call("knowledge_agent.shared_services.get_knowledge_snapshot")

    def _snap_summary(snap: Optional[Dict], label: str, key_fields: List[str]) -> Dict[str, Any]:
        if not snap or not snap.get("available"):
            return {"source": label, "status": "UNAVAILABLE", "contribution": "No data available"}
        out: Dict[str, Any] = {"source": label, "status": "AVAILABLE"}
        for kf in key_fields:
            val = snap.get(kf)
            if val is not None:
                out[kf] = val
        return out

    # Most recent recommendation (from AI decision snapshot)
    top_rec:   Optional[Dict] = None
    rec_count: int            = 0
    if decision_snap and decision_snap.get("available"):
        recs = decision_snap.get("recommendations") or decision_snap.get("top_recommendations", [])
        if recs:
            top_rec   = recs[0]
            rec_count = len(recs)

    lineage_steps: List[Dict[str, Any]] = [
        {
            "step":         1,
            "agent":        "market_data",
            "label":        "Originating Market Snapshot",
            **_snap_summary(market_snap, "Market Data Agent", [
                "symbols_tracked", "market_status", "data_freshness_s",
            ]),
        },
        {
            "step":         2,
            "agent":        "research",
            "label":        "Research Contribution",
            **_snap_summary(research_snap, "Research Agent", [
                "total_reports", "fresh_reports", "avg_confidence",
            ]),
        },
        {
            "step":         3,
            "agent":        "market_intelligence",
            "label":        "Market Intelligence Contribution",
            **_snap_summary(mi_snap, "Market Intelligence Agent", [
                "current_regime", "regime_strength", "overall_market_health",
            ]),
        },
        {
            "step":         4,
            "agent":        "stock_monitoring",
            "label":        "Stock Monitoring Contribution",
            **_snap_summary(monitoring_snap, "Stock Monitoring Agent", [
                "monitored_count", "alert_count", "events_today",
            ]),
        },
        {
            "step":         5,
            "agent":        "strategy",
            "label":        "Strategy Contribution",
            **_snap_summary(strategy_snap, "Strategy Agent", [
                "active_strategies", "top_strategy", "avg_strategy_confidence",
            ]),
        },
        {
            "step":         6,
            "agent":        "risk",
            "label":        "Risk Contribution",
            **_snap_summary(risk_snap, "Risk Agent", [
                "risk_level", "risk_score", "exposure_pct",
            ]),
        },
        {
            "step":         7,
            "agent":        "ai_decision",
            "label":        "AI Decision Reasoning",
            "status":       "AVAILABLE" if top_rec else "NO_RECOMMENDATIONS",
            "source":       "AI Decision Agent",
            "recommendation_count": rec_count,
            "top_symbol":   (top_rec or {}).get("symbol", "—"),
            "top_action":   (top_rec or {}).get("decision_type", "—"),
            "top_confidence": (top_rec or {}).get("confidence", 0),
            "explanation":  (top_rec or {}).get("explanation", "No explanation available"),
        },
        {
            "step":         8,
            "agent":        "execution",
            "label":        "Execution Validation",
            **_snap_summary(execution_snap, "Execution Agent", [
                "execution_health", "pending_count", "validation_checks",
            ]),
        },
        {
            "step":         9,
            "agent":        "learning",
            "label":        "Learning Outcome",
            **_snap_summary(learning_snap, "Learning Agent", [
                "recommendation_accuracy", "strategy_win_rate", "confidence_calibration",
            ]),
        },
        {
            "step":         10,
            "agent":        "knowledge",
            "label":        "Knowledge References",
            **_snap_summary(knowledge_snap, "Knowledge Agent", [
                "knowledge_base_size", "trades_learned", "patterns_identified",
            ]),
        },
    ]

    available_steps = sum(1 for s in lineage_steps if s.get("status") == "AVAILABLE")
    traceability_pct = round(available_steps / len(lineage_steps) * 100, 1)

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "advisory_only":       True,
        "read_only":           True,
        "lineage_steps":       lineage_steps,
        "step_count":          len(lineage_steps),
        "available_steps":     available_steps,
        "traceability_pct":    traceability_pct,
        "top_recommendation":  top_rec,
        "lineage_latency_ms":  latency_ms,
        "generated_at":        _now_iso(),
    }
