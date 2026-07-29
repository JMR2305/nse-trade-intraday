"""
target_analyser.py — Phase 6.4
Target hits, average reward, reward/risk ratio, missed profit,
early profit booking, and extended winners.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations


def analyse_targets(records: list) -> dict:
    """
    Analyse target/profit-taking behaviour.

    Target hits: exit_reason containing 'target', 'tgt', 'profit', 'take_profit'
    """
    if not records:
        return _empty_targets()

    n = len(records)
    wins = [r for r in records if (r.get("pnl") or 0.0) > 0]
    losses = [r for r in records if (r.get("pnl") or 0.0) <= 0]

    target_hits = []
    for r in records:
        reason = (r.get("exit_reason") or "").lower()
        if any(kw in reason for kw in ("target", "tgt", "profit_target", "take_profit")):
            target_hits.append(r)

    th_count = len(target_hits)
    th_rate = th_count / n if n > 0 else 0.0

    avg_reward = sum(r.get("pnl") or 0.0 for r in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(r.get("pnl") or 0.0 for r in losses) / len(losses)) if losses else 1.0
    rr_ratio = avg_reward / avg_loss if avg_loss > 0 else 0.0

    avg_win_pct = sum(r.get("pnl_pct") or 0.0 for r in wins) / len(wins) if wins else 0.0

    # Early profit booking: wins with pnl_pct < 1%
    early_booking = [r for r in wins if (r.get("pnl_pct") or 0.0) < 0.01]
    # Extended winners: wins with pnl_pct > 5%
    extended_winners = [r for r in wins if (r.get("pnl_pct") or 0.0) > 0.05]
    # Missed profit: wins that could have been larger (held less than avg)
    avg_hold = (sum(r.get("holding_time_minutes") or 0.0 for r in wins) / len(wins)) if wins else 0.0
    missed_profit = [r for r in wins if (r.get("holding_time_minutes") or 0.0) < avg_hold * 0.5]

    # Target achievement rate score
    target_score = min(1.0, th_rate * 1.5 + rr_ratio * 0.1)

    return {
        "total_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / n, 4) if n > 0 else 0.0,
        "target_hits": th_count,
        "target_hit_rate": round(th_rate, 4),
        "avg_reward_inr": round(avg_reward, 2),
        "avg_loss_inr": round(avg_loss, 2),
        "reward_risk_ratio": round(rr_ratio, 4),
        "avg_win_pct": round(avg_win_pct, 4),
        "early_profit_booking": len(early_booking),
        "extended_winners": len(extended_winners),
        "missed_profit_count": len(missed_profit),
        "target_achievement_score": round(min(1.0, target_score), 4),
        "advisory": _target_advisory(rr_ratio, early_booking, extended_winners, th_rate),
    }


def _target_advisory(rr: float, early: list, extended: list, th_rate: float) -> str:
    if rr < 1.0:
        return "Reward/risk ratio below 1.0: average wins are smaller than losses — review target levels."
    if len(early) > len(extended) * 2:
        return "Frequent early profit booking detected: consider holding winners longer with trailing stops."
    if th_rate < 0.20 and len(extended) > 0:
        return "Low target hit rate with extended winners: targets may be too aggressive — consider partial profit booking."
    if rr > 2.5:
        return "Strong reward/risk ratio — maintain current target discipline."
    return "Target performance is within acceptable parameters."


def _empty_targets() -> dict:
    return {
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "win_rate": 0.0,
        "target_hits": 0,
        "target_hit_rate": 0.0,
        "avg_reward_inr": 0.0,
        "avg_loss_inr": 0.0,
        "reward_risk_ratio": 0.0,
        "avg_win_pct": 0.0,
        "early_profit_booking": 0,
        "extended_winners": 0,
        "missed_profit_count": 0,
        "target_achievement_score": 0.5,
        "advisory": "No trades recorded yet.",
    }
