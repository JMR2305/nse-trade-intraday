"""
strategies.py
Strategy Framework — defines entry/exit rules for paper-trading strategies.

Each strategy:
  - check_entry()         : Should we open a position? Returns (bool, reason)
  - check_exit()          : Should we close a position? Returns (bool, reason)
  - inspect_entry_rules() : Per-rule pass/fail breakdown (for rule inspector / debug)
  - stop_loss()           : Where is the stop loss?
  - target()              : Where is the profit target?
  - risk_pct              : fraction of capital risked per trade (e.g. 0.01 = 1%)

Available strategies:
  trend_rider      : EMA crossover + MACD + RSI + VWAP confirmation
  breakout_hunter  : Bollinger Band upper breakout + ADX + volume
  mean_reversion   : RSI oversold + BB lower bounce

Future strategies can subclass StrategyBase and register in STRATEGY_REGISTRY.
"""

import math
from dataclasses import dataclass
from typing import TypedDict

import numpy as np
import pandas as pd


# ── Safe float helper ─────────────────────────────────────────────────────────

def _sf(v, default: float = 0.0) -> float:
    """Safe float — returns default on NaN / Inf / TypeError."""
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


# ── Info TypedDict (returned by GET /api/strategies) ─────────────────────────

class StrategyInfo(TypedDict):
    id:          str
    name:        str
    description: str
    type:        str   # TREND | BREAKOUT | MEAN_REVERSION
    best_interval: str
    risk_pct:    float
    entry_rules: list
    exit_rules:  list


# ── Base class ────────────────────────────────────────────────────────────────

class StrategyBase:
    """
    All strategies inherit from this.
    The backtesting engine calls these methods bar-by-bar.
    Indicators are passed as a pandas row (Series) from the enriched DataFrame.
    """
    id:          str = ""
    name:        str = ""
    description: str = ""
    type:        str = "TREND"
    best_interval: str = "1d"
    risk_pct:    float = 0.01   # 1% of capital per trade
    entry_rules: list = []
    exit_rules:  list = []

    def check_entry(
        self,
        row: pd.Series,
        prev: pd.Series,
    ) -> tuple[bool, str]:
        """
        Decide whether to enter a position on this bar.

        Args:
            row  : current bar's indicator values (Series)
            prev : previous bar's indicator values

        Returns:
            (should_enter, reason_string)
        """
        return False, "Base strategy — no entry logic"

    def check_exit(
        self,
        row: pd.Series,
        prev: pd.Series,
        entry_price: float,
        stop_loss: float,
        target: float,
    ) -> tuple[bool, str]:
        """
        Decide whether to exit the current position on this bar.
        Stop/target hits are handled by the backtest engine directly;
        this covers SIGNAL-based exits only.
        """
        return False, ""

    def inspect_entry_rules(
        self,
        row: pd.Series,
        prev: pd.Series,
    ) -> list:
        """
        Return per-rule pass/fail for the Rule Inspector and debug mode.

        Returns a list of dicts:
            {
                "rule":           str   — human-readable rule description
                "current_value":  str   — what the indicator shows right now
                "required_value": str   — what is needed to pass
                "passed":         bool  — True if the rule is satisfied
            }
        """
        return []

    def compute_stop_loss(self, row: pd.Series, entry_price: float) -> float:
        """ATR-based stop by default: entry - 2×ATR."""
        atr = _sf(row.get("atr", 0)) or entry_price * 0.02
        return round(entry_price - 2 * atr, 2)

    def compute_target(self, entry_price: float, stop_loss: float) -> float:
        """2:1 RR target by default."""
        risk = entry_price - stop_loss
        return round(entry_price + 2 * risk, 2)

    def to_info(self) -> StrategyInfo:
        return StrategyInfo(
            id=self.id, name=self.name, description=self.description,
            type=self.type, best_interval=self.best_interval,
            risk_pct=self.risk_pct,
            entry_rules=self.entry_rules, exit_rules=self.exit_rules,
        )


# ── Strategy 1: Trend Rider ───────────────────────────────────────────────────

class TrendRider(StrategyBase):
    """
    Classic EMA trend-following with multi-indicator confirmation.

    Entry:
      EMA9 > EMA20 > EMA50 (stacked EMAs)
      RSI 40–68 (trend, not overbought)
      MACD line > MACD signal (bullish)
      Price > VWAP

    Stop:  entry − 2×ATR
    Target: entry + 3×ATR  (3:1 RR)

    Exit signal: EMA9 crosses below EMA20
    """
    id            = "trend_rider"
    name          = "Trend Rider"
    description   = "EMA stack + MACD + RSI + VWAP — classic trend following"
    type          = "TREND"
    best_interval = "1d"
    risk_pct      = 0.01
    entry_rules = [
        "EMA9 > EMA20 > EMA50 (stacked bullish)",
        "RSI between 40 and 68",
        "MACD line above signal line",
        "Close above rolling VWAP",
    ]
    exit_rules = [
        "EMA9 crosses below EMA20",
        "Stop hit: entry − 2×ATR",
        "Target hit: entry + 3×ATR",
    ]

    def check_entry(self, row: pd.Series, prev: pd.Series) -> tuple[bool, str]:
        ema9  = _sf(row.get("ema9",  0))
        ema20 = _sf(row.get("ema20", 0))
        ema50 = _sf(row.get("ema50", 0))
        rsi   = _sf(row.get("rsi",   50))
        macd_line   = _sf(row.get("macd_line",   0))
        macd_signal = _sf(row.get("macd_signal", 0))
        vwap  = _sf(row.get("vwap",  0))
        close = _sf(row.get("close", 0))

        if not (ema9 > 0 and ema20 > 0 and ema50 > 0):
            return False, "indicators not ready"

        ema_stacked  = ema9 > ema20 > ema50
        rsi_ok       = 40 <= rsi <= 68
        macd_bullish = macd_line > macd_signal
        above_vwap   = vwap > 0 and close > vwap

        if ema_stacked and rsi_ok and macd_bullish and above_vwap:
            return True, f"EMA stack ✓, RSI {rsi:.0f}, MACD bullish, above VWAP"
        return False, ""

    def inspect_entry_rules(self, row: pd.Series, prev: pd.Series) -> list:
        ema9  = _sf(row.get("ema9",  0))
        ema20 = _sf(row.get("ema20", 0))
        ema50 = _sf(row.get("ema50", 0))
        rsi   = _sf(row.get("rsi",   50))
        macd_line   = _sf(row.get("macd_line",   0))
        macd_signal = _sf(row.get("macd_signal", 0))
        vwap  = _sf(row.get("vwap",  0))
        close = _sf(row.get("close", 0))

        ema_stacked  = ema9 > ema20 > ema50
        rsi_ok       = 40 <= rsi <= 68
        macd_bullish = macd_line > macd_signal
        above_vwap   = vwap > 0 and close > vwap

        return [
            {
                "rule":           "EMA9 > EMA20 > EMA50 (stacked bullish)",
                "current_value":  f"EMA9={ema9:.1f}, EMA20={ema20:.1f}, EMA50={ema50:.1f}",
                "required_value": "EMA9 > EMA20 > EMA50",
                "passed":         ema_stacked,
            },
            {
                "rule":           "RSI between 40 and 68",
                "current_value":  f"RSI={rsi:.1f}",
                "required_value": "40 ≤ RSI ≤ 68",
                "passed":         rsi_ok,
            },
            {
                "rule":           "MACD line above signal",
                "current_value":  f"MACD={macd_line:.3f}, Signal={macd_signal:.3f}",
                "required_value": "MACD > Signal",
                "passed":         macd_bullish,
            },
            {
                "rule":           "Close above rolling VWAP",
                "current_value":  f"Close={close:.1f}, VWAP={vwap:.1f}",
                "required_value": "Close > VWAP",
                "passed":         above_vwap,
            },
        ]

    def check_exit(self, row, prev, entry_price, stop_loss, target) -> tuple[bool, str]:
        ema9   = _sf(row.get("ema9",   0))
        ema20  = _sf(row.get("ema20",  0))
        prev9  = _sf(prev.get("ema9",  0))
        prev20 = _sf(prev.get("ema20", 0))
        if prev9 > prev20 and ema9 < ema20:
            return True, "EMA9 crossed below EMA20 (death cross)"
        return False, ""

    def compute_stop_loss(self, row: pd.Series, entry_price: float) -> float:
        atr = _sf(row.get("atr", 0)) or entry_price * 0.02
        return round(entry_price - 2 * atr, 2)

    def compute_target(self, entry_price: float, stop_loss: float) -> float:
        risk = entry_price - stop_loss
        return round(entry_price + 3 * risk, 2)   # 3:1 RR


# ── Strategy 2: Breakout Hunter ───────────────────────────────────────────────

class BreakoutHunter(StrategyBase):
    """
    Volatility breakout when price closes above Bollinger upper band
    with ADX strength and volume confirmation.

    Entry:
      Close > BB upper band
      ADX > 25 (trending market)
      Volume ≥ 1.5× average
      Supertrend direction = UP

    Stop:  BB middle band at entry
    Target: entry + 2 × (BB upper − BB middle)

    Exit signal: Close drops below BB middle OR Supertrend flips DOWN
    """
    id            = "breakout_hunter"
    name          = "Breakout Hunter"
    description   = "BB upper breakout + ADX strength + volume surge"
    type          = "BREAKOUT"
    best_interval = "1d"
    risk_pct      = 0.01
    entry_rules = [
        "Close > Bollinger Band upper (breakout)",
        "ADX > 25 (strong trend)",
        "Volume ≥ 1.5× 20-period average",
        "Supertrend direction is UP",
    ]
    exit_rules = [
        "Close drops below BB middle",
        "Supertrend flips to DOWN",
        "Stop hit: BB middle at entry bar",
        "Target hit: entry + 2×(BB upper − BB middle)",
    ]

    def check_entry(self, row: pd.Series, prev: pd.Series) -> tuple[bool, str]:
        close    = _sf(row.get("close",    0))
        bb_upper = _sf(row.get("bb_upper", 0))
        bb_mid   = _sf(row.get("bb_middle",0))
        adx      = _sf(row.get("adx",      0))
        vol_ratio = _sf(row.get("volume_ratio", 0))
        st_dir   = str(row.get("supertrend_dir", "DOWN"))

        if not (close > 0 and bb_upper > 0):
            return False, "indicators not ready"

        breakout   = close > bb_upper
        adx_strong = adx >= 25
        vol_ok     = vol_ratio >= 1.5
        st_up      = st_dir == "UP"

        if breakout and adx_strong and vol_ok and st_up:
            return True, (f"BB breakout (close {close:.0f} > upper {bb_upper:.0f}), "
                          f"ADX {adx:.0f}, vol {vol_ratio:.1f}×, ST=UP")
        return False, ""

    def inspect_entry_rules(self, row: pd.Series, prev: pd.Series) -> list:
        close    = _sf(row.get("close",    0))
        bb_upper = _sf(row.get("bb_upper", 0))
        adx      = _sf(row.get("adx",      0))
        vol_ratio = _sf(row.get("volume_ratio", 0))
        st_dir   = str(row.get("supertrend_dir", "DOWN"))

        breakout   = close > bb_upper and bb_upper > 0
        adx_strong = adx >= 25
        vol_ok     = vol_ratio >= 1.5
        st_up      = st_dir == "UP"

        return [
            {
                "rule":           "Close > Bollinger Band upper (breakout)",
                "current_value":  f"Close={close:.1f}, BB Upper={bb_upper:.1f}",
                "required_value": "Close > BB Upper",
                "passed":         breakout,
            },
            {
                "rule":           "ADX > 25 (strong trend)",
                "current_value":  f"ADX={adx:.1f}",
                "required_value": "ADX ≥ 25",
                "passed":         adx_strong,
            },
            {
                "rule":           "Volume ≥ 1.5× 20-period average",
                "current_value":  f"Vol Ratio={vol_ratio:.2f}×",
                "required_value": "Vol Ratio ≥ 1.5×",
                "passed":         vol_ok,
            },
            {
                "rule":           "Supertrend direction is UP",
                "current_value":  f"Supertrend={st_dir}",
                "required_value": "UP",
                "passed":         st_up,
            },
        ]

    def check_exit(self, row, prev, entry_price, stop_loss, target) -> tuple[bool, str]:
        close  = _sf(row.get("close",    0))
        bb_mid = _sf(row.get("bb_middle",0))
        st_dir = str(row.get("supertrend_dir", "UP"))

        if bb_mid > 0 and close < bb_mid:
            return True, "Close dropped below BB middle"
        if st_dir == "DOWN":
            return True, "Supertrend flipped to DOWN"
        return False, ""

    def compute_stop_loss(self, row: pd.Series, entry_price: float) -> float:
        bb_mid = _sf(row.get("bb_middle", 0))
        if bb_mid > 0:
            return round(bb_mid, 2)
        atr = _sf(row.get("atr", 0)) or entry_price * 0.02
        return round(entry_price - 2 * atr, 2)

    def compute_target(self, entry_price: float, stop_loss: float) -> float:
        risk = entry_price - stop_loss
        return round(entry_price + 2 * risk, 2)


# ── Strategy 3: Mean Reversion ────────────────────────────────────────────────

class MeanReversion(StrategyBase):
    """
    Buy oversold dips in an uptrending stock.

    Entry:
      RSI < 38 (oversold — Indian markets rarely hit 30; 38 is practical)
      Close ≤ BB lower band × 1.01 (within 1% of BB lower)
      ADX < 35 (not in a strong trend — avoids catching a falling knife)

    Stop:  entry − 1.5×ATR
    Target: BB middle band

    Exit signal: RSI > 55 OR Close > BB middle
    """
    id            = "mean_reversion"
    name          = "Mean Reversion"
    description   = "RSI oversold + BB lower band bounce (non-trending market)"
    type          = "MEAN_REVERSION"
    best_interval = "1d"
    risk_pct      = 0.01
    entry_rules = [
        "RSI < 38 (oversold)",
        "Close within 1% of BB lower band",
        "ADX < 35 (not in strong trending market)",
    ]
    exit_rules = [
        "RSI rises above 55",
        "Close crosses above BB middle",
        "Stop hit: entry − 1.5×ATR",
        "Target: BB middle or entry + 1.5×ATR",
    ]

    def check_entry(self, row: pd.Series, prev: pd.Series) -> tuple[bool, str]:
        close    = _sf(row.get("close",    0))
        rsi      = _sf(row.get("rsi",     50))
        bb_lower = _sf(row.get("bb_lower", 0))
        adx      = _sf(row.get("adx",      0))

        if not (close > 0 and bb_lower > 0):
            return False, "indicators not ready"

        oversold  = rsi < 38
        at_bb_low = close <= bb_lower * 1.01
        not_trend = adx < 35

        if oversold and at_bb_low and not_trend:
            return True, f"RSI {rsi:.0f} oversold, at BB lower {bb_lower:.0f}, ADX {adx:.0f}"
        return False, ""

    def inspect_entry_rules(self, row: pd.Series, prev: pd.Series) -> list:
        close    = _sf(row.get("close",    0))
        rsi      = _sf(row.get("rsi",     50))
        bb_lower = _sf(row.get("bb_lower", 0))
        adx      = _sf(row.get("adx",      0))

        oversold  = rsi < 38
        at_bb_low = (close <= bb_lower * 1.01) if bb_lower > 0 else False
        not_trend = adx < 35

        return [
            {
                "rule":           "RSI < 38 (oversold)",
                "current_value":  f"RSI={rsi:.1f}",
                "required_value": "RSI < 38",
                "passed":         oversold,
            },
            {
                "rule":           "Close within 1% of BB lower band",
                "current_value":  f"Close={close:.1f}, BB Lower={bb_lower:.1f}",
                "required_value": "Close ≤ BB Lower × 1.01",
                "passed":         at_bb_low,
            },
            {
                "rule":           "ADX < 35 (not strongly trending)",
                "current_value":  f"ADX={adx:.1f}",
                "required_value": "ADX < 35",
                "passed":         not_trend,
            },
        ]

    def check_exit(self, row, prev, entry_price, stop_loss, target) -> tuple[bool, str]:
        close  = _sf(row.get("close",    0))
        rsi    = _sf(row.get("rsi",     50))
        bb_mid = _sf(row.get("bb_middle",0))

        if rsi > 55:
            return True, f"RSI recovered to {rsi:.0f}"
        if bb_mid > 0 and close > bb_mid:
            return True, "Close crossed above BB middle"
        return False, ""

    def compute_stop_loss(self, row: pd.Series, entry_price: float) -> float:
        atr = _sf(row.get("atr", 0)) or entry_price * 0.015
        return round(entry_price - 1.5 * atr, 2)

    def compute_target(self, entry_price: float, stop_loss: float) -> float:
        risk = entry_price - stop_loss
        return round(entry_price + 1.5 * risk, 2)


# ── Registry ──────────────────────────────────────────────────────────────────

STRATEGY_REGISTRY: dict[str, StrategyBase] = {
    "trend_rider":     TrendRider(),
    "breakout_hunter": BreakoutHunter(),
    "mean_reversion":  MeanReversion(),
}


def get_strategy(name: str) -> StrategyBase:
    """Look up strategy by id. Raises ValueError if unknown."""
    s = STRATEGY_REGISTRY.get(name.lower())
    if s is None:
        valid = list(STRATEGY_REGISTRY.keys())
        raise ValueError(f"Unknown strategy '{name}'. Valid: {valid}")
    return s


def list_strategies() -> list[StrategyInfo]:
    """Return all registered strategy infos (for GET /api/strategies)."""
    return [s.to_info() for s in STRATEGY_REGISTRY.values()]
