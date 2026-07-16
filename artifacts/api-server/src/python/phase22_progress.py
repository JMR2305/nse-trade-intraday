"""
phase22_progress.py — Phase 22 evidence progress panel + milestones.

Milestones are informational only: reaching a trade-count threshold NEVER
labels the model "validated" by itself.

PAPER TRADING / RESEARCH ONLY. No live orders anywhere.
"""

from __future__ import annotations

from typing import Any, Dict, List

MILESTONES = [
    (10, "Smoke-test evidence"),
    (30, "Early review"),
    (50, "Initial calibration review"),
    (100, "Meaningful challenger evaluation"),
    (250, "Intermediate validation"),
    (500, "Advanced validation"),
]

_BULL = ("BULLISH", "STRONG_BULLISH", "UPTREND")
_BEAR = ("BEARISH", "STRONG_BEARISH", "DOWNTREND")
_RANGE = ("RANGE", "RANGE_BOUND", "SIDEWAYS", "NEUTRAL")
_HIVOL = ("HIGH_VOLATILITY", "VOLATILE")
_LOVOL = ("LOW_VOLATILITY", "QUIET")


def _bucket(regime: str) -> str:
    r = (regime or "").upper().replace(" ", "_").replace("-", "_")
    if any(k in r for k in _HIVOL):
        return "high_volatility"
    if any(k in r for k in _LOVOL):
        return "low_volatility"
    if any(k in r for k in _BULL):
        return "bullish"
    if any(k in r for k in _BEAR):
        return "bearish"
    if any(k in r for k in _RANGE):
        return "range_bound"
    return "unknown"


def get_progress() -> Dict[str, Any]:
    from phase22_evidence import list_evidence
    rows = list_evidence(limit=5000)

    from phase20_executor import get_ledger
    ledger = get_ledger(500)
    completed = [t for t in ledger if t.get("status") == "CLOSED"]
    open_trades = [t for t in ledger if t.get("status") in ("OPEN", "EXIT_PENDING")]

    regime_counts: Dict[str, int] = {}
    for t in completed:
        regime_counts[_bucket(str(t.get("regime") or ""))] = \
            regime_counts.get(_bucket(str(t.get("regime") or "")), 0) + 1

    strategies = sorted({str(t.get("strategy_name") or t.get("strategy_id") or "")
                         for t in ledger if t.get("strategy_name") or t.get("strategy_id")})
    sectors = sorted({str(t.get("sector") or "") for t in ledger if t.get("sector")})

    n_done = len(completed)
    milestones: List[Dict[str, Any]] = []
    next_milestone = None
    for count, label in MILESTONES:
        reached = n_done >= count
        m = {"trades": count, "label": label, "reached": reached,
             "remaining": max(0, count - n_done)}
        milestones.append(m)
        if not reached and next_milestone is None:
            next_milestone = m

    return {
        "completed_paper_trades": n_done,
        "open_paper_trades": len(open_trades),
        "blocked_candidates": len([r for r in rows
                                   if r.get("eligibility_result") == "BLOCKED"]),
        "total_evaluated_candidates": len(rows),
        "distinct_trading_days": len({str(r.get("recorded_at") or "")[:10]
                                      for r in rows} |
                                     {str(t.get("fill_ts") or "")[:10]
                                      for t in ledger if t.get("fill_ts")}),
        "regime_trade_counts": {
            "bullish": regime_counts.get("bullish", 0),
            "bearish": regime_counts.get("bearish", 0),
            "range_bound": regime_counts.get("range_bound", 0),
            "high_volatility": regime_counts.get("high_volatility", 0),
            "low_volatility": regime_counts.get("low_volatility", 0),
            "unknown": regime_counts.get("unknown", 0),
        },
        "strategy_coverage": strategies,
        "sector_coverage": sectors,
        "milestones": milestones,
        "next_milestone": next_milestone,
        "validation_note": ("Reaching a trade-count milestone does NOT by "
                            "itself mean the model is validated. Statistical "
                            "review is still required at each milestone."),
        "label": "PAPER / RESEARCH ONLY",
    }
