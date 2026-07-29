"""
parameter_optimiser.py — Phase 6.2
Advisory parameter recommendations per strategy.

ADVISORY ONLY — no live parameters are ever modified.
Every recommendation carries advisory_only=True.

Parameters covered:
  Stop Loss, Target, Risk/Reward, Position Size, Holding Time,
  Confidence Threshold, Execution Threshold.
"""
from __future__ import annotations
import sys, os
from typing import List
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .optimisation_models import ParameterRec, StrategyProfile


def _avg(vals: list) -> float:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else 0.0


def _percentile(vals: list, pct: float) -> float:
    if not vals:
        return 0.0
    sorted_v = sorted(vals)
    idx = int(len(sorted_v) * pct / 100)
    return sorted_v[min(idx, len(sorted_v) - 1)]


def generate_recommendations(profile: StrategyProfile, records: list) -> List[ParameterRec]:
    """
    Derive advisory parameter recommendations from historical performance.
    Only generated when there are ≥3 trades for the strategy.
    """
    recs: List[ParameterRec] = []
    if not records or len(records) < 3:
        return recs

    # -----------------------------------------------------------------------
    # Stop Loss — based on distribution of losing trade returns
    # -----------------------------------------------------------------------
    losses = [abs(r.pnl_pct) for r in records if r.pnl < 0]
    if losses:
        median_loss = _percentile(losses, 50)
        tight_sl = round(median_loss * 0.8, 2)
        recs.append(ParameterRec(
            strategy=profile.strategy,
            parameter="Stop Loss",
            current_observation=f"Avg losing trade: -{_avg(losses):.2f}% of entry",
            recommended_value=f"-{tight_sl:.2f}% from entry (tighter than median loss)",
            rationale=(
                f"Median losing trade is -{median_loss:.2f}%. A tighter stop at "
                f"-{tight_sl:.2f}% would have cut {len([l for l in losses if l > tight_sl])} "
                f"of {len(losses)} losing trades earlier."
            ),
            confidence="MEDIUM" if len(losses) >= 5 else "LOW",
        ))

    # -----------------------------------------------------------------------
    # Target — based on distribution of winning trade returns
    # -----------------------------------------------------------------------
    wins = [abs(r.pnl_pct) for r in records if r.pnl > 0]
    if wins:
        median_win = _percentile(wins, 50)
        p75_win = _percentile(wins, 75)
        recs.append(ParameterRec(
            strategy=profile.strategy,
            parameter="Target",
            current_observation=f"Median winning trade: +{median_win:.2f}%",
            recommended_value=f"+{p75_win:.2f}% (75th percentile of winners)",
            rationale=(
                f"75% of winning trades reach +{p75_win:.2f}%. "
                "Setting target here preserves most wins while avoiding over-holding."
            ),
            confidence="MEDIUM" if len(wins) >= 5 else "LOW",
        ))

    # -----------------------------------------------------------------------
    # Risk/Reward
    # -----------------------------------------------------------------------
    if losses and wins:
        avg_win = _avg(wins)
        avg_loss = _avg(losses)
        rr = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0
        ideal_rr = max(rr, 1.5)
        recs.append(ParameterRec(
            strategy=profile.strategy,
            parameter="Risk/Reward",
            current_observation=f"Current R/R ratio: {rr:.2f}",
            recommended_value=f"≥ {ideal_rr:.1f}:1",
            rationale=(
                f"With win rate {profile.win_rate * 100:.1f}%, "
                f"a minimum R/R of {ideal_rr:.1f}:1 ensures positive expectancy."
            ),
            confidence="HIGH" if len(records) >= 10 else "MEDIUM",
        ))

    # -----------------------------------------------------------------------
    # Holding Time — optimal window from win/loss holding comparison
    # -----------------------------------------------------------------------
    winning_holds = [r.holding_time_minutes for r in records if r.pnl > 0 and r.holding_time_minutes > 0]
    losing_holds = [r.holding_time_minutes for r in records if r.pnl < 0 and r.holding_time_minutes > 0]
    if winning_holds:
        opt_hold = round(_avg(winning_holds), 0)
        recs.append(ParameterRec(
            strategy=profile.strategy,
            parameter="Holding Time",
            current_observation=f"Avg hold: {profile.avg_holding_time_minutes:.0f}m | winners: {_avg(winning_holds):.0f}m | losers: {_avg(losing_holds) if losing_holds else 'N/A'}m",
            recommended_value=f"~{opt_hold:.0f} minutes",
            rationale=(
                "Winning trades average shorter holding than overall. "
                "Consider tightening time-based exits for this strategy."
                if winning_holds and losing_holds and _avg(winning_holds) < _avg(losing_holds)
                else "Holding time consistent across wins and losses — no change needed."
            ),
            confidence="LOW" if len(winning_holds) < 5 else "MEDIUM",
        ))

    # -----------------------------------------------------------------------
    # Confidence Threshold
    # -----------------------------------------------------------------------
    winning_conf = [r.ai_confidence for r in records if r.pnl > 0 and r.ai_confidence is not None]
    losing_conf = [r.ai_confidence for r in records if r.pnl < 0 and r.ai_confidence is not None]
    if winning_conf and losing_conf:
        avg_win_conf = _avg(winning_conf)
        avg_loss_conf = _avg(losing_conf)
        if avg_win_conf > avg_loss_conf + 0.05:
            threshold = round(avg_loss_conf + (avg_win_conf - avg_loss_conf) * 0.5, 2)
            recs.append(ParameterRec(
                strategy=profile.strategy,
                parameter="Confidence Threshold",
                current_observation=f"Winners avg conf: {avg_win_conf:.2f} | Losers avg conf: {avg_loss_conf:.2f}",
                recommended_value=f"≥ {threshold:.2f}",
                rationale=(
                    f"Trades with AI confidence ≥ {threshold:.2f} win at a higher rate. "
                    "Filtering below this threshold would reduce losing trades."
                ),
                confidence="HIGH" if len(winning_conf) >= 5 and len(losing_conf) >= 5 else "MEDIUM",
            ))

    # -----------------------------------------------------------------------
    # Execution Threshold
    # -----------------------------------------------------------------------
    winning_eq = [r.execution_quality_score for r in records if r.pnl > 0 and r.execution_quality_score is not None]
    losing_eq = [r.execution_quality_score for r in records if r.pnl < 0 and r.execution_quality_score is not None]
    if winning_eq and losing_eq:
        avg_win_eq = _avg(winning_eq)
        avg_loss_eq = _avg(losing_eq)
        if avg_win_eq > avg_loss_eq + 5:
            threshold = round(avg_loss_eq + (avg_win_eq - avg_loss_eq) * 0.5, 0)
            recs.append(ParameterRec(
                strategy=profile.strategy,
                parameter="Execution Threshold",
                current_observation=f"Winners avg EQ: {avg_win_eq:.1f} | Losers avg EQ: {avg_loss_eq:.1f}",
                recommended_value=f"≥ {threshold:.0f} execution score",
                rationale=(
                    "Better-executed trades (higher EQ score) correlate with wins. "
                    f"Skipping trades with EQ < {threshold:.0f} may improve net P&L."
                ),
                confidence="MEDIUM",
            ))

    # -----------------------------------------------------------------------
    # Position Size (advisory)
    # -----------------------------------------------------------------------
    if profile.max_drawdown > 0.10:
        recs.append(ParameterRec(
            strategy=profile.strategy,
            parameter="Position Size",
            current_observation=f"Max drawdown: {profile.max_drawdown * 100:.1f}%",
            recommended_value="Reduce position size by 20–30%",
            rationale=(
                f"Max drawdown of {profile.max_drawdown * 100:.1f}% exceeds a 10% threshold. "
                "Reducing position size would limit downside without changing strategy logic."
            ),
            confidence="MEDIUM",
        ))

    return recs
