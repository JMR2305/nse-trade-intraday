"""
multi_timeframe_analyser.py — Phase 7.1
Multi-timeframe trend analysis for NIFTY 50 index.

Analyses: 1m, 5m, 15m, 30m, 1h, Daily, Weekly
Generates: unified trend agreement, alignment score.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import time
from typing import List, Optional
from .hub_models import (
    TimeframeResult, TIMEFRAMES, NIFTY_SYMBOL, clamp
)


def analyse_timeframes() -> dict:
    """
    Fetch NIFTY at each timeframe and compute EMA9 vs EMA20 trend.
    Falls back gracefully when a timeframe is unavailable.
    Returns alignment score, agreement count, and per-timeframe details.
    """
    t0 = time.monotonic()
    results: List[TimeframeResult] = []

    for key, label, period, interval in TIMEFRAMES:
        tf = _analyse_one(key, label, period, interval)
        results.append(tf)

    available   = [r for r in results if r.available]
    up_count    = sum(1 for r in available if r.trend == "UP")
    down_count  = sum(1 for r in available if r.trend == "DOWN")
    total_avail = len(available)

    alignment_score = clamp(
        (up_count / total_avail * 100) if total_avail > 0 else 50.0
    )
    agreement = _agreement_label(up_count, down_count, total_avail)
    primary_trend = "UP" if up_count > down_count else "DOWN" if down_count > up_count else "NEUTRAL"

    elapsed_ms = (time.monotonic() - t0) * 1000

    return {
        "timeframes": [r.to_dict() for r in results],
        "alignment_score": round(alignment_score, 2),
        "agreement": agreement,
        "primary_trend": primary_trend,
        "up_count": up_count,
        "down_count": down_count,
        "neutral_count": total_avail - up_count - down_count,
        "available_count": total_avail,
        "total_timeframes": len(results),
        "elapsed_ms": round(elapsed_ms, 1),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _analyse_one(key: str, label: str, period: str, interval: str) -> TimeframeResult:
    """Fetch NIFTY for one timeframe and compute EMA9 vs EMA20."""
    try:
        df = _fetch(NIFTY_SYMBOL, period, interval)
        if df is None or len(df) < 10:
            return _unavailable(key, label)

        close = df["Close"].squeeze()
        ema9  = _ema(close, 9).iloc[-1]
        ema20 = _ema(close, 20).iloc[-1]
        price = float(close.iloc[-1])

        if ema9 > ema20 * 1.001:
            trend = "UP"
        elif ema9 < ema20 * 0.999:
            trend = "DOWN"
        else:
            trend = "NEUTRAL"

        # Strength: how far apart are EMA9 and EMA20 relative to price?
        strength = clamp(abs(ema9 - ema20) / price * 5000)

        return TimeframeResult(
            key=key, label=label, trend=trend,
            strength=strength, ema9=float(ema9), ema20=float(ema20),
            price=price, available=True,
        )
    except Exception:
        return _unavailable(key, label)


def _fetch(symbol: str, period: str, interval: str):
    """Fetch OHLCV data via yfinance with a 10-second timeout guard."""
    import yfinance as yf
    import threading

    result = [None]
    exc    = [None]

    def _dl():
        try:
            result[0] = yf.download(
                symbol, period=period, interval=interval,
                auto_adjust=True, progress=False, timeout=8,
            )
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_dl, daemon=True)
    t.start()
    t.join(timeout=12)

    if exc[0] is not None:
        raise exc[0]
    return result[0]


def _ema(series, period: int):
    return series.ewm(span=period, adjust=False).mean()


def _unavailable(key: str, label: str) -> TimeframeResult:
    return TimeframeResult(
        key=key, label=label, trend="UNAVAILABLE",
        strength=0.0, ema9=0.0, ema20=0.0, price=0.0, available=False,
    )


def _agreement_label(up: int, down: int, total: int) -> str:
    if total == 0:
        return "INSUFFICIENT_DATA"
    ratio = up / total
    if ratio >= 0.85:  return "STRONG_BULLISH"
    if ratio >= 0.65:  return "BULLISH"
    if ratio >= 0.50:  return "MILDLY_BULLISH"
    if ratio <= 0.15:  return "STRONG_BEARISH"
    if ratio <= 0.35:  return "BEARISH"
    if ratio <= 0.50:  return "MILDLY_BEARISH"
    return "MIXED"
