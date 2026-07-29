"""
strategy_intelligence/strategy_rankings.py — Multi-criteria strategy ranking.

Produces a composite rank score and per-criterion rankings.
READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from typing import List, Dict, Any

from .strategy_models import StrategyProfile


def _normalise(values: List[float], higher_better: bool = True) -> List[float]:
    """Min-max normalise to [0, 1]. Returns 0.5 for all-equal lists."""
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)
    normed = [(v - mn) / (mx - mn) for v in values]
    return normed if higher_better else [1 - n for n in normed]


def compute_rank_scores(profiles: List[StrategyProfile]) -> List[StrategyProfile]:
    """
    Assign composite rank scores (0–100) to each StrategyProfile.

    Weights:
      net_pnl           20 %
      win_rate          20 %
      profit_factor     20 %
      risk_adj_return   15 %   (net_pnl / max_drawdown, or net_pnl when dd=0)
      max_drawdown      15 %   (lower is better)
      avg_quality_score 10 %
      consistency       10 %   (1 – std_dev_normalised of trade P&Ls)

    Profiles with zero trades score 0.
    """
    if not profiles:
        return profiles

    # Consistency: for each profile compute stdev of pnl_pcts (lower stdev = more consistent)
    # We'll store it as a raw field to pass to the normaliser
    import statistics as _stats
    consistencies = []
    for p in profiles:
        # stdev of pnl across its trades — lower = more consistent
        pnls = [p.net_pnl]   # fallback: just use net
        stdev = 0.0
        consistencies.append(stdev)  # placeholder; enriched below

    n = len(profiles)

    def col(fn):
        return [fn(p) for p in profiles]

    # Raw metric columns
    net_pnls     = col(lambda p: p.net_pnl)
    win_rates    = col(lambda p: p.win_rate)
    pfs          = col(lambda p: min(p.profit_factor, 20.0))   # cap to avoid inf dominating
    risk_adj     = col(lambda p: p.net_pnl / p.max_drawdown if p.max_drawdown > 0 else p.net_pnl)
    drawdowns    = col(lambda p: p.max_drawdown_pct)
    qualities    = col(lambda p: p.avg_quality_score)

    # Consistency: use negative avg_loss / avg_profit ratio (higher ratio = more consistent)
    consistencies = col(lambda p: (p.avg_profit / abs(p.avg_loss)) if p.avg_loss != 0 else (1.0 if p.avg_profit > 0 else 0.0))

    # Normalise
    n_net   = _normalise(net_pnls,    higher_better=True)
    n_wr    = _normalise(win_rates,   higher_better=True)
    n_pf    = _normalise(pfs,         higher_better=True)
    n_ra    = _normalise(risk_adj,    higher_better=True)
    n_dd    = _normalise(drawdowns,   higher_better=False)   # lower drawdown = better
    n_qual  = _normalise(qualities,   higher_better=True)
    n_cons  = _normalise(consistencies, higher_better=True)

    weights = (0.20, 0.20, 0.20, 0.15, 0.15, 0.10, 0.10)

    for i, p in enumerate(profiles):
        if p.total_trades == 0:
            p.rank_score = 0.0
        else:
            raw = (
                n_net[i]  * weights[0] +
                n_wr[i]   * weights[1] +
                n_pf[i]   * weights[2] +
                n_ra[i]   * weights[3] +
                n_dd[i]   * weights[4] +
                n_qual[i] * weights[5] +
                n_cons[i] * weights[6]
            )
            p.rank_score = round(raw * 100, 2)

    # Sort by rank_score descending; assign rank
    profiles.sort(key=lambda p: -p.rank_score)
    for i, p in enumerate(profiles):
        p.rank = i + 1

    return profiles


def get_leaderboard(profiles: List[StrategyProfile]) -> List[Dict[str, Any]]:
    """Compact leaderboard row per strategy (sorted by rank)."""
    ranked = [p for p in profiles if p.rank > 0]
    ranked.sort(key=lambda p: p.rank)
    return [
        {
            "rank":             p.rank,
            "strategy_name":    p.strategy_name,
            "total_trades":     p.total_trades,
            "win_rate":         round(p.win_rate, 2),
            "profit_factor":    round(p.profit_factor, 2),
            "net_pnl":          round(p.net_pnl, 2),
            "max_drawdown_pct": round(p.max_drawdown_pct, 2),
            "avg_quality_score": round(p.avg_quality_score, 1),
            "rank_score":       round(p.rank_score, 2),
            "recommendation":   p.recommendation,
        }
        for p in ranked
    ]


def get_criterion_rankings(profiles: List[StrategyProfile]) -> Dict[str, Any]:
    """Return per-criterion top strategies."""
    if not profiles:
        return {}

    with_trades = [p for p in profiles if p.total_trades > 0]
    if not with_trades:
        return {}

    def _top(key_fn, label):
        p = max(with_trades, key=key_fn)
        return {"strategy_name": p.strategy_name, label: round(key_fn(p), 2)}

    return {
        "highest_net_profit":    _top(lambda p: p.net_pnl,             "net_pnl"),
        "highest_win_rate":      _top(lambda p: p.win_rate,            "win_rate"),
        "highest_profit_factor": _top(lambda p: p.profit_factor,       "profit_factor"),
        "lowest_drawdown":       {
            "strategy_name": min(with_trades, key=lambda p: p.max_drawdown_pct).strategy_name,
            "max_drawdown_pct": round(min(with_trades, key=lambda p: p.max_drawdown_pct).max_drawdown_pct, 2),
        },
        "best_execution":        _top(lambda p: p.avg_quality_score,   "avg_quality_score"),
        "highest_rank_score":    _top(lambda p: p.rank_score,          "rank_score"),
    }
