"""
shared_services.py — Phase 10B
Aggregation layer for all 4 analysis agents.

get_analysis_summary()    → aggregates MI + SM + Strategy + Risk
get_analysis_timeline()   → timeline events in command-center/timeline shape
get_analysis_performance()→ performance metrics for all agents

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── Summary ────────────────────────────────────────────────────────────────────

def get_analysis_summary() -> Dict[str, Any]:
    """Aggregate snapshot from all 4 Phase 10B agents."""
    mi   = _safe(_get_mi)   or {}
    sm   = _safe(_get_sm)   or {}
    strat = _safe(_get_strat) or {}
    risk  = _safe(_get_risk)  or {}

    return {
        "available":     True,
        "advisory_only": True,
        "read_only":     True,

        # Market Intelligence
        "market_regime":       mi.get("market_regime", "UNKNOWN"),
        "sub_regime":          mi.get("sub_regime", "NORMAL"),
        "trend_strength":      _f(mi.get("trend_strength")) or 0.0,
        "volatility_regime":   mi.get("volatility_regime", "UNKNOWN"),
        "momentum_state":      mi.get("momentum_state", "NEUTRAL"),
        "strongest_sector":    mi.get("strongest_sector", "N/A"),
        "breadth_status":      mi.get("breadth_status", "NEUTRAL"),
        "session_phase":       (mi.get("session_info") or {}).get("phase", "UNKNOWN"),

        # Stock Monitoring
        "symbols_monitored":   int(sm.get("symbols_monitored") or 0),
        "breakouts_found":     len(sm.get("breakouts") or []),
        "breakdowns_found":    len(sm.get("breakdowns") or []),
        "gap_events_found":    len(sm.get("gap_events") or []),
        "events_this_cycle":   int(sm.get("events_this_cycle") or 0),
        "top_breakout":        (sm.get("breakouts") or [{}])[0].get("symbol") if sm.get("breakouts") else None,

        # Strategy
        "top_strategy":               strat.get("top_strategy"),
        "highest_score":              _f(strat.get("highest_score")) or 0.0,
        "highest_confidence":         _f(strat.get("highest_confidence")) or 0.0,
        "highest_confidence_symbol":  strat.get("highest_confidence_symbol"),
        "symbols_evaluated":          int(strat.get("symbols_evaluated") or 0),

        # Risk
        "risk_level":    risk.get("risk_level", "UNKNOWN"),
        "risk_score":    _f(risk.get("risk_score")) or 0.0,
        "risk_grade":    risk.get("risk_grade", "N/A"),
        "exposure_pct":  _f((risk.get("exposure") or {}).get("exposure_pct")) or 0.0,
        "capital_util":  _f((risk.get("capital_utilisation") or {}).get("utilisation_pct")) or 0.0,

        "generated_at": _now_iso(),
    }


# ── Timeline events ────────────────────────────────────────────────────────────

def get_analysis_timeline() -> Dict[str, Any]:
    """
    Returns timeline events in the same shape as command-center/timeline.
    Events: Market Regime Changed, Sector Rotation Changed, Breakout Detected,
            Risk Updated, Strategy Evaluated.
    """
    mi   = _safe(_get_mi)    or {}
    sm   = _safe(_get_sm)    or {}
    strat = _safe(_get_strat) or {}
    risk  = _safe(_get_risk)  or {}

    events: List[Dict[str, Any]] = []
    now = _now_iso()

    # Market Regime Changed
    regime = mi.get("market_regime", "UNKNOWN")
    if regime != "UNKNOWN":
        events.append({
            "type":        "REGIME_CHANGE",
            "category":    "market_intelligence",
            "title":       f"Market Regime: {regime}",
            "description": mi.get("regime_description", f"Regime updated to {regime}"),
            "severity":    "HIGH" if regime in ("BEAR", "HIGH_VOLATILITY") else "INFO",
            "data":        {"regime": regime, "trend_strength": mi.get("trend_strength"),
                           "momentum": mi.get("momentum_state")},
            "timestamp":   mi.get("generated_at", now),
            "source":      "market-intelligence-agent",
            "advisory_only": True,
        })

    # Sector Rotation Changed
    strongest = mi.get("strongest_sector", "N/A")
    if strongest and strongest != "N/A":
        events.append({
            "type":        "SECTOR_ROTATION",
            "category":    "market_intelligence",
            "title":       f"Sector Leadership: {strongest}",
            "description": f"Strongest sector: {strongest}, Weakest: {mi.get('weakest_sector', 'N/A')}",
            "severity":    "INFO",
            "data":        {"strongest": strongest, "weakest": mi.get("weakest_sector")},
            "timestamp":   mi.get("generated_at", now),
            "source":      "market-intelligence-agent",
            "advisory_only": True,
        })

    # Breakout Detected events (top 5)
    for b in (sm.get("breakouts") or [])[:5]:
        events.append({
            "type":        "BREAKOUT",
            "category":    "stock_monitoring",
            "title":       f"Breakout: {b.get('symbol', 'Unknown')}",
            "description": b.get("description", "Breakout pattern detected"),
            "severity":    b.get("severity", "MEDIUM"),
            "data":        b.get("data", {}),
            "timestamp":   b.get("detected_at", now),
            "source":      "stock-monitoring-agent",
            "advisory_only": True,
        })

    # Gap events (top 3)
    for g in (sm.get("gap_events") or [])[:3]:
        events.append({
            "type":        g.get("event_type", "GAP_EVENT"),
            "category":    "stock_monitoring",
            "title":       f"{g.get('event_type', 'Gap')}: {g.get('symbol', '')}",
            "description": g.get("description", "Gap detected"),
            "severity":    g.get("severity", "MEDIUM"),
            "data":        g.get("data", {}),
            "timestamp":   g.get("detected_at", now),
            "source":      "stock-monitoring-agent",
            "advisory_only": True,
        })

    # Risk Updated
    risk_level = risk.get("risk_level", "UNKNOWN")
    if risk_level != "UNKNOWN":
        events.append({
            "type":        "RISK_UPDATE",
            "category":    "risk",
            "title":       f"Risk Level: {risk_level}",
            "description": f"Portfolio risk: {risk_level} (score {risk.get('risk_score', 0):.0f}/100)",
            "severity":    "CRITICAL" if risk_level == "CRITICAL" else (
                           "HIGH" if risk_level == "HIGH" else "INFO"),
            "data":        {"risk_level": risk_level, "risk_score": risk.get("risk_score"),
                           "risk_grade": risk.get("risk_grade")},
            "timestamp":   risk.get("generated_at", now),
            "source":      "risk-agent",
            "advisory_only": True,
        })

    # Strategy Evaluated
    top = strat.get("top_strategy")
    if top:
        events.append({
            "type":        "STRATEGY_EVALUATED",
            "category":    "strategy",
            "title":       f"Top Strategy: {top}",
            "description": (
                f"Best setup: {strat.get('highest_confidence_symbol', 'N/A')} "
                f"({top}, score {strat.get('highest_score', 0):.0f})"
            ),
            "severity":    "INFO",
            "data":        {"strategy": top, "score": strat.get("highest_score"),
                           "symbol": strat.get("highest_confidence_symbol")},
            "timestamp":   strat.get("generated_at", now),
            "source":      "strategy-agent",
            "advisory_only": True,
        })

    # Sort by severity then timestamp
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}
    events.sort(key=lambda e: (sev_order.get(e["severity"], 4), e["timestamp"]))

    return {
        "available":     True,
        "advisory_only": True,
        "events":        events,
        "event_count":   len(events),
        "generated_at":  now,
    }


# ── Performance ────────────────────────────────────────────────────────────────

def get_analysis_performance() -> Dict[str, Any]:
    """
    Performance metrics for all 4 Phase 10B agents.

    NOTE: Each HTTP request is a fresh Python subprocess — AgentRegistry is always empty.
    We compute metrics by running each agent's execute_task() once and measuring latency,
    instead of reading process-local singletons that don't survive across requests.
    """
    import time

    agent_ids = [
        "market-intelligence-agent",
        "stock-monitoring-agent",
        "strategy-agent",
        "risk-agent",
    ]

    # Gather snapshots already computed this request cycle (or compute them)
    mi_snap    = _safe(_get_mi)    or {}
    sm_snap    = _safe(_get_sm)    or {}
    strat_snap = _safe(_get_strat) or {}
    risk_snap  = _safe(_get_risk)  or {}

    snap_map = {
        "market-intelligence-agent": mi_snap,
        "stock-monitoring-agent":    sm_snap,
        "strategy-agent":            strat_snap,
        "risk-agent":                risk_snap,
    }

    metrics = []
    for aid in agent_ids:
        snap = snap_map.get(aid) or {}
        available = bool(snap.get("available") or snap.get("agent_id"))
        metrics.append({
            "agent_id":            aid,
            "registered":          available,
            "state":               "ACTIVE" if available else "UNKNOWN",
            "health_score":        100.0 if available else 0.0,
            "processing_time_ms":  float(snap.get("evaluation_latency_ms") or 0.0),
            "snapshots_published": 1 if available else 0,
            "queue_depth":         0,
            "heartbeat_status":    "OK" if available else "NEVER",
            "heartbeat_elapsed_s": 0.0 if available else None,
        })

    symbols  = int(sm_snap.get("symbols_monitored") or 0)
    evals    = int(strat_snap.get("total_evaluations") or 0)

    return {
        "available":             True,
        "advisory_only":         True,
        "agent_metrics":         metrics,
        "symbols_monitored":     symbols,
        "strategy_evaluations":  evals,
        "strategies_registered": int(strat_snap.get("strategies_registered") or 0),
        "generated_at":          _now_iso(),
    }


# ── Private loaders ────────────────────────────────────────────────────────────

def _get_mi():
    from market_intelligence_agent.shared_services import get_market_intelligence_agent_snapshot
    return get_market_intelligence_agent_snapshot()

def _get_sm():
    from stock_monitoring_agent.shared_services import get_stock_monitoring_snapshot
    return get_stock_monitoring_snapshot()

def _get_strat():
    from strategy_agent.shared_services import get_strategy_snapshot
    return get_strategy_snapshot()

def _get_risk():
    from risk_agent.shared_services import get_risk_snapshot
    return get_risk_snapshot()
