"""
market_flows.py — Phase 7.3
Market flow intelligence: FII/DII activity, institutional flows, sector rotation,
liquidity trend — inferred from scan signal patterns and Phase 7.1 regime.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Dict, Any

_cache: dict = {}
_CACHE_TTL_S = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_valid(key: str) -> bool:
    if key not in _cache:
        return False
    return (datetime.now(timezone.utc) - _cache[key]["ts"]).total_seconds() < _CACHE_TTL_S


def _load_signals() -> list:
    try:
        import signals_cache
        return signals_cache.get_latest_signals() or []
    except Exception:
        return []


def _get_mi_regime() -> dict:
    try:
        from market_intelligence_hub.shared_services import get_summary as mi_summary
        s = mi_summary()
        return {
            "regime": s.get("market_regime", "SIDEWAYS"),
            "health": float(s.get("market_health_score", 50.0)),
            "adv_dec_ratio": s.get("breadth", {}).get("advance_decline_ratio", 1.0),
        }
    except Exception:
        return {"regime": "SIDEWAYS", "health": 50.0, "adv_dec_ratio": 1.0}


def _infer_fii_dii(signals: list, regime: dict) -> dict:
    """
    Infer FII / DII posture from:
    - Market regime + breadth (BULLISH + adv_dec > 1.5 → DII buying)
    - Average opportunity score (high → institutional interest)
    - High-confidence large-cap signals (→ FII activity indicator)
    """
    if not signals:
        avg_score = 50.0
        high_conf = 0
    else:
        scores     = [float(s.get("opportunity_score", 50)) for s in signals]
        conf       = [float(s.get("confidence", 50)) for s in signals]
        avg_score  = sum(scores) / len(scores)
        high_conf  = sum(1 for c in conf if c >= 70)

    r = regime["regime"]
    adv_dec = float(regime.get("adv_dec_ratio", 1.0))
    health  = float(regime["health"])

    # FII inference
    if r in ("BULLISH_MOMENTUM", "STRONG_UPTREND") and high_conf >= 5:
        fii_flow   = "NET_BUYER"
        fii_score  = min(85.0, 60.0 + high_conf * 2.0)
        fii_trend  = "INFLOW"
    elif r in ("BEARISH_MOMENTUM", "STRONG_DOWNTREND"):
        fii_flow   = "NET_SELLER"
        fii_score  = max(25.0, 60.0 - high_conf * 3.0)
        fii_trend  = "OUTFLOW"
    else:
        fii_flow   = "NEUTRAL"
        fii_score  = 50.0
        fii_trend  = "MIXED"

    # DII inference — DIIs tend to be counter-cyclical
    if fii_flow == "NET_SELLER" and health < 45:
        dii_flow   = "NET_BUYER"    # DIIs buy on dips
        dii_score  = 65.0
        dii_trend  = "INFLOW"
    elif adv_dec >= 1.5 and avg_score >= 60:
        dii_flow   = "NET_BUYER"
        dii_score  = 60.0 + (adv_dec - 1.5) * 10
        dii_trend  = "INFLOW"
    elif adv_dec < 0.8:
        dii_flow   = "NET_SELLER"
        dii_score  = 35.0
        dii_trend  = "OUTFLOW"
    else:
        dii_flow   = "NEUTRAL"
        dii_score  = 50.0
        dii_trend  = "MIXED"

    return {
        "fii": {
            "flow":        fii_flow,
            "trend":       fii_trend,
            "score":       round(min(100, max(0, fii_score)), 1),
            "description": _fii_description(fii_flow, r),
        },
        "dii": {
            "flow":        dii_flow,
            "trend":       dii_trend,
            "score":       round(min(100, max(0, dii_score)), 1),
            "description": _dii_description(dii_flow),
        },
    }


def _fii_description(flow: str, regime: str) -> str:
    if flow == "NET_BUYER":
        return f"FII buying inferred from {regime} regime and high institutional confidence signals."
    if flow == "NET_SELLER":
        return "FII selling inferred from bearish regime and low confidence across watchlist."
    return "FII activity mixed — regime not strongly directional."


def _dii_description(flow: str) -> str:
    if flow == "NET_BUYER":
        return "DII buying inferred — breadth improvement and counter-cyclical accumulation pattern."
    if flow == "NET_SELLER":
        return "DII selling inferred — broad market weakness with declining advance/decline ratio."
    return "DII activity neutral — mixed signals across institutional-grade large caps."


def _infer_sector_rotation(signals: list) -> list:
    """Identify leading and lagging sectors from scan signal distribution."""
    from collections import defaultdict
    sector_scores: Dict[str, List[float]] = defaultdict(list)
    for s in signals:
        sector = s.get("sector", "Unknown")
        if sector:
            sector_scores[sector].append(float(s.get("opportunity_score", 50)))

    rotation = []
    for sector, scores in sector_scores.items():
        avg = sum(scores) / len(scores)
        rotation.append({
            "sector":    sector,
            "avg_score": round(avg, 1),
            "count":     len(scores),
            "direction": "INFLOW" if avg >= 60 else ("OUTFLOW" if avg <= 40 else "NEUTRAL"),
        })
    rotation.sort(key=lambda x: x["avg_score"], reverse=True)
    return rotation


def _infer_liquidity(signals: list, regime: dict) -> dict:
    if not signals:
        return {"trend": "NEUTRAL", "score": 50.0, "label": "Insufficient data"}

    vol_ratios = [float(s.get("volume_ratio", 1.0)) for s in signals]
    avg_vol    = sum(vol_ratios) / len(vol_ratios)
    high_vol   = sum(1 for v in vol_ratios if v > 1.5)

    if avg_vol >= 1.5 and high_vol >= len(signals) * 0.4:
        trend   = "HIGH_LIQUIDITY"
        score   = min(100, 60 + avg_vol * 10)
        label   = "Strong liquidity — above-average volume across watchlist."
    elif avg_vol <= 0.7:
        trend   = "LOW_LIQUIDITY"
        score   = max(0, 50 - (1.0 - avg_vol) * 30)
        label   = "Thin liquidity — caution on position sizing."
    else:
        trend   = "NORMAL_LIQUIDITY"
        score   = 50.0 + (avg_vol - 1.0) * 15
        label   = "Normal liquidity conditions."

    return {
        "trend":          trend,
        "score":          round(min(100, max(0, score)), 1),
        "avg_volume_ratio": round(avg_vol, 2),
        "high_volume_pct": round(high_vol / max(1, len(signals)) * 100, 1),
        "label":          label,
    }


def get_market_flows() -> dict:
    """Returns FII/DII activity, institutional flow, sector rotation, liquidity."""
    cache_key = "market_flows"
    if _cache_valid(cache_key):
        return _cache[cache_key]["data"]

    signals = _load_signals()
    regime  = _get_mi_regime()

    fii_dii   = _infer_fii_dii(signals, regime)
    rotation  = _infer_sector_rotation(signals)
    liquidity = _infer_liquidity(signals, regime)

    # Cash vs derivatives flow inference
    if fii_dii["fii"]["flow"] == "NET_BUYER":
        cash_flow_label = "NET_POSITIVE"
        deriv_flow_label = "HEDGED_LONG"
    elif fii_dii["fii"]["flow"] == "NET_SELLER":
        cash_flow_label = "NET_NEGATIVE"
        deriv_flow_label = "SHORT_HEAVY"
    else:
        cash_flow_label = "NEUTRAL"
        deriv_flow_label = "BALANCED"

    result = {
        "available":       True,
        "advisory_only":   True,
        "generated_at":    _now_iso(),
        "fii":             fii_dii["fii"],
        "dii":             fii_dii["dii"],
        "institutional": {
            "net_posture": "BUYING" if fii_dii["dii"]["flow"] == "NET_BUYER" or
                           fii_dii["fii"]["flow"] == "NET_BUYER" else
                           ("SELLING" if fii_dii["fii"]["flow"] == "NET_SELLER" and
                            fii_dii["dii"]["flow"] == "NET_SELLER" else "MIXED"),
            "description": (
                "Both FII and DII are buying — strong institutional conviction."
                if fii_dii["fii"]["flow"] == "NET_BUYER" and
                fii_dii["dii"]["flow"] == "NET_BUYER" else
                "Institutional sentiment mixed — inferred from scan signal patterns."
            ),
        },
        "cash_market_flow":   cash_flow_label,
        "derivatives_flow":   deriv_flow_label,
        "sector_rotation":    rotation[:10],
        "top_inflow_sectors": [r["sector"] for r in rotation if r["direction"] == "INFLOW"][:5],
        "top_outflow_sectors":[r["sector"] for r in rotation if r["direction"] == "OUTFLOW"][:5],
        "liquidity":          liquidity,
        "regime_context":     regime["regime"],
        "signals_analysed":   len(signals),
        "data_source":        "INFERRED_FROM_SCAN_SIGNALS",
        "disclaimer":         (
            "FII/DII flow data is inferred from scan signal patterns and market regime. "
            "Not based on actual SEBI/NSE institutional flow data."
        ),
    }

    _cache[cache_key] = {"data": result, "ts": datetime.now(timezone.utc)}
    return result
