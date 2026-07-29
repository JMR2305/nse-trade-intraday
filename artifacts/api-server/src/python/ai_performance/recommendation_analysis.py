"""
ai_performance/recommendation_analysis.py — Advisory recommendation analysis.

Evaluates Phase 5D.3 strategy-level recommendations against actual trade outcomes.

  "Accepted" recommendation = strategies labelled "Increase Allocation" / "Excellent Consistency"
  "Rejected" / flagged = strategies labelled "Reduce Allocation" / "Underperforming" / "High Drawdown Risk"

Computes:
  • Recommendation success %
  • Recommendation failure %
  • Average profit per accepted recommendation trade
  • Average loss per rejected recommendation trade
  • Accepted recommendation success rate (win rate of trades under accepted strategies)
  • Rejected recommendation success rate (win rate of trades under rejected strategies)

READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import List, Dict, Any, Set

from .ai_models import AISignalRecord

_ACCEPTED_LABELS: Set[str] = {
    "Increase Allocation",
    "Excellent Consistency",
}
_FLAGGED_LABELS: Set[str] = {
    "Reduce Allocation",
    "Underperforming",
    "High Drawdown Risk",
    "Needs Review",
}
_NEUTRAL_LABELS: Set[str] = {
    "Neutral Performance",
    "Promising — More Data Needed",
    "Monitor Closely",
}


def compute_recommendation_analysis(signals: List[AISignalRecord]) -> Dict[str, Any]:
    """Compute recommendation performance breakdown."""
    if not signals:
        return {
            "total_signals":           0,
            "recommendation_success_pct": 0.0,
            "recommendation_failure_pct": 0.0,
            "avg_profit_per_recommendation": 0.0,
            "avg_loss_per_recommendation":   0.0,
            "accepted_win_rate":   0.0,
            "rejected_win_rate":   0.0,
            "neutral_win_rate":    0.0,
            "per_recommendation":  [],
        }

    accepted = [s for s in signals if s.strategy_recommendation in _ACCEPTED_LABELS]
    flagged  = [s for s in signals if s.strategy_recommendation in _FLAGGED_LABELS]
    neutral  = [s for s in signals if s.strategy_recommendation in _NEUTRAL_LABELS]

    winners      = [s for s in signals if s.is_winner]
    losers       = [s for s in signals if not s.is_winner]
    total        = len(signals)

    rec_success_pct = len(winners) / total * 100 if total > 0 else 0.0
    rec_failure_pct = len(losers)  / total * 100 if total > 0 else 0.0

    win_profits = [s.pnl for s in winners]
    loss_losses = [s.pnl for s in losers]

    avg_profit = _stats.mean(win_profits) if win_profits else 0.0
    avg_loss   = _stats.mean(loss_losses) if loss_losses else 0.0

    def _win_rate(group):
        if not group:
            return 0.0
        return sum(1 for s in group if s.is_winner) / len(group) * 100

    accepted_wr = _win_rate(accepted)
    rejected_wr = _win_rate(flagged)
    neutral_wr  = _win_rate(neutral)

    # Per-recommendation breakdown
    by_rec: Dict[str, List[AISignalRecord]] = {}
    for s in signals:
        rec = s.strategy_recommendation or "No Recommendation"
        by_rec.setdefault(rec, []).append(s)

    per_rec_rows = []
    for rec, group in sorted(by_rec.items()):
        w = [g for g in group if g.is_winner]
        l = [g for g in group if not g.is_winner]
        per_rec_rows.append({
            "recommendation": rec,
            "count":          len(group),
            "wins":           len(w),
            "losses":         len(l),
            "win_rate":       round(_win_rate(group), 2),
            "net_pnl":        round(sum(g.pnl for g in group), 2),
            "avg_pnl":        round(_stats.mean(g.pnl for g in group), 2),
            "category":       (
                "accepted" if rec in _ACCEPTED_LABELS else
                "flagged"  if rec in _FLAGGED_LABELS  else
                "neutral"
            ),
        })

    return {
        "total_signals":                  total,
        "recommendation_success_pct":     round(rec_success_pct, 2),
        "recommendation_failure_pct":     round(rec_failure_pct, 2),
        "avg_profit_per_recommendation":  round(avg_profit, 2),
        "avg_loss_per_recommendation":    round(avg_loss, 2),
        "accepted_win_rate":              round(accepted_wr, 2),
        "rejected_win_rate":              round(rejected_wr, 2),
        "neutral_win_rate":               round(neutral_wr, 2),
        "accepted_count":                 len(accepted),
        "flagged_count":                  len(flagged),
        "neutral_count":                  len(neutral),
        "per_recommendation":             per_rec_rows,
    }
