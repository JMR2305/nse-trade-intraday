"""
portfolio_performance/performance_models.py — Phase 5D.2 data models.

PAPER TRADING / ADVISORY ONLY.
No order submission, no broker call, no portfolio mutation.
"""
from __future__ import annotations

import os as _os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

_ENABLED_VAR = "PORTFOLIO_PERFORMANCE_ENABLED"
_LABEL = "PAPER TRADING / ADVISORY ONLY"


def is_enabled() -> bool:
    # Enabled by default — portfolio performance analytics is a core read-only
    # page. Set PORTFOLIO_PERFORMANCE_ENABLED=false to explicitly disable.
    return _os.environ.get(_ENABLED_VAR, "true").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":       "DISABLED",
        "feature_flag": _ENABLED_VAR,
        "message":      f"Set {_ENABLED_VAR}=true to enable Phase 5D.2 portfolio performance analytics.",
        "label":        _LABEL,
    }


@dataclass
class ClosedTrade:
    """One round-trip BUY→SELL pair."""
    trade_id:      str   = ""
    symbol:        str   = ""
    strategy_id:   str   = ""
    strategy_name: str   = ""
    sector:        str   = ""

    entry_ts:   Optional[str] = None
    exit_ts:    Optional[str] = None
    entry_price: float = 0.0
    exit_price:  float = 0.0
    quantity:    int   = 0
    entry_total: float = 0.0
    exit_total:  float = 0.0

    pnl:     float = 0.0
    pnl_pct: float = 0.0

    stop_loss: float = 0.0
    target:    float = 0.0
    exit_type: str   = ""

    holding_seconds: float = 0.0  # seconds from entry to exit

    def to_dict(self) -> dict:
        return {
            "trade_id":       self.trade_id,
            "symbol":         self.symbol,
            "strategy_id":    self.strategy_id,
            "strategy_name":  self.strategy_name,
            "sector":         self.sector,
            "entry_ts":       self.entry_ts,
            "exit_ts":        self.exit_ts,
            "entry_price":    round(self.entry_price, 2),
            "exit_price":     round(self.exit_price, 2),
            "quantity":       self.quantity,
            "entry_total":    round(self.entry_total, 2),
            "exit_total":     round(self.exit_total, 2),
            "pnl":            round(self.pnl, 2),
            "pnl_pct":        round(self.pnl_pct, 4),
            "stop_loss":      round(self.stop_loss, 2),
            "target":         round(self.target, 2),
            "exit_type":      self.exit_type,
            "holding_seconds": round(self.holding_seconds, 1),
        }


@dataclass
class OpenPosition:
    """One open paper position (no SELL yet)."""
    symbol:       str   = ""
    sector:       str   = ""
    quantity:     int   = 0
    avg_cost:     float = 0.0
    current_value: float = 0.0
    unrealised_pnl: float = 0.0
    unrealised_pnl_pct: float = 0.0
    weight_pct:   float = 0.0   # % of total portfolio value

    def to_dict(self) -> dict:
        return {
            "symbol":             self.symbol,
            "sector":             self.sector,
            "quantity":           self.quantity,
            "avg_cost":           round(self.avg_cost, 2),
            "current_value":      round(self.current_value, 2),
            "unrealised_pnl":     round(self.unrealised_pnl, 2),
            "unrealised_pnl_pct": round(self.unrealised_pnl_pct, 4),
            "weight_pct":         round(self.weight_pct, 2),
        }


@dataclass
class EquityPoint:
    """Single point on the equity curve."""
    timestamp: str   = ""
    equity:    float = 0.0
    drawdown:  float = 0.0   # absolute ₹ from peak
    drawdown_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp":    self.timestamp,
            "equity":       round(self.equity, 2),
            "drawdown":     round(self.drawdown, 2),
            "drawdown_pct": round(self.drawdown_pct, 4),
        }


@dataclass
class PerformanceSummary:
    """Aggregated portfolio performance snapshot."""
    # ── Portfolio value ───────────────────────────────────────────────────────
    total_portfolio_value: float = 0.0
    initial_capital:       float = 0.0
    cash_available:        float = 0.0
    invested_capital:      float = 0.0
    unrealised_pnl:        float = 0.0
    realised_pnl:          float = 0.0
    total_net_pnl:         float = 0.0
    total_return_pct:      float = 0.0
    today_pnl:             float = 0.0
    weekly_pnl:            float = 0.0
    monthly_pnl:           float = 0.0
    lifetime_pnl:          float = 0.0

    # ── Trade statistics ──────────────────────────────────────────────────────
    total_trades:     int   = 0
    winning_trades:   int   = 0
    losing_trades:    int   = 0
    open_trades:      int   = 0
    win_rate:         float = 0.0   # %
    loss_rate:        float = 0.0   # %
    avg_winner:       float = 0.0
    avg_loser:        float = 0.0
    largest_profit:   float = 0.0
    largest_loss:     float = 0.0
    avg_holding_seconds: float = 0.0

    # ── Risk metrics ──────────────────────────────────────────────────────────
    max_drawdown:     float = 0.0   # absolute ₹
    max_drawdown_pct: float = 0.0   # %
    current_drawdown: float = 0.0
    current_drawdown_pct: float = 0.0
    recovery_pct:     float = 0.0   # how much of drawdown recovered
    profit_factor:    float = 0.0   # gross profit / gross loss
    expectancy:       float = 0.0   # expected ₹ per trade
    risk_reward_ratio: float = 0.0  # avg_winner / abs(avg_loser)
    avg_r_multiple:   float = 0.0   # avg pnl / avg stop-loss distance

    # ── Portfolio analytics ───────────────────────────────────────────────────
    portfolio_utilisation_pct: float = 0.0
    position_concentration_pct: float = 0.0  # largest single position %

    def to_dict(self) -> dict:
        return {
            "total_portfolio_value":   round(self.total_portfolio_value, 2),
            "initial_capital":         round(self.initial_capital, 2),
            "cash_available":          round(self.cash_available, 2),
            "invested_capital":        round(self.invested_capital, 2),
            "unrealised_pnl":          round(self.unrealised_pnl, 2),
            "realised_pnl":            round(self.realised_pnl, 2),
            "total_net_pnl":           round(self.total_net_pnl, 2),
            "total_return_pct":        round(self.total_return_pct, 4),
            "today_pnl":               round(self.today_pnl, 2),
            "weekly_pnl":              round(self.weekly_pnl, 2),
            "monthly_pnl":             round(self.monthly_pnl, 2),
            "lifetime_pnl":            round(self.lifetime_pnl, 2),
            "total_trades":            self.total_trades,
            "winning_trades":          self.winning_trades,
            "losing_trades":           self.losing_trades,
            "open_trades":             self.open_trades,
            "win_rate":                round(self.win_rate, 4),
            "loss_rate":               round(self.loss_rate, 4),
            "avg_winner":              round(self.avg_winner, 2),
            "avg_loser":               round(self.avg_loser, 2),
            "largest_profit":          round(self.largest_profit, 2),
            "largest_loss":            round(self.largest_loss, 2),
            "avg_holding_seconds":     round(self.avg_holding_seconds, 1),
            "max_drawdown":            round(self.max_drawdown, 2),
            "max_drawdown_pct":        round(self.max_drawdown_pct, 4),
            "current_drawdown":        round(self.current_drawdown, 2),
            "current_drawdown_pct":    round(self.current_drawdown_pct, 4),
            "recovery_pct":            round(self.recovery_pct, 4),
            "profit_factor":           round(self.profit_factor, 4),
            "expectancy":              round(self.expectancy, 2),
            "risk_reward_ratio":       round(self.risk_reward_ratio, 4),
            "avg_r_multiple":          round(self.avg_r_multiple, 4),
            "portfolio_utilisation_pct": round(self.portfolio_utilisation_pct, 4),
            "position_concentration_pct": round(self.position_concentration_pct, 4),
        }
