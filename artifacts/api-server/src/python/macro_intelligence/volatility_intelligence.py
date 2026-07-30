"""
volatility_intelligence.py — Phase 7.3
India VIX and volatility regime analysis.
Fetches via yfinance with session-level cache; falls back to scan-inferred VIX.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from datetime import datetime, timezone

_cache: dict = {}
# TTL must stay ≤ 30 s so that a VIX spike is visible within one
# Executive Dashboard polling cycle (refetchInterval = 30 000 ms).
_CACHE_TTL_S = 25

VIX_TICKER = "^INDIAVIX"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_valid(key: str) -> bool:
    if key not in _cache:
        return False
    return (datetime.now(timezone.utc) - _cache[key]["ts"]).total_seconds() < _CACHE_TTL_S


def _fetch_vix() -> dict:
    """Fetch India VIX current + 5-day history."""
    try:
        import yfinance as yf
        t  = yf.Ticker(VIX_TICKER)
        fi = t.fast_info
        current = float(fi.last_price or 0)
        prev    = float(fi.previous_close or current)

        # 5-day history for regime classification
        hist = t.history(period="5d", interval="1d")
        closes = [float(r) for r in hist["Close"].dropna()] if not hist.empty else []

        return {
            "current": round(current, 2),
            "prev":    round(prev, 2),
            "closes":  closes,
            "available": current > 0,
        }
    except Exception:
        return {"current": 0.0, "prev": 0.0, "closes": [], "available": False}


def _vix_from_regime() -> float:
    """Fallback: infer VIX from Phase 7.1 regime."""
    try:
        from market_intelligence_hub.shared_services import get_summary as mi_summary
        s = mi_summary()
        return float(s.get("vix_value", 18.0))
    except Exception:
        return 18.0


def _risk_level(vix: float) -> str:
    if vix >= 30:   return "EXTREME"
    if vix >= 22:   return "HIGH"
    if vix >= 15:   return "MEDIUM"
    return "LOW"


def _regime(current: float, closes: list) -> str:
    """EXPANSION / CONTRACTION / STABLE based on 5-day trend."""
    if len(closes) < 2:
        return "STABLE"
    trend_chg = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] else 0
    if trend_chg > 10:   return "EXPANSION"
    if trend_chg < -10:  return "CONTRACTION"
    return "STABLE"


def _vix_interpretation(vix: float, regime: str) -> str:
    if vix >= 30 and regime == "EXPANSION":
        return "Extreme fear — highly elevated VIX expanding. Reduce position sizes, hedge aggressively."
    if vix >= 22:
        return "Elevated volatility — options premiums high. Favour defined-risk strategies."
    if vix <= 13 and regime == "CONTRACTION":
        return "Low complacency zone — VIX contracting. Favourable for directional trades."
    if regime == "EXPANSION":
        return "VIX expanding — intraday swings widening. Tighten stop-losses."
    if regime == "CONTRACTION":
        return "VIX contracting — improving risk environment."
    return "VIX within normal range — standard risk management applies."


def _trading_implication(vix: float, regime: str) -> str:
    if vix >= 30:
        return "High VIX: avoid naked options selling; consider protective puts; reduce beta."
    if vix >= 22:
        return "Elevated VIX: wider stop-losses required; options premiums inflated."
    if vix <= 13:
        return "Low VIX: options cheap for directional bets; normal stop placement."
    return "Normal VIX: standard position sizing and stop-loss rules apply."


def get_volatility_intelligence() -> dict:
    cache_key = "volatility_intelligence"
    if _cache_valid(cache_key):
        return _cache[cache_key]["data"]

    data = _fetch_vix()
    if not data["available"]:
        data["current"] = _vix_from_regime()
        data["prev"]    = data["current"]

    current = data["current"]
    prev    = data["prev"]
    closes  = data["closes"]
    chg_pct = round(((current - prev) / prev * 100) if prev else 0.0, 2)

    regime      = _regime(current, closes)
    risk_level  = _risk_level(current)

    # Percentile-like score: VIX 10=LOW(80), 18=MEDIUM(50), 30=HIGH(20), 40+=EXTREME(5)
    # Score = 100 when VIX is 0 (impossible), 0 when VIX is 50
    vix_score = round(max(0, min(100, 100 - (current / 50) * 100)), 1)

    result = {
        "available":          True,
        "advisory_only":      True,
        "generated_at":       _now_iso(),
        "india_vix": {
            "current":    current,
            "prev_close": prev,
            "change_pct": chg_pct,
            "available":  data["available"],
        },
        "regime":             regime,
        "risk_level":         risk_level,
        "vix_score":          vix_score,   # 100 = low vol, 0 = extreme
        "historical_closes":  closes,
        "interpretation":     _vix_interpretation(current, regime),
        "trading_implication": _trading_implication(current, regime),
        "vix_zones": {
            "extreme": ">= 30",
            "high":    "22 – 30",
            "medium":  "15 – 22",
            "low":     "< 15",
            "current_zone": risk_level,
        },
        "options_environment": (
            "EXPENSIVE" if current >= 22 else
            "CHEAP"     if current <= 13 else
            "NORMAL"
        ),
    }

    _cache[cache_key] = {"data": result, "ts": datetime.now(timezone.utc)}
    return result
