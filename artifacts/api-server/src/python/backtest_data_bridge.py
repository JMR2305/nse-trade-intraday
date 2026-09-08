"""
backtest_data_bridge.py — cache-first daily OHLCV fetch for backtesting.

Task: wire all daily (1d) backtest data fetches through the same priority
chain the live scan path uses:

    1. Local daily_ohlcv_cache (PostgreSQL)  — sub-second, as-of filtered
    2. yfinance via market_data_engine       — for cache misses / gaps
    3. Write-back to the cache               — so the next run hits step 1

Intraday intervals (5m, 15m, 1h) are NOT cached; they pass straight
through to market_data_engine.fetch_candles_df unchanged.

Safety guarantees:
  * Read-only w.r.t. trading state — no live orders, no paper ledger writes.
  * Mock candles are NEVER written back to the cache.  If market_data_engine
    falls back to synthetic data the bridge reports source="mock" so callers
    can gate on it, and the cache stays clean.
  * No silent empty data: an empty result is returned as an empty DataFrame
    with an explicit source string; callers keep their existing
    "insufficient data" handling.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger("backtest_data_bridge")

# Sources returned by fetch_candles_for_backtest
SOURCE_CACHE = "local_ohlcv_cache"
SOURCE_YFINANCE = "yfinance"
SOURCE_MOCK = "mock"
SOURCE_NONE = "none"

# Calendar-day slack when checking whether the cache covers the requested
# window.  NSE holidays + weekends mean the first/last trading day can be a
# few calendar days inside the requested boundary dates.
_COVERAGE_SLACK_DAYS = 7

# yfinance-style period string → approximate calendar days
_PERIOD_DAYS = {
    "1mo": 31, "3mo": 92, "6mo": 183,
    "1y": 366, "2y": 731, "5y": 1827, "10y": 3653,
}


def _effective_window(
    period: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalise (period, start_date, end_date) into explicit ISO bounds.

    Explicit start/end always win.  A period-only request is anchored to
    end_date (or today) and converted to a start bound so the cache read,
    coverage check, and slice all match what yfinance would have returned —
    otherwise a cache enlarged by a prior long fetch would silently turn a
    3-month request into a multi-year evaluation.  "max"/unknown periods
    leave the start unbounded.
    """
    eff_end = end_date or date.today().isoformat()
    eff_start = start_date
    if eff_start is None and period:
        days = _PERIOD_DAYS.get(period.strip().lower())
        if days is not None:
            eff_start = (date.fromisoformat(eff_end) - timedelta(days=days)).isoformat()
    return eff_start, eff_end


def _cache_covers_window(
    df: pd.DataFrame,
    start_date: Optional[str],
    end_date: Optional[str],
) -> bool:
    """True if cached bars cover [start_date, end_date] within slack."""
    if df is None or df.empty:
        return False
    try:
        first_bar = df.index[0].date()
        last_bar = df.index[-1].date()
        if start_date:
            want_start = date.fromisoformat(start_date)
            if first_bar > want_start + timedelta(days=_COVERAGE_SLACK_DAYS):
                return False
        if end_date:
            want_end = date.fromisoformat(end_date)
            if last_bar < want_end - timedelta(days=_COVERAGE_SLACK_DAYS):
                return False
        return True
    except Exception:
        return False


def _slice_window(
    df: pd.DataFrame,
    start_date: Optional[str],
    end_date: Optional[str],
) -> pd.DataFrame:
    """Slice a DatetimeIndex DataFrame to [start_date, end_date] inclusive."""
    out = df
    if start_date:
        out = out[out.index >= pd.Timestamp(start_date)]
    if end_date:
        out = out[out.index <= pd.Timestamp(end_date)]
    return out


def fetch_candles_for_backtest(
    symbol: str,
    interval: str = "1d",
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Tuple[pd.DataFrame, str]:
    """
    Cache-first daily OHLCV fetch for backtesting.

    Returns (df, source) where source is one of:
      "local_ohlcv_cache" — served entirely from daily_ohlcv_cache
      "yfinance"          — fetched from yfinance (and written back to cache)
      "mock"              — market_data_engine fell back to synthetic data
                            (NEVER written to cache; callers should gate)
      "none"              — no data available at all

    Non-daily intervals bypass the cache entirely and go straight to
    market_data_engine (source reflects what that engine used).
    """
    from market_data_engine import fetch_candles_df, get_last_source

    sym = symbol.upper().replace(".NS", "")

    # ── Intraday: pass-through, no caching ────────────────────────────────
    if interval != "1d":
        df = fetch_candles_df(
            symbol, interval=interval, period=period,
            start=start_date, end=end_date,
        )
        src = get_last_source(sym)
        if df is None or df.empty:
            return pd.DataFrame(), SOURCE_NONE
        return df, (SOURCE_MOCK if src == "mock" else SOURCE_YFINANCE)

    # ── Step 1: local cache (as-of read over the effective window) ────────
    # Period-only requests are normalised to explicit bounds so a cache
    # enlarged by a prior long fetch never silently widens the evaluation.
    eff_start, eff_end = _effective_window(period, start_date, end_date)
    try:
        from ohlcv_cache_store import read_symbol_from_cache, write_symbol_to_cache
        cached = read_symbol_from_cache(sym, min_bars=1, end_date=eff_end)
    except Exception as exc:
        logger.warning("backtest_data_bridge: cache read failed for %s: %s", sym, exc)
        cached = None
        write_symbol_to_cache = None  # type: ignore[assignment]

    if cached is not None and _cache_covers_window(cached, eff_start, eff_end):
        sliced = _slice_window(cached, eff_start, eff_end)
        if not sliced.empty:
            out = sliced.copy()
            out.index.name = "time"
            return out, SOURCE_CACHE

    # ── Step 2: yfinance via market_data_engine ───────────────────────────
    df = fetch_candles_df(
        symbol, interval="1d", period=period,
        start=start_date, end=end_date,
    )
    src = get_last_source(sym)

    if df is None or df.empty:
        return pd.DataFrame(), SOURCE_NONE

    if src == "mock":
        # Synthetic fallback data — surface it explicitly, never cache it.
        logger.warning(
            "backtest_data_bridge: %s returned MOCK candles — not cached", sym
        )
        return df, SOURCE_MOCK

    # ── Step 3: write-back so the next run hits the cache ─────────────────
    try:
        if write_symbol_to_cache is not None:
            written = write_symbol_to_cache(sym, df, source="yfinance")
            if written:
                logger.info(
                    "backtest_data_bridge: wrote %d bars for %s back to cache",
                    written, sym,
                )
    except Exception as exc:
        logger.warning("backtest_data_bridge: write-back failed for %s: %s", sym, exc)

    return df, SOURCE_YFINANCE
