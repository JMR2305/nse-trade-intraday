"""
strategy_intelligence/recommendations.py — Advisory recommendation engine.

Generates read-only, advisory-only recommendations per strategy.
NEVER modifies, enables, disables, or changes any strategy configuration.
PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from typing import List, Dict, Any

from .strategy_models import StrategyProfile

# Recommendation labels (ordered by priority — first matching rule wins)
_REC_INCREASE   = "Increase Allocation"
_REC_REDUCE     = "Reduce Allocation"
_REC_MONITOR    = "Monitor Closely"
_REC_EXCELLENT  = "Excellent Consistency"
_REC_UNDERPERF  = "Underperforming"
_REC_HIGH_DD    = "High Drawdown Risk"
_REC_NEEDS_REV  = "Needs Review"
_REC_PROMISING  = "Promising — More Data Needed"
_REC_NEUTRAL    = "Neutral Performance"


def _classify(p: StrategyProfile) -> str:
    """Apply rule-based logic to produce a single advisory label."""
    n = p.total_trades

    # Not enough data
    if n == 0:
        return _REC_MONITOR
    if n < 5:
        return _REC_PROMISING

    # Clear winner
    if p.win_rate >= 60 and p.profit_factor >= 2.0 and p.max_drawdown_pct < 10:
        return _REC_INCREASE

    # Excellent consistency
    if p.win_rate >= 55 and p.profit_factor >= 1.5 and p.max_drawdown_pct < 8:
        return _REC_EXCELLENT

    # High drawdown risk
    if p.max_drawdown_pct >= 25:
        return _REC_HIGH_DD

    # Poor performance
    if p.win_rate < 35 or p.profit_factor < 0.8:
        return _REC_UNDERPERF

    # Losing money overall
    if p.net_pnl < 0 and p.profit_factor < 1.0:
        return _REC_REDUCE

    # Needs human review
    if p.win_rate < 45 or p.max_drawdown_pct >= 15:
        return _REC_NEEDS_REV

    # Decent but nothing standout
    if p.win_rate >= 45 and p.profit_factor >= 1.0:
        return _REC_NEUTRAL

    return _REC_MONITOR


def apply_recommendations(profiles: List[StrategyProfile]) -> List[StrategyProfile]:
    """Mutate each profile's recommendation field in-place. Returns the list."""
    for p in profiles:
        p.recommendation = _classify(p)
    return profiles


def get_recommendation_matrix(profiles: List[StrategyProfile]) -> List[Dict[str, Any]]:
    """
    Return a structured recommendation row per strategy, sorted by rank.
    Advisory-only — no executable actions.
    """
    rows = []
    for p in profiles:
        severity = _severity(p.recommendation)
        rows.append({
            "rank":            p.rank,
            "strategy_name":   p.strategy_name,
            "recommendation":  p.recommendation,
            "severity":        severity,
            "rationale":       _rationale(p),
            "win_rate":        round(p.win_rate, 2),
            "profit_factor":   round(p.profit_factor, 2),
            "net_pnl":         round(p.net_pnl, 2),
            "max_drawdown_pct": round(p.max_drawdown_pct, 2),
            "total_trades":    p.total_trades,
        })
    return sorted(rows, key=lambda r: (r["rank"] or 999))


def _severity(rec: str) -> str:
    """Map recommendation to a UI severity level."""
    if rec in (_REC_INCREASE, _REC_EXCELLENT):
        return "success"
    if rec in (_REC_REDUCE, _REC_UNDERPERF, _REC_HIGH_DD):
        return "danger"
    if rec in (_REC_NEEDS_REV, _REC_MONITOR):
        return "warning"
    return "info"


def _rationale(p: StrategyProfile) -> str:
    """One-sentence human-readable rationale for the recommendation."""
    rec = p.recommendation
    n   = p.total_trades
    if n == 0:
        return "No completed trades yet."
    if n < 5:
        return f"Only {n} completed trade(s) — too early to draw conclusions."
    if rec == _REC_INCREASE:
        return (f"Win rate {p.win_rate:.1f}%, PF {p.profit_factor:.2f}, "
                f"drawdown {p.max_drawdown_pct:.1f}% — strong across all criteria.")
    if rec == _REC_EXCELLENT:
        return f"Consistent performer: {p.win_rate:.1f}% win rate, PF {p.profit_factor:.2f}."
    if rec == _REC_HIGH_DD:
        return f"Max drawdown of {p.max_drawdown_pct:.1f}% exceeds acceptable threshold."
    if rec == _REC_UNDERPERF:
        return f"Win rate {p.win_rate:.1f}%, PF {p.profit_factor:.2f} — consistently losing edge."
    if rec == _REC_REDUCE:
        return f"Net P&L negative (₹{p.net_pnl:,.0f}) with PF below 1.0 — consider reducing exposure."
    if rec == _REC_NEEDS_REV:
        return f"Mixed signals: win rate {p.win_rate:.1f}%, drawdown {p.max_drawdown_pct:.1f}%."
    if rec == _REC_PROMISING:
        return f"Early results look {'positive' if p.net_pnl >= 0 else 'mixed'} — needs more trades."
    return f"Win rate {p.win_rate:.1f}%, PF {p.profit_factor:.2f} — performing adequately."
