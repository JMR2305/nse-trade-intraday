"""
strategy_intelligence/strategy_models.py — Phase 5D.3 data models.

PAPER TRADING / ADVISORY ONLY.
No order submission, no portfolio mutation, no strategy execution change.
"""
from __future__ import annotations

import os as _os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

_ENABLED_VAR = "STRATEGY_INTELLIGENCE_ENABLED"
_LABEL = "PAPER TRADING / ADVISORY ONLY"

# ── Market regime canonical values ────────────────────────────────────────────
# These match market_regime_at_entry stored in paper_trades metadata.
REGIMES = [
    "Strong Bullish",
    "Bullish",
    "Neutral",
    "Bearish",
    "Strong Bearish",
    "High Volatility",
    "Low Volatility",
]

# ── IST intraday time slots ───────────────────────────────────────────────────
TIME_SLOTS = [
    "09:15–10:00",
    "10:00–11:00",
    "11:00–12:00",
    "12:00–13:00",
    "13:00–14:00",
    "14:00–15:30",
]

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def is_enabled() -> bool:
    return _os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":       "DISABLED",
        "feature_flag": _ENABLED_VAR,
        "message":      f"Set {_ENABLED_VAR}=true to enable Phase 5D.3 strategy intelligence.",
        "label":        _LABEL,
    }


@dataclass
class ClosedTrade:
    """One BUY→SELL round-trip, strategy-enriched."""
    trade_id:       str   = ""
    symbol:         str   = ""
    sector:         str   = ""
    strategy_id:    str   = ""
    strategy_name:  str   = ""

    entry_ts:       Optional[str] = None
    exit_ts:        Optional[str] = None
    entry_price:    float = 0.0
    exit_price:     float = 0.0
    quantity:       int   = 0
    entry_total:    float = 0.0

    pnl:            float = 0.0
    pnl_pct:        float = 0.0
    stop_loss:      float = 0.0
    target:         float = 0.0
    exit_type:      str   = ""
    holding_seconds: float = 0.0

    market_regime:       str   = "Unknown"
    signal_confidence:   float = 0.0
    quality_score:       int   = 0    # from execution quality (0-100)
    quality_grade:       str   = ""

    # IST bucketed fields (populated by engine)
    time_slot:  str = ""   # e.g. "09:15–10:00"
    day_of_week: str = ""  # e.g. "Monday"
    hour_ist:   int = 9

    def is_winner(self) -> bool:
        return self.pnl > 0

    def to_dict(self) -> dict:
        return {
            "trade_id":         self.trade_id,
            "symbol":           self.symbol,
            "sector":           self.sector,
            "strategy_id":      self.strategy_id,
            "strategy_name":    self.strategy_name,
            "entry_ts":         self.entry_ts,
            "exit_ts":          self.exit_ts,
            "entry_price":      round(self.entry_price, 2),
            "exit_price":       round(self.exit_price, 2),
            "quantity":         self.quantity,
            "pnl":              round(self.pnl, 2),
            "pnl_pct":          round(self.pnl_pct, 4),
            "stop_loss":        round(self.stop_loss, 2),
            "target":           round(self.target, 2),
            "exit_type":        self.exit_type,
            "holding_seconds":  round(self.holding_seconds, 1),
            "market_regime":    self.market_regime,
            "signal_confidence": round(self.signal_confidence, 4),
            "quality_score":    self.quality_score,
            "quality_grade":    self.quality_grade,
            "time_slot":        self.time_slot,
            "day_of_week":      self.day_of_week,
            "hour_ist":         self.hour_ist,
        }


@dataclass
class StrategyProfile:
    """Aggregated performance profile for one strategy."""
    strategy_id:   str = ""
    strategy_name: str = ""

    # Trade counts
    total_trades:   int = 0
    winning_trades: int = 0
    losing_trades:  int = 0
    open_trades:    int = 0

    # P&L
    net_pnl:       float = 0.0
    gross_profit:  float = 0.0
    gross_loss:    float = 0.0
    avg_profit:    float = 0.0
    avg_loss:      float = 0.0
    largest_profit: float = 0.0
    largest_loss:   float = 0.0

    # Rates
    win_rate:      float = 0.0   # %
    loss_rate:     float = 0.0   # %
    profit_factor: float = 0.0
    expectancy:    float = 0.0
    risk_reward:   float = 0.0

    # Risk
    max_drawdown:      float = 0.0
    max_drawdown_pct:  float = 0.0

    # Time
    avg_holding_seconds: float = 0.0

    # Quality
    avg_quality_score: float = 0.0

    # Regime breakdown: {regime: {trades, wins, pnl, win_rate}}
    regime_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Sector breakdown: {sector: {trades, wins, pnl, win_rate}}
    sector_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Time slot breakdown: {slot: {trades, wins, pnl, win_rate}}
    time_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Composite rank score (populated by rankings module)
    rank_score:  float = 0.0
    rank:        int   = 0
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "strategy_id":         self.strategy_id,
            "strategy_name":       self.strategy_name,
            "total_trades":        self.total_trades,
            "winning_trades":      self.winning_trades,
            "losing_trades":       self.losing_trades,
            "open_trades":         self.open_trades,
            "net_pnl":             round(self.net_pnl, 2),
            "gross_profit":        round(self.gross_profit, 2),
            "gross_loss":          round(self.gross_loss, 2),
            "avg_profit":          round(self.avg_profit, 2),
            "avg_loss":            round(self.avg_loss, 2),
            "largest_profit":      round(self.largest_profit, 2),
            "largest_loss":        round(self.largest_loss, 2),
            "win_rate":            round(self.win_rate, 4),
            "loss_rate":           round(self.loss_rate, 4),
            "profit_factor":       round(self.profit_factor, 4),
            "expectancy":          round(self.expectancy, 2),
            "risk_reward":         round(self.risk_reward, 4),
            "max_drawdown":        round(self.max_drawdown, 2),
            "max_drawdown_pct":    round(self.max_drawdown_pct, 4),
            "avg_holding_seconds": round(self.avg_holding_seconds, 1),
            "avg_quality_score":   round(self.avg_quality_score, 1),
            "rank_score":          round(self.rank_score, 4),
            "rank":                self.rank,
            "recommendation":      self.recommendation,
            "regime_breakdown":    self.regime_breakdown,
            "sector_breakdown":    self.sector_breakdown,
            "time_breakdown":      self.time_breakdown,
        }
