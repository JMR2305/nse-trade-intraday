"""IndicatorEngine — rolling technical indicator computation.

Pure indicator functions are deterministic: identical input bars → identical
output values.  All arithmetic uses Decimal for precision safety.

IndicatorEngine maintains bounded rolling buffers per (instrument_token, timeframe)
and recomputes indicators on each update.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal, getcontext
from typing import Deque, Dict, List, Optional, Tuple

from market_data.contracts import CompletedBar

logger = logging.getLogger(__name__)

# Use 28 significant digits for intermediate calculations
getcontext().prec = 28

_TWO = Decimal("2")
_ONE = Decimal("1")
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


# ---------------------------------------------------------------------------
# Pure indicator functions
# ---------------------------------------------------------------------------

def compute_sma(bars: List[CompletedBar], period: int) -> Optional[Decimal]:
    """Simple Moving Average of the last `period` close prices."""
    if len(bars) < period:
        return None
    closes = [b.close for b in bars[-period:]]
    return sum(closes, _ZERO) / Decimal(str(period))


def compute_ema(bars: List[CompletedBar], period: int) -> Optional[Decimal]:
    """Exponential Moving Average (EMA) using seed = SMA of first `period` bars."""
    if len(bars) < period:
        return None
    multiplier = _TWO / (Decimal(str(period)) + _ONE)
    # Seed with SMA
    ema = sum((b.close for b in bars[:period]), _ZERO) / Decimal(str(period))
    for bar in bars[period:]:
        ema = bar.close * multiplier + ema * (_ONE - multiplier)
    return ema


def compute_rsi(bars: List[CompletedBar], period: int = 14) -> Optional[Decimal]:
    """Relative Strength Index using Wilder's smoothing.

    Returns a value in [0, 100], or None when insufficient data.
    """
    if len(bars) < period + 1:
        return None

    closes = [b.close for b in bars]
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, _ZERO) for c in changes]
    losses = [max(-c, _ZERO) for c in changes]

    # Initial Wilder averages over first `period` values
    avg_gain = sum(gains[:period], _ZERO) / Decimal(str(period))
    avg_loss = sum(losses[:period], _ZERO) / Decimal(str(period))

    for i in range(period, len(changes)):
        avg_gain = (avg_gain * Decimal(str(period - 1)) + gains[i]) / Decimal(str(period))
        avg_loss = (avg_loss * Decimal(str(period - 1)) + losses[i]) / Decimal(str(period))

    if avg_loss == _ZERO:
        return _HUNDRED
    rs = avg_gain / avg_loss
    return _HUNDRED - (_HUNDRED / (_ONE + rs))


def compute_atr(bars: List[CompletedBar], period: int = 14) -> Optional[Decimal]:
    """Average True Range using Wilder's smoothing.

    Returns None when fewer than period+1 bars are available.
    """
    if len(bars) < period + 1:
        return None

    trs: List[Decimal] = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    if len(trs) < period:
        return None

    # Seed with simple average
    atr = sum(trs[:period], _ZERO) / Decimal(str(period))
    for tr in trs[period:]:
        atr = (atr * Decimal(str(period - 1)) + tr) / Decimal(str(period))
    return atr


def compute_adx(
    bars: List[CompletedBar], period: int = 14
) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
    """ADX, +DI, -DI using Wilder's smoothing.

    Returns (ADX, +DI, -DI) or None when insufficient data.
    Requires at least 2*period + 1 bars.
    """
    if len(bars) < 2 * period + 1:
        return None

    plus_dms: List[Decimal] = []
    minus_dms: List[Decimal] = []
    trs: List[Decimal] = []

    for i in range(1, len(bars)):
        high_diff = bars[i].high - bars[i - 1].high
        low_diff = bars[i - 1].low - bars[i].low
        tr = max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - bars[i - 1].close),
            abs(bars[i].low - bars[i - 1].close),
        )
        trs.append(tr)
        if high_diff > low_diff and high_diff > _ZERO:
            plus_dms.append(high_diff)
            minus_dms.append(_ZERO)
        elif low_diff > high_diff and low_diff > _ZERO:
            plus_dms.append(_ZERO)
            minus_dms.append(low_diff)
        else:
            plus_dms.append(_ZERO)
            minus_dms.append(_ZERO)

    if len(trs) < period:
        return None

    # Wilder seed
    smooth_tr = sum(trs[:period], _ZERO)
    smooth_plus_dm = sum(plus_dms[:period], _ZERO)
    smooth_minus_dm = sum(minus_dms[:period], _ZERO)

    _p = Decimal(str(period))

    dxs: List[Decimal] = []
    for i in range(period, len(trs)):
        smooth_tr = smooth_tr - smooth_tr / _p + trs[i]
        smooth_plus_dm = smooth_plus_dm - smooth_plus_dm / _p + plus_dms[i]
        smooth_minus_dm = smooth_minus_dm - smooth_minus_dm / _p + minus_dms[i]

        if smooth_tr == _ZERO:
            continue
        plus_di = _HUNDRED * smooth_plus_dm / smooth_tr
        minus_di = _HUNDRED * smooth_minus_dm / smooth_tr
        di_sum = plus_di + minus_di
        if di_sum == _ZERO:
            dxs.append(_ZERO)
        else:
            dxs.append(_HUNDRED * abs(plus_di - minus_di) / di_sum)

    if len(dxs) < period:
        return None

    # ADX = Wilder smoothing of DX
    adx = sum(dxs[:period], _ZERO) / _p
    for dx in dxs[period:]:
        adx = (adx * (_p - _ONE) + dx) / _p

    # Recompute final +DI / -DI from last smoothed values
    plus_di_final = _HUNDRED * smooth_plus_dm / smooth_tr if smooth_tr != _ZERO else _ZERO
    minus_di_final = _HUNDRED * smooth_minus_dm / smooth_tr if smooth_tr != _ZERO else _ZERO

    return adx, plus_di_final, minus_di_final


def compute_macd(
    bars: List[CompletedBar],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> Optional[Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]]:
    """MACD line, signal line, histogram.

    Returns (macd_line, signal, histogram).
    macd_line is available when len(bars) >= slow.
    signal and histogram are available when len(bars) >= slow + signal_period.
    """
    if len(bars) < slow:
        return None

    # Compute MACD line at each bar (EMA_fast - EMA_slow)
    macd_values: List[Decimal] = []
    for i in range(slow, len(bars) + 1):
        window = bars[:i]
        ema_f = compute_ema(window, fast)
        ema_s = compute_ema(window, slow)
        if ema_f is not None and ema_s is not None:
            macd_values.append(ema_f - ema_s)

    if not macd_values:
        return None

    macd_line = macd_values[-1]

    if len(macd_values) < signal_period:
        return macd_line, None, None

    # Signal = EMA of macd_values
    sig_multiplier = _TWO / (Decimal(str(signal_period)) + _ONE)
    signal = sum(macd_values[:signal_period], _ZERO) / Decimal(str(signal_period))
    for mv in macd_values[signal_period:]:
        signal = mv * sig_multiplier + signal * (_ONE - sig_multiplier)

    histogram = macd_line - signal
    return macd_line, signal, histogram


def compute_vwap(bars: List[CompletedBar]) -> Optional[Decimal]:
    """Session VWAP: sum(typical_price * volume) / sum(volume).

    Returns None when no bars or total volume is zero.
    """
    if not bars:
        return None
    total_tpv = _ZERO
    total_vol = _ZERO
    for bar in bars:
        tp = (bar.high + bar.low + bar.close) / Decimal("3")
        total_tpv += tp * bar.volume
        total_vol += bar.volume
    if total_vol == _ZERO:
        return None
    return total_tpv / total_vol


def compute_bollinger(
    bars: List[CompletedBar], period: int = 20, num_std: int = 2
) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
    """Bollinger Bands: (upper, middle/SMA, lower).

    Returns None when fewer than `period` bars are available.
    """
    if len(bars) < period:
        return None
    closes = [b.close for b in bars[-period:]]
    n = Decimal(str(period))
    mean = sum(closes, _ZERO) / n
    variance = sum((c - mean) ** 2 for c in closes) / n
    std = variance.sqrt()
    band = Decimal(str(num_std)) * std
    return mean + band, mean, mean - band


# ---------------------------------------------------------------------------
# IndicatorEngine
# ---------------------------------------------------------------------------

class IndicatorEngine:
    """Rolling indicator cache for multiple instruments and timeframes.

    Not coroutine-safe.  One instance per strategy runtime is the expected
    usage pattern; the coordinator owns the shared instance.
    """

    def __init__(self, max_bars: int = 150) -> None:
        self._max_bars = max_bars
        # _buffers[(instrument_token, timeframe)] -> deque of CompletedBar
        self._buffers: Dict[Tuple[str, str], Deque[CompletedBar]] = defaultdict(
            lambda: deque(maxlen=self._max_bars)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, instrument_token: str, timeframe: str) -> None:
        """Pre-create a buffer for (instrument_token, timeframe)."""
        key = (instrument_token, timeframe)
        if key not in self._buffers:
            self._buffers[key] = deque(maxlen=self._max_bars)

    def update(self, bar: CompletedBar, timeframe: str) -> None:
        """Append a bar to the buffer for its instrument_token + timeframe."""
        key = (bar.instrument_token, timeframe)
        self._buffers[key].append(bar)

    def get_bars(self, instrument_token: str, timeframe: str) -> List[CompletedBar]:
        """Return a copy of the current bar buffer."""
        key = (instrument_token, timeframe)
        if key not in self._buffers:
            return []
        return list(self._buffers[key])

    def get_indicators(self, instrument_token: str, timeframe: str) -> Dict[str, Decimal]:
        """Compute and return all available indicators for this (token, timeframe)."""
        key = (instrument_token, timeframe)
        if key not in self._buffers:
            return {}
        bars = list(self._buffers[key])
        if not bars:
            return {}
        return self._compute_all(bars)

    def get_all_timeframes(self, instrument_token: str) -> Dict[str, Dict[str, Decimal]]:
        """Return indicators for every timeframe subscribed for this instrument."""
        result: Dict[str, Dict[str, Decimal]] = {}
        for (token, tf) in self._buffers:
            if token == instrument_token:
                indicators = self.get_indicators(token, tf)
                if indicators:
                    result[tf] = indicators
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_all(self, bars: List[CompletedBar]) -> Dict[str, Decimal]:
        out: Dict[str, Decimal] = {}

        # Always include current close
        out["close"] = bars[-1].close

        # SMA
        for period in [10, 20, 50]:
            v = compute_sma(bars, period)
            if v is not None:
                out[f"sma_{period}"] = v

        # EMA
        for period in [9, 21]:
            v = compute_ema(bars, period)
            if v is not None:
                out[f"ema_{period}"] = v

        # RSI
        rsi = compute_rsi(bars, 14)
        if rsi is not None:
            out["rsi_14"] = rsi

        # ATR
        atr = compute_atr(bars, 14)
        if atr is not None:
            out["atr_14"] = atr

        # ADX
        adx_result = compute_adx(bars, 14)
        if adx_result is not None:
            adx, plus_di, minus_di = adx_result
            out["adx_14"] = adx
            out["plus_di_14"] = plus_di
            out["minus_di_14"] = minus_di

        # MACD
        macd_result = compute_macd(bars, 12, 26, 9)
        if macd_result is not None:
            macd_line, signal, histogram = macd_result
            if macd_line is not None:
                out["macd_line"] = macd_line
            if signal is not None:
                out["macd_signal"] = signal
            if histogram is not None:
                out["macd_histogram"] = histogram

        # VWAP
        vwap = compute_vwap(bars)
        if vwap is not None:
            out["vwap"] = vwap

        # Bollinger Bands
        bb = compute_bollinger(bars, 20, 2)
        if bb is not None:
            upper, middle, lower = bb
            out["bb_upper_20"] = upper
            out["bb_middle_20"] = middle
            out["bb_lower_20"] = lower

        return out
