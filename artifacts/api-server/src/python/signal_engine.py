"""
signal_engine.py
Professional rule-based signal engine for NSE stocks.

Indicators:
  EMA 9, 20, 50, 200 | RSI 14 | MACD 12/26/9 | VWAP (rolling 20-day)
  Bollinger Bands (20, 2) | ATR 14 | ADX 14 | Supertrend (10, 3)
  Volume spike detection | Support & Resistance levels

Signals:  STRONG_BUY | BUY | WATCH | SELL | STRONG_SELL | NO_TRADE

Scoring (max 100):
  BUY  side: VWAP+15 | EMA20>50+15 | EMA9>20+10 | MACD bull+15 |
             RSI 45-65+10 | Vol spike+10 | Near resistance+10 |
             Supertrend bull+10 | ADX>20+5
  SELL side: same weights, mirrored conditions

Decision:  80-100 → STRONG | 65-79 → BUY/SELL | 50-64 → WATCH | <50 → NO_TRADE
Risk:      ATR-based stop-loss and target
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import TypedDict
from market_data import fetch_ohlcv


# ── Type definitions ───────────────────────────────────────────────────────────

class Signal(TypedDict):
    stock: str
    time: str
    signal: str          # STRONG_BUY | BUY | WATCH | SELL | STRONG_SELL | NO_TRADE
    quantity: int
    price: float
    confidence: float    # 0–100
    reasons: list[str]
    risk_level: str      # LOW | MEDIUM | HIGH
    stop_loss: float
    target: float


# ── Indicator helpers ──────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, sig)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    mid = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    upper = mid + std * sigma
    lower = mid - std * sigma
    return upper, mid, lower


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat(
        [(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def _adx(df: pd.DataFrame, period: int = 14):
    h, l = df["high"].values, df["low"].values
    prev_h = np.roll(h, 1)
    prev_l = np.roll(l, 1)
    prev_h[0] = h[0]
    prev_l[0] = l[0]

    up_move = h - prev_h
    down_move = prev_l - l

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    idx = df.index
    atr_s = _atr(df, period)
    plus_di = 100 * (
        pd.Series(plus_dm, index=idx).ewm(com=period - 1, min_periods=period).mean()
        / atr_s.replace(0, np.nan)
    )
    minus_di = 100 * (
        pd.Series(minus_dm, index=idx).ewm(com=period - 1, min_periods=period).mean()
        / atr_s.replace(0, np.nan)
    )
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    adx = dx.ewm(com=period - 1, min_periods=period).mean()
    return adx, plus_di, minus_di


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """Returns a Series of direction: +1 (bullish) or -1 (bearish)."""
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    atr_vals = _atr(df, period).values
    hl2 = (high + low) / 2.0

    upper_raw = hl2 + multiplier * atr_vals
    lower_raw = hl2 - multiplier * atr_vals

    upper = upper_raw.copy()
    lower = lower_raw.copy()
    direction = np.ones(n, dtype=int)

    for i in range(1, n):
        # Final lower band: take higher of new lower or previous (trend support)
        lower[i] = lower_raw[i] if (lower_raw[i] > lower[i - 1] or close[i - 1] < lower[i - 1]) else lower[i - 1]
        # Final upper band: take lower of new upper or previous (trend resistance)
        upper[i] = upper_raw[i] if (upper_raw[i] < upper[i - 1] or close[i - 1] > upper[i - 1]) else upper[i - 1]

        # Direction: flip on breakout of previous band
        if direction[i - 1] == -1 and close[i] > upper[i - 1]:
            direction[i] = 1
        elif direction[i - 1] == 1 and close[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

    return pd.Series(direction, index=df.index)


def _vwap_rolling(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Rolling VWAP over `window` daily bars — acts as a dynamic fair-value line."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].replace(0, np.nan)
    cum_tp_vol = (typical * vol).rolling(window).sum()
    cum_vol = vol.rolling(window).sum()
    return cum_tp_vol / cum_vol


def _support_resistance(close: pd.Series, lookback: int = 60, n: int = 3):
    """Identify the top-n support and resistance levels from recent price swings."""
    subset = close.tail(lookback)
    local_max = subset[
        (subset.shift(1) < subset) & (subset.shift(-1) < subset)
    ]
    local_min = subset[
        (subset.shift(1) > subset) & (subset.shift(-1) > subset)
    ]
    resistance = sorted(local_max.values, reverse=True)[:n]
    support = sorted(local_min.values)[:n]
    return support, resistance


# ── Scoring engine ─────────────────────────────────────────────────────────────

def _score(
    price: float,
    prev_close: float,
    vwap: float,
    ema9: float,
    ema20: float,
    ema50: float,
    macd_line_curr: float,
    signal_line_curr: float,
    macd_line_prev: float,
    signal_line_prev: float,
    rsi_curr: float,
    rsi_prev: float,
    vol_curr: float,
    vol_avg: float,
    supertrend_dir: int,
    adx_val: float,
    support: list,
    resistance: list,
    atr: float,
) -> tuple[int, int, list[str], list[str]]:
    """
    Compute buy_score and sell_score (each 0–100) with reason strings.
    Returns (buy_score, sell_score, buy_reasons, sell_reasons).
    """
    buy_score = 0
    sell_score = 0
    buy_reasons: list[str] = []
    sell_reasons: list[str] = []

    tol = atr * 0.10  # 10% of ATR as proximity tolerance

    # ── VWAP (+15) ──────────────────────────────────────────────────────────────
    if price > vwap:
        buy_score += 15
        buy_reasons.append(f"Price ₹{price:.2f} above VWAP ₹{vwap:.2f} (+15)")
    else:
        sell_score += 15
        sell_reasons.append(f"Price ₹{price:.2f} below VWAP ₹{vwap:.2f} (+15)")

    # ── EMA20 vs EMA50 (+15) ────────────────────────────────────────────────────
    if ema20 > ema50:
        buy_score += 15
        buy_reasons.append(f"EMA20 {ema20:.2f} > EMA50 {ema50:.2f} — bullish trend (+15)")
    else:
        sell_score += 15
        sell_reasons.append(f"EMA20 {ema20:.2f} < EMA50 {ema50:.2f} — bearish trend (+15)")

    # ── EMA9 vs EMA20 (+10) ─────────────────────────────────────────────────────
    if ema9 > ema20:
        buy_score += 10
        buy_reasons.append(f"EMA9 {ema9:.2f} > EMA20 {ema20:.2f} — short-term momentum up (+10)")
    else:
        sell_score += 10
        sell_reasons.append(f"EMA9 {ema9:.2f} < EMA20 {ema20:.2f} — short-term momentum down (+10)")

    # ── MACD (+15) ──────────────────────────────────────────────────────────────
    macd_bull = macd_line_curr > signal_line_curr
    macd_cross_up = (macd_line_prev <= signal_line_prev) and (macd_line_curr > signal_line_curr)
    macd_cross_dn = (macd_line_prev >= signal_line_prev) and (macd_line_curr < signal_line_curr)

    if macd_bull:
        buy_score += 15
        tag = " (fresh crossover)" if macd_cross_up else ""
        buy_reasons.append(f"MACD bullish{tag}: line {macd_line_curr:.3f} > signal {signal_line_curr:.3f} (+15)")
    else:
        sell_score += 15
        tag = " (fresh crossover)" if macd_cross_dn else ""
        sell_reasons.append(f"MACD bearish{tag}: line {macd_line_curr:.3f} < signal {signal_line_curr:.3f} (+15)")

    # ── RSI (+10) ───────────────────────────────────────────────────────────────
    if 45 <= rsi_curr <= 65:
        buy_score += 10
        buy_reasons.append(f"RSI {rsi_curr:.1f} in bullish momentum zone 45–65 (+10)")
    elif rsi_curr > 70 and rsi_curr < rsi_prev:
        sell_score += 10
        sell_reasons.append(f"RSI {rsi_curr:.1f} overbought and turning down (+10)")
    elif rsi_curr < 30:
        buy_reasons.append(f"RSI {rsi_curr:.1f} oversold — potential reversal (neutral)")
    elif rsi_curr > 70:
        sell_reasons.append(f"RSI {rsi_curr:.1f} overbought (no downward turn yet)")

    # ── Volume spike (+10) ──────────────────────────────────────────────────────
    vol_ratio = vol_curr / vol_avg if vol_avg > 0 else 1.0
    is_red_candle = price < prev_close

    if vol_ratio >= 1.5 and not is_red_candle:
        buy_score += 10
        buy_reasons.append(f"Volume {vol_ratio:.1f}x avg on up-move — strong buying pressure (+10)")
    elif vol_ratio >= 1.5 and is_red_candle:
        sell_score += 10
        sell_reasons.append(f"Volume {vol_ratio:.1f}x avg on down-move — strong selling pressure (+10)")

    # ── Support / Resistance proximity (+10) ────────────────────────────────────
    near_resistance = any(abs(price - r) <= tol or price > r for r in resistance)
    near_support = any(abs(price - s) <= tol or price < s for s in support)

    if resistance and near_resistance:
        buy_score += 10
        buy_reasons.append(f"Price near/breaking resistance — breakout potential (+10)")
    if support and near_support:
        sell_score += 10
        sell_reasons.append(f"Price near/breaking support — breakdown risk (+10)")

    # ── Supertrend (+10) ────────────────────────────────────────────────────────
    if supertrend_dir == 1:
        buy_score += 10
        buy_reasons.append("Supertrend bullish — trend confirmation (+10)")
    else:
        sell_score += 10
        sell_reasons.append("Supertrend bearish — trend confirmation (+10)")

    # ── ADX (+5) ────────────────────────────────────────────────────────────────
    if adx_val > 20:
        buy_score += 5
        sell_score += 5
        note = f"ADX {adx_val:.1f} — strong trend ({'+5' if buy_score >= sell_score else '+5'})"
        buy_reasons.append(note)
        sell_reasons.append(note)

    return buy_score, sell_score, buy_reasons, sell_reasons


# ── Main signal generation ─────────────────────────────────────────────────────

def generate_signal(symbol: str, available_cash: float = 5000.0) -> Signal:
    """
    Generate a professional trading signal for a single NSE stock.
    Requires ≥ 60 days of OHLCV data.
    """
    df = fetch_ohlcv(symbol, period="6mo", interval="1d")

    if len(df) < 60:
        return Signal(
            stock=symbol.upper(),
            time=datetime.now().isoformat(),
            signal="NO_TRADE",
            quantity=0,
            price=float(df["close"].iloc[-1]) if not df.empty else 0.0,
            confidence=0.0,
            reasons=["Insufficient historical data (need ≥ 60 days)"],
            risk_level="HIGH",
            stop_loss=0.0,
            target=0.0,
        )

    close = df["close"]
    price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])

    # ── Compute indicators ────────────────────────────────────────────────────
    ema9_s = _ema(close, 9)
    ema20_s = _ema(close, 20)
    ema50_s = _ema(close, 50)
    ema200_s = _ema(close, 200)

    rsi_s = _rsi(close)
    macd_line, signal_line, histogram = _macd(close)
    vwap_s = _vwap_rolling(df)
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    atr_s = _atr(df)
    adx_s, plus_di, minus_di = _adx(df)
    st_dir = _supertrend(df)

    # Latest values
    ema9 = float(ema9_s.iloc[-1])
    ema20 = float(ema20_s.iloc[-1])
    ema50 = float(ema50_s.iloc[-1])
    ema200 = float(ema200_s.iloc[-1])
    rsi_curr = float(rsi_s.iloc[-1])
    rsi_prev = float(rsi_s.iloc[-2])
    macd_curr = float(macd_line.iloc[-1])
    sig_curr = float(signal_line.iloc[-1])
    macd_prev = float(macd_line.iloc[-2])
    sig_prev = float(signal_line.iloc[-2])
    vwap = float(vwap_s.iloc[-1]) if not np.isnan(vwap_s.iloc[-1]) else price
    atr = float(atr_s.iloc[-1])
    adx_val = float(adx_s.iloc[-1]) if not np.isnan(adx_s.iloc[-1]) else 0.0
    st_direction = int(st_dir.iloc[-1])
    vol_curr = float(df["volume"].iloc[-1])
    vol_avg = float(df["volume"].tail(20).mean())

    support, resistance = _support_resistance(close)

    # ── Score ─────────────────────────────────────────────────────────────────
    buy_score, sell_score, buy_reasons, sell_reasons = _score(
        price=price,
        prev_close=prev_close,
        vwap=vwap,
        ema9=ema9,
        ema20=ema20,
        ema50=ema50,
        macd_line_curr=macd_curr,
        signal_line_curr=sig_curr,
        macd_line_prev=macd_prev,
        signal_line_prev=sig_prev,
        rsi_curr=rsi_curr,
        rsi_prev=rsi_prev,
        vol_curr=vol_curr,
        vol_avg=vol_avg,
        supertrend_dir=st_direction,
        adx_val=adx_val,
        support=support,
        resistance=resistance,
        atr=atr,
    )

    # ── Decide signal direction and confidence ────────────────────────────────
    is_bullish = buy_score >= sell_score
    dominant_score = buy_score if is_bullish else sell_score
    active_reasons = buy_reasons if is_bullish else sell_reasons

    if dominant_score >= 80:
        signal_type = "STRONG_BUY" if is_bullish else "STRONG_SELL"
    elif dominant_score >= 65:
        signal_type = "BUY" if is_bullish else "SELL"
    elif dominant_score >= 50:
        signal_type = "WATCH"
    else:
        signal_type = "NO_TRADE"

    confidence = float(min(dominant_score, 100))

    # ── Risk management (ATR-based) ───────────────────────────────────────────
    atr_pct = (atr / price * 100) if price > 0 else 0.0
    if atr_pct < 2.0:
        risk_level = "LOW"
    elif atr_pct < 4.0:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    if is_bullish:
        stop_loss = round(price - 1.5 * atr, 2)
        target = round(price + 2.0 * atr, 2)
    else:
        stop_loss = round(price + 1.5 * atr, 2)
        target = round(price - 2.0 * atr, 2)

    # ── Position sizing: 20% of available cash per trade ─────────────────────
    allocation = available_cash * 0.20
    quantity = int(allocation / price) if price > 0 else 0

    # Add context reasons about key levels
    active_reasons.append(
        f"EMA levels — 9:{ema9:.1f} 20:{ema20:.1f} 50:{ema50:.1f} 200:{ema200:.1f}"
    )
    active_reasons.append(
        f"Bollinger Bands — upper:{float(bb_upper.iloc[-1]):.1f} mid:{float(bb_mid.iloc[-1]):.1f} lower:{float(bb_lower.iloc[-1]):.1f}"
    )

    return Signal(
        stock=symbol.upper(),
        time=datetime.now().isoformat(),
        signal=signal_type,
        quantity=quantity,
        price=round(price, 2),
        confidence=confidence,
        reasons=active_reasons,
        risk_level=risk_level,
        stop_loss=stop_loss,
        target=target,
    )


def scan_watchlist(symbols: list[str], available_cash: float = 5000.0) -> list[Signal]:
    """
    Run signal generation across a list of NSE symbols.
    Individual errors are caught and returned as NO_TRADE signals.
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
                    signal="NO_TRADE",
                    quantity=0,
                    price=0.0,
                    confidence=0.0,
                    reasons=[f"Error fetching data: {str(e)}"],
                    risk_level="HIGH",
                    stop_loss=0.0,
                    target=0.0,
                )
            )
    return results
