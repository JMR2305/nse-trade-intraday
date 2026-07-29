"""
regime_analyser.py — Phase 7.1
Extended market regime detection.

Wraps market_regime.get_regime() and maps to the full Phase 7.1 regime set:
Bull / Bear / Sideways / Trending / High Volatility / Low Volatility /
Breakout / Reversal / Transition.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from .hub_models import (
    REGIME_BULL, REGIME_BEAR, REGIME_SIDEWAYS, REGIME_TRENDING,
    REGIME_HIGH_VOL, REGIME_LOW_VOL, REGIME_BREAKOUT, REGIME_REVERSAL,
    REGIME_TRANSITION, clamp,
)


_VIX_HIGH = 20.0
_VIX_LOW  = 15.0
_VIX_EXTREME = 25.0


def analyse_regime() -> dict:
    """
    Call market_regime.get_regime() and extend with Phase 7.1 regime taxonomy.
    Returns regime, sub_regime, vix metrics, trend strength, confidence.
    """
    raw = _get_base_regime()

    regime         = _map_regime(raw)
    sub_regime     = _sub_regime(raw)
    trend_strength = _trend_strength(raw)
    confidence     = _confidence(raw, trend_strength)
    vix_value      = raw.get("vix_value", 0.0) or 0.0
    vix_status     = raw.get("vix_status", "MODERATE")
    description    = _description(regime, sub_regime, raw)

    return {
        "regime": regime,
        "sub_regime": sub_regime,
        "trend_strength": round(trend_strength, 2),
        "confidence": round(confidence, 2),
        "nifty_price": raw.get("nifty_price", 0.0),
        "nifty_change_pct": round(raw.get("nifty_change_pct", 0.0), 4),
        "nifty_trend": raw.get("nifty_trend", "SIDEWAYS"),
        "banknifty_price": raw.get("banknifty_price", 0.0),
        "banknifty_change_pct": round(raw.get("banknifty_change_pct", 0.0), 4),
        "banknifty_trend": raw.get("banknifty_trend", "SIDEWAYS"),
        "vix_value": round(vix_value, 2),
        "vix_status": vix_status,
        "high_volatility": raw.get("high_volatility", False),
        "adj_buy": raw.get("adj_buy", 1.0),
        "adj_sell": raw.get("adj_sell", 1.0),
        "description": description,
        "advisory_only": True,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_base_regime() -> dict:
    try:
        from market_regime import get_regime
        result = get_regime()
        return dict(result)
    except Exception:
        # Fallback neutral regime
        return {
            "regime": "SIDEWAYS", "nifty_price": 0.0, "nifty_change_pct": 0.0,
            "nifty_trend": "SIDEWAYS", "banknifty_price": 0.0,
            "banknifty_change_pct": 0.0, "banknifty_trend": "SIDEWAYS",
            "vix_value": 18.0, "vix_status": "MODERATE",
            "adj_buy": 1.0, "adj_sell": 1.0,
            "high_volatility": False,
            "description": "Market data unavailable — using neutral fallback.",
        }


def _map_regime(raw: dict) -> str:
    """Map base regime + VIX to the Phase 7.1 extended regime taxonomy."""
    base    = (raw.get("regime") or "SIDEWAYS").upper()
    vix     = raw.get("vix_value", 18.0) or 18.0
    nifty_t = (raw.get("nifty_trend") or "SIDEWAYS").upper()
    bn_t    = (raw.get("banknifty_trend") or "SIDEWAYS").upper()
    n_chg   = raw.get("nifty_change_pct", 0.0) or 0.0

    # Extreme volatility overrides everything (panic / crisis state)
    if vix >= _VIX_EXTREME:
        return REGIME_HIGH_VOL

    # Directional regimes take priority over low-volatility label
    if "BULL" in base or (nifty_t == "UP" and bn_t == "UP"):
        return REGIME_BULL
    if "BEAR" in base or (nifty_t == "DOWN" and bn_t == "DOWN"):
        return REGIME_BEAR

    # Low volatility only when the market is non-directional
    if vix <= _VIX_LOW:
        return REGIME_LOW_VOL

    # Breakout: strong one-day move
    if abs(n_chg) > 1.5 and raw.get("high_volatility", False):
        return REGIME_BREAKOUT

    # Transition: disagreement between NIFTY and BankNifty
    if nifty_t != bn_t and nifty_t != "SIDEWAYS" and bn_t != "SIDEWAYS":
        return REGIME_TRANSITION

    # Trending: moderate directional move
    if abs(n_chg) > 0.5:
        return REGIME_TRENDING

    return REGIME_SIDEWAYS


def _sub_regime(raw: dict) -> str:
    """Finer-grained label within the primary regime."""
    vix = raw.get("vix_value", 18.0) or 18.0
    n_chg = raw.get("nifty_change_pct", 0.0) or 0.0
    if vix >= _VIX_EXTREME:
        return "PANIC"
    if vix >= _VIX_HIGH:
        return "ELEVATED_VOL"
    if abs(n_chg) > 2.0:
        return "STRONG_MOMENTUM"
    if abs(n_chg) > 1.0:
        return "MODERATE_MOMENTUM"
    if abs(n_chg) < 0.2:
        return "TIGHT_RANGE"
    return "NORMAL"


def _trend_strength(raw: dict) -> float:
    """0–100 trend strength from price change and VIX."""
    n_chg = abs(raw.get("nifty_change_pct", 0.0) or 0.0)
    b_chg = abs(raw.get("banknifty_change_pct", 0.0) or 0.0)
    vix   = raw.get("vix_value", 18.0) or 18.0
    vix_penalty = max(0.0, (vix - _VIX_HIGH) * 2)
    raw_strength = (n_chg * 25 + b_chg * 15) - vix_penalty
    return clamp(raw_strength)


def _confidence(raw: dict, trend_strength: float) -> float:
    nifty_t = (raw.get("nifty_trend") or "SIDEWAYS").upper()
    bn_t    = (raw.get("banknifty_trend") or "SIDEWAYS").upper()
    agreement = nifty_t == bn_t and nifty_t != "SIDEWAYS"
    base = 60.0 if agreement else 40.0
    return clamp(base + trend_strength * 0.3)


def _description(regime: str, sub_regime: str, raw: dict) -> str:
    n_chg = raw.get("nifty_change_pct", 0.0) or 0.0
    vix   = raw.get("vix_value", 18.0) or 18.0
    d = raw.get("description", "")
    if d:
        return f"{regime} ({sub_regime}) — {d}"
    return (
        f"{regime} regime ({sub_regime}). "
        f"NIFTY {'+' if n_chg >= 0 else ''}{n_chg:.2%}, VIX {vix:.1f}. "
        "Advisory analysis only."
    )
