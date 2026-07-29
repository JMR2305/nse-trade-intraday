"""Phase 7.5 – Market regime comparison engine (read-only, advisory-only)."""
from __future__ import annotations
from typing import Any, Dict, List

from .models import RegimeProfile, ALL_REGIMES, ALL_STRATEGIES

_REGIME_VIX: Dict[str, str] = {
    "BULL":          "< 14",
    "BEAR":          "> 22",
    "RANGE":         "14–18",
    "VOLATILE":      "> 20",
    "LOW_VOLATILITY": "< 12",
    "TRANSITION":    "16–22",
}

_REGIME_BEST_STRATEGY: Dict[str, str] = {
    "BULL":          "TREND_FOLLOWING",
    "BEAR":          "VOLATILITY_BASED",
    "RANGE":         "RANGE_TRADING",
    "VOLATILE":      "VOLATILITY_BASED",
    "LOW_VOLATILITY": "TREND_FOLLOWING",
    "TRANSITION":    "SECTOR_ROTATION",
}

_REGIME_WORST_STRATEGY: Dict[str, str] = {
    "BULL":          "MEAN_REVERSION",
    "BEAR":          "TREND_FOLLOWING",
    "RANGE":         "BREAKOUT",
    "VOLATILE":      "BREAKOUT",
    "LOW_VOLATILITY": "VOLATILITY_BASED",
    "TRANSITION":    "MOMENTUM",
}

# Win rate and confidence modifiers per regime
_REGIME_WIN_MOD: Dict[str, float] = {
    "BULL":          0.65,
    "BEAR":          0.35,
    "RANGE":         0.50,
    "VOLATILE":      0.40,
    "LOW_VOLATILITY": 0.60,
    "TRANSITION":    0.45,
}

_REGIME_CONF_MOD: Dict[str, float] = {
    "BULL":          68.0,
    "BEAR":          48.0,
    "RANGE":         55.0,
    "VOLATILE":      42.0,
    "LOW_VOLATILITY": 65.0,
    "TRANSITION":    52.0,
}


def _map_signal_regime(regime: str) -> str:
    """Map signal regime string to one of our 6 research regimes."""
    r = (regime or "NEUTRAL").upper()
    if r in ("TRENDING_UP", "MOMENTUM"):   return "BULL"
    if r in ("TRENDING_DOWN",):            return "BEAR"
    if r in ("MEAN_REVERSION", "RANGE"):   return "RANGE"
    if r == "HIGH_VOLATILITY":             return "VOLATILE"
    if r == "LOW_VOLATILITY":              return "LOW_VOLATILITY"
    return "TRANSITION"


def build_regime_profiles(
    signals: List[Dict[str, Any]],
    risk_snap: Dict[str, Any],
) -> List[RegimeProfile]:
    """Build one RegimeProfile for each of the 6 research regimes."""
    max_dd = float(risk_snap.get("max_drawdown", 0.08) or 0.08)
    max_dd = max_dd * 100 if max_dd < 1.0 else max_dd

    # Group signals by mapped regime
    regime_buckets: Dict[str, List[Dict[str, Any]]] = {r: [] for r in ALL_REGIMES}
    for s in signals:
        mapped = _map_signal_regime(s.get("regime", "NEUTRAL"))
        regime_buckets[mapped].append(s)

    profiles: List[RegimeProfile] = []
    for regime in ALL_REGIMES:
        bucket = regime_buckets[regime]
        count  = len(bucket)

        # Use modelled values when bucket is empty (no live data for that regime)
        win_rate = _REGIME_WIN_MOD[regime]
        avg_conf = _REGIME_CONF_MOD[regime]

        if bucket:
            conf_vals = []
            for s in bucket:
                c = float(s.get("confidence", 0.5) or 0.5)
                conf_vals.append(c * 100 if c <= 1.0 else c)
            avg_conf = sum(conf_vals) / len(conf_vals)
            actionable = [s for s in bucket if s.get("signal") in
                          ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL")]
            win_rate = len(actionable) / len(bucket)

        # Drawdown estimate calibrated by regime risk
        dd_mod = {
            "BULL": 0.6, "BEAR": 1.4, "RANGE": 0.9,
            "VOLATILE": 1.5, "LOW_VOLATILITY": 0.5, "TRANSITION": 1.0,
        }
        avg_dd = round(max_dd * dd_mod.get(regime, 1.0), 2)

        profiles.append(RegimeProfile(
            regime=regime,
            signal_count=count,
            win_rate=round(win_rate, 3),
            avg_confidence=round(avg_conf, 1),
            avg_drawdown=avg_dd,
            best_strategy=_REGIME_BEST_STRATEGY[regime],
            worst_strategy=_REGIME_WORST_STRATEGY[regime],
            vix_range=_REGIME_VIX[regime],
        ))

    return profiles
