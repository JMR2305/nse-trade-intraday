"""
phase15_quality.py — Phase 15: Data Quality Engine + Stale Data Detection

Per-stock Data Quality Score (0-100) from the canonical scan snapshot:
  price feed validity, volume data, indicator completeness, historical depth,
  missing-candle detection (via data age), and feed freshness.

Bands: 95-100 Excellent | 90-94 Good | 80-89 Warning | <80 Do Not Trade.

Stale detection compares current time vs last scan time vs market feed time.
When stale: BUY recommendations are disabled — only Refresh or Watch allowed.

Read-only over cached data. PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from phase15_scan_context import (
    build_scan_context, scan_age_seconds, STALE_AFTER_S, _load, _load_scan, SCAN_CACHE, _parse_ts,
)

BAND_EXCELLENT = "EXCELLENT"
BAND_GOOD = "GOOD"
BAND_WARNING = "WARNING"
BAND_DO_NOT_TRADE = "DO_NOT_TRADE"


def _band(score: float) -> str:
    if score >= 95:
        return BAND_EXCELLENT
    if score >= 90:
        return BAND_GOOD
    if score >= 80:
        return BAND_WARNING
    return BAND_DO_NOT_TRADE


def score_symbol(item: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the data quality score for one canonical scan item."""
    components: List[Dict[str, Any]] = []

    def add(name: str, earned: float, maximum: float, note: str) -> None:
        components.append({"component": name, "earned": round(earned, 1),
                           "max": maximum, "note": note})

    # 1. Price feed (25)
    entry = float(item.get("entry_price") or 0)
    if item.get("error"):
        add("price_feed", 0, 25, f"Symbol errored: {item['error']}")
    elif entry > 1.0:
        add("price_feed", 25, 25, f"Valid price ₹{entry:.2f}")
    else:
        add("price_feed", 0, 25, f"Invalid/missing price ₹{entry}")

    # 2. Volume data (15)
    vr = item.get("indicators", {}).get("volume_ratio")
    if vr is None or (isinstance(vr, (int, float)) and vr <= 0):
        add("volume_data", 0, 15, "Volume ratio missing or zero")
    elif vr < 0.3:
        add("volume_data", 8, 15, f"Very low volume ratio {vr}")
    else:
        add("volume_data", 15, 15, f"Volume ratio {vr}")

    # 3. Indicator completeness (20)
    ind = item.get("indicators", {})
    present = sum(1 for k in ("adx", "rsi", "volume_ratio") if ind.get(k) not in (None, 0, 0.0))
    add("indicator_completeness", present / 3 * 20, 20,
        f"{present}/3 core indicators non-zero (ADX/RSI/VolumeRatio)")

    # 4. Historical depth (20)
    bars = int(item.get("bars_available") or 0)
    if bars >= 200:
        add("historical_depth", 20, 20, f"{bars} bars")
    elif bars >= 100:
        add("historical_depth", 15, 20, f"{bars} bars (limited)")
    elif bars >= 30:
        add("historical_depth", 8, 20, f"{bars} bars (thin history)")
    else:
        add("historical_depth", 0, 20, f"Only {bars} bars")

    # 5. Feed freshness / missing candles (20)
    age = item.get("data_age_days")
    quality = str(item.get("data_quality") or "")
    if quality in ("LIVE", "NEAR_LIVE") and age is not None and age <= 3:
        add("feed_freshness", 20, 20, f"{quality}, age {age}d")
    elif quality == "STALE" or (age is not None and age > 3):
        add("feed_freshness", 8, 20, f"Stale feed — age {age}d ({quality}) — possible missing candles")
    else:
        add("feed_freshness", 0, 20, f"Feed {quality or 'UNKNOWN'}, age {age}")

    total = round(sum(c["earned"] for c in components), 1)
    band = _band(total)
    return {
        "symbol": item.get("symbol"),
        "data_quality_score": total,
        "band": band,
        "tradeable": band != BAND_DO_NOT_TRADE,
        "components": components,
    }


def quality_report() -> Dict[str, Any]:
    ctx = build_scan_context()
    if not ctx.get("available"):
        return {"available": False, "reason": ctx.get("reason")}
    scores = [score_symbol(item) for item in ctx["symbols"].values()]
    scores.sort(key=lambda s: s["data_quality_score"], reverse=True)
    bands: Dict[str, int] = {}
    for s in scores:
        bands[s["band"]] = bands.get(s["band"], 0) + 1
    return {
        "available": True,
        "scan_id": ctx["scan_id"], "snapshot_ts": ctx["snapshot_ts"],
        "band_thresholds": {"EXCELLENT": "95-100", "GOOD": "90-94",
                            "WARNING": "80-89", "DO_NOT_TRADE": "<80"},
        "band_counts": bands,
        "avg_score": round(sum(s["data_quality_score"] for s in scores) / len(scores), 1) if scores else 0,
        "symbols": scores,
        "label": "PAPER / RESEARCH ONLY",
    }


def staleness_report() -> Dict[str, Any]:
    # Phase 19B fix: use the DB-backed canonical store (same source as
    # /live-data/scan and build_scan_context), not the local file only.
    # The local phase7_scan_cache.json may lag the DB on Autoscale — reading
    # it directly caused false-stale reports even when the scan had just
    # completed successfully and was visible in all other endpoints.
    scan = _load_scan() or {}
    now = datetime.now(timezone.utc)
    age_s = scan_age_seconds(scan)
    stale = age_s is None or age_s > STALE_AFTER_S

    # Build a machine-readable stale_reason so operators (and UIs) know exactly
    # why the scan is considered stale — avoids the opaque "age unknown" message.
    if not stale:
        _stale_reason = None
    elif age_s is None:
        _stale_reason = (
            "no_snapshot_ts"  # scan dict loaded but snapshot_ts field absent/unparseable
            if scan
            else "no_snapshot"  # _load_scan() returned nothing at all
        )
    else:
        _stale_reason = "age_exceeded"  # snapshot_ts present but older than 90m

    # Market feed time = newest bar across recommendations
    feed_dates = [r.get("latest_bar_date") for r in scan.get("recommendations", [])
                  if r.get("latest_bar_date")]
    latest_feed = max(feed_dates) if feed_dates else None
    feed_age_days = None
    if latest_feed:
        dt = _parse_ts(str(latest_feed)[:19])
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            feed_age_days = round((now - dt).total_seconds() / 86400, 2)

    def _fmt(seconds: float) -> str:
        m = int(seconds // 60)
        return f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"

    return {
        "current_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_scan_time": scan.get("snapshot_ts"),
        "scan_id": scan.get("scan_id"),
        "market_feed_time": latest_feed,
        "scan_age_seconds": round(age_s, 0) if age_s is not None else None,
        "scan_age_human": _fmt(age_s) if age_s is not None else None,
        "feed_age_days": feed_age_days,
        "stale_after_seconds": STALE_AFTER_S,
        "stale": stale,
        # Machine-readable reason: null (fresh) | "no_snapshot" | "no_snapshot_ts" | "age_exceeded"
        "stale_reason": _stale_reason,
        "buy_recommendations_disabled": stale,
        "allowed_actions_when_stale": ["REFRESH", "WATCH"],
        "warning": (f"Scan data is stale ({_fmt(age_s)} old — limit "
                    f"{STALE_AFTER_S // 60}m). BUY recommendations disabled; "
                    "refresh the scan or continue watching only.") if stale and age_s is not None
                   else ("No scan snapshot available — run a scan." if stale else None),
        "label": "PAPER / RESEARCH ONLY",
    }
