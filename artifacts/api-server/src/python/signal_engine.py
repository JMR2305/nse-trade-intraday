"""
signal_engine.py
Professional rule-based signal engine for NSE stocks.

Indicators:
  EMA 9, 20, 50, 200 | RSI 14 | MACD 12/26/9 | VWAP (rolling 20-day)
  Bollinger Bands (20, 2σ) | ATR 14 | ADX 14 | Supertrend (10, 3)
  Volume spike | Support & Resistance

Multi-Timeframe Analysis:
  5m | 15m | 1h | 1d — signal generated only when ≥3 timeframes agree

Market Regime Integration:
  BEARISH      → buy_score  -= 20
  BULLISH      → sell_score -= 20
  SIDEWAYS     → both       -= 10
  HIGH_VOLATILITY → risk level upgraded

Signal types:
  STRONG_BUY (90-100) | BUY (75-89) | WATCH (60-74) | SELL (75-89) | STRONG_SELL (90-100) | NO_TRADE (<60)

Output: Signal TypedDict with explanation, timeframe_alignment, regime.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import TypedDict, Optional
from market_data import fetch_ohlcv


# ── Type definitions ───────────────────────────────────────────────────────────

class Explanation(TypedDict):
    trend: str
    momentum: str
    volume: str
    indicator_summary: str
    regime_impact: str
    plain_english: str


class Signal(TypedDict):
    stock: str
    time: str
    signal: str            # STRONG_BUY | BUY | WATCH | SELL | STRONG_SELL | NO_TRADE
    quantity: int
    price: float
    confidence: float      # 0–100
    reasons: list[str]
    risk_level: str        # LOW | MEDIUM | HIGH
    stop_loss: float
    target: float
    explanation: Explanation
    timeframe_alignment: int   # number of timeframes (0-4) agreeing with signal direction
    regime: str


# ── Indicator library ──────────────────────────────────────────────────────────

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


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, sig_period: int = 9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, sig_period)
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
    prev_h = np.roll(h, 1); prev_h[0] = h[0]
    prev_l = np.roll(l, 1); prev_l[0] = l[0]

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
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_series = dx.ewm(com=period - 1, min_periods=period).mean()
    return adx_series, plus_di, minus_di


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """Returns direction Series: +1 (bullish) or -1 (bearish)."""
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
        lower[i] = lower_raw[i] if (lower_raw[i] > lower[i-1] or close[i-1] < lower[i-1]) else lower[i-1]
        upper[i] = upper_raw[i] if (upper_raw[i] < upper[i-1] or close[i-1] > upper[i-1]) else upper[i-1]
        if direction[i-1] == -1 and close[i] > upper[i-1]:
            direction[i] = 1
        elif direction[i-1] == 1 and close[i] < lower[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]

    return pd.Series(direction, index=df.index)


def _vwap_rolling(df: pd.DataFrame, window: int = 20) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].replace(0, np.nan)
    return (typical * vol).rolling(window).sum() / vol.rolling(window).sum()


def _support_resistance(close: pd.Series, lookback: int = 60, n: int = 3):
    subset = close.tail(lookback)
    local_max = subset[(subset.shift(1) < subset) & (subset.shift(-1) < subset)]
    local_min = subset[(subset.shift(1) > subset) & (subset.shift(-1) > subset)]
    resistance = sorted(local_max.values, reverse=True)[:n]
    support = sorted(local_min.values)[:n]
    return support, resistance


# ── Timeframe analysis (simplified scoring for MTF consensus) ─────────────────

def _analyze_timeframe(symbol: str, interval: str, period: str) -> str:
    """
    Quick bullish/bearish/neutral assessment for a single timeframe.
    Uses: EMA9 vs EMA20, MACD direction, RSI zone.
    Returns: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    """
    try:
        df = fetch_ohlcv(symbol, period=period, interval=interval)
        if len(df) < 20:
            return "NEUTRAL"
        close = df["close"]
        ema9 = float(_ema(close, 9).iloc[-1])
        ema20 = float(_ema(close, 20).iloc[-1])
        macd_line, signal_line, _ = _macd(close)
        macd_bull = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])
        rsi = float(_rsi(close).iloc[-1])

        bull_points = 0
        bear_points = 0
        if ema9 > ema20: bull_points += 1
        else: bear_points += 1
        if macd_bull: bull_points += 1
        else: bear_points += 1
        if 40 <= rsi <= 65: bull_points += 1
        elif rsi > 65: bear_points += 1
        elif rsi < 40: bull_points += 1  # oversold = potential bounce

        if bull_points >= 2: return "BULLISH"
        if bear_points >= 2: return "BEARISH"
        return "NEUTRAL"
    except Exception:
        return "NEUTRAL"


# Timeframes to check (interval → fetch period)
TIMEFRAMES = [
    ("5m",  "5d"),
    ("15m", "5d"),
    ("1h",  "1mo"),
    ("1d",  "6mo"),
]


def _multi_timeframe_consensus(symbol: str, daily_direction: str) -> tuple[int, list[str]]:
    """
    Check how many of the 4 timeframes agree with the daily direction.

    Returns:
        (alignment_count, [tf_labels])
        alignment_count: 0-4 — number of timeframes agreeing with daily direction
    """
    agreements = []
    labels: list[str] = []

    for interval, period in TIMEFRAMES:
        result = _analyze_timeframe(symbol, interval, period)
        tf_label = interval.upper()
        if result == daily_direction:
            agreements.append(tf_label)
            labels.append(f"✓ {tf_label}")
        elif result == "NEUTRAL":
            labels.append(f"~ {tf_label}")
        else:
            labels.append(f"✗ {tf_label}")

    return len(agreements), labels


# ── Scoring engine ─────────────────────────────────────────────────────────────

def _score(
    price: float, prev_close: float, vwap: float,
    ema9: float, ema20: float, ema50: float,
    macd_line_curr: float, signal_line_curr: float,
    macd_line_prev: float, signal_line_prev: float,
    rsi_curr: float, rsi_prev: float,
    vol_curr: float, vol_avg: float,
    supertrend_dir: int, adx_val: float,
    support: list, resistance: list, atr: float,
) -> tuple[int, int, list[str], list[str]]:
    """
    Score BUY and SELL sides independently (each 0–100).
    Returns (buy_score, sell_score, buy_reasons, sell_reasons).
    """
    buy_score = 0
    sell_score = 0
    buy_reasons: list[str] = []
    sell_reasons: list[str] = []
    tol = atr * 0.10

    # VWAP ±15
    if price > vwap:
        buy_score += 15
        buy_reasons.append(f"Price ₹{price:.2f} above VWAP ₹{vwap:.2f} (+15)")
    else:
        sell_score += 15
        sell_reasons.append(f"Price ₹{price:.2f} below VWAP ₹{vwap:.2f} (+15)")

    # EMA20 vs EMA50 ±15
    if ema20 > ema50:
        buy_score += 15
        buy_reasons.append(f"EMA20 {ema20:.1f} > EMA50 {ema50:.1f} — golden cross (+15)")
    else:
        sell_score += 15
        sell_reasons.append(f"EMA20 {ema20:.1f} < EMA50 {ema50:.1f} — death cross (+15)")

    # EMA9 vs EMA20 ±10
    if ema9 > ema20:
        buy_score += 10
        buy_reasons.append(f"EMA9 {ema9:.1f} > EMA20 {ema20:.1f} — short-term momentum up (+10)")
    else:
        sell_score += 10
        sell_reasons.append(f"EMA9 {ema9:.1f} < EMA20 {ema20:.1f} — short-term momentum down (+10)")

    # MACD ±15
    macd_bull = macd_line_curr > signal_line_curr
    cross_up = (macd_line_prev <= signal_line_prev) and macd_bull
    cross_dn = (macd_line_prev >= signal_line_prev) and (not macd_bull)
    if macd_bull:
        tag = " — fresh crossover!" if cross_up else ""
        buy_score += 15
        buy_reasons.append(f"MACD bullish{tag}: {macd_line_curr:.3f} > {signal_line_curr:.3f} (+15)")
    else:
        tag = " — fresh crossover!" if cross_dn else ""
        sell_score += 15
        sell_reasons.append(f"MACD bearish{tag}: {macd_line_curr:.3f} < {signal_line_curr:.3f} (+15)")

    # RSI ±10
    if 45 <= rsi_curr <= 65:
        buy_score += 10
        buy_reasons.append(f"RSI {rsi_curr:.1f} in bullish momentum zone 45–65 (+10)")
    elif rsi_curr > 70 and rsi_curr < rsi_prev:
        sell_score += 10
        sell_reasons.append(f"RSI {rsi_curr:.1f} overbought and turning down (+10)")
    elif rsi_curr < 30:
        buy_reasons.append(f"RSI {rsi_curr:.1f} — oversold, potential reversal")
    elif rsi_curr > 70:
        sell_reasons.append(f"RSI {rsi_curr:.1f} — overbought (no confirmed turn yet)")

    # Volume spike ±10
    vol_ratio = vol_curr / vol_avg if vol_avg > 0 else 1.0
    is_red = price < prev_close
    if vol_ratio >= 1.5 and not is_red:
        buy_score += 10
        buy_reasons.append(f"Volume {vol_ratio:.1f}× avg on up-candle — strong buying (+10)")
    elif vol_ratio >= 1.5 and is_red:
        sell_score += 10
        sell_reasons.append(f"Volume {vol_ratio:.1f}× avg on down-candle — strong selling (+10)")

    # S/R proximity ±10
    near_res = any(abs(price - r) <= tol or price > r for r in resistance)
    near_sup = any(abs(price - s) <= tol or price < s for s in support)
    if resistance and near_res:
        buy_score += 10
        buy_reasons.append("Price near/breaking resistance — breakout signal (+10)")
    if support and near_sup:
        sell_score += 10
        sell_reasons.append("Price near/breaking support — breakdown signal (+10)")

    # Supertrend ±10
    if supertrend_dir == 1:
        buy_score += 10
        buy_reasons.append("Supertrend bullish — trend following confirmation (+10)")
    else:
        sell_score += 10
        sell_reasons.append("Supertrend bearish — trend following confirmation (+10)")

    # ADX +5 (adds to both sides — strong trend helps directional trades)
    if adx_val > 20:
        buy_score += 5
        sell_score += 5
        buy_reasons.append(f"ADX {adx_val:.1f} — trend strength confirmed (+5)")
        sell_reasons.append(f"ADX {adx_val:.1f} — trend strength confirmed (+5)")

    return buy_score, sell_score, buy_reasons, sell_reasons


# ── Explanation builder ────────────────────────────────────────────────────────

def _build_explanation(
    signal_type: str,
    ema9: float, ema20: float, ema50: float,
    rsi: float, macd_bull: bool,
    vol_ratio: float,
    regime_name: str, adj_buy: float, adj_sell: float,
    tf_labels: list[str],
    dominant_score: float,
    bb_upper: float, bb_mid: float, bb_lower: float,
    price: float,
) -> Explanation:
    is_buy = signal_type in ("STRONG_BUY", "BUY", "WATCH") and (ema20 > ema50 or macd_bull)

    # Trend sentence
    if ema9 > ema20 > ema50:
        trend = "Strong uptrend — all EMAs stacked bullishly (EMA9 > EMA20 > EMA50)."
    elif ema9 < ema20 < ema50:
        trend = "Strong downtrend — all EMAs stacked bearishly (EMA9 < EMA20 < EMA50)."
    elif ema20 > ema50:
        trend = "Moderate uptrend — EMA20 above EMA50 with short-term pullback."
    else:
        trend = "Moderate downtrend — EMA20 below EMA50."

    # Momentum sentence
    rsi_desc = (
        f"Oversold RSI {rsi:.0f}" if rsi < 30 else
        f"Bullish RSI {rsi:.0f}" if 45 <= rsi <= 65 else
        f"Overbought RSI {rsi:.0f}" if rsi > 70 else
        f"Neutral RSI {rsi:.0f}"
    )
    macd_desc = "MACD bullish (line above signal)" if macd_bull else "MACD bearish (line below signal)"
    momentum = f"{rsi_desc}. {macd_desc}."

    # Volume sentence
    if vol_ratio >= 2.0:
        volume = f"Very strong volume ({vol_ratio:.1f}× average) — confirms conviction."
    elif vol_ratio >= 1.5:
        volume = f"Above-average volume ({vol_ratio:.1f}×) — supports the move."
    else:
        volume = f"Normal volume ({vol_ratio:.1f}×) — no special conviction."

    # Bollinger context
    if price > bb_upper:
        bb_note = f"Price above upper Bollinger Band (₹{bb_upper:.0f}) — extended, risk of pullback."
    elif price < bb_lower:
        bb_note = f"Price below lower Bollinger Band (₹{bb_lower:.0f}) — oversold, watch for reversal."
    else:
        bb_note = f"Price inside Bollinger Bands (₹{bb_lower:.0f}–₹{bb_upper:.0f}) — normal range."

    indicator_summary = f"{bb_note} Timeframes: {', '.join(tf_labels)}."

    # Regime impact sentence
    if adj_buy > 0 and is_buy:
        regime_impact = f"{regime_name} market regime: BUY confidence reduced by {adj_buy:.0f} points."
    elif adj_sell > 0 and not is_buy:
        regime_impact = f"{regime_name} market regime: SELL confidence reduced by {adj_sell:.0f} points."
    elif regime_name == "HIGH_VOLATILITY":
        regime_impact = "HIGH VOLATILITY: risk level upgraded — reduce position sizes."
    elif regime_name == "LOW_VOLATILITY":
        regime_impact = "LOW VOLATILITY: compressed ranges — favour breakout entries."
    else:
        regime_impact = f"{regime_name} market: no confidence adjustment for this signal direction."

    # Plain English
    direction_word = "bullish" if signal_type in ("STRONG_BUY", "BUY") else \
                     "bearish" if signal_type in ("STRONG_SELL", "SELL") else "mixed"
    if signal_type in ("STRONG_BUY", "STRONG_SELL"):
        plain = (
            f"Very strong {direction_word} signal. Multiple indicators align with "
            f"{len([l for l in tf_labels if '✓' in l])} of 4 timeframes confirming the direction. "
            f"Confidence {dominant_score:.0f}/100. Suitable for paper trading with full position size."
        )
    elif signal_type in ("BUY", "SELL"):
        plain = (
            f"Moderate {direction_word} signal. Indicators show a clear bias but not all timeframes agree. "
            f"Confidence {dominant_score:.0f}/100. Consider half position size."
        )
    elif signal_type == "WATCH":
        plain = (
            f"Signal is too weak to act on. Indicators are mixed — only {dominant_score:.0f}/100 confidence. "
            "Monitor for confirmation before entering."
        )
    else:
        plain = (
            f"No clear trade setup. Confidence below 60 ({dominant_score:.0f}/100). "
            "Stay out and wait for better alignment across indicators."
        )

    return Explanation(
        trend=trend,
        momentum=momentum,
        volume=volume,
        indicator_summary=indicator_summary,
        regime_impact=regime_impact,
        plain_english=plain,
    )


# ── Main signal generation ─────────────────────────────────────────────────────

def generate_signal(
    symbol: str,
    available_cash: float = 5000.0,
    regime: Optional[dict] = None,
    skip_mtf: bool = False,
) -> Signal:
    """
    Generate a professional multi-indicator signal for a single NSE stock.

    Args:
        symbol: NSE ticker without .NS (e.g. 'RELIANCE')
        available_cash: cash available for position sizing
        regime: pre-computed RegimeResult dict (fetched once per scan run)
        skip_mtf: if True, skip multi-timeframe analysis (faster, used for market overview ranking)
    """
    # Lazy-import to avoid circular deps when called from market_overview
    if regime is None:
        from market_regime import get_regime
        regime = get_regime()

    adj_buy: float = regime.get("adj_buy", 0.0)
    adj_sell: float = regime.get("adj_sell", 0.0)
    regime_name: str = regime.get("regime", "SIDEWAYS")
    high_vol: bool = regime.get("high_volatility", False)

    # ── Daily OHLCV data ──────────────────────────────────────────────────────
    df = fetch_ohlcv(symbol, period="6mo", interval="1d")
    if len(df) < 60:
        return Signal(
            stock=symbol.upper(), time=datetime.now().isoformat(),
            signal="NO_TRADE", quantity=0,
            price=float(df["close"].iloc[-1]) if not df.empty else 0.0,
            confidence=0.0,
            reasons=["Insufficient historical data (need ≥60 days)"],
            risk_level="HIGH", stop_loss=0.0, target=0.0,
            explanation=Explanation(
                trend="Unknown", momentum="Unknown", volume="Unknown",
                indicator_summary="Not enough data",
                regime_impact=f"Regime: {regime_name}",
                plain_english="Cannot generate signal — not enough price history.",
            ),
            timeframe_alignment=0,
            regime=regime_name,
        )

    close = df["close"]
    price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])

    # ── Compute indicators ────────────────────────────────────────────────────
    ema9_s = _ema(close, 9);  ema9  = float(ema9_s.iloc[-1])
    ema20_s = _ema(close, 20); ema20 = float(ema20_s.iloc[-1])
    ema50_s = _ema(close, 50); ema50 = float(ema50_s.iloc[-1])
    ema200_s = _ema(close, 200); ema200 = float(ema200_s.iloc[-1])

    rsi_s = _rsi(close)
    rsi_curr = float(rsi_s.iloc[-1])
    rsi_prev = float(rsi_s.iloc[-2])

    macd_line, signal_line, _ = _macd(close)
    macd_curr = float(macd_line.iloc[-1]); sig_curr = float(signal_line.iloc[-1])
    macd_prev = float(macd_line.iloc[-2]); sig_prev = float(signal_line.iloc[-2])

    vwap_s = _vwap_rolling(df)
    vwap = float(vwap_s.iloc[-1]) if not np.isnan(vwap_s.iloc[-1]) else price

    bb_upper_s, bb_mid_s, bb_lower_s = _bollinger(close)
    bb_upper = float(bb_upper_s.iloc[-1])
    bb_mid = float(bb_mid_s.iloc[-1])
    bb_lower = float(bb_lower_s.iloc[-1])

    atr_s = _atr(df)
    atr = float(atr_s.iloc[-1])

    adx_s, _, _ = _adx(df)
    adx_val = float(adx_s.iloc[-1]) if not np.isnan(adx_s.iloc[-1]) else 0.0

    st_dir_s = _supertrend(df)
    st_dir = int(st_dir_s.iloc[-1])

    vol_curr = float(df["volume"].iloc[-1])
    vol_avg = float(df["volume"].tail(20).mean())
    vol_ratio = vol_curr / vol_avg if vol_avg > 0 else 1.0

    support, resistance = _support_resistance(close)

    # ── Score ─────────────────────────────────────────────────────────────────
    buy_score, sell_score, buy_reasons, sell_reasons = _score(
        price=price, prev_close=prev_close, vwap=vwap,
        ema9=ema9, ema20=ema20, ema50=ema50,
        macd_line_curr=macd_curr, signal_line_curr=sig_curr,
        macd_line_prev=macd_prev, signal_line_prev=sig_prev,
        rsi_curr=rsi_curr, rsi_prev=rsi_prev,
        vol_curr=vol_curr, vol_avg=vol_avg,
        supertrend_dir=st_dir, adx_val=adx_val,
        support=support, resistance=resistance, atr=atr,
    )

    is_bullish = buy_score >= sell_score
    daily_direction = "BULLISH" if is_bullish else "BEARISH"

    # ── Multi-timeframe consensus ─────────────────────────────────────────────
    if skip_mtf:
        # Skip intraday fetches for speed (used in market overview ranking)
        tf_alignment = 4 if is_bullish and buy_score > sell_score else 0
        tf_labels = ["~ 5M", "~ 15M", "~ 1H", f"{'✓' if is_bullish else '✗'} 1D"]
        mtf_gate_active = False
    else:
        tf_alignment, tf_labels = _multi_timeframe_consensus(symbol, daily_direction)
        # MTF gating: if fewer than 3 of 4 timeframes agree, cap at WATCH
        mtf_gate_active = tf_alignment < 3

    # ── Apply regime adjustments ──────────────────────────────────────────────
    raw_buy = buy_score - adj_buy
    raw_sell = sell_score - adj_sell

    dominant_score = float(max(0.0, min(100.0, raw_buy if is_bullish else raw_sell)))
    active_reasons = buy_reasons if is_bullish else sell_reasons

    # ── Signal classification with updated thresholds ─────────────────────────
    if mtf_gate_active:
        # Force WATCH/NO_TRADE when timeframes disagree
        if dominant_score >= 60:
            signal_type = "WATCH"
        else:
            signal_type = "NO_TRADE"
    else:
        if dominant_score >= 90:
            signal_type = "STRONG_BUY" if is_bullish else "STRONG_SELL"
        elif dominant_score >= 75:
            signal_type = "BUY" if is_bullish else "SELL"
        elif dominant_score >= 60:
            signal_type = "WATCH"
        else:
            signal_type = "NO_TRADE"

    # ── Risk management (ATR-based) ───────────────────────────────────────────
    atr_pct = (atr / price * 100) if price > 0 else 0.0
    if high_vol or atr_pct >= 4.0:
        risk_level = "HIGH"
    elif atr_pct >= 2.0:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    if is_bullish:
        stop_loss = round(price - 1.5 * atr, 2)
        target = round(price + 2.0 * atr, 2)
    else:
        stop_loss = round(price + 1.5 * atr, 2)
        target = round(price - 2.0 * atr, 2)

    # ── Position sizing (20% of available cash) ───────────────────────────────
    quantity = int(available_cash * 0.20 / price) if price > 0 else 0

    # ── Explanation ───────────────────────────────────────────────────────────
    expl = _build_explanation(
        signal_type=signal_type,
        ema9=ema9, ema20=ema20, ema50=ema50,
        rsi=rsi_curr, macd_bull=(macd_curr > sig_curr),
        vol_ratio=vol_ratio,
        regime_name=regime_name, adj_buy=adj_buy, adj_sell=adj_sell,
        tf_labels=tf_labels,
        dominant_score=dominant_score,
        bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
        price=price,
    )

    # Append context to reasons
    active_reasons.append(
        f"EMA stack: 9={ema9:.1f} 20={ema20:.1f} 50={ema50:.1f} 200={ema200:.1f}"
    )
    active_reasons.append(f"ATR={atr:.2f} ({atr_pct:.1f}%) | Risk={risk_level}")
    if mtf_gate_active:
        active_reasons.append(
            f"MTF gate: only {tf_alignment}/4 timeframes agree — capped at {signal_type}"
        )
    active_reasons.append(f"Regime: {regime_name} | adj_buy=-{adj_buy} adj_sell=-{adj_sell}")

    return Signal(
        stock=symbol.upper(),
        time=datetime.now().isoformat(),
        signal=signal_type,
        quantity=quantity,
        price=round(price, 2),
        confidence=dominant_score,
        reasons=active_reasons,
        risk_level=risk_level,
        stop_loss=stop_loss,
        target=target,
        explanation=expl,
        timeframe_alignment=tf_alignment,
        regime=regime_name,
    )


def scan_watchlist(
    symbols: list[str],
    available_cash: float = 5000.0,
    regime: Optional[dict] = None,
) -> list[Signal]:
    """
    Run signal generation across a list of NSE symbols.
    Fetches regime once and reuses across all symbols.
    """
    if regime is None:
        from market_regime import get_regime
        regime = get_regime()

    results: list[Signal] = []
    for sym in symbols:
        try:
            sig = generate_signal(sym, available_cash, regime=regime)
            results.append(sig)
        except Exception as e:
            results.append(Signal(
                stock=sym.upper(), time=datetime.now().isoformat(),
                signal="NO_TRADE", quantity=0, price=0.0, confidence=0.0,
                reasons=[f"Error: {str(e)}"],
                risk_level="HIGH", stop_loss=0.0, target=0.0,
                explanation=Explanation(
                    trend="Unknown", momentum="Unknown", volume="Unknown",
                    indicator_summary=f"Data error: {str(e)}",
                    regime_impact="Unknown", plain_english=f"Could not analyse {sym}.",
                ),
                timeframe_alignment=0,
                regime=regime.get("regime", "UNKNOWN") if regime else "UNKNOWN",
            ))
    return results
