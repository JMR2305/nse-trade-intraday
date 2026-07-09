"""
analytics_engine.py
Shared Performance Analytics helpers used by both the Backtest engine and
Market Replay, so both surfaces report metrics the same way.

PAPER TRADING ONLY — pure computation over already-simulated/historical
trade lists; never places or touches real orders.
"""

from typing import TypedDict


class TradeAnalytics(TypedDict):
    starting_capital:     float
    ending_capital:       float
    total_return_pct:     float
    total_trades:         int
    win_rate:             float
    avg_win:              float
    avg_loss:             float
    profit_factor:        float
    expectancy:           float   # avg ₹ P&L per trade
    max_drawdown:         float
    max_drawdown_pct:     float
    max_consecutive_wins:   int
    max_consecutive_losses: int
    capital_curve:        list    # list[float], capital after each trade (incl. starting point)


def classify_outcome(return_pct: float | None) -> str:
    """
    Shared 5-tier outcome classification by realized return %:
    Excellent (>5%) / Good (2-5%) / Weak (0-2%) / Small Loss (0 to -2%) / Failed (<-2%).
    Used by both Market Replay and the Trade Journal so labels stay consistent.
    """
    if return_pct is None:
        return "Pending"
    if return_pct > 5.0:
        return "Excellent"
    if return_pct > 2.0:
        return "Good"
    if return_pct > 0.0:
        return "Weak"
    if return_pct > -2.0:
        return "Small Loss"
    return "Failed"


def _max_streak(results: list[bool]) -> int:
    best = cur = 0
    for r in results:
        cur = cur + 1 if r else 0
        best = max(best, cur)
    return best


def compute_trade_analytics(trades: list[dict], starting_capital: float) -> TradeAnalytics:
    """
    Args:
        trades: list of dicts, chronologically ordered, each with at least
                a numeric "pnl" key (₹ profit/loss for that trade).
        starting_capital: capital before the first trade.
    """
    if starting_capital <= 0:
        starting_capital = 1.0

    pnls = [float(t.get("pnl", 0.0)) for t in trades]
    total_trades = len(pnls)

    capital_curve = [round(starting_capital, 2)]
    capital = starting_capital
    peak = starting_capital
    max_dd_abs = 0.0
    max_dd_pct = 0.0
    for pnl in pnls:
        capital += pnl
        capital_curve.append(round(capital, 2))
        peak = max(peak, capital)
        dd_abs = peak - capital
        dd_pct = (dd_abs / peak * 100) if peak > 0 else 0.0
        max_dd_abs = max(max_dd_abs, dd_abs)
        max_dd_pct = max(max_dd_pct, dd_pct)

    ending_capital = capital
    total_return_pct = round((ending_capital - starting_capital) / starting_capital * 100, 2)

    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = round(len(wins) / total_trades * 100, 1) if total_trades else 0.0
    avg_win  = round(sum(wins) / len(wins), 2) if wins else 0.0
    avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))
    profit_factor = (round(gross_profit / gross_loss, 2) if gross_loss > 0
                      else 99.0 if gross_profit > 0 else 0.0)
    expectancy = round(sum(pnls) / total_trades, 2) if total_trades else 0.0

    max_consecutive_wins   = _max_streak([p > 0 for p in pnls])
    max_consecutive_losses = _max_streak([p < 0 for p in pnls])

    return TradeAnalytics(
        starting_capital=round(starting_capital, 2),
        ending_capital=round(ending_capital, 2),
        total_return_pct=total_return_pct,
        total_trades=total_trades,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown=round(max_dd_abs, 2),
        max_drawdown_pct=round(max_dd_pct, 2),
        max_consecutive_wins=max_consecutive_wins,
        max_consecutive_losses=max_consecutive_losses,
        capital_curve=capital_curve,
    )
