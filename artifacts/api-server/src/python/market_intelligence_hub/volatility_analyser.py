"""
volatility_analyser.py — Phase 7.1
Volatility analysis: ATR trend, volatility regime, expansion/contraction,
gap risk measurement.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from .hub_models import clamp


_VIX_LOW     = 15.0
_VIX_MODERATE = 20.0
_VIX_HIGH    = 25.0


def analyse_volatility(scan_items: list, regime: dict) -> dict:
    """
    Compute volatility metrics from scan items and the regime result.
    """
    vix_value  = float(regime.get("vix_value", 18.0) or 18.0)
    vix_status = str(regime.get("vix_status", "MODERATE") or "MODERATE")

    atrs = [float(i.get("atr") or 0.0) for i in scan_items if i.get("atr")]
    prices = [float(i.get("price") or 0.0) for i in scan_items if i.get("price") and i.get("price") > 0]

    atr_avg = sum(atrs) / len(atrs) if atrs else 0.0
    price_avg = sum(prices) / len(prices) if prices else 1.0

    # ATR as % of price — normalized volatility proxy
    atr_pct = (atr_avg / price_avg * 100) if price_avg > 0 else 0.0

    vol_regime = _vol_regime(vix_value)
    expansion  = _expansion_label(vix_value, atr_pct)
    gap_risk   = _gap_risk(vix_value)
    vol_score  = _vol_score(vix_value)

    # ATR trend across symbols (high dispersion = expansion)
    if len(atrs) > 3:
        high_atr = sorted(atrs)[-3:]
        low_atr  = sorted(atrs)[:3]
        atr_spread = (sum(high_atr) / 3 - sum(low_atr) / 3) if (sum(low_atr) > 0) else 0.0
        atr_trend = "EXPANDING" if atr_spread > atr_avg * 0.5 else "CONTRACTING"
    else:
        atr_spread = 0.0
        atr_trend = "STABLE"

    # Symbol-level volatility breakdown
    symbol_vol = []
    for item in scan_items[:20]:  # top 20 only
        atr = float(item.get("atr") or 0.0)
        price = float(item.get("price") or 1.0) or 1.0
        atr_pct_i = atr / price * 100
        symbol_vol.append({
            "symbol": str(item.get("stock") or item.get("symbol") or ""),
            "atr": round(atr, 2),
            "atr_pct": round(atr_pct_i, 4),
            "vol_level": "HIGH" if atr_pct_i > 2.0 else "MODERATE" if atr_pct_i > 1.0 else "LOW",
        })

    return {
        "vix_value": round(vix_value, 2),
        "vix_status": vix_status,
        "volatility_regime": vol_regime,
        "volatility_score": round(vol_score, 2),
        "atr_avg": round(atr_avg, 4),
        "atr_pct": round(atr_pct, 4),
        "atr_trend": atr_trend,
        "expansion": expansion,
        "gap_risk": gap_risk,
        "gap_risk_score": round(_gap_risk_score(vix_value), 2),
        "symbol_volatility": symbol_vol,
        "high_vol_symbols": sum(1 for s in symbol_vol if s["vol_level"] == "HIGH"),
        "total_symbols": len(scan_items),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _vol_regime(vix: float) -> str:
    if vix >= _VIX_HIGH:   return "HIGH_VOLATILITY"
    if vix >= _VIX_MODERATE: return "MODERATE_VOLATILITY"
    if vix <= _VIX_LOW:    return "LOW_VOLATILITY"
    return "NORMAL_VOLATILITY"


def _expansion_label(vix: float, atr_pct: float) -> str:
    if vix > _VIX_HIGH or atr_pct > 2.5:   return "EXPANDING"
    if vix < _VIX_LOW  and atr_pct < 1.0:   return "CONTRACTING"
    return "STABLE"


def _gap_risk(vix: float) -> str:
    if vix >= _VIX_HIGH:   return "HIGH"
    if vix >= _VIX_MODERATE: return "MODERATE"
    return "LOW"


def _gap_risk_score(vix: float) -> float:
    return clamp((vix - _VIX_LOW) / (_VIX_HIGH - _VIX_LOW) * 100)


def _vol_score(vix: float) -> float:
    """Inverse volatility score — higher is better (lower VIX = more favourable)."""
    return clamp(100.0 - (vix / 40.0 * 100))
