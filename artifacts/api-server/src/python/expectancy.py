"""
Expectancy Engine — Sprint 4.

Computes the full deterministic metric set for a group of historical trades
(a "pattern"). Replaces win-rate-based learning with expectancy-based
learning everywhere. Pure arithmetic — no ML, no randomness.

PAPER TRADING ONLY — research and ranking assistance, never places orders.
"""

from __future__ import annotations

import math

# Expectancy rating thresholds (% expectancy per trade, deterministic)
RATING_EXCELLENT = 1.5
RATING_GOOD      = 0.5
RATING_NEUTRAL   = -0.2   # anything >= this (and < GOOD) is "Neutral"
RATING_POOR      = -1.0   # anything >= this (and < NEUTRAL) is "Poor"
# below RATING_POOR → "Negative"

KELLY_CAP = 100.0
SHARPE_CAP = 99.0
PF_CAP = 999.0


def expectancy_rating(expectancy: float) -> str:
    if expectancy >= RATING_EXCELLENT:
        return "Excellent"
    if expectancy >= RATING_GOOD:
        return "Good"
    if expectancy >= RATING_NEUTRAL:
        return "Neutral"
    if expectancy >= RATING_POOR:
        return "Poor"
    return "Negative"


def _empty_metrics() -> dict:
    return {
        "trades": 0, "wins": 0, "losses": 0,
        "win_rate": 0.0, "loss_rate": 0.0,
        "avg_win": 0.0, "avg_loss": 0.0,
        "average_return": 0.0,
        "profit_factor": 0.0,
        "expectancy": 0.0, "expected_value": 0.0,
        "kelly_percent": 0.0,
        "max_drawdown": 0.0, "recovery_factor": 0.0,
        "sharpe": 0.0, "sortino": 0.0,
        "avg_holding_days": 0.0,
        "expectancy_rating": "Neutral",
    }


def compute_metrics(trades: list[dict]) -> dict:
    """
    Full expectancy metrics for a list of historical trades.
    Each trade needs `return_percent`; `holding_days` and `exit_date`
    are used when present (holding time, drawdown sequencing).
    """
    n = len(trades)
    if n == 0:
        return _empty_metrics()

    ordered = sorted(trades, key=lambda t: str(t.get("exit_date") or ""))
    rets = [float(t.get("return_percent") or 0.0) for t in ordered]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]

    win_rate = len(wins) / n * 100.0
    loss_rate = 100.0 - win_rate
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (abs(sum(losses)) / len(losses)) if losses else 0.0   # magnitude
    mean_ret = sum(rets) / n

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (PF_CAP if gross_win > 0 else 0.0)
    pf = min(pf, PF_CAP)

    # Expectancy (spec formula): WR × AvgWin − LR × AvgLoss (per trade, %)
    expectancy = (win_rate / 100.0) * avg_win - (loss_rate / 100.0) * avg_loss
    expected_value = mean_ret   # mean return per trade (signed losses incl. 0s)

    # Kelly %: W − (1−W)/R,  R = AvgWin/AvgLoss. Clamped to 0..100.
    if avg_loss > 0:
        r_ratio = avg_win / avg_loss
        kelly = (win_rate / 100.0) - (loss_rate / 100.0) / r_ratio if r_ratio > 0 else 0.0
    else:
        kelly = (win_rate / 100.0) if wins else 0.0
    kelly_pct = max(0.0, min(KELLY_CAP, kelly * 100.0))

    # Max drawdown: compounded equity curve over trades in exit-date order
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for r in rets:
        equity *= (1.0 + r / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            dd = (peak - equity) / peak * 100.0
            max_dd = max(max_dd, dd)
    total_return = (equity - 1.0) * 100.0
    recovery = (total_return / max_dd) if max_dd > 0 else (total_return if total_return > 0 else 0.0)

    # Per-trade Sharpe / Sortino (rf = 0, population std). Deterministic and
    # comparable across patterns; no annualization.
    var = sum((r - mean_ret) ** 2 for r in rets) / n
    std = math.sqrt(var)
    sharpe = (mean_ret / std) if std > 0 else (SHARPE_CAP if mean_ret > 0 else 0.0)
    downside = [r for r in rets if r < 0]
    if downside:
        dvar = sum(r ** 2 for r in downside) / n
        dstd = math.sqrt(dvar)
        sortino = (mean_ret / dstd) if dstd > 0 else (SHARPE_CAP if mean_ret > 0 else 0.0)
    else:
        sortino = SHARPE_CAP if mean_ret > 0 else 0.0

    hold_vals = [float(t.get("holding_days")) for t in ordered
                 if t.get("holding_days") is not None]
    avg_hold = (sum(hold_vals) / len(hold_vals)) if hold_vals else 0.0

    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "loss_rate": round(loss_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "average_return": round(mean_ret, 2),
        "profit_factor": round(min(pf, PF_CAP), 2),
        "expectancy": round(expectancy, 2),
        "expected_value": round(expected_value, 2),
        "kelly_percent": round(kelly_pct, 1),
        "max_drawdown": round(max_dd, 2),
        "recovery_factor": round(recovery, 2),
        "sharpe": round(min(sharpe, SHARPE_CAP), 2),
        "sortino": round(min(sortino, SHARPE_CAP), 2),
        "avg_holding_days": round(avg_hold, 1),
        "expectancy_rating": expectancy_rating(round(expectancy, 2)),
    }


# ── Score mappers for the Sprint 4 opportunity blend (all 0-100) ──────────────

def expectancy_score(expectancy: float) -> float:
    """Map % expectancy per trade to 0-100 (0% → 50, ±2.5% → 100/0)."""
    return round(max(0.0, min(100.0, 50.0 + expectancy * 20.0)), 1)


def profit_factor_score(pf: float) -> float:
    """Map profit factor to 0-100 (PF 3.0+ → 100)."""
    return round(max(0.0, min(100.0, min(pf, 3.0) / 3.0 * 100.0)), 1)


def risk_score(max_drawdown: float) -> float:
    """Map historical pattern drawdown to 0-100 (lower drawdown = better)."""
    return round(max(0.0, min(100.0, 100.0 - max_drawdown * 4.0)), 1)
