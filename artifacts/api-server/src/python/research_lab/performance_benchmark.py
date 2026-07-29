"""Phase 7.5 – Performance benchmarking (advisory comparison, read-only)."""
from __future__ import annotations
from typing import Any, Dict, List

from .models import BenchmarkComparison

# Simulated NIFTY 50 baseline metrics
_NIFTY_BASELINE = {
    "annual_return_pct": 12.0,
    "max_drawdown_pct":  18.0,
    "sharpe_ratio":       0.9,
    "win_rate":           0.55,
}


def compute_benchmark(
    signals: List[Dict[str, Any]],
    risk_snap: Dict[str, Any],
    performance_snap: Dict[str, Any],
    explainable_snap: Dict[str, Any],
) -> BenchmarkComparison:
    """
    Compare research score vs baseline (NIFTY) vs market vs paper trading results.
    All values are advisory estimates.
    """
    # Research score from explainable AI
    res_score = float(explainable_snap.get("explainable_ai_score", 50.0) or 50.0)

    # Baseline: normalise NIFTY metrics to 0-100
    baseline_score = min(100.0, (
        _NIFTY_BASELINE["win_rate"] * 40 +
        (100 - _NIFTY_BASELINE["max_drawdown_pct"]) * 0.3 +
        _NIFTY_BASELINE["sharpe_ratio"] * 20 +
        _NIFTY_BASELINE["annual_return_pct"] * 0.5
    ))

    # Market score from Phase 7.1
    market_score = float(performance_snap.get("market_health_score", 50.0) or 50.0)

    # Paper score from portfolio performance
    paper_win_rate = float(performance_snap.get("win_rate", 0.5) or 0.5)
    paper_dd       = float(performance_snap.get("max_drawdown", 0.08) or 0.08)
    paper_dd_pct   = paper_dd * 100 if paper_dd < 1.0 else paper_dd
    paper_score    = min(100.0, (
        paper_win_rate * 50 +
        (100 - paper_dd_pct) * 0.3 +
        res_score * 0.2
    ))

    # Relative alpha: research vs baseline
    rel_alpha = round(res_score - baseline_score, 2)

    # Risk-adjusted return: normalised Sharpe proxy
    risk_opt_score = float(risk_snap.get("risk_optimisation_score", 60.0) or 60.0)
    risk_adj       = round(min(100.0, res_score * (risk_opt_score / 100.0)), 2)

    # Consistency: rolling win-rate stability proxy
    conf_vals = []
    for s in signals:
        c = float(s.get("confidence", 0.5) or 0.5)
        conf_vals.append(c * 100 if c <= 1.0 else c)
    consistency = round(sum(conf_vals) / len(conf_vals), 1) if conf_vals else 55.0

    # Determine winner
    scores = {
        "Research": res_score,
        "Baseline (NIFTY)": baseline_score,
        "Market": market_score,
        "Paper Trading": paper_score,
    }
    winner = max(scores, key=lambda k: scores[k])

    # Narrative
    if rel_alpha > 5:
        alpha_desc = f"Research strategy outperforms NIFTY baseline by {rel_alpha:.1f} points."
    elif rel_alpha > 0:
        alpha_desc = f"Research strategy marginally exceeds NIFTY baseline (+{rel_alpha:.1f})."
    elif rel_alpha == 0:
        alpha_desc = "Research strategy is in line with the NIFTY baseline."
    else:
        alpha_desc = f"Research strategy lags NIFTY baseline by {abs(rel_alpha):.1f} points."

    narrative = (
        f"{alpha_desc} "
        f"Risk-adjusted return score: {risk_adj:.0f}/100. "
        f"Consistency (avg signal confidence): {consistency:.0f}/100. "
        f"Top performer: {winner}. "
        f"All values are advisory estimates based on cached snapshots."
    )

    return BenchmarkComparison(
        research_score=round(res_score, 1),
        baseline_score=round(baseline_score, 1),
        market_score=round(market_score, 1),
        paper_score=round(paper_score, 1),
        relative_alpha=rel_alpha,
        risk_adj_return=risk_adj,
        consistency=consistency,
        winner=winner,
        narrative=narrative,
    )
