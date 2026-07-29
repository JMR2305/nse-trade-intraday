"""
hub_models.py — Phase 7.1
Feature flag, constants, shared dataclasses and scoring helpers.

READ-ONLY. ADVISORY-ONLY.
This module NEVER modifies orders, portfolio, strategies, AI, risk engine or signals.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return os.environ.get("MARKET_INTELLIGENCE_HUB_ENABLED", "false").lower() == "true"


def disabled_response() -> dict:
    return {
        "status": "DISABLED",
        "message": "Set MARKET_INTELLIGENCE_HUB_ENABLED=true to enable.",
    }


# ---------------------------------------------------------------------------
# Market regime constants
# ---------------------------------------------------------------------------

REGIME_BULL          = "BULL"
REGIME_BEAR          = "BEAR"
REGIME_SIDEWAYS      = "SIDEWAYS"
REGIME_TRENDING      = "TRENDING"
REGIME_HIGH_VOL      = "HIGH_VOLATILITY"
REGIME_LOW_VOL       = "LOW_VOLATILITY"
REGIME_BREAKOUT      = "BREAKOUT"
REGIME_REVERSAL      = "REVERSAL"
REGIME_TRANSITION    = "TRANSITION"

ALL_REGIMES = {
    REGIME_BULL, REGIME_BEAR, REGIME_SIDEWAYS, REGIME_TRENDING,
    REGIME_HIGH_VOL, REGIME_LOW_VOL, REGIME_BREAKOUT, REGIME_REVERSAL, REGIME_TRANSITION,
}

# Timeframe labels (short_key, label, period, interval)
TIMEFRAMES = [
    ("1m",  "1 Minute",  "7d",  "1m"),
    ("5m",  "5 Minute",  "5d",  "5m"),
    ("15m", "15 Minute", "5d",  "15m"),
    ("30m", "30 Minute", "1mo", "30m"),
    ("1h",  "1 Hour",    "1mo", "1h"),
    ("1d",  "Daily",     "3mo", "1d"),
    ("1wk", "Weekly",    "6mo", "1wk"),
]

NIFTY_SYMBOL = "^NSEI"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def health_grade(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 65: return "B"
    if score >= 50: return "C"
    return "D"


def health_trend(current: float, previous: float) -> str:
    delta = current - previous
    if delta > 3:   return "IMPROVING"
    if delta < -3:  return "WEAKENING"
    return "STABLE"


def clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


# ---------------------------------------------------------------------------
# Shared dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TimeframeResult:
    key: str
    label: str
    trend: str        # UP / DOWN / NEUTRAL / UNAVAILABLE
    strength: float   # 0–100
    ema9: float
    ema20: float
    price: float
    available: bool

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label,
            "trend": self.trend, "strength": round(self.strength, 2),
            "ema9": round(self.ema9, 2), "ema20": round(self.ema20, 2),
            "price": round(self.price, 2), "available": self.available,
        }


@dataclass
class SectorRank:
    rank: int
    sector: str
    relative_strength: float   # 0–100
    momentum: float            # -100 to 100
    participation: int         # number of stocks
    strong_buys: int
    buys: int
    watches: int
    ignores: int
    heat: str                  # HOT / WARM / NEUTRAL / COOL / COLD
    rotation_signal: str       # INFLOW / OUTFLOW / STABLE
    leadership: bool           # top sector

    def to_dict(self) -> dict:
        return {
            "rank": self.rank, "sector": self.sector,
            "relative_strength": round(self.relative_strength, 2),
            "momentum": round(self.momentum, 2),
            "participation": self.participation,
            "strong_buys": self.strong_buys, "buys": self.buys,
            "watches": self.watches, "ignores": self.ignores,
            "heat": self.heat, "rotation_signal": self.rotation_signal,
            "leadership": self.leadership,
        }


@dataclass
class WatchlistRank:
    rank: int
    symbol: str
    sector: str
    priority_score: float
    opportunity_score: float
    risk_score: float
    composite_score: float
    final_action: str
    regime_adjusted: bool
    reason: str
    price: float

    def to_dict(self) -> dict:
        return {
            "rank": self.rank, "symbol": self.symbol, "sector": self.sector,
            "priority_score": round(self.priority_score, 2),
            "opportunity_score": round(self.opportunity_score, 2),
            "risk_score": round(self.risk_score, 2),
            "composite_score": round(self.composite_score, 2),
            "final_action": self.final_action,
            "regime_adjusted": self.regime_adjusted,
            "reason": self.reason, "price": round(self.price, 2),
        }
