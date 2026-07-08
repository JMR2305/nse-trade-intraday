"""
signal_engine.py
Generates BUY / SELL / HOLD signals for NSE stocks using:
  - RSI (14-period)
  - MACD (12, 26, 9)
  - Simple Moving Averages (SMA20, SMA50)

Each signal includes a confidence score (0-1) and a human-readable reason.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import TypedDict
from market_data import fetch_ohlcv


class Signal(TypedDict):
    stock: str
    time: str
    signal: str          # "BUY" | "SELL" | "HOLD"
    quantity: int
    price: float
    confidence: float    # 0.0 – 1.0
    reason: str


# ── Technical indicator helpers ──────────────────────────────────────────────

def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _calc_sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window).mean()


# ── Signal generation ─────────────────────────────────────────────────────────

def _score_signals(rsi: float, macd_hist: float, macd_cross: str, sma_trend: str) -> tuple[str, float, list[str]]:
    """
    Combine indicator outputs into a single signal + confidence + reason list.

    Returns: (signal, confidence, [reason strings])
    """
    bullish_points = 0
    bearish_points = 0
    reasons: list[str] = []

    # RSI
    if rsi < 30:
        bullish_points += 2
        reasons.append(f"RSI {rsi:.1f} — oversold territory (< 30)")
    elif rsi < 45:
        bullish_points += 1
        reasons.append(f"RSI {rsi:.1f} — approaching oversold zone")
    elif rsi > 70:
        bearish_points += 2
        reasons.append(f"RSI {rsi:.1f} — overbought territory (> 70)")
    elif rsi > 55:
        bearish_points += 1
        reasons.append(f"RSI {rsi:.1f} — approaching overbought zone")
    else:
        reasons.append(f"RSI {rsi:.1f} — neutral zone")

    # MACD histogram
    if macd_hist > 0:
        bullish_points += 1
        reasons.append("MACD histogram positive — bullish momentum")
    else:
        bearish_points += 1
        reasons.append("MACD histogram negative — bearish momentum")

    # MACD crossover
    if macd_cross == "bullish":
        bullish_points += 2
        reasons.append("MACD bullish crossover — signal line crossed above zero")
    elif macd_cross == "bearish":
        bearish_points += 2
        reasons.append("MACD bearish crossover — signal line crossed below zero")

    # SMA trend
    if sma_trend == "bullish":
        bullish_points += 1
        reasons.append("SMA20 > SMA50 — golden cross, uptrend confirmed")
    elif sma_trend == "bearish":
        bearish_points += 1
        reasons.append("SMA20 < SMA50 — death cross, downtrend detected")
    else:
        reasons.append("SMA20 ≈ SMA50 — no clear trend direction")

    total = bullish_points + bearish_points
    if total == 0:
        return "HOLD", 0.5, reasons

    bull_ratio = bullish_points / total

    if bull_ratio >= 0.70:
        signal = "BUY"
        confidence = round(0.50 + (bull_ratio - 0.70) * 1.67, 2)  # 0.50 – 1.0
    elif bull_ratio <= 0.30:
        signal = "SELL"
        confidence = round(0.50 + (0.30 - bull_ratio) * 1.67, 2)
    else:
        signal = "HOLD"
        confidence = round(0.50 - abs(bull_ratio - 0.50) * 2, 2)

    confidence = max(0.0, min(1.0, confidence))
    return signal, confidence, reasons


def generate_signal(symbol: str, available_cash: float = 5000.0) -> Signal:
    """
    Generate a trading signal for a single NSE stock.

    Args:
        symbol: NSE ticker without .NS suffix (e.g. 'RELIANCE')
        available_cash: cash available to determine position size

    Returns:
        Signal dict
    """
    df = fetch_ohlcv(symbol, period="3mo", interval="1d")

    if len(df) < 50:
        return Signal(
            stock=symbol.upper(),
            time=datetime.now().isoformat(),
            signal="HOLD",
            quantity=0,
            price=float(df["close"].iloc[-1]) if not df.empty else 0.0,
            confidence=0.0,
            reason="Insufficient historical data (need ≥ 50 days)",
        )

    close = df["close"]
    price = float(close.iloc[-1])

    # Calculate indicators
    rsi_series = _calc_rsi(close)
    rsi = float(rsi_series.iloc[-1])

    macd_line, signal_line, histogram = _calc_macd(close)
    macd_hist = float(histogram.iloc[-1])

    # Detect MACD crossover in last 3 bars
    macd_cross = "none"
    for i in range(-3, 0):
        prev_diff = macd_line.iloc[i - 1] - signal_line.iloc[i - 1]
        curr_diff = macd_line.iloc[i] - signal_line.iloc[i]
        if prev_diff < 0 < curr_diff:
            macd_cross = "bullish"
            break
        elif prev_diff > 0 > curr_diff:
            macd_cross = "bearish"
            break

    sma20 = float(_calc_sma(close, 20).iloc[-1])
    sma50 = float(_calc_sma(close, 50).iloc[-1])

    if sma20 > sma50 * 1.002:
        sma_trend = "bullish"
    elif sma20 < sma50 * 0.998:
        sma_trend = "bearish"
    else:
        sma_trend = "neutral"

    sig, confidence, reason_parts = _score_signals(rsi, macd_hist, macd_cross, sma_trend)

    # Position sizing: allocate up to 20% of available cash per trade
    allocation = min(available_cash * 0.20, available_cash)
    quantity = int(allocation / price) if price > 0 else 0

    return Signal(
        stock=symbol.upper(),
        time=datetime.now().isoformat(),
        signal=sig,
        quantity=quantity,
        price=round(price, 2),
        confidence=round(confidence, 2),
        reason="; ".join(reason_parts),
    )


def scan_watchlist(symbols: list[str], available_cash: float = 5000.0) -> list[Signal]:
    """
    Run signal generation across a list of NSE symbols.
    Errors for individual symbols are caught and returned as HOLD signals.
    """
    results: list[Signal] = []
    for sym in symbols:
        try:
            sig = generate_signal(sym, available_cash)
            results.append(sig)
        except Exception as e:
            results.append(
                Signal(
                    stock=sym.upper(),
                    time=datetime.now().isoformat(),
                    signal="HOLD",
                    quantity=0,
                    price=0.0,
                    confidence=0.0,
                    reason=f"Error fetching data: {str(e)}",
                )
            )
    return results
