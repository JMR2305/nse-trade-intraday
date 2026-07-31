"""
layout.py — Section ordering and Executive Score computation for Phase 5D.5.
"""
from __future__ import annotations
from .dashboard_models import ExecutiveScore


# ---------------------------------------------------------------------------
# Executive Score derivation
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def compute_executive_score(widgets: dict) -> ExecutiveScore:
    """
    Derive component scores from widget data.
    All inputs are already computed by existing modules — no recalculation here.
    """
    # ── Portfolio Health (25%) ─────────────────────────────────────────────
    port = widgets.get("portfolio_overview", {})
    net_pnl      = port.get("net_pnl", 0.0)
    drawdown     = abs(port.get("drawdown", 0.0))
    win_rate     = port.get("win_rate", 50.0)
    profit_factor = port.get("profit_factor", 1.0)
    # Score = 60 (base) + win_rate delta from 50 + profit_factor bonus - drawdown penalty
    portfolio_score = _clamp(
        60.0
        + (win_rate - 50.0) * 0.5
        + min(profit_factor - 1.0, 2.0) * 10.0
        - drawdown * 1.5
        + (5.0 if net_pnl > 0 else -5.0)
    )

    # ── AI Health (20%) ───────────────────────────────────────────────────
    ai = widgets.get("ai_health", {})
    ai_score = _clamp(ai.get("health_score", 50.0))

    # ── Strategy Health (20%) ─────────────────────────────────────────────
    strat = widgets.get("strategy_overview", {})
    strat_wr  = strat.get("overall_win_rate", 50.0)
    strat_pnl = strat.get("total_net_pnl", 0.0)
    strong_buy = strat.get("strong_buy_count", 0)
    strategy_score = _clamp(
        55.0
        + (strat_wr - 50.0) * 0.6
        + min(strong_buy, 5) * 3.0
        + (5.0 if strat_pnl > 0 else -5.0)
    )

    # ── Execution Quality (15%) ───────────────────────────────────────────
    eq = widgets.get("execution_quality", {})
    execution_score = _clamp(eq.get("execution_score", 50.0))

    # ── Risk (10%) — inverse of alert count and kill-switch ───────────────
    rk = widgets.get("portfolio_risk", {})
    alert_count     = rk.get("alert_count", 0)
    kill_active     = rk.get("kill_switch_active", False)
    utilisation     = rk.get("utilisation", 0.0)
    risk_score = _clamp(
        90.0
        - alert_count * 5.0
        - (30.0 if kill_active else 0.0)
        - max(utilisation - 80.0, 0.0) * 0.5
    )

    # ── System Health (10%) ───────────────────────────────────────────────
    sys_widget = widgets.get("system_health", {})
    app_up  = sys_widget.get("application_health", "UNKNOWN") not in ("DOWN", "ERROR", "CRITICAL")
    db_up   = sys_widget.get("database_status",    "UNKNOWN") not in ("DOWN", "ERROR")
    api_up  = sys_widget.get("api_status",         "UNKNOWN") not in ("DOWN", "ERROR")
    sched_up = sys_widget.get("scheduler_health",  "UNKNOWN") not in ("DOWN", "ERROR")
    system_score = _clamp(
        (25.0 if app_up else 0.0)
        + (25.0 if db_up else 0.0)
        + (25.0 if api_up else 0.0)
        + (25.0 if sched_up else 0.0)
    )

    # ── Paper Analytics (10%) ─────────────────────────────────────────────────
    # Reads from the paper_analytics widget (Phase 8.2).  Falls back to 50.0
    # when the feature flag is off so the composite is never deflated by a
    # disabled module.
    pa = widgets.get("paper_analytics", {})
    if pa.get("available", False):
        pa_analytics_score = _clamp(pa.get("analytics_score", 50.0))
    else:
        pa_analytics_score = 50.0  # neutral default — disabled modules don't penalise

    return ExecutiveScore(
        portfolio_health  = portfolio_score,
        ai_health         = ai_score,
        strategy_health   = strategy_score,
        execution_quality = execution_score,
        risk              = risk_score,
        system_health     = system_score,
        paper_analytics   = pa_analytics_score,
    )


# ---------------------------------------------------------------------------
# Dashboard layout configuration
# ---------------------------------------------------------------------------

SECTIONS = [
    {"id": "system_health",        "title": "System Health",          "order": 1},
    {"id": "portfolio_overview",   "title": "Portfolio Overview",     "order": 2},
    {"id": "ai_health",            "title": "AI Health",              "order": 3},
    {"id": "strategy_overview",    "title": "Strategy Overview",      "order": 4},
    {"id": "execution_quality",    "title": "Execution Quality",      "order": 5},
    {"id": "preopen_intelligence", "title": "Pre-Open Intelligence",  "order": 6},
    {"id": "portfolio_risk",       "title": "Portfolio Risk",         "order": 7},
    {"id": "live_alerts",          "title": "Live Alerts",            "order": 8},
    {"id": "market_snapshot",      "title": "Market Snapshot",        "order": 9},
    {"id": "quick_actions",        "title": "Quick Actions",          "order": 10},
]

QUICK_ACTIONS = [
    {"label": "Open Portfolio",           "href": "/portfolio"},
    {"label": "Open Strategy Intelligence", "href": "/strategy-intelligence"},
    {"label": "Open AI Performance",      "href": "/ai-performance"},
    {"label": "Open Execution Quality",   "href": "/execution-quality"},
    {"label": "Open Pre-Open Intelligence", "href": "/pre-open-intelligence"},
    {"label": "Open Portfolio Risk",      "href": "/portfolio-risk"},
    {"label": "Open Trade Decisions",     "href": "/trade-decisions"},
]
