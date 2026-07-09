"""
strategies.py
Strategy Framework — defines entry/exit rules for paper-trading strategies.

Each strategy:
  - check_entry()         : Should we open a position? Returns (bool, reason)
  - check_exit()          : Should we close a position? Returns (bool, reason)
  - inspect_entry_rules() : Per-rule pass/fail (rule inspector / debug mode)
  - compute_stop_loss()   : Where is the stop loss?
  - compute_target()      : Where is the profit target?
  - best_regime           : Market condition this strategy works best in

Strategies available:
  trend_rider        : EMA stack + MACD + RSI + VWAP — multi-confirmation trend
  breakout_hunter    : BB upper breakout + ADX + volume surge
  mean_reversion     : RSI oversold + BB lower bounce (ranging markets)
  ema_cross          : Simple EMA9/EMA20 golden-cross
  macd_cross         : MACD line crosses above signal line
  supertrend_follow  : Supertrend direction flip to UP

Rule: DO NOT change existing strategy logic (trend_rider, breakout_hunter, mean_reversion).
"""

import math
from typing import TypedDict

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
    id:           str
    name:         str
    description:  str
    type:         str       # TREND | BREAKOUT | MEAN_REVERSION
    best_interval: str
    best_regime:  str
    risk_pct:     float
    entry_rules:  list
    exit_rules:   list


# ── Base class ────────────────────────────────────────────────────────────────

class StrategyBase:
    """
    All strategies inherit from this.
    The backtesting engine calls these methods bar-by-bar.
    Indicators are passed as a pandas row (Series) from the enriched DataFrame.
    """
    id:            str   = ""
    name:          str   = ""
    description:   str   = ""
    type:          str   = "TREND"
    best_interval: str   = "1d"
    best_regime:   str   = ""
    risk_pct:      float = 0.01
    entry_rules:   list  = []
    exit_rules:    list  = []

    def check_entry(self, row: pd.Series, prev: pd.Series) -> tuple[bool, str]:
        return False, "Base strategy — no entry logic"

    def check_exit(
        self, row: pd.Series, prev: pd.Series,
        entry_price: float, stop_loss: float, target: float,
    ) -> tuple[bool, str]:
        return False, ""

    def inspect_entry_rules(self, row: pd.Series, prev: pd.Series) -> list:
        """Return per-rule pass/fail dicts for the Rule Inspector."""
        return []

    def compute_stop_loss(self, row: pd.Series, entry_price: float) -> float:
        atr = _sf(row.get("atr", 0)) or entry_price * 0.02
        return round(entry_price - 2 * atr, 2)

    def compute_target(self, entry_price: float, stop_loss: float) -> float:
        risk = entry_price - stop_loss
        return round(entry_price + 2 * risk, 2)

    def to_info(self) -> StrategyInfo:
        return StrategyInfo(
            id=self.id, name=self.name, description=self.description,
            type=self.type, best_interval=self.best_interval,
            best_regime=self.best_regime, risk_pct=self.risk_pct,
            entry_rules=self.entry_rules, exit_rules=self.exit_rules,
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXISTING STRATEGIES  (logic unchanged — only best_regime attribute added)
# ══════════════════════════════════════════════════════════════════════════════

class TrendRider(StrategyBase):
    """
    Classic EMA trend-following with multi-indicator confirmation.
    Entry: EMA9>EMA20>EMA50, RSI 40–68, MACD bullish, price>VWAP
    Stop:  entry − 2×ATR  |  Target: entry + 3×ATR  (3:1 RR)
    Exit:  EMA9 crosses below EMA20
    """
    id            = "trend_rider"
    name          = "Trend Rider"
    description   = "EMA stack + MACD + RSI + VWAP — classic trend following"
    type          = "TREND"
    best_interval = "1d"
    best_regime   = "Strong uptrend"
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

    def check_entry(self, row, prev):
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

    def inspect_entry_rules(self, row, prev):
        ema9  = _sf(row.get("ema9",  0))
        ema20 = _sf(row.get("ema20", 0))
        ema50 = _sf(row.get("ema50", 0))
        rsi   = _sf(row.get("rsi",   50))
        macd_line   = _sf(row.get("macd_line",   0))
        macd_signal = _sf(row.get("macd_signal", 0))
        vwap  = _sf(row.get("vwap",  0))
        close = _sf(row.get("close", 0))
        return [
            {"rule": "EMA9 > EMA20 > EMA50 (stacked bullish)",
             "current_value": f"EMA9={ema9:.1f}, EMA20={ema20:.1f}, EMA50={ema50:.1f}",
             "required_value": "EMA9 > EMA20 > EMA50",
             "passed": ema9 > ema20 > ema50},
            {"rule": "RSI between 40 and 68",
             "current_value": f"RSI={rsi:.1f}",
             "required_value": "40 ≤ RSI ≤ 68",
             "passed": 40 <= rsi <= 68},
            {"rule": "MACD line above signal",
             "current_value": f"MACD={macd_line:.3f}, Signal={macd_signal:.3f}",
             "required_value": "MACD > Signal",
             "passed": macd_line > macd_signal},
            {"rule": "Close above rolling VWAP",
             "current_value": f"Close={close:.1f}, VWAP={vwap:.1f}",
             "required_value": "Close > VWAP",
             "passed": vwap > 0 and close > vwap},
        ]

    def check_exit(self, row, prev, entry_price, stop_loss, target):
        ema9   = _sf(row.get("ema9",   0))
        ema20  = _sf(row.get("ema20",  0))
        prev9  = _sf(prev.get("ema9",  0))
        prev20 = _sf(prev.get("ema20", 0))
        if prev9 > prev20 and ema9 < ema20:
            return True, "EMA9 crossed below EMA20 (death cross)"
        return False, ""

    def compute_stop_loss(self, row, entry_price):
        atr = _sf(row.get("atr", 0)) or entry_price * 0.02
        return round(entry_price - 2 * atr, 2)

    def compute_target(self, entry_price, stop_loss):
        risk = entry_price - stop_loss
        return round(entry_price + 3 * risk, 2)


class BreakoutHunter(StrategyBase):
    """
    BB upper breakout + ADX strength + volume surge + Supertrend UP.
    Stop: BB middle  |  Target: entry + 2×(BB upper − BB middle)
    Exit: Close < BB middle OR Supertrend flips DOWN
    """
    id            = "breakout_hunter"
    name          = "Breakout Hunter"
    description   = "BB upper breakout + ADX strength + volume surge"
    type          = "BREAKOUT"
    best_interval = "1d"
    best_regime   = "High volatility breakout"
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

    def check_entry(self, row, prev):
        close    = _sf(row.get("close",    0))
        bb_upper = _sf(row.get("bb_upper", 0))
        adx      = _sf(row.get("adx",      0))
        vol_ratio = _sf(row.get("volume_ratio", 0))
        st_dir   = str(row.get("supertrend_dir", "DOWN"))
        if not (close > 0 and bb_upper > 0):
            return False, "indicators not ready"
        if close > bb_upper and adx >= 25 and vol_ratio >= 1.5 and st_dir == "UP":
            return True, (f"BB breakout (close {close:.0f} > upper {bb_upper:.0f}), "
                          f"ADX {adx:.0f}, vol {vol_ratio:.1f}×, ST=UP")
        return False, ""

    def inspect_entry_rules(self, row, prev):
        close    = _sf(row.get("close",    0))
        bb_upper = _sf(row.get("bb_upper", 0))
        adx      = _sf(row.get("adx",      0))
        vol_ratio = _sf(row.get("volume_ratio", 0))
        st_dir   = str(row.get("supertrend_dir", "DOWN"))
        return [
            {"rule": "Close > Bollinger Band upper (breakout)",
             "current_value": f"Close={close:.1f}, BB Upper={bb_upper:.1f}",
             "required_value": "Close > BB Upper",
             "passed": close > bb_upper and bb_upper > 0},
            {"rule": "ADX > 25 (strong trend)",
             "current_value": f"ADX={adx:.1f}",
             "required_value": "ADX ≥ 25",
             "passed": adx >= 25},
            {"rule": "Volume ≥ 1.5× 20-period average",
             "current_value": f"Vol Ratio={vol_ratio:.2f}×",
             "required_value": "Vol Ratio ≥ 1.5×",
             "passed": vol_ratio >= 1.5},
            {"rule": "Supertrend direction is UP",
             "current_value": f"Supertrend={st_dir}",
             "required_value": "UP",
             "passed": st_dir == "UP"},
        ]

    def check_exit(self, row, prev, entry_price, stop_loss, target):
        close  = _sf(row.get("close",    0))
        bb_mid = _sf(row.get("bb_middle",0))
        st_dir = str(row.get("supertrend_dir", "UP"))
        if bb_mid > 0 and close < bb_mid:
            return True, "Close dropped below BB middle"
        if st_dir == "DOWN":
            return True, "Supertrend flipped to DOWN"
        return False, ""

    def compute_stop_loss(self, row, entry_price):
        bb_mid = _sf(row.get("bb_middle", 0))
        if bb_mid > 0:
            return round(bb_mid, 2)
        atr = _sf(row.get("atr", 0)) or entry_price * 0.02
        return round(entry_price - 2 * atr, 2)

    def compute_target(self, entry_price, stop_loss):
        risk = entry_price - stop_loss
        return round(entry_price + 2 * risk, 2)


class MeanReversion(StrategyBase):
    """
    RSI oversold + BB lower band bounce (non-trending market).
    Entry: RSI<38, close≤BB lower×1.01, ADX<35
    Stop: entry − 1.5×ATR  |  Target: BB middle
    Exit: RSI>55 OR close>BB middle
    """
    id            = "mean_reversion"
    name          = "Mean Reversion"
    description   = "RSI oversold + BB lower band bounce (non-trending market)"
    type          = "MEAN_REVERSION"
    best_interval = "1d"
    best_regime   = "Ranging / sideways"
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

    def check_entry(self, row, prev):
        close    = _sf(row.get("close",    0))
        rsi      = _sf(row.get("rsi",     50))
        bb_lower = _sf(row.get("bb_lower", 0))
        adx      = _sf(row.get("adx",      0))
        if not (close > 0 and bb_lower > 0):
            return False, "indicators not ready"
        if rsi < 38 and close <= bb_lower * 1.01 and adx < 35:
            return True, f"RSI {rsi:.0f} oversold, at BB lower {bb_lower:.0f}, ADX {adx:.0f}"
        return False, ""

    def inspect_entry_rules(self, row, prev):
        close    = _sf(row.get("close",    0))
        rsi      = _sf(row.get("rsi",     50))
        bb_lower = _sf(row.get("bb_lower", 0))
        adx      = _sf(row.get("adx",      0))
        return [
            {"rule": "RSI < 38 (oversold)",
             "current_value": f"RSI={rsi:.1f}",
             "required_value": "RSI < 38",
             "passed": rsi < 38},
            {"rule": "Close within 1% of BB lower band",
             "current_value": f"Close={close:.1f}, BB Lower={bb_lower:.1f}",
             "required_value": "Close ≤ BB Lower × 1.01",
             "passed": (close <= bb_lower * 1.01) if bb_lower > 0 else False},
            {"rule": "ADX < 35 (not strongly trending)",
             "current_value": f"ADX={adx:.1f}",
             "required_value": "ADX < 35",
             "passed": adx < 35},
        ]

    def check_exit(self, row, prev, entry_price, stop_loss, target):
        close  = _sf(row.get("close",    0))
        rsi    = _sf(row.get("rsi",     50))
        bb_mid = _sf(row.get("bb_middle",0))
        if rsi > 55:
            return True, f"RSI recovered to {rsi:.0f}"
        if bb_mid > 0 and close > bb_mid:
            return True, "Close crossed above BB middle"
        return False, ""

    def compute_stop_loss(self, row, entry_price):
        atr = _sf(row.get("atr", 0)) or entry_price * 0.015
        return round(entry_price - 1.5 * atr, 2)

    def compute_target(self, entry_price, stop_loss):
        risk = entry_price - stop_loss
        return round(entry_price + 1.5 * risk, 2)


# ══════════════════════════════════════════════════════════════════════════════
# NEW STRATEGIES  (for Strategy Lab comparison)
# ══════════════════════════════════════════════════════════════════════════════

class EMACross(StrategyBase):
    """
    Simple EMA9 / EMA20 golden-cross entry.
    Entry: EMA9 crosses above EMA20 AND RSI < 70
    Stop:  entry − 2×ATR  |  Target: entry + 2×ATR  (2:1 RR)
    Exit:  EMA9 crosses below EMA20 (death cross)
    """
    id            = "ema_cross"
    name          = "EMA Cross"
    description   = "EMA9 golden cross above EMA20 — simple momentum entry"
    type          = "TREND"
    best_interval = "1d"
    best_regime   = "Trending (momentum)"
    risk_pct      = 0.01
    entry_rules = [
        "EMA9 crosses above EMA20 (golden cross)",
        "RSI < 70 (not overbought)",
    ]
    exit_rules = [
        "EMA9 crosses below EMA20 (death cross)",
        "Stop hit: entry − 2×ATR",
        "Target hit: entry + 2×ATR",
    ]

    def check_entry(self, row, prev):
        ema9  = _sf(row.get("ema9",  0))
        ema20 = _sf(row.get("ema20", 0))
        prev9 = _sf(prev.get("ema9",  0))
        prev20= _sf(prev.get("ema20", 0))
        rsi   = _sf(row.get("rsi",  50))
        if not (ema9 > 0 and ema20 > 0):
            return False, "indicators not ready"
        golden_cross = prev9 <= prev20 and ema9 > ema20
        rsi_ok = rsi < 70
        if golden_cross and rsi_ok:
            return True, f"EMA9 crossed above EMA20 (golden cross), RSI={rsi:.0f}"
        return False, ""

    def inspect_entry_rules(self, row, prev):
        ema9  = _sf(row.get("ema9",  0))
        ema20 = _sf(row.get("ema20", 0))
        prev9 = _sf(prev.get("ema9",  0))
        prev20= _sf(prev.get("ema20", 0))
        rsi   = _sf(row.get("rsi",  50))
        golden_cross = prev9 <= prev20 and ema9 > ema20
        return [
            {"rule": "EMA9 crosses above EMA20 (golden cross)",
             "current_value": f"prev EMA9={prev9:.1f}≤EMA20={prev20:.1f} → EMA9={ema9:.1f}>EMA20={ema20:.1f}",
             "required_value": "prev EMA9 ≤ prev EMA20 AND EMA9 > EMA20",
             "passed": golden_cross},
            {"rule": "RSI < 70 (not overbought)",
             "current_value": f"RSI={rsi:.1f}",
             "required_value": "RSI < 70",
             "passed": rsi < 70},
        ]

    def check_exit(self, row, prev, entry_price, stop_loss, target):
        ema9  = _sf(row.get("ema9",  0))
        ema20 = _sf(row.get("ema20", 0))
        prev9 = _sf(prev.get("ema9",  0))
        prev20= _sf(prev.get("ema20", 0))
        if prev9 > prev20 and ema9 < ema20:
            return True, "EMA9 crossed below EMA20 (death cross)"
        return False, ""


class MACDCross(StrategyBase):
    """
    MACD line crosses above signal line — momentum entry.
    Entry: MACD crosses above signal AND RSI < 65
    Stop:  entry − 2×ATR  |  Target: entry + 2.5×ATR
    Exit:  MACD crosses below signal
    """
    id            = "macd_cross"
    name          = "MACD Cross"
    description   = "MACD line crosses above signal — momentum entry"
    type          = "TREND"
    best_interval = "1d"
    best_regime   = "Trending (momentum)"
    risk_pct      = 0.01
    entry_rules = [
        "MACD line crosses above signal line",
        "RSI < 65 (not overbought)",
    ]
    exit_rules = [
        "MACD line crosses below signal line (bearish)",
        "Stop hit: entry − 2×ATR",
        "Target hit: entry + 2.5×ATR",
    ]

    def check_entry(self, row, prev):
        macd  = _sf(row.get("macd_line",   0))
        sig   = _sf(row.get("macd_signal", 0))
        pmacd = _sf(prev.get("macd_line",  0))
        psig  = _sf(prev.get("macd_signal",0))
        rsi   = _sf(row.get("rsi", 50))
        cross_up = pmacd <= psig and macd > sig
        if cross_up and rsi < 65:
            return True, f"MACD crossed above signal, RSI={rsi:.0f}"
        return False, ""

    def inspect_entry_rules(self, row, prev):
        macd  = _sf(row.get("macd_line",   0))
        sig   = _sf(row.get("macd_signal", 0))
        pmacd = _sf(prev.get("macd_line",  0))
        psig  = _sf(prev.get("macd_signal",0))
        rsi   = _sf(row.get("rsi", 50))
        cross_up = pmacd <= psig and macd > sig
        return [
            {"rule": "MACD line crosses above signal",
             "current_value": f"MACD={macd:.3f}, Signal={sig:.3f}",
             "required_value": "prev MACD ≤ prev Signal AND MACD > Signal",
             "passed": cross_up},
            {"rule": "RSI < 65 (not overbought)",
             "current_value": f"RSI={rsi:.1f}",
             "required_value": "RSI < 65",
             "passed": rsi < 65},
        ]

    def check_exit(self, row, prev, entry_price, stop_loss, target):
        macd  = _sf(row.get("macd_line",   0))
        sig   = _sf(row.get("macd_signal", 0))
        pmacd = _sf(prev.get("macd_line",  0))
        psig  = _sf(prev.get("macd_signal",0))
        if pmacd > psig and macd < sig:
            return True, "MACD crossed below signal (bearish)"
        return False, ""

    def compute_target(self, entry_price, stop_loss):
        risk = entry_price - stop_loss
        return round(entry_price + 2.5 * risk, 2)


class SupertrendFollow(StrategyBase):
    """
    Trade in the direction of Supertrend when it flips to UP.
    Entry: Supertrend flips DOWN→UP AND close above Supertrend line
    Stop:  Supertrend line value at entry bar
    Target: entry + 3×ATR
    Exit:  Supertrend flips to DOWN
    """
    id            = "supertrend_follow"
    name          = "Supertrend"
    description   = "Trade Supertrend direction flip to UP — sustained trend"
    type          = "TREND"
    best_interval = "1d"
    best_regime   = "Sustained trend"
    risk_pct      = 0.01
    entry_rules = [
        "Supertrend flips from DOWN to UP",
        "Close above Supertrend line",
    ]
    exit_rules = [
        "Supertrend flips to DOWN",
        "Stop hit: Supertrend line at entry bar",
        "Target hit: entry + 3×ATR",
    ]

    def check_entry(self, row, prev):
        st_dir  = str(row.get("supertrend_dir",  "DOWN"))
        pst_dir = str(prev.get("supertrend_dir", "DOWN"))
        close   = _sf(row.get("close",      0))
        st_line = _sf(row.get("supertrend", 0))
        if not (close > 0):
            return False, "indicators not ready"
        flip_up  = pst_dir == "DOWN" and st_dir == "UP"
        above_st = st_line > 0 and close > st_line
        if flip_up and above_st:
            return True, f"Supertrend flipped UP, close={close:.0f} > ST={st_line:.0f}"
        return False, ""

    def inspect_entry_rules(self, row, prev):
        st_dir  = str(row.get("supertrend_dir",  "DOWN"))
        pst_dir = str(prev.get("supertrend_dir", "DOWN"))
        close   = _sf(row.get("close",      0))
        st_line = _sf(row.get("supertrend", 0))
        flip_up  = pst_dir == "DOWN" and st_dir == "UP"
        above_st = st_line > 0 and close > st_line
        return [
            {"rule": "Supertrend flips from DOWN to UP",
             "current_value": f"prev={pst_dir}, current={st_dir}",
             "required_value": "prev=DOWN AND current=UP",
             "passed": flip_up},
            {"rule": "Close above Supertrend line",
             "current_value": f"Close={close:.1f}, ST Line={st_line:.1f}",
             "required_value": "Close > Supertrend",
             "passed": above_st},
        ]

    def check_exit(self, row, prev, entry_price, stop_loss, target):
        st_dir = str(row.get("supertrend_dir", "UP"))
        if st_dir == "DOWN":
            return True, "Supertrend flipped to DOWN"
        return False, ""

    def compute_stop_loss(self, row, entry_price):
        st_line = _sf(row.get("supertrend", 0))
        if 0 < st_line < entry_price:
            return round(st_line, 2)
        atr = _sf(row.get("atr", 0)) or entry_price * 0.02
        return round(entry_price - 2 * atr, 2)

    def compute_target(self, entry_price, stop_loss):
        risk = entry_price - stop_loss
        return round(entry_price + 3 * risk, 2)


# ── Registry & lab ────────────────────────────────────────────────────────────

STRATEGY_REGISTRY: dict[str, StrategyBase] = {
    "trend_rider":       TrendRider(),
    "breakout_hunter":   BreakoutHunter(),
    "mean_reversion":    MeanReversion(),
    "ema_cross":         EMACross(),
    "macd_cross":        MACDCross(),
    "supertrend_follow": SupertrendFollow(),
}

# Ordered list used by the Strategy Lab (run all 6 for comparison)
LAB_STRATEGY_IDS = [
    "ema_cross",
    "macd_cross",
    "mean_reversion",
    "trend_rider",
    "breakout_hunter",
    "supertrend_follow",
]


def get_strategy(name: str) -> StrategyBase:
    s = STRATEGY_REGISTRY.get(name.lower())
    if s is None:
        raise ValueError(f"Unknown strategy '{name}'. Valid: {list(STRATEGY_REGISTRY.keys())}")
    return s


def list_strategies() -> list[StrategyInfo]:
    return [s.to_info() for s in STRATEGY_REGISTRY.values()]
