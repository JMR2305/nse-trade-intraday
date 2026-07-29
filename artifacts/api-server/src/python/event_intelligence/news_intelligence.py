"""
news_intelligence.py — Phase 7.2
Synthesises company, sector, market, global, and economic news
from existing scan data and market regime analysis.

Generates: News Importance Score, News Freshness Score, Duplicate Detection,
           Related Companies, Related Sectors.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List

from .models import (
    EventRecord, TYPE_NEWS,
    NEWS_COMPANY, NEWS_SECTOR, NEWS_MARKET, NEWS_GLOBAL, NEWS_ECONOMIC, NEWS_BREAKING,
    IMPACT_BULLISH, IMPACT_BEARISH, IMPACT_NEUTRAL, IMPACT_VOLATILE,
    priority_from_score,
)


def _eid(prefix: str, key: str) -> str:
    raw = f"{prefix}:{key}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _freshness_score(event_date: str) -> float:
    """Decays from 100 (today) to ~10 (7 days old)."""
    try:
        dt = datetime.fromisoformat(event_date)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return max(10.0, 100.0 - age_hours * 1.5)
    except Exception:
        return 50.0


def _sector_for(symbol: str) -> str:
    _MAP = {
        "RELIANCE": "Energy", "TCS": "IT", "INFY": "IT",
        "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
        "WIPRO": "IT", "LT": "Infrastructure", "BAJFINANCE": "NBFC",
        "MARUTI": "Auto",
    }
    return _MAP.get(symbol, "Diversified")


# ── Company news from scan signals ────────────────────────────────────────────

def _build_company_news(signals: list) -> List[EventRecord]:
    events: List[EventRecord] = []
    for sig in signals:
        symbol = sig.get("symbol", "")
        if not symbol:
            continue
        score_raw = float(sig.get("opportunity_score") or sig.get("composite_score") or 50.0)
        confidence = float(sig.get("confidence") or 50.0)
        recommendation = str(sig.get("recommendation") or sig.get("ai_recommendation") or "HOLD")
        sector = sig.get("sector") or _sector_for(symbol)

        if score_raw > 70:
            direction = IMPACT_BULLISH
            headline  = f"{symbol} — Strong Buy Signal: Opportunity Score {score_raw:.0f}/100"
            desc      = (f"{symbol} ({sector}) generating strong opportunity signals. "
                         f"AI confidence: {confidence:.0f}%. Advisory only — not a trade order.")
            imp_score = min(85.0, score_raw)
        elif score_raw < 35:
            direction = IMPACT_BEARISH
            headline  = f"{symbol} — Caution: Weak Signal (Score {score_raw:.0f}/100)"
            desc      = (f"{symbol} ({sector}) showing weakness. "
                         f"Score: {score_raw:.0f}/100 · Confidence: {confidence:.0f}%.")
            imp_score = 60.0
        else:
            continue   # Only surface notable signals as "news"

        events.append(EventRecord(
            event_id          = _eid("CNEWS", f"{symbol}_{_today()}"),
            event_type        = TYPE_NEWS,
            sub_type          = NEWS_COMPANY,
            title             = headline,
            description       = desc,
            symbol            = symbol,
            sector            = sector,
            event_date        = _today(),
            discovered_at     = _now_iso(),
            importance_score  = imp_score,
            confidence_score  = confidence,
            impact_direction  = direction,
            expected_volatility = 1.5,
            expected_duration = "1D",
            priority          = priority_from_score(imp_score),
            affected_stocks   = [symbol],
            affected_sectors  = [sector],
            trading_risk      = "Advisory signal only — verify before acting",
            opportunity       = f"Recommendation: {recommendation}" if direction == IMPACT_BULLISH else None,
            source            = "SCAN_SIGNALS",
        ))
    return events


# ── Sector news from regime + sector analysis ─────────────────────────────────

def _build_sector_news() -> List[EventRecord]:
    events: List[EventRecord] = []
    try:
        from market_intelligence_hub.shared_services import get_sectors
        sector_data = get_sectors()
        rankings = sector_data.get("rankings", [])
        for rank_item in rankings[:3]:  # Top 3 sectors
            sector = rank_item.get("sector") or rank_item.get("name", "Unknown")
            score  = float(rank_item.get("score") or rank_item.get("composite_score") or 50.0)
            trend  = rank_item.get("trend") or rank_item.get("direction") or "NEUTRAL"
            impact = IMPACT_BULLISH if "BULL" in trend.upper() or score > 65 else \
                     IMPACT_BEARISH if "BEAR" in trend.upper() or score < 35 else IMPACT_NEUTRAL
            events.append(EventRecord(
                event_id          = _eid("SNEWS", f"{sector}_{_today()}"),
                event_type        = TYPE_NEWS,
                sub_type          = NEWS_SECTOR,
                title             = f"{sector} Sector — {trend} Trend (Score {score:.0f}/100)",
                description       = (f"{sector} sector composite score: {score:.0f}/100. "
                                     f"Trend: {trend}. Monitor sector-level rotation."),
                symbol            = None,
                sector            = sector,
                event_date        = _today(),
                discovered_at     = _now_iso(),
                importance_score  = min(80.0, score),
                confidence_score  = 65.0,
                impact_direction  = impact,
                expected_volatility = 1.0,
                expected_duration = "3D",
                priority          = priority_from_score(min(80.0, score)),
                affected_stocks   = [],
                affected_sectors  = [sector],
                trading_risk      = "Sector rotation may affect individual stocks",
                opportunity       = f"Top sector: rotate into {sector} names" if impact == IMPACT_BULLISH else None,
                source            = "MARKET_INTELLIGENCE",
            ))
    except Exception:
        pass
    return events


# ── Market-level and economic news ────────────────────────────────────────────

def _build_market_news() -> List[EventRecord]:
    events: List[EventRecord] = []
    try:
        from market_intelligence_hub.shared_services import get_summary
        summary = get_summary()
        regime  = str(summary.get("market_regime") or summary.get("regime", "UNKNOWN")).upper()
        health  = float(summary.get("health_score") or 50.0)
        breadth = summary.get("breadth") or {}
        adv_dec = float(breadth.get("advance_decline_ratio") or 1.0)

        # Market health headline
        impact    = IMPACT_BULLISH if health > 65 else IMPACT_BEARISH if health < 40 else IMPACT_NEUTRAL
        imp_score = health
        events.append(EventRecord(
            event_id          = _eid("MNEWS", f"health_{_today()}"),
            event_type        = TYPE_NEWS,
            sub_type          = NEWS_MARKET,
            title             = f"Market Intelligence: {regime} Regime · Health {health:.0f}/100",
            description       = (f"Current market regime: {regime}. "
                                 f"Health score: {health:.0f}/100. "
                                 f"Advance/Decline ratio: {adv_dec:.2f}."),
            symbol            = None,
            sector            = None,
            event_date        = _today(),
            discovered_at     = _now_iso(),
            importance_score  = imp_score,
            confidence_score  = 70.0,
            impact_direction  = impact,
            expected_volatility = 1.0,
            expected_duration = "1D",
            priority          = priority_from_score(imp_score),
            affected_stocks   = [],
            affected_sectors  = ["All"],
            trading_risk      = "Regime shift may invalidate existing signals",
            opportunity       = "Align strategy with regime direction" if impact == IMPACT_BULLISH else None,
            source            = "MARKET_INTELLIGENCE",
        ))
    except Exception:
        # Fallback static market news
        events.append(EventRecord(
            event_id         = _eid("MNEWS", f"fallback_{_today()}"),
            event_type       = TYPE_NEWS,
            sub_type         = NEWS_MARKET,
            title            = "Market Intelligence Data: Status Check Required",
            description      = "Market Intelligence Hub data not available. Run a live scan to update.",
            event_date       = _today(),
            discovered_at    = _now_iso(),
            importance_score = 40.0,
            confidence_score = 30.0,
            impact_direction = IMPACT_NEUTRAL,
            expected_duration = "1D",
            priority         = priority_from_score(40.0),
            affected_sectors = ["All"],
            source           = "SYSTEM",
        ))

    # Economic headlines (static advisory)
    econ_items = [
        ("RBI Monetary Policy: Rate Decision Pending",
         "RBI MPC meeting scheduled. Interest rate decision expected to impact "
         "Banking, NBFC, and rate-sensitive sectors.",
         NEWS_ECONOMIC, 75.0, IMPACT_VOLATILE, "Banking"),
        ("India CPI Inflation Data Release",
         "Monthly CPI inflation data release. Above-expectation inflation "
         "could trigger rate hike concerns.",
         NEWS_ECONOMIC, 70.0, IMPACT_VOLATILE, "All"),
    ]
    for i, (title, desc, sub, imp, direction, sector_) in enumerate(econ_items):
        offset = i * 5
        events.append(EventRecord(
            event_id         = _eid("ECON", f"{i}_{_today()}"),
            event_type       = TYPE_NEWS,
            sub_type         = sub,
            title            = title,
            description      = desc,
            symbol           = None,
            sector           = sector_,
            event_date       = (datetime.now(timezone.utc) + timedelta(days=offset)).strftime("%Y-%m-%d"),
            discovered_at    = _now_iso(),
            importance_score = imp,
            confidence_score = 60.0,
            impact_direction = direction,
            expected_volatility = 2.0,
            expected_duration = "2D",
            priority         = priority_from_score(imp),
            affected_stocks  = [],
            affected_sectors = [sector_],
            trading_risk     = "Macro events can cause sudden volatility",
            opportunity      = None,
            source           = "ADVISORY_CALENDAR",
        ))
    return events


# ── Duplicate detection ───────────────────────────────────────────────────────

def _deduplicate(events: List[EventRecord]) -> List[EventRecord]:
    seen_ids: set = set()
    seen_titles: set = set()
    result = []
    for e in events:
        title_key = e.title[:40].lower().strip()
        if e.event_id in seen_ids or title_key in seen_titles:
            e.is_duplicate = True
            continue
        seen_ids.add(e.event_id)
        seen_titles.add(title_key)
        result.append(e)
    return result


# ── Public function ───────────────────────────────────────────────────────────

def get_news_events() -> dict:
    """Returns all categorised news events with importance/freshness scores."""
    try:
        signals: list = []
        try:
            from signals_cache import get_latest_signals
            signals = get_latest_signals() or []
        except Exception:
            pass

        events: List[EventRecord] = []
        events.extend(_build_company_news(signals))
        events.extend(_build_sector_news())
        events.extend(_build_market_news())

        deduped = _deduplicate(events)
        deduped.sort(key=lambda e: e.importance_score, reverse=True)

        # Compute freshness scores
        for e in deduped:
            if e.event_date:
                e.confidence_score = min(
                    e.confidence_score,
                    _freshness_score(e.event_date)
                )

        by_type = {
            NEWS_COMPANY:  [e.to_dict() for e in deduped if e.sub_type == NEWS_COMPANY],
            NEWS_SECTOR:   [e.to_dict() for e in deduped if e.sub_type == NEWS_SECTOR],
            NEWS_MARKET:   [e.to_dict() for e in deduped if e.sub_type == NEWS_MARKET],
            NEWS_ECONOMIC: [e.to_dict() for e in deduped if e.sub_type == NEWS_ECONOMIC],
            NEWS_GLOBAL:   [],  # Requires external feed — future integration
        }

        return {
            "available":       True,
            "events":          [e.to_dict() for e in deduped],
            "total":           len(deduped),
            "by_type":         {k: len(v) for k, v in by_type.items()},
            "categorised":     by_type,
            "high_importance": [e.to_dict() for e in deduped if e.importance_score >= 70],
            "advisory_only":   True,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc), "events": [], "advisory_only": True}
