"""
indicator_engine.py
Indicator Engine — computes all technical indicators from raw OHLCV data.

Indicators:
  EMA 9, 20, 50, 200 | RSI 14 | MACD 12/26/9 | VWAP (rolling 20)
  ATR 14 | ADX 14 | Bollinger Bands 20,2σ | Supertrend 10,3
  Volume 20-avg | Volume spike (ratio > 1.5)

Two output modes:
  - snapshot : latest bar values only (for signal/decision logic)
  - series   : full time-series (for charting / backtesting)

Designed to be imported by signal_engine, backtesting_engine, and the API.
"""

from datetime import datetime
from typing import TypedDict, Optional

import numpy as np
import pandas as pd


# ── TypedDicts ─────────────────────────────────────────────────────────────────

class IndicatorSnapshot(TypedDict):
    """Latest bar values for all indicators."""
    ema9:            float
    ema20:           float
    ema50:           float
    ema200:          float
    rsi:             float
    macd_line:       float
    macd_signal:     float
    macd_hist:       float
    vwap:            float
    atr:             float
    adx:             float
    bb_upper:        float
    bb_middle:       float
    bb_lower:        float
    supertrend:      float
    supertrend_dir:  str    # UP | DOWN
    volume_avg:      float
    volume_ratio:    float
    volume_spike:    bool


class IndicatorSeries(TypedDict):
    """Full time-series arrays (same length as input bars)."""
    time:           list
    open:           list
    high:           list
    low:            list
    close:          list
    volume:         list
    ema9:           list
    ema20:          list
    ema50:          list
    ema200:         list
    rsi:            list
    macd_line:      list
    macd_signal:    list
    macd_hist:      list
    bb_upper:       list
    bb_middle:      list
    bb_lower:       list
    supertrend:     list
    supertrend_dir: list
    atr:            list
    adx:            list
    vwap:           list
    volume_avg:     list


class IndicatorResult(TypedDict):
    symbol:      str
    interval:    str
    bar_count:   int
    snapshot:    IndicatorSnapshot
    series:      IndicatorSeries
    computed_at: str


# ── Core computations (pure pandas) ───────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9):
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    line = fast_ema - slow_ema
    signal = _ema(line, sig)
    hist = line - signal
    return line, signal, hist


def _bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return mid + std * sd, mid, mid - std * sd


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift()).abs()
    lpc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low  = df["low"]
    close = df["close"]

    plus_dm  = (high.diff()).clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # When both are positive, keep only the larger
    mask = plus_dm >= minus_dm
    plus_dm  = plus_dm.where(mask, 0)
    minus_dm = minus_dm.where(~mask, 0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr_s    = tr.ewm(com=period - 1, adjust=False).mean()
    plus_di  = 100 * (plus_dm.ewm(com=period - 1, adjust=False).mean() / atr_s.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(com=period - 1, adjust=False).mean() / atr_s.replace(0, np.nan))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(com=period - 1, adjust=False).mean()
    return adx.fillna(0)


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    atr = _atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    st = pd.Series(index=df.index, dtype=float)
    direction = pd.Series("UP", index=df.index)

    for i in range(1, len(df)):
        prev_st = st.iloc[i - 1] if not pd.isna(st.iloc[i - 1]) else lower.iloc[i]
        prev_dir = direction.iloc[i - 1]

        if prev_dir == "UP":
            cur_lower = max(lower.iloc[i], prev_st)
            if df["close"].iloc[i] < cur_lower:
                st.iloc[i] = upper.iloc[i]
                direction.iloc[i] = "DOWN"
            else:
                st.iloc[i] = cur_lower
                direction.iloc[i] = "UP"
        else:
            cur_upper = min(upper.iloc[i], prev_st)
            if df["close"].iloc[i] > cur_upper:
                st.iloc[i] = lower.iloc[i]
                direction.iloc[i] = "UP"
            else:
                st.iloc[i] = cur_upper
                direction.iloc[i] = "DOWN"

    st.iloc[0] = lower.iloc[0]
    return st, direction


def _vwap_rolling(df: pd.DataFrame, window: int = 20) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical * df["volume"]
    return pv.rolling(window).sum() / df["volume"].rolling(window).sum()


def _safe(val) -> float:
    """Convert NaN / inf to 0.0 safely."""
    if val is None:
        return 0.0
    try:
        f = float(val)
        return 0.0 if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return 0.0


def _safe_list(series: pd.Series) -> list:
    return [_safe(v) for v in series.values]


def _safe_str_list(series: pd.Series) -> list:
    return [str(v) if v is not None else "UP" for v in series.values]


# ── Core compute function ─────────────────────────────────────────────────────

def compute_indicators_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all indicators on a DataFrame with columns: open, high, low, close, volume.
    Returns enriched DataFrame with all indicator columns added.
    No lookahead — each row uses only past data.
    """
    df = df.copy()
    close  = df["close"]
    volume = df["volume"]

    df["ema9"]   = _ema(close, 9)
    df["ema20"]  = _ema(close, 20)
    df["ema50"]  = _ema(close, 50)
    df["ema200"] = _ema(close, 200)
    df["rsi"]    = _rsi(close)

    ml, ms, mh   = _macd(close)
    df["macd_line"]   = ml
    df["macd_signal"] = ms
    df["macd_hist"]   = mh

    bb_u, bb_m, bb_l = _bollinger(close)
    df["bb_upper"]  = bb_u
    df["bb_middle"] = bb_m
    df["bb_lower"]  = bb_l

    df["atr"] = _atr(df)
    df["adx"] = _adx(df)
    df["vwap"] = _vwap_rolling(df)

    st, st_dir = _supertrend(df)
    df["supertrend"]     = st
    df["supertrend_dir"] = st_dir

    df["volume_avg"]   = volume.rolling(20).mean()
    df["volume_ratio"] = volume / df["volume_avg"].replace(0, np.nan)

    return df


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_indicators(
    df: pd.DataFrame,
    symbol:   str = "",
    interval: str = "1d",
) -> IndicatorResult:
    """
    Compute all indicators and return structured result.

    Args:
        df       : DataFrame with columns open/high/low/close/volume (time index)
        symbol   : stock symbol for metadata
        interval : data interval for metadata

    Returns:
        IndicatorResult with snapshot (latest values) and full series.
    """
    if df.empty or len(df) < 10:
        # Return zero-filled result for empty data
        snap: IndicatorSnapshot = {k: 0.0 for k in IndicatorSnapshot.__annotations__}  # type: ignore
        snap["supertrend_dir"] = "UP"  # type: ignore
        snap["volume_spike"] = False  # type: ignore
        return IndicatorResult(
            symbol=symbol, interval=interval, bar_count=0,
            snapshot=snap,
            series=IndicatorSeries(  # type: ignore
                **{k: [] for k in IndicatorSeries.__annotations__}
            ),
            computed_at=datetime.now().isoformat(),
        )

    enriched = compute_indicators_df(df)
    last = enriched.iloc[-1]

    vol_ratio = _safe(last.get("volume_ratio", 0))

    snapshot = IndicatorSnapshot(
        ema9           = _safe(last.get("ema9")),
        ema20          = _safe(last.get("ema20")),
        ema50          = _safe(last.get("ema50")),
        ema200         = _safe(last.get("ema200")),
        rsi            = _safe(last.get("rsi")),
        macd_line      = _safe(last.get("macd_line")),
        macd_signal    = _safe(last.get("macd_signal")),
        macd_hist      = _safe(last.get("macd_hist")),
        vwap           = _safe(last.get("vwap")),
        atr            = _safe(last.get("atr")),
        adx            = _safe(last.get("adx")),
        bb_upper       = _safe(last.get("bb_upper")),
        bb_middle      = _safe(last.get("bb_middle")),
        bb_lower       = _safe(last.get("bb_lower")),
        supertrend     = _safe(last.get("supertrend")),
        supertrend_dir = str(last.get("supertrend_dir", "UP")),
        volume_avg     = _safe(last.get("volume_avg")),
        volume_ratio   = _safe(vol_ratio),
        volume_spike   = bool(vol_ratio >= 1.5),
    )

    times = (
        [str(t) for t in enriched.index.tolist()]
        if hasattr(enriched.index, "tolist")
        else [str(i) for i in range(len(enriched))]
    )

    series = IndicatorSeries(
        time          = times,
        open          = _safe_list(enriched["open"]),
        high          = _safe_list(enriched["high"]),
        low           = _safe_list(enriched["low"]),
        close         = _safe_list(enriched["close"]),
        volume        = _safe_list(enriched["volume"]),
        ema9          = _safe_list(enriched["ema9"]),
        ema20         = _safe_list(enriched["ema20"]),
        ema50         = _safe_list(enriched["ema50"]),
        ema200        = _safe_list(enriched["ema200"]),
        rsi           = _safe_list(enriched["rsi"]),
        macd_line     = _safe_list(enriched["macd_line"]),
        macd_signal   = _safe_list(enriched["macd_signal"]),
        macd_hist     = _safe_list(enriched["macd_hist"]),
        bb_upper      = _safe_list(enriched["bb_upper"]),
        bb_middle     = _safe_list(enriched["bb_middle"]),
        bb_lower      = _safe_list(enriched["bb_lower"]),
        supertrend    = _safe_list(enriched["supertrend"]),
        supertrend_dir= _safe_str_list(enriched["supertrend_dir"]),
        atr           = _safe_list(enriched["atr"]),
        adx           = _safe_list(enriched["adx"]),
        vwap          = _safe_list(enriched["vwap"]),
        volume_avg    = _safe_list(enriched["volume_avg"]),
    )

    return IndicatorResult(
        symbol      = symbol,
        interval    = interval,
        bar_count   = len(enriched),
        snapshot    = snapshot,
        series      = series,
        computed_at = datetime.now().isoformat(),
    )
