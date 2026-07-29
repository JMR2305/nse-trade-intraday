"""
commodity_intelligence.py — Phase 7.3
Commodity intelligence: Gold, Silver, Crude Oil, Natural Gas, Copper.
Fetches via yfinance with session-level cache.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from datetime import datetime, timezone

_cache: dict = {}
_CACHE_TTL_S = 300

_COMMODITY_TICKERS = {
    "Gold":         {"ticker": "GC=F",   "unit": "USD/oz",   "symbol": "GOLD"},
    "Silver":       {"ticker": "SI=F",   "unit": "USD/oz",   "symbol": "SILVER"},
    "Crude Oil":    {"ticker": "CL=F",   "unit": "USD/bbl",  "symbol": "OIL"},
    "Natural Gas":  {"ticker": "NG=F",   "unit": "USD/MMBtu","symbol": "NG"},
    "Copper":       {"ticker": "HG=F",   "unit": "USD/lb",   "symbol": "COPPER"},
}

_SECTOR_IMPACT = {
    "Gold":        {"positive": ["Jewellery", "Mining"],    "negative": []},
    "Silver":      {"positive": ["Electronics", "Mining"],  "negative": []},
    "Crude Oil":   {"positive": ["Oil & Gas"],              "negative": ["Aviation", "Paints", "Chemicals", "FMCG"]},
    "Natural Gas": {"positive": ["Gas utilities"],          "negative": ["Fertilisers", "Chemicals"]},
    "Copper":      {"positive": ["Mining", "Metals"],       "negative": ["Electricals", "Auto (wiring cost)"]},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_valid(key: str) -> bool:
    if key not in _cache:
        return False
    return (datetime.now(timezone.utc) - _cache[key]["ts"]).total_seconds() < _CACHE_TTL_S


def _fetch_commodity(ticker: str) -> dict:
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info
        price = float(fi.last_price or 0)
        prev  = float(fi.previous_close or price)
        chg   = round(((price - prev) / prev * 100) if prev else 0.0, 2)
        return {"price": round(price, 2), "change_pct": chg, "available": price > 0}
    except Exception:
        return {"price": 0.0, "change_pct": 0.0, "available": False}


def _trend(change_pct: float) -> str:
    if change_pct > 0.5:   return "BULLISH"
    if change_pct < -0.5:  return "BEARISH"
    return "NEUTRAL"


def _volatility(change_pct: float) -> str:
    a = abs(change_pct)
    if a >= 2.0:   return "HIGH"
    if a >= 0.8:   return "MEDIUM"
    return "LOW"


def _crude_impact_description(change_pct: float) -> str:
    if change_pct > 1.5:
        return ("Rising crude — bearish for Aviation, Paints, Chemicals. "
                "Positive for Oil & Gas companies.")
    if change_pct < -1.5:
        return ("Falling crude — positive for inflation outlook, "
                "lower input costs across manufacturing.")
    return "Crude oil stable — limited input cost impact today."


def get_commodity_intelligence() -> dict:
    cache_key = "commodity_intelligence"
    if _cache_valid(cache_key):
        return _cache[cache_key]["data"]

    commodities = []
    for name, cfg in _COMMODITY_TICKERS.items():
        data = _fetch_commodity(cfg["ticker"])
        chg  = data["change_pct"]
        impact = _SECTOR_IMPACT.get(name, {})
        commodities.append({
            "name":             name,
            "ticker":           cfg["ticker"],
            "unit":             cfg["unit"],
            "symbol":           cfg["symbol"],
            "price":            data["price"],
            "change_pct":       chg,
            "trend":            _trend(chg),
            "volatility":       _volatility(chg),
            "available":        data["available"],
            "positive_sectors": impact.get("positive", []),
            "negative_sectors": impact.get("negative", []),
        })

    crude = next((c for c in commodities if c["name"] == "Crude Oil"), {})
    gold  = next((c for c in commodities if c["name"] == "Gold"), {})

    # Composite commodity risk score (crude & metals weighted)
    crude_chg = float(crude.get("change_pct", 0))
    gold_chg  = float(gold.get("change_pct", 0))
    # Crude rising = inflation risk; gold rising = risk-off
    risk_score = 50.0 + crude_chg * 4 + gold_chg * 2
    risk_score = round(min(100, max(0, risk_score)), 1)

    bullish = sum(1 for c in commodities if c["trend"] == "BULLISH")
    bearish = sum(1 for c in commodities if c["trend"] == "BEARISH")

    result = {
        "available":           True,
        "advisory_only":       True,
        "generated_at":        _now_iso(),
        "commodities":         commodities,
        "crude_oil":           crude,
        "gold":                gold,
        "bullish_count":       bullish,
        "bearish_count":       bearish,
        "commodity_risk_score": risk_score,
        "crude_impact":        _crude_impact_description(crude_chg),
        "gold_signal": (
            "RISK_OFF — gold rising signals defensive demand."
            if gold_chg > 0.5 else
            "RISK_ON — gold falling, investors prefer equities." if gold_chg < -0.5
            else "Gold neutral — no strong risk signal."
        ),
        "inflation_risk": (
            "HIGH" if crude_chg > 2 else
            "MEDIUM" if crude_chg > 0.5 else "LOW"
        ),
    }

    _cache[cache_key] = {"data": result, "ts": datetime.now(timezone.utc)}
    return result
