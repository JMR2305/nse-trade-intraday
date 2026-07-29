"""
capital_analyser.py — Phase 6.4
Capital utilisation, efficiency, turnover, idle capital, recommended allocation.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List

# Assumed paper portfolio starting capital (₹5,00,000)
DEFAULT_CAPITAL = 500_000.0


def analyse_capital(records: list, starting_capital: float = DEFAULT_CAPITAL) -> dict:
    """
    Analyse capital allocation from FIFO-matched TradeRecord list.

    Returns dict with:
      - avg_capital_usage, max_capital_usage, min_capital_usage
      - capital_utilisation_rate (0–1)
      - idle_capital (₹)
      - capital_efficiency (win_pnl / total_capital_deployed)
      - capital_turnover (total_capital_deployed / starting_capital)
      - recommended_allocation (₹) — based on optimal position sizing
      - allocation_stability (std dev of capital usage normalised)
      - per_trade_capital (list of ₹ deployed per trade)
    """
    if not records:
        return _empty_capital(starting_capital)

    capital_deployed = []
    win_pnl = 0.0
    total_pnl = 0.0

    for r in records:
        cap = _capital_for(r)
        capital_deployed.append(cap)
        pnl = r.get("pnl", 0.0) or 0.0
        total_pnl += pnl
        if pnl > 0:
            win_pnl += pnl

    n = len(capital_deployed)
    avg_cap = sum(capital_deployed) / n
    max_cap = max(capital_deployed)
    min_cap = min(capital_deployed)
    total_deployed = sum(capital_deployed)

    util_rate = min(1.0, avg_cap / starting_capital)
    idle_capital = max(0.0, starting_capital - avg_cap)

    # Capital efficiency: return on deployed capital
    if total_deployed > 0:
        cap_efficiency = min(1.0, max(0.0, (win_pnl / total_deployed) + 0.5))
    else:
        cap_efficiency = 0.5

    turnover = total_deployed / starting_capital if starting_capital > 0 else 0.0

    # Recommended allocation: Kelly-inspired — size down in losing runs
    win_rate = sum(1 for r in records if (r.get("pnl") or 0) > 0) / n
    avg_win = (sum((r.get("pnl") or 0) for r in records if (r.get("pnl") or 0) > 0) /
               max(1, sum(1 for r in records if (r.get("pnl") or 0) > 0)))
    avg_loss = abs(sum((r.get("pnl") or 0) for r in records if (r.get("pnl") or 0) <= 0) /
                   max(1, sum(1 for r in records if (r.get("pnl") or 0) <= 0)))
    rr_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0
    # Half-Kelly fraction
    kelly_f = max(0.0, min(0.25, (win_rate * rr_ratio - (1 - win_rate)) / rr_ratio * 0.5))
    recommended_allocation = round(starting_capital * kelly_f, 2)

    # Allocation stability (coefficient of variation of capital deployed)
    if n > 1:
        mean = avg_cap
        variance = sum((c - mean) ** 2 for c in capital_deployed) / n
        std = variance ** 0.5
        cv = std / mean if mean > 0 else 0.0
        allocation_stability = max(0.0, min(1.0, 1.0 - cv))
    else:
        allocation_stability = 1.0

    return {
        "total_trades": n,
        "starting_capital": starting_capital,
        "avg_capital_usage": round(avg_cap, 2),
        "max_capital_usage": round(max_cap, 2),
        "min_capital_usage": round(min_cap, 2),
        "total_capital_deployed": round(total_deployed, 2),
        "capital_utilisation_rate": round(util_rate, 4),
        "idle_capital": round(idle_capital, 2),
        "capital_efficiency": round(cap_efficiency, 4),
        "capital_turnover": round(turnover, 4),
        "recommended_allocation": recommended_allocation,
        "allocation_stability": round(allocation_stability, 4),
        "kelly_fraction": round(kelly_f, 4),
        "win_rate": round(win_rate, 4),
        "avg_win_inr": round(avg_win, 2),
        "avg_loss_inr": round(avg_loss, 2),
        "reward_risk_ratio": round(rr_ratio, 4),
    }


def analyse_position_sizing(records: list, starting_capital: float = DEFAULT_CAPITAL) -> dict:
    """
    Position sizing analysis: avg, largest, smallest, winning vs losing,
    recommended position size, maximum safe position, risk per trade.
    """
    if not records:
        return {
            "total_trades": 0,
            "avg_position_size": 0.0,
            "largest_position": 0.0,
            "smallest_position": 0.0,
            "avg_winning_position": 0.0,
            "avg_losing_position": 0.0,
            "recommended_position_size": 0.0,
            "max_safe_position": 0.0,
            "avg_risk_per_trade_pct": 0.0,
            "position_sizing_score": 0.5,
        }

    sizes = [_capital_for(r) for r in records]
    wins = [_capital_for(r) for r in records if (r.get("pnl") or 0) > 0]
    losses = [_capital_for(r) for r in records if (r.get("pnl") or 0) <= 0]

    n = len(sizes)
    avg_size = sum(sizes) / n
    largest = max(sizes)
    smallest = min(sizes)
    avg_win_size = sum(wins) / len(wins) if wins else 0.0
    avg_loss_size = sum(losses) / len(losses) if losses else 0.0

    # Risk per trade = |loss pnl| / position size
    risk_pcts = []
    for r in records:
        pnl = r.get("pnl") or 0.0
        cap = _capital_for(r)
        if cap > 0 and pnl < 0:
            risk_pcts.append(abs(pnl) / cap)
    avg_risk_pct = sum(risk_pcts) / len(risk_pcts) if risk_pcts else 0.0

    # Max safe position: 2% risk rule
    max_safe = starting_capital * 0.02 / max(avg_risk_pct, 0.001)
    max_safe = min(max_safe, starting_capital * 0.20)  # never > 20% of capital

    # Recommended: optimal fraction based on risk
    recommended = starting_capital * 0.05  # 5% base

    # Position sizing score: penalise over-concentration
    concentration_penalty = max(0.0, (largest / starting_capital) - 0.20)  # penalty if > 20%
    ps_score = max(0.0, min(1.0, 0.8 - concentration_penalty * 2.0))

    return {
        "total_trades": n,
        "avg_position_size": round(avg_size, 2),
        "largest_position": round(largest, 2),
        "smallest_position": round(smallest, 2),
        "avg_winning_position": round(avg_win_size, 2),
        "avg_losing_position": round(avg_loss_size, 2),
        "recommended_position_size": round(recommended, 2),
        "max_safe_position": round(max_safe, 2),
        "avg_risk_per_trade_pct": round(avg_risk_pct, 4),
        "position_sizing_score": round(ps_score, 4),
        "largest_position_pct_of_capital": round(largest / starting_capital, 4) if starting_capital > 0 else 0.0,
    }


def _capital_for(r: dict) -> float:
    entry = r.get("entry_price") or 0.0
    qty = r.get("quantity") or 0.0
    cap = float(entry) * float(qty)
    return cap if cap > 0 else 0.0


def _empty_capital(starting_capital: float) -> dict:
    return {
        "total_trades": 0,
        "starting_capital": starting_capital,
        "avg_capital_usage": 0.0,
        "max_capital_usage": 0.0,
        "min_capital_usage": 0.0,
        "total_capital_deployed": 0.0,
        "capital_utilisation_rate": 0.0,
        "idle_capital": starting_capital,
        "capital_efficiency": 0.0,
        "capital_turnover": 0.0,
        "recommended_allocation": 0.0,
        "allocation_stability": 1.0,
        "kelly_fraction": 0.0,
        "win_rate": 0.0,
        "avg_win_inr": 0.0,
        "avg_loss_inr": 0.0,
        "reward_risk_ratio": 0.0,
    }
