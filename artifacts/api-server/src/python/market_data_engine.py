"""
market_data_engine.py
Market Data Engine — fetches clean OHLCV candle data for NSE stocks.

Responsibilities:
  - Auto-append .NS suffix for NSE symbols (yfinance requires SYMBOL.NS)
  - Support intervals: 5m, 15m, 1h, 1d
  - Return typed Candle list with: time, open, high, low, close, volume
  - Handle NaN / missing rows safely
  - Fallback to synthetic mock data if yfinance fails

Future Zerodha: swap _fetch_yfinance() with kiteconnect historical data.
"""

import math
import random
from datetime import datetime, timedelta
from typing import Optional, TypedDict

import numpy as np
import pandas as pd
import yfinance as yf

# ── TypedDicts ─────────────────────────────────────────────────────────────────

class Candle(TypedDict):
    time:   str
    open:   float
    high:   float
    low:    float
    close:  float
    volume: float


class MarketDataResult(TypedDict):
    symbol:   str
    interval: str
    candles:  list
    bar_count: int
    source:   str   # "yfinance" | "mock"
    fetched_at: str


# ── Symbol helpers ─────────────────────────────────────────────────────────────

_YFINANCE_SKIP = {".NS", ".BO", "^NSEI", "^NSEBANK", "^INDIAVIX"}

def to_yf_symbol(symbol: str) -> str:
    """
    Convert NSE symbol to yfinance format.
    RELIANCE → RELIANCE.NS
    ^NSEI    → ^NSEI   (index, no suffix)
    """
    s = symbol.upper().strip()
    if any(s.endswith(x) or s.startswith("^") for x in _YFINANCE_SKIP):
        return s
    return s + ".NS"


# ── yfinance fetcher ───────────────────────────────────────────────────────────

_INTERVAL_PERIOD_MAP: dict[str, str] = {
    "5m":  "7d",
    "15m": "60d",
    "1h":  "730d",
    "1d":  "max",
}

_INTERVAL_VALID = {"5m", "15m", "30m", "1h", "1d", "1wk"}


def _fetch_yfinance(
    symbol: str,
    interval: str,
    period: Optional[str],
    start: Optional[str],
    end: Optional[str],
) -> pd.DataFrame:
    """
    Raw yfinance download. Returns DataFrame with OHLCV columns.
    Raises on failure.
    """
    yf_sym = to_yf_symbol(symbol)
    kwargs: dict = {"interval": interval}

    if start:
        kwargs["start"] = start
        if end:
            kwargs["end"] = end
    else:
        kwargs["period"] = period or _INTERVAL_PERIOD_MAP.get(interval, "3mo")

    ticker = yf.Ticker(yf_sym)
    df = ticker.history(**kwargs)

    if df is None or df.empty:
        raise ValueError(f"No data returned for {yf_sym}")

    df.index = pd.to_datetime(df.index)
    df = df[["Open", "High", "Low", "Close", "Volume"]].rename(
        columns={"Open": "open", "High": "high", "Low": "low",
                 "Close": "close", "Volume": "volume"}
    )
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    return df


def _df_to_candles(df: pd.DataFrame) -> list[Candle]:
    candles = []
    for ts, row in df.iterrows():
        t = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        candles.append(Candle(
            time   = t,
            open   = round(float(row["open"]),   2),
            high   = round(float(row["high"]),   2),
            low    = round(float(row["low"]),    2),
            close  = round(float(row["close"]),  2),
            volume = int(row["volume"]),
        ))
    return candles


# ── Mock data fallback ─────────────────────────────────────────────────────────

_SEED_PRICES: dict[str, float] = {
    "RELIANCE": 2950.0, "TCS": 3800.0, "INFY": 1720.0,
    "HDFCBANK": 1650.0, "ICICIBANK": 1250.0, "SBIN": 830.0,
    "WIPRO": 550.0, "LT": 3600.0, "BAJFINANCE": 6800.0, "MARUTI": 12500.0,
}

def _generate_mock_candles(
    symbol: str, n_bars: int, interval: str
) -> list[Candle]:
    """
    Synthetic OHLCV data using geometric Brownian motion.
    Used as fallback when yfinance fails.
    """
    base_price = _SEED_PRICES.get(symbol.upper().replace(".NS", ""), 1000.0)
    daily_vol = 0.015   # 1.5% daily volatility
    daily_drift = 0.0002

    # Scale for intraday
    scale = {"5m": 0.1, "15m": 0.2, "1h": 0.4, "1d": 1.0}.get(interval, 1.0)
    vol = daily_vol * scale
    drift = daily_drift * scale

    seed = sum(ord(c) for c in symbol) % 1000
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    prices = [base_price]
    for _ in range(n_bars):
        r = drift + vol * np_rng.standard_normal()
        prices.append(prices[-1] * (1 + r))

    now = datetime.now()
    # Step back from now
    step_map = {"5m": 5, "15m": 15, "1h": 60, "1d": 1440}
    step_min = step_map.get(interval, 1440)

    candles = []
    for i in range(n_bars):
        t = now - timedelta(minutes=step_min * (n_bars - i))
        c = prices[i + 1]
        o = prices[i]
        rng_h = rng.uniform(0.002, 0.012)
        rng_l = rng.uniform(0.002, 0.012)
        h = max(o, c) * (1 + rng_h)
        l = min(o, c) * (1 - rng_l)
        vol_base = int(base_price * 100000 / base_price)
        vol = int(vol_base * rng.uniform(0.5, 2.5))
        candles.append(Candle(
            time   = t.isoformat(),
            open   = round(o, 2),
            high   = round(h, 2),
            low    = round(l, 2),
            close  = round(c, 2),
            volume = vol,
        ))
    return candles


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_candles(
    symbol:   str,
    interval: str  = "1d",
    period:   Optional[str] = None,
    start:    Optional[str] = None,
    end:      Optional[str] = None,
    n_mock:   int = 300,
) -> MarketDataResult:
    """
    Fetch OHLCV candles for an NSE stock.

    Args:
        symbol   : NSE symbol (RELIANCE, TCS, etc.) or SYMBOL.NS
        interval : 5m | 15m | 1h | 1d
        period   : yfinance period string (3mo, 6mo, 1y, 2y, max)
        start    : ISO date string for start (overrides period)
        end      : ISO date string for end
        n_mock   : number of mock bars to generate on fallback

    Returns:
        MarketDataResult with candles list and metadata.
    """
    if interval not in _INTERVAL_VALID:
        interval = "1d"

    source = "yfinance"
    candles: list[Candle] = []

    try:
        df = _fetch_yfinance(symbol, interval, period, start, end)
        candles = _df_to_candles(df)
    except Exception:
        source = "mock"
        candles = _generate_mock_candles(symbol, n_mock, interval)

    return MarketDataResult(
        symbol     = symbol.upper().replace(".NS", ""),
        interval   = interval,
        candles    = candles,
        bar_count  = len(candles),
        source     = source,
        fetched_at = datetime.now().isoformat(),
    )


def fetch_candles_df(
    symbol:   str,
    interval: str  = "1d",
    period:   Optional[str] = None,
    start:    Optional[str] = None,
    end:      Optional[str] = None,
) -> pd.DataFrame:
    """
    Same as fetch_candles() but returns a pandas DataFrame.
    Columns: time (index), open, high, low, close, volume.
    Used internally by the backtesting engine.
    """
    result = fetch_candles(symbol, interval, period, start, end)
    candles = result["candles"]
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time").sort_index()
    return df
