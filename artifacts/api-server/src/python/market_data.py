"""
market_data.py
Fetches OHLCV price data for NSE-listed stocks using yfinance.
NSE symbols are appended with the .NS suffix automatically.
Designed so this module can be swapped for Zerodha Kite Connect later
by replacing fetch_ohlcv() and get_ltp() with Kite API calls.
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional


def _nse_symbol(symbol: str) -> str:
    """Ensure the symbol has the .NS suffix for Yahoo Finance."""
    symbol = symbol.upper().strip()
    if not symbol.endswith(".NS"):
        symbol += ".NS"
    return symbol


def fetch_ohlcv(symbol: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV data for an NSE stock.

    Args:
        symbol: NSE ticker (e.g. 'RELIANCE' or 'RELIANCE.NS')
        period:  yfinance period string ('1d','5d','1mo','3mo','6mo','1y','2y','5y','10y','ytd','max')
        interval: yfinance interval string ('1m','2m','5m','15m','30m','60m','90m','1h','1d','5d','1wk','1mo','3mo')

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume
    """
    ticker = _nse_symbol(symbol)
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No data returned for {ticker}. Check the symbol.")
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    df = df.dropna()
    return df


def get_ltp(symbol: str) -> Optional[float]:
    """
    Get Last Traded Price for an NSE stock.

    Returns:
        Latest closing price, or None if unavailable.
    """
    try:
        df = fetch_ohlcv(symbol, period="5d", interval="1d")
        if df.empty:
            return None
        return float(df["close"].iloc[-1])
    except Exception:
        return None


def get_multiple_ltp(symbols: list[str]) -> dict[str, Optional[float]]:
    """
    Batch fetch LTPs for multiple NSE symbols.

    Returns:
        Dict mapping symbol -> last price (or None on failure)
    """
    result = {}
    for sym in symbols:
        result[sym.upper()] = get_ltp(sym)
    return result
