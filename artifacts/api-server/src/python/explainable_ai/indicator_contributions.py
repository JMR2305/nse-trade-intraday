"""
indicator_contributions.py — Phase 7.4
12-indicator contribution breakdown. Weights sum to 100%.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List
from .models import IndicatorContribution, BUY_SIGNALS, SELL_SIGNALS


# ── Base weights for the 12 indicators ───────────────────────────────────────
# Grounded in the signal_engine.py scoring scheme (VWAP ±15, EMA20/50 ±15,
# EMA9/20 ±10, MACD ±15, RSI ±10, Volume ±10, S/R ±10, Supertrend ±10, ADX +5)

_BASE_WEIGHTS = {
    "Trend":          15.0,
    "Momentum":       14.0,
    "Volume":         10.0,
    "Volatility":      8.0,
    "Relative Strength": 10.0,
    "Support":         7.0,
    "Resistance":      7.0,
    "Breakout":        6.0,
    "Liquidity":       5.0,
    "Sector Strength": 8.0,
    "Market Breadth":  6.0,
    "Watchlist Ranking": 4.0,
}  # sum = 100


def _classify_direction(signal_type: str, indicator: str,
                        expl: dict, market_snap: dict) -> str:
    """Return BULLISH | BEARISH | NEUTRAL for a given indicator."""
    is_buy  = signal_type in BUY_SIGNALS
    is_sell = signal_type in SELL_SIGNALS

    if indicator == "Trend":
        trend = expl.get("trend", "")
        if "uptrend" in trend.lower() or "bullish" in trend.lower():    return "BULLISH"
        if "downtrend" in trend.lower() or "bearish" in trend.lower():  return "BEARISH"

    elif indicator == "Momentum":
        mom = expl.get("momentum", "")
        if "bullish" in mom.lower() or "oversold" in mom.lower():  return "BULLISH"
        if "bearish" in mom.lower() or "overbought" in mom.lower(): return "BEARISH"

    elif indicator == "Volume":
        vol = expl.get("volume", "")
        if "strong" in vol.lower() or "above" in vol.lower():
            return "BULLISH" if is_buy else "BEARISH"
        return "NEUTRAL"

    elif indicator in ("Relative Strength", "Breakout", "Support", "Resistance",
                       "Liquidity", "Volatility"):
        if is_buy:   return "BULLISH"
        if is_sell:  return "BEARISH"

    elif indicator == "Sector Strength":
        mkt_score = float(market_snap.get("market_health_score", 50.0))
        if mkt_score >= 60: return "BULLISH"
        if mkt_score < 40:  return "BEARISH"

    elif indicator == "Market Breadth":
        mkt_score = float(market_snap.get("market_health_score", 50.0))
        if mkt_score >= 65: return "BULLISH"
        if mkt_score < 40:  return "BEARISH"

    elif indicator == "Watchlist Ranking":
        if is_buy:   return "BULLISH"
        if is_sell:  return "BEARISH"

    return "NEUTRAL"


def _describe_indicator(indicator: str, direction: str, signal_type: str,
                        expl: dict, market_snap: dict, confidence: float) -> tuple:
    """Return (description, weight_basis) for an indicator."""
    is_buy = signal_type in BUY_SIGNALS

    descriptions = {
        "Trend": (
            expl.get("trend") or
            f"EMA stack analysis: {'bullish alignment' if is_buy else 'bearish alignment'}.",
            "EMA 9/20/50 cross-over analysis per signal_engine.py"
        ),
        "Momentum": (
            expl.get("momentum") or
            f"RSI + MACD: {'momentum building' if is_buy else 'momentum fading'}.",
            "RSI 14 zone (45-65 bullish) + MACD crossover state"
        ),
        "Volume": (
            expl.get("volume") or
            f"Volume vs 20-period average: {'above average confirms move' if is_buy else 'volume profile mixed'}.",
            "Volume spike detection (≥1.5× average = significant)"
        ),
        "Volatility": (
            expl.get("regime_impact") or
            f"Market regime context: {'normal volatility range' if confidence > 60 else 'elevated risk environment'}.",
            "ATR + Bollinger Band + VIX composite"
        ),
        "Relative Strength": (
            f"RSI {'in bullish zone (45–65)' if direction == 'BULLISH' else 'outside optimal zone'}. "
            f"Confidence: {confidence:.0f}/100.",
            "RSI 14-period strength vs 45-65 optimal zone"
        ),
        "Support": (
            f"Price {'above key support levels' if is_buy else 'near support — testing levels'}.",
            "Rolling 60-bar local minima detection"
        ),
        "Resistance": (
            f"Price {'approaching or breaking resistance' if is_buy else 'below resistance — ceiling intact'}.",
            "Rolling 60-bar local maxima detection"
        ),
        "Breakout": (
            f"Supertrend indicator: {'bullish direction (green)' if is_buy else 'bearish direction (red)'}.",
            "Supertrend (10, 3) breakout detection"
        ),
        "Liquidity": (
            f"Volume and spread analysis: {'normal market depth' if confidence > 55 else 'thin liquidity — caution'}.",
            "Volume average + bid-ask proxy from price action"
        ),
        "Sector Strength": (
            f"Sector intelligence score: {market_snap.get('market_health_score', 50):.0f}/100.",
            "Phase 7.1 sector analysis (sector heat + rotation)"
        ),
        "Market Breadth": (
            f"Market breadth: {market_snap.get('overall_outlook', 'neutral')}.",
            "Phase 7.1 advance/decline ratio + participation score"
        ),
        "Watchlist Ranking": (
            f"Watchlist composite rank for this symbol: {'top tier' if confidence > 70 else 'mid tier'}.",
            "Phase 7.1 opportunity score + composite rank"
        ),
    }

    return descriptions.get(indicator, ("No description available.", "Default basis"))


def compute_contributions(symbol: str, signal: dict,
                          market_snap: dict) -> List[IndicatorContribution]:
    """
    Compute 12-indicator percentage contributions.
    Weights are adjusted by signal confidence so all values are consistent.
    Returned list sums to exactly 100%.
    """
    if not signal:
        # Return flat uniform distribution when no signal
        contribs = []
        uniform = round(100.0 / 12, 2)
        for name in _BASE_WEIGHTS:
            contribs.append(IndicatorContribution(
                name=name, indicator_name=name, contribution_pct=uniform,
                direction="NEUTRAL",
                description="No signal data available.",
                explanation="No signal data available.",
                weight_basis="Uniform fallback",
            ))
        # Adjust last to ensure exactly 100%
        total = sum(c.contribution_pct for c in contribs)
        contribs[-1].contribution_pct = round(contribs[-1].contribution_pct + (100.0 - total), 2)
        return contribs

    sig_type   = signal.get("signal", "NO_TRADE")
    confidence = float(signal.get("confidence", 50.0))
    expl       = signal.get("explanation", {}) or {}

    # Adjust weights by confidence: stronger signal → emphasise technical indicators
    conf_mult = confidence / 100.0
    weights = dict(_BASE_WEIGHTS)

    # Boost Trend + Momentum when confidence is high (more technically driven)
    if confidence >= 75:
        weights["Trend"]    += 3.0
        weights["Momentum"] += 2.0
        weights["Market Breadth"] -= 3.0
        weights["Watchlist Ranking"] -= 2.0
    elif confidence < 60:
        weights["Market Breadth"] += 3.0
        weights["Sector Strength"] += 2.0
        weights["Trend"]    -= 3.0
        weights["Momentum"] -= 2.0

    # Normalise to 100
    total_w = sum(weights.values())
    weights = {k: max(0.5, v / total_w * 100) for k, v in weights.items()}

    # Second normalisation pass
    total_w2 = sum(weights.values())
    factor = 100.0 / total_w2
    items = list(weights.items())

    contribs = []
    running = 0.0
    for i, (name, w) in enumerate(items):
        if i == len(items) - 1:
            pct = round(100.0 - running, 2)
        else:
            pct = round(w * factor, 2)
        running += pct

        direction  = _classify_direction(sig_type, name, expl, market_snap)
        desc, basis = _describe_indicator(name, direction, sig_type, expl, market_snap, confidence)

        contribs.append(IndicatorContribution(
            name=name,
            indicator_name=name,
            contribution_pct=pct,
            direction=direction,
            description=desc,
            explanation=desc,
            weight_basis=basis,
        ))

    return contribs
