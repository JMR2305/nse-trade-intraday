"""
trade_quality.py
Trade Quality Score Engine.

Decomposes a signal into 6 sub-scores and combines them into a
single Trade Quality Score (0–100) with a letter grade.

Sub-scores:
  trend_score    (0–100) — EMA alignment + multi-timeframe consensus
  momentum_score (0–100) — RSI position + MACD direction
  volume_score   (0–100) — volume vs average (spike = higher score)
  breakout_score (0–100) — price vs VWAP + Bollinger Band position
  risk_score     (0–100) — RR ratio + stop-loss distance quality
  market_score   (0–100) — inherited from MarketContext

All inputs come from the existing Signal dict (no extra yfinance calls).
"""

import re
from typing import TypedDict
from config import TRADE_QUALITY_WEIGHTS, TRADE_QUALITY_GRADES


# ── TypedDict ─────────────────────────────────────────────────────────────────

class TradeQuality(TypedDict):
    trend_score:    float
    momentum_score: float
    volume_score:   float
    breakout_score: float
    risk_score:     float
    market_score:   float
    total_score:    float
    grade:          str    # A+ | A | B | C | D | F


# ── Helpers ───────────────────────────────────────────────────────────────────

BULLISH_SIGNALS = {"STRONG_BUY", "BUY"}
BEARISH_SIGNALS = {"STRONG_SELL", "SELL"}


def _grade(total: float) -> str:
    for threshold, letter in TRADE_QUALITY_GRADES:
        if total >= threshold:
            return letter
    return "F"


def _trend_score(signal: dict) -> float:
    """
    Score trend quality from EMA alignment and MTF consensus.

    EMA alignment gives 0–60 points.
    MTF consensus gives 0–40 points.
    """
    tf_align   = signal.get("timeframe_alignment", 0)
    explanation = signal.get("explanation", {})
    trend_text = explanation.get("trend", "").lower()

    # MTF contribution (0-40 pts)
    tf_score = tf_align * 10.0

    # EMA alignment contribution (0-60 pts)
    ema_score = 0.0
    if "golden cross" in trend_text:
        ema_score = 60
    elif "all emas stacked bullish" in trend_text or "strong uptrend" in trend_text:
        ema_score = 50
    elif "bullish" in trend_text:
        ema_score = 35
    elif "death cross" in trend_text:
        ema_score = 0
    elif "all emas stacked bearish" in trend_text or "strong downtrend" in trend_text:
        ema_score = 10
    elif "bearish" in trend_text:
        ema_score = 20
    else:
        ema_score = 25  # neutral

    return round(min(100.0, tf_score + ema_score), 1)


def _momentum_score(signal: dict) -> float:
    """
    Score from RSI position and MACD direction.
    Base: 50. +/- based on RSI zone and MACD.
    """
    explanation    = signal.get("explanation", {})
    momentum_text  = explanation.get("momentum", "").lower()
    reasons        = signal.get("reasons", [])

    score = 50.0

    # RSI parsing: look for RSI value in reasons
    for r in reasons:
        m = re.search(r"rsi[=\s]+(\d+\.?\d*)", r.lower())
        if m:
            rsi = float(m.group(1))
            if 50 <= rsi <= 65:
                score += 15   # healthy bullish
            elif 65 < rsi <= 75:
                score += 8    # strong but watch overbought
            elif rsi > 75:
                score -= 10   # overbought
            elif 35 <= rsi < 50:
                score += 5    # slight bearish lean
            elif 25 <= rsi < 35:
                score += 10   # oversold bounce potential
            else:
                score -= 5
            break

    # MACD
    if "macd bullish" in momentum_text or "macd above" in momentum_text:
        score += 20
    elif "macd bearish" in momentum_text or "macd below" in momentum_text:
        score -= 20

    return round(max(0.0, min(100.0, score)), 1)


def _volume_score(signal: dict) -> float:
    """
    Score from volume vs average. Higher volume spike = better conviction.
    Looks for patterns like 'Volume 2.1×' in reasons.
    """
    score = 50.0
    reasons = signal.get("reasons", [])
    explanation = signal.get("explanation", {})
    volume_text = explanation.get("volume", "").lower()

    # Search reasons for volume multiplier pattern
    for r in reasons:
        m = re.search(r"volume\s+(\d+\.?\d*)\s*[×x×]", r.lower())
        if m:
            mult = float(m.group(1))
            if mult >= 3.0:
                score = 95
            elif mult >= 2.0:
                score = 85
            elif mult >= 1.5:
                score = 70
            elif mult >= 1.2:
                score = 60
            elif mult >= 0.8:
                score = 45
            else:
                score = 30
            break

    # Fallback: text hints
    if score == 50.0:
        if "high volume" in volume_text or "strong volume" in volume_text:
            score = 75
        elif "normal volume" in volume_text:
            score = 50
        elif "low volume" in volume_text or "thin" in volume_text:
            score = 30
        elif "spike" in volume_text:
            score = 80

    return round(max(0.0, min(100.0, score)), 1)


def _breakout_score(signal: dict) -> float:
    """
    Score from VWAP position and Bollinger Band location.
    Above VWAP with room to upper band = high score.
    """
    score = 50.0
    explanation = signal.get("explanation", {})
    indicator_text = explanation.get("indicator_summary", "").lower()
    reasons = signal.get("reasons", [])
    signal_type = signal.get("signal", "NO_TRADE")

    # VWAP
    for r in reasons:
        rl = r.lower()
        if "above vwap" in rl:
            score += 20
            break
        elif "below vwap" in rl:
            score -= 20
            break

    # Bollinger Band position
    if "upper band" in indicator_text or "near upper" in indicator_text:
        if signal_type in BULLISH_SIGNALS:
            score += 10  # breakout continuation
        else:
            score -= 10  # overbought at resistance
    elif "lower band" in indicator_text or "near lower" in indicator_text:
        if signal_type in BEARISH_SIGNALS:
            score += 10  # breakdown continuation
        else:
            score -= 10  # oversold — potential bounce down
    elif "inside" in indicator_text or "normal range" in indicator_text:
        pass  # neutral

    # Supertrend
    for r in reasons:
        rl = r.lower()
        if "supertrend: bullish" in rl:
            score += 10
            break
        elif "supertrend: bearish" in rl:
            score -= 10
            break

    return round(max(0.0, min(100.0, score)), 1)


def _risk_score(signal: dict) -> float:
    """
    Score from RR ratio and stop distance quality.
    RR 3:1 → near-perfect; RR < 1.5 → poor.
    """
    price     = signal.get("price", 0.0)
    stop      = signal.get("stop_loss", 0.0)
    target    = signal.get("target", 0.0)
    signal_type = signal.get("signal", "NO_TRADE")
    risk_level  = signal.get("risk_level", "MEDIUM")

    if price <= 0 or stop <= 0 or target <= 0:
        return 50.0

    is_long = signal_type in BULLISH_SIGNALS
    if is_long:
        risk   = price - stop
        reward = target - price
    else:
        risk   = stop - price
        reward = price - target

    if risk <= 0:
        return 30.0

    rr = reward / risk
    stop_pct = risk / price * 100

    # RR quality (0-80 pts)
    if rr >= 3.5:
        rr_score = 90
    elif rr >= 3.0:
        rr_score = 80
    elif rr >= 2.5:
        rr_score = 70
    elif rr >= 2.0:
        rr_score = 60
    elif rr >= 1.5:
        rr_score = 45
    elif rr >= 1.0:
        rr_score = 30
    else:
        rr_score = 15

    # Stop distance penalty
    penalty = 0.0
    if stop_pct < 0.5:
        penalty = 20  # too tight — whipsaw risk
    elif stop_pct > 6.0:
        penalty = 15  # too wide — excessive risk
    elif stop_pct > 4.0:
        penalty = 5

    # Risk level bonus
    bonus = 0.0
    if risk_level == "LOW":
        bonus = 5
    elif risk_level == "HIGH":
        bonus = -5

    return round(max(0.0, min(100.0, rr_score - penalty + bonus)), 1)


# ── Core function ─────────────────────────────────────────────────────────────

def compute_trade_quality(
    signal: dict,
    market_context: dict,
) -> TradeQuality:
    """
    Compute Trade Quality Score from a signal + market context.

    All computation uses data already in the signal dict —
    no additional market data fetches needed.

    Args:
        signal         : Signal dict from signal_engine
        market_context : MarketContext dict from market_context module

    Returns:
        TradeQuality with 6 sub-scores, weighted total, and grade
    """
    w = TRADE_QUALITY_WEIGHTS

    trend_s    = _trend_score(signal)
    momentum_s = _momentum_score(signal)
    volume_s   = _volume_score(signal)
    breakout_s = _breakout_score(signal)
    risk_s     = _risk_score(signal)

    # Market score: from context, adjusted for signal direction
    mkt_score  = float(market_context.get("score", 50.0))
    bias       = market_context.get("bias", "NEUTRAL")
    sig_type   = signal.get("signal", "NO_TRADE")
    if sig_type in BULLISH_SIGNALS and bias == "BULLISH":
        mkt_score = min(100.0, mkt_score + 8)
    elif sig_type in BULLISH_SIGNALS and bias == "BEARISH":
        mkt_score = max(0.0, mkt_score - 12)
    elif sig_type in BEARISH_SIGNALS and bias == "BEARISH":
        mkt_score = min(100.0, mkt_score + 8)
    market_s = round(mkt_score, 1)

    total = (
        trend_s    * w["trend"]    +
        momentum_s * w["momentum"] +
        volume_s   * w["volume"]   +
        breakout_s * w["breakout"] +
        risk_s     * w["risk"]     +
        market_s   * w["market"]
    )

    return TradeQuality(
        trend_score    = trend_s,
        momentum_score = momentum_s,
        volume_score   = volume_s,
        breakout_score = breakout_s,
        risk_score     = risk_s,
        market_score   = market_s,
        total_score    = round(total, 1),
        grade          = _grade(total),
    )
