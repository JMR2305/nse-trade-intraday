"""Phase 7.4 – Scenario generator: bullish / neutral / bearish with probability weighting."""
from __future__ import annotations
from typing import Any, Dict, List

from .models import ScenarioAnalysis


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def generate_scenarios(
    symbol: str,
    signal: Dict[str, Any],
    market_snap: Dict[str, Any],
    macro_snap: Dict[str, Any],
) -> List[ScenarioAnalysis]:
    """Return three scenario objects (BULLISH, NEUTRAL, BEARISH) with probabilities that sum to 1."""
    sig_type    = signal.get("signal", "HOLD")
    _conf_raw   = float(signal.get("confidence", 0.5) or 0.5)
    # Normalise to 0–1: live signals arrive as 0–100 (e.g. 75.0), not 0–1
    confidence  = _conf_raw / 100.0 if _conf_raw > 1.0 else _conf_raw
    price       = float(signal.get("price", 100) or 100)
    target      = float(signal.get("target", price * 1.03) or price * 1.03)
    stop_loss   = float(signal.get("stop_loss", price * 0.97) or price * 0.97)
    regime      = signal.get("regime", "NEUTRAL") or "NEUTRAL"

    market_health = float((market_snap or {}).get("market_health_score", 50))
    macro_score   = float((macro_snap or {}).get("macro_score", 50))

    # Base bull probability from confidence and signal direction
    if sig_type == "BUY":
        base_bull = _clamp(confidence)
    elif sig_type == "SELL":
        base_bull = _clamp(1.0 - confidence)
    else:
        base_bull = 0.40

    # Adjust for regime
    regime_adj = {
        "TRENDING_UP":     +0.10,
        "MOMENTUM":        +0.08,
        "MEAN_REVERSION":  -0.05,
        "TRENDING_DOWN":   -0.12,
        "HIGH_VOLATILITY": -0.08,
    }.get(regime, 0.0)

    # Adjust for macro and market
    market_adj = (market_health - 50) / 500   # ±10% range
    macro_adj  = (macro_score - 50) / 500

    bull_prob  = _clamp(base_bull + regime_adj + market_adj + macro_adj)
    bear_prob  = _clamp(1.0 - bull_prob - 0.25)   # leave ~25% for neutral
    bear_prob  = max(0.10, bear_prob)
    neut_prob  = _clamp(1.0 - bull_prob - bear_prob)

    # Normalise to exactly 1.0
    total = bull_prob + neut_prob + bear_prob
    bull_prob = round(bull_prob / total, 3)
    neut_prob = round(neut_prob / total, 3)
    bear_prob = round(1.0 - bull_prob - neut_prob, 3)

    # Price targets
    upside_pct  = ((target - price) / price * 100) if price else 3.0
    downside_pct = ((price - stop_loss) / price * 100) if price else 2.0

    bullish = ScenarioAnalysis(
        scenario_type="BULLISH",
        probability=bull_prob,
        expected_return=round(upside_pct, 2),
        key_conditions=[
            "Market breadth remains positive",
            "FIIs continue buying",
            "No adverse macro surprise",
            f"{symbol} holds above support and breaks resistance",
        ],
        risk_factors=[
            "Sudden VIX spike could invalidate trend",
            "Profit-booking near resistance",
        ],
        narrative=(
            f"If bullish conditions hold, {symbol} could reach its target of "
            f"₹{target:.2f} for a gain of ~{upside_pct:.1f}%. "
            f"Probability: {bull_prob * 100:.0f}%."
        ),
        price_target=round(target, 2),
    )

    neutral = ScenarioAnalysis(
        scenario_type="NEUTRAL",
        probability=neut_prob,
        expected_return=round(upside_pct * 0.3, 2),
        key_conditions=[
            "Mixed signals from market breadth",
            "Sideways macro environment",
            f"{symbol} consolidates between support and resistance",
        ],
        risk_factors=[
            "Time decay on intraday positions",
            "Low volume may cause slippage",
        ],
        narrative=(
            f"A neutral outcome would see {symbol} trade in a narrow range with "
            f"limited directional conviction. Probability: {neut_prob * 100:.0f}%."
        ),
        price_target=round(price * 1.005, 2),
    )

    bearish = ScenarioAnalysis(
        scenario_type="BEARISH",
        probability=bear_prob,
        expected_return=round(-downside_pct, 2),
        key_conditions=[
            "Market turns risk-off",
            "FII selling accelerates",
            f"{symbol} breaks below support at ₹{stop_loss:.2f}",
        ],
        risk_factors=[
            "Stop-loss may be hit",
            "Sector rotation out of this segment",
            "Macro deterioration",
        ],
        narrative=(
            f"A bearish scenario would trigger the stop-loss at ₹{stop_loss:.2f}, "
            f"a downside of ~{downside_pct:.1f}%. "
            f"Probability: {bear_prob * 100:.0f}%."
        ),
        price_target=round(stop_loss, 2),
    )

    return [bullish, neutral, bearish]
