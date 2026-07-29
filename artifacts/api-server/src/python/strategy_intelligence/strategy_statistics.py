"""
strategy_intelligence/strategy_statistics.py — Per-strategy statistics.

Builds StrategyProfile objects from a list of ClosedTrade records.
READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import List, Dict, Any

from .strategy_models import ClosedTrade, StrategyProfile, REGIMES, TIME_SLOTS


def _breakdown(trades: List[ClosedTrade], key_fn) -> Dict[str, Dict[str, Any]]:
    """Generic breakdown by an arbitrary key function."""
    groups: Dict[str, List[ClosedTrade]] = {}
    for t in trades:
        k = key_fn(t) or "Unknown"
        groups.setdefault(k, []).append(t)
    result = {}
    for k, ts in groups.items():
        wins  = [t for t in ts if t.is_winner()]
        pnl   = sum(t.pnl for t in ts)
        wr    = len(wins) / len(ts) * 100 if ts else 0.0
        result[k] = {
            "trades":   len(ts),
            "wins":     len(wins),
            "losses":   len(ts) - len(wins),
            "pnl":      round(pnl, 2),
            "win_rate": round(wr, 2),
            "avg_pnl":  round(_stats.mean(t.pnl for t in ts), 2) if ts else 0.0,
        }
    return result


def _running_drawdown(pnls: List[float]) -> tuple[float, float]:
    """
    Return (max_drawdown_abs, max_drawdown_pct) computed from cumulative P&L stream.
    """
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    max_dd_pct = 0.0
    for pnl in pnls:
        equity += pnl
        if equity > peak:
            peak = equity
        dd = peak - equity
        if peak > 0:
            dd_pct = dd / peak * 100
        else:
            dd_pct = 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
    return round(max_dd, 2), round(max_dd_pct, 4)


def build_strategy_profile(
    strategy_name: str,
    strategy_id:   str,
    trades:        List[ClosedTrade],
    open_count:    int = 0,
) -> StrategyProfile:
    """Build a full StrategyProfile from a list of closed trades."""
    p = StrategyProfile(
        strategy_id   = strategy_id,
        strategy_name = strategy_name,
        open_trades   = open_count,
    )

    if not trades:
        return p

    winners = [t for t in trades if t.is_winner()]
    losers  = [t for t in trades if not t.is_winner()]
    n = len(trades)

    p.total_trades   = n
    p.winning_trades = len(winners)
    p.losing_trades  = len(losers)

    p.gross_profit = sum(t.pnl for t in winners)
    p.gross_loss   = abs(sum(t.pnl for t in losers))
    p.net_pnl      = sum(t.pnl for t in trades)

    p.avg_profit    = _stats.mean(t.pnl for t in winners) if winners else 0.0
    p.avg_loss      = _stats.mean(t.pnl for t in losers)  if losers  else 0.0
    p.largest_profit = max(t.pnl for t in trades)
    p.largest_loss   = min(t.pnl for t in trades)

    p.win_rate  = len(winners) / n * 100 if n > 0 else 0.0
    p.loss_rate = len(losers)  / n * 100 if n > 0 else 0.0

    p.profit_factor = (p.gross_profit / p.gross_loss) if p.gross_loss > 0 else (999.0 if p.gross_profit > 0 else 0.0)
    p.profit_factor = min(p.profit_factor, 999.0)

    wr = p.win_rate / 100
    p.expectancy = (wr * p.avg_profit) + ((1 - wr) * p.avg_loss)

    p.risk_reward = (p.avg_profit / abs(p.avg_loss)) if p.avg_loss != 0 else 0.0

    # Drawdown: computed from chronological P&L stream
    sorted_pnls = [t.pnl for t in sorted(trades, key=lambda t: t.entry_ts or "")]
    p.max_drawdown, p.max_drawdown_pct = _running_drawdown(sorted_pnls)

    holding_times = [t.holding_seconds for t in trades if t.holding_seconds > 0]
    p.avg_holding_seconds = _stats.mean(holding_times) if holding_times else 0.0

    scores = [t.quality_score for t in trades if t.quality_score > 0]
    p.avg_quality_score = _stats.mean(scores) if scores else 0.0

    # Breakdowns
    p.regime_breakdown = _breakdown(trades, lambda t: t.market_regime)
    p.sector_breakdown = _breakdown(trades, lambda t: t.sector)
    p.time_breakdown   = _breakdown(trades, lambda t: t.time_slot)

    return p


def build_all_profiles(
    closed_trades: List[ClosedTrade],
    open_counts:   Dict[str, int],
) -> List[StrategyProfile]:
    """Group closed trades by strategy_name → one StrategyProfile per strategy."""
    by_strategy: Dict[str, List[ClosedTrade]] = {}
    id_map: Dict[str, str] = {}
    for t in closed_trades:
        by_strategy.setdefault(t.strategy_name, []).append(t)
        id_map[t.strategy_name] = t.strategy_id

    profiles = []
    for name, trades in by_strategy.items():
        sid    = id_map.get(name, "unknown")
        opens  = open_counts.get(name, 0)
        p = build_strategy_profile(name, sid, trades, opens)
        profiles.append(p)

    # If there are open trades for strategies with no closed trades yet
    for name, cnt in open_counts.items():
        if name not in by_strategy:
            p = StrategyProfile(
                strategy_name=name, strategy_id="unknown", open_trades=cnt
            )
            profiles.append(p)

    return profiles
