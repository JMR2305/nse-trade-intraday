"""
strategy_analyser.py — Phase 6.2
Per-strategy metrics, health scores, grades, and underperforming detection.
All computation from TradeRecord objects — no raw trade re-reads.
"""
from __future__ import annotations
import sys, os
import math
from typing import List, Dict
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .optimisation_models import StrategyProfile, grade, underperform_action


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def _avg(vals: list) -> float:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else 0.0


def _std(vals: list) -> float:
    v = [x for x in vals if x is not None]
    if len(v) < 2:
        return 0.0
    mean = sum(v) / len(v)
    variance = sum((x - mean) ** 2 for x in v) / len(v)
    return math.sqrt(variance)


def _profit_factor(records: list) -> float:
    wins = sum(r.pnl for r in records if r.pnl > 0)
    losses = abs(sum(r.pnl for r in records if r.pnl < 0))
    if losses == 0:
        return round(wins, 2) if wins > 0 else 1.0
    return round(wins / losses, 3)


def _max_drawdown(records: list) -> float:
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in sorted(records, key=lambda x: x.timestamp):
        running += r.pnl
        peak = max(peak, running)
        dd = (peak - running) / abs(peak) if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def _sharpe(records: list) -> float:
    """Approximate annualised Sharpe on daily P&L pct returns."""
    returns = [r.pnl_pct for r in records if r.pnl_pct is not None]
    if len(returns) < 2:
        return 0.0
    mean_r = _avg(returns)
    std_r = _std(returns)
    if std_r == 0:
        return 0.0
    # Approximate 252 trading days
    return round((mean_r / std_r) * math.sqrt(252), 3)


def _consistency(records: list) -> float:
    """
    Consistency score: proportion of rolling 5-trade windows with positive net P&L.
    Falls back to win-rate × 0.8 when fewer than 5 trades.
    """
    if len(records) < 5:
        win_rate = sum(1 for r in records if r.pnl > 0) / max(len(records), 1)
        return round(win_rate * 0.8, 4)
    sorted_recs = sorted(records, key=lambda x: x.timestamp)
    windows_positive = 0
    total_windows = len(sorted_recs) - 4
    for i in range(total_windows):
        window = sorted_recs[i:i + 5]
        if sum(r.pnl for r in window) > 0:
            windows_positive += 1
    return round(windows_positive / total_windows, 4)


def _stability(records: list) -> float:
    """
    Stability score: how low the volatility of win rate is across rolling windows.
    1.0 = perfectly stable, 0 = highly volatile.
    """
    if len(records) < 6:
        return 0.5
    sorted_recs = sorted(records, key=lambda x: x.timestamp)
    window_size = max(3, len(sorted_recs) // 3)
    win_rates = []
    for i in range(0, len(sorted_recs), window_size):
        chunk = sorted_recs[i:i + window_size]
        if chunk:
            win_rates.append(sum(1 for r in chunk if r.pnl > 0) / len(chunk))
    if len(win_rates) < 2:
        return 0.5
    std_wr = _std(win_rates)
    return round(max(0.0, 1.0 - std_wr * 2), 4)


def _recovery(records: list) -> float:
    """
    Recovery score: proportion of losing trades followed by a winning trade
    within the next 2 trades. Higher = faster recovery.
    """
    if len(records) < 2:
        return 0.5
    sorted_recs = sorted(records, key=lambda x: x.timestamp)
    recoveries = 0
    loss_count = 0
    for i, rec in enumerate(sorted_recs[:-1]):
        if rec.pnl < 0:
            loss_count += 1
            next_two = sorted_recs[i + 1: i + 3]
            if any(r.pnl > 0 for r in next_two):
                recoveries += 1
    if loss_count == 0:
        return 1.0
    return round(recoveries / loss_count, 4)


def _health_score(win_rate: float, profit_factor: float, consistency: float,
                  stability: float, recovery: float) -> float:
    """
    Weighted health score 0–100.
    Win rate 35%, profit factor 25%, consistency 20%, stability 10%, recovery 10%.
    """
    pf_norm = min(profit_factor / 3.0, 1.0)
    score = (
        win_rate * 35.0
        + pf_norm * 25.0
        + consistency * 20.0
        + stability * 10.0
        + recovery * 10.0
    )
    return round(min(max(score, 0.0), 100.0), 2)


# ---------------------------------------------------------------------------
# Underperforming detection
# ---------------------------------------------------------------------------

def _detect_underperform(records: list, profile: StrategyProfile) -> tuple:
    """Return (is_underperforming, reasons)."""
    reasons = []

    # Falling win rate: recent 10 vs overall
    if len(records) >= 10:
        recent = sorted(records, key=lambda x: x.timestamp)[-10:]
        recent_wr = sum(1 for r in recent if r.pnl > 0) / 10
        if recent_wr < profile.win_rate - 0.15:
            reasons.append("Falling Win Rate")

    # Increasing drawdown: recent 10-trade drawdown vs overall
    if len(records) >= 10:
        recent = sorted(records, key=lambda x: x.timestamp)[-10:]
        recent_dd = _max_drawdown(recent)
        if profile.max_drawdown > 0 and recent_dd > profile.max_drawdown * 1.5:
            reasons.append("Increasing Drawdown")

    # Poor execution
    if profile.avg_execution_score > 0 and profile.avg_execution_score < 60:
        reasons.append("Poor Execution")

    # Poor confidence
    if profile.avg_confidence > 0 and profile.avg_confidence < 0.5:
        reasons.append("Poor AI Confidence")

    # Increasing risk
    if len(records) >= 10 and profile.avg_risk_score > 0:
        recent = sorted(records, key=lambda x: x.timestamp)[-10:]
        recent_risk = _avg([r.risk_score for r in recent])
        if recent_risk > profile.avg_risk_score * 1.3:
            reasons.append("Increasing Risk")

    return bool(reasons), reasons


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def analyse_strategies(records: list) -> List[StrategyProfile]:
    """Build one StrategyProfile per strategy from all TradeRecord objects."""
    by_strategy: Dict[str, list] = defaultdict(list)
    for r in records:
        by_strategy[r.strategy].append(r)

    profiles: List[StrategyProfile] = []
    for strategy, recs in by_strategy.items():
        if not recs:
            continue
        wr = sum(1 for r in recs if r.pnl > 0) / len(recs)
        avg_ret = _avg([r.pnl_pct for r in recs])
        pf = _profit_factor(recs)
        dd = _max_drawdown(recs)
        sharpe = _sharpe(recs)
        avg_hold = _avg([r.holding_time_minutes for r in recs])
        avg_conf = _avg([r.ai_confidence for r in recs])
        avg_eq = _avg([r.execution_quality_score for r in recs])
        avg_risk = _avg([r.risk_score for r in recs])
        consistency = _consistency(recs)
        stability = _stability(recs)
        recovery = _recovery(recs)
        hs = _health_score(wr, pf, consistency, stability, recovery)
        g = grade(hs)
        action = underperform_action(hs)

        profile = StrategyProfile(
            strategy=strategy,
            total_trades=len(recs),
            win_rate=round(wr, 4),
            avg_return_pct=round(avg_ret, 4),
            profit_factor=pf,
            max_drawdown=round(dd, 4),
            sharpe_ratio=sharpe,
            avg_holding_time_minutes=round(avg_hold, 1),
            avg_confidence=round(avg_conf, 4),
            avg_execution_score=round(avg_eq, 4),
            avg_risk_score=round(avg_risk, 4),
            consistency_score=consistency,
            stability_score=stability,
            recovery_score=recovery,
            health_score=hs,
            grade=g,
            action=action,
            is_underperforming=False,
            underperform_reasons=[],
        )

        is_up, reasons = _detect_underperform(recs, profile)
        profile.is_underperforming = is_up
        profile.underperform_reasons = reasons
        if is_up:
            profile.action = underperform_action(hs)

        profiles.append(profile)

    # Sort by health score descending
    profiles.sort(key=lambda p: p.health_score, reverse=True)
    return profiles
