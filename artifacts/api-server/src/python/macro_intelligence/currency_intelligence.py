"""
currency_intelligence.py — Phase 7.3
Currency intelligence: USD/INR, EUR/INR, JPY/INR, Dollar Index.
Fetches via yfinance with session-level cache.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from datetime import datetime, timezone

_cache: dict = {}
_CACHE_TTL_S = 300   # 5 minutes

_CURRENCY_TICKERS = {
    "USD/INR":      "USDINR=X",
    "EUR/INR":      "EURINR=X",
    "JPY/INR":      "JPYINR=X",
    "Dollar Index": "DX-Y.NYB",
    "GBP/INR":      "GBPINR=X",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_valid(key: str) -> bool:
    if key not in _cache:
        return False
    return (datetime.now(timezone.utc) - _cache[key]["ts"]).total_seconds() < _CACHE_TTL_S


def _fetch_pair(ticker: str) -> dict:
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info
        price = float(fi.last_price or 0)
        prev  = float(fi.previous_close or price)
        change_pct = round(((price - prev) / prev * 100) if prev else 0.0, 3)
        return {"price": round(price, 4), "change_pct": change_pct, "available": price > 0}
    except Exception:
        return {"price": 0.0, "change_pct": 0.0, "available": False}


def _volatility_label(pairs: list) -> str:
    changes = [abs(p["change_pct"]) for p in pairs if p.get("available")]
    if not changes:
        return "UNKNOWN"
    avg = sum(changes) / len(changes)
    if avg >= 0.5:   return "HIGH"
    if avg >= 0.25:  return "MEDIUM"
    return "LOW"


def _usd_inr_impact(change_pct: float) -> str:
    """Describes the market impact of INR move vs USD."""
    if change_pct > 0.3:
        return "INR weakening — bearish for importers (Oil, Electronics). Positive for IT/Pharma exporters."
    if change_pct < -0.3:
        return "INR strengthening — positive for importers. May weigh on IT/Pharma export margins."
    return "INR stable — limited currency impact on equities today."


def _dxy_impact(change_pct: float) -> str:
    if change_pct > 0.3:
        return "Strong USD (DXY rising) → FII outflow pressure on EMs including India."
    if change_pct < -0.3:
        return "Weak USD (DXY falling) → EM inflow, positive for Indian equities."
    return "DXY neutral — no significant EM currency pressure."


def get_currency_intelligence() -> dict:
    cache_key = "currency_intelligence"
    if _cache_valid(cache_key):
        return _cache[cache_key]["data"]

    pairs = []
    for name, ticker in _CURRENCY_TICKERS.items():
        data = _fetch_pair(ticker)
        direction = (
            "BEARISH_INR" if (name != "Dollar Index" and data["change_pct"] > 0.2)
            else "BULLISH_INR" if (name != "Dollar Index" and data["change_pct"] < -0.2)
            else ("BULLISH" if data["change_pct"] < -0.2 else
                  "BEARISH" if data["change_pct"] > 0.2 else "NEUTRAL")
        )
        pairs.append({
            "name":        name,
            "ticker":      ticker,
            "price":       data["price"],
            "change_pct":  data["change_pct"],
            "direction":   direction,
            "available":   data["available"],
        })

    usd_inr  = next((p for p in pairs if p["name"] == "USD/INR"), {})
    dxy      = next((p for p in pairs if p["name"] == "Dollar Index"), {})
    vol_lbl  = _volatility_label(pairs)

    # Overall currency risk: DXY strength + INR weakness = bearish for India
    usd_chg  = float(usd_inr.get("change_pct", 0))
    dxy_chg  = float(dxy.get("change_pct", 0))
    risk_score = 50.0 + usd_chg * 15 + dxy_chg * 10
    risk_score = round(min(100, max(0, risk_score)), 1)

    result = {
        "available":            True,
        "advisory_only":        True,
        "generated_at":         _now_iso(),
        "pairs":                pairs,
        "usd_inr":              usd_inr,
        "dollar_index":         dxy,
        "currency_volatility":  vol_lbl,
        "currency_risk_score":  risk_score,
        "usd_inr_impact":       _usd_inr_impact(usd_chg),
        "dxy_impact":           _dxy_impact(dxy_chg),
        "affected_sectors": {
            "exporters": ["IT", "Pharma", "Textiles", "Chemicals"],
            "importers":  ["Oil & Gas", "Consumer Electronics", "Aviation"],
        },
        "summary": (
            f"USD/INR at {usd_inr.get('price', 'N/A')} "
            f"({'weakening' if usd_chg > 0 else 'strengthening'} INR). "
            f"DXY {'+' if dxy_chg >= 0 else ''}{dxy_chg}%."
        ),
    }

    _cache[cache_key] = {"data": result, "ts": datetime.now(timezone.utc)}
    return result
