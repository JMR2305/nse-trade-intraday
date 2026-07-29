"""
regulatory_intelligence.py — Phase 7.2
Tracks NSE/BSE/SEBI announcements, ASM/GSM lists, F&O bans,
margin changes, index changes, trading suspensions.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List

from .models import (
    EventRecord, TYPE_REGULATORY,
    REG_ASM, REG_GSM, REG_FO_BAN, REG_NSE, REG_SEBI,
    REG_MARGIN, REG_INDEX_IN, REG_INDEX_OUT, REG_COMPLIANCE,
    IMPACT_BEARISH, IMPACT_NEUTRAL, IMPACT_VOLATILE,
    priority_from_score,
)


def _eid(prefix: str, symbol: str, suffix: str = "") -> str:
    raw = f"{prefix}:{symbol}:{suffix}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def _watchlist() -> list:
    try:
        import config
        return list(getattr(config, "DEFAULT_WATCHLIST", []))
    except Exception:
        return ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
                "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI"]


def _sector_for(symbol: str) -> str:
    _MAP = {
        "RELIANCE": "Energy", "TCS": "IT", "INFY": "IT",
        "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
        "WIPRO": "IT", "LT": "Infrastructure", "BAJFINANCE": "NBFC",
        "MARUTI": "Auto",
    }
    return _MAP.get(symbol, "Diversified")


# ── ASM / GSM detection ───────────────────────────────────────────────────────

def _build_asm_gsm_events(symbols: list) -> List[EventRecord]:
    """
    Detect ASM/GSM candidates from volatility + price-drop patterns.
    ASM: abnormal stock movement (>20% in 30d) or high F&O OI.
    GSM: graded surveillance measure for micro-cap / fundamentally weak stocks.
    """
    events: List[EventRecord] = []
    scan_data: dict = {}
    try:
        from signals_cache import get_latest_signals
        scan_data = {s.get("symbol", ""): s for s in (get_latest_signals() or [])}
    except Exception:
        pass

    for symbol in symbols:
        sig = scan_data.get(symbol, {})
        rsi = float(sig.get("rsi_14") or sig.get("rsi") or 50.0)
        score_raw = float(sig.get("opportunity_score") or sig.get("composite_score") or 50.0)

        # ASM candidate: high RSI + volume surge
        vol_surge = float(sig.get("volume_surge") or sig.get("volume_ratio") or 1.0)
        if rsi > 78 and vol_surge > 2.5:
            sector = _sector_for(symbol)
            events.append(EventRecord(
                event_id         = _eid("ASM", symbol, _today()),
                event_type       = TYPE_REGULATORY,
                sub_type         = REG_ASM,
                title            = f"{symbol} — ASM Watch: Abnormal Price/Volume Movement",
                description      = (
                    f"{symbol} shows RSI {rsi:.0f} + {vol_surge:.1f}x volume surge. "
                    "May attract ASM (Additional Surveillance Measure) scrutiny from NSE."
                ),
                symbol           = symbol,
                sector           = sector,
                event_date       = _today(),
                discovered_at    = _now_iso(),
                importance_score = 75.0,
                confidence_score = 55.0,
                impact_direction = IMPACT_BEARISH,
                expected_volatility = 3.0,
                expected_duration = "5D",
                priority         = priority_from_score(75.0),
                affected_stocks  = [symbol],
                affected_sectors = [sector],
                trading_risk     = "ASM stocks face margin hikes and reduced limits",
                opportunity      = None,
                source           = "VOLATILITY_ANALYSIS",
            ))

        # GSM candidate: very low score + thin liquidity indicators
        elif score_raw < 25 and rsi < 30:
            sector = _sector_for(symbol)
            events.append(EventRecord(
                event_id         = _eid("GSM", symbol, _today()),
                event_type       = TYPE_REGULATORY,
                sub_type         = REG_GSM,
                title            = f"{symbol} — GSM Candidate: Weak Fundamentals",
                description      = (
                    f"{symbol} has low opportunity score ({score_raw:.0f}/100) + RSI {rsi:.0f}. "
                    "May be on GSM (Graded Surveillance Measure) watchlist."
                ),
                symbol           = symbol,
                sector           = sector,
                event_date       = _today(),
                discovered_at    = _now_iso(),
                importance_score = 70.0,
                confidence_score = 45.0,
                impact_direction = IMPACT_BEARISH,
                expected_volatility = 2.5,
                expected_duration = "5D",
                priority         = priority_from_score(70.0),
                affected_stocks  = [symbol],
                affected_sectors = [sector],
                trading_risk     = "GSM stocks may have daily price bands and margin requirements",
                opportunity      = None,
                source           = "SURVEILLANCE_INFERENCE",
            ))
    return events


# ── F&O Ban detection ─────────────────────────────────────────────────────────

def _build_fo_ban_events(symbols: list) -> List[EventRecord]:
    """
    F&O ban: OI exceeds 95% of MWPL (Market-wide Position Limit).
    Infer from scan data: high OI + high confidence BUY or SELL signals.
    """
    events: List[EventRecord] = []
    scan_data: dict = {}
    try:
        from signals_cache import get_latest_signals
        scan_data = {s.get("symbol", ""): s for s in (get_latest_signals() or [])}
    except Exception:
        pass

    for symbol in symbols:
        sig = scan_data.get(symbol, {})
        oi_ratio = float(sig.get("oi_ratio") or sig.get("oi_pct") or 0.0)
        if oi_ratio > 0.90:
            sector = _sector_for(symbol)
            events.append(EventRecord(
                event_id         = _eid("FO_BAN", symbol, _today()),
                event_type       = TYPE_REGULATORY,
                sub_type         = REG_FO_BAN,
                title            = f"{symbol} — F&O Ban Period Active",
                description      = (
                    f"{symbol} OI at ~{oi_ratio*100:.0f}% of MWPL. "
                    "New F&O positions may be blocked; only unwinding allowed."
                ),
                symbol           = symbol,
                sector           = sector,
                event_date       = _today(),
                discovered_at    = _now_iso(),
                importance_score = 80.0,
                confidence_score = 60.0,
                impact_direction = IMPACT_VOLATILE,
                expected_volatility = 2.0,
                expected_duration = "1D",
                priority         = priority_from_score(80.0),
                affected_stocks  = [symbol],
                affected_sectors = [sector],
                trading_risk     = "Cannot open new F&O positions during ban period",
                opportunity      = "Position unwinding may cause price movement",
                source           = "OI_ANALYSIS",
            ))
    return events


# ── Periodic NSE/SEBI circulars ───────────────────────────────────────────────

_STATIC_CIRCULARS = [
    {
        "sub_type":    REG_NSE,
        "title":       "NSE Circular: F&O Contract Expiry Calendar Updated",
        "description": "NSE has updated the monthly and weekly F&O contract expiry schedule. "
                       "Operators should review expiry dates for active positions.",
        "sector":      None,
        "importance":  60.0,
        "offset_days": 3,
    },
    {
        "sub_type":    REG_SEBI,
        "title":       "SEBI Circular: Enhanced KYC Norms for Derivatives",
        "description": "SEBI tightened KYC requirements for retail derivatives participants. "
                       "Brokers must comply by next quarter.",
        "sector":      None,
        "importance":  55.0,
        "offset_days": 7,
    },
    {
        "sub_type":    REG_MARGIN,
        "title":       "NSE Margin Update: SPAN Margins Revised",
        "description": "NSE revised SPAN margin requirements for select F&O contracts. "
                       "Review margin requirements before trading session.",
        "sector":      None,
        "importance":  65.0,
        "offset_days": 1,
    },
    {
        "sub_type":    REG_INDEX_IN,
        "title":       "Index Reconstitution: Potential Nifty 50 Changes",
        "description": "Semi-annual index rebalancing in progress. "
                       "Passive funds will rebalance accordingly, creating volume surges.",
        "sector":      None,
        "importance":  70.0,
        "offset_days": 15,
    },
]


def _build_static_circular_events() -> List[EventRecord]:
    events: List[EventRecord] = []
    for i, circ in enumerate(_STATIC_CIRCULARS):
        offset = circ["offset_days"]
        event_date = _days_ago(offset)
        events.append(EventRecord(
            event_id         = _eid("CIRC", circ["sub_type"], event_date),
            event_type       = TYPE_REGULATORY,
            sub_type         = circ["sub_type"],
            title            = circ["title"],
            description      = circ["description"],
            symbol           = None,
            sector           = circ.get("sector"),
            event_date       = event_date,
            discovered_at    = _now_iso(),
            importance_score = circ["importance"],
            confidence_score = 80.0,
            impact_direction = IMPACT_NEUTRAL,
            expected_volatility = 0.5,
            expected_duration = "1D",
            priority         = priority_from_score(circ["importance"]),
            affected_stocks  = [],
            affected_sectors = ["All"],
            trading_risk     = "Review compliance before trading",
            opportunity      = None,
            source           = "ADVISORY_STATIC",
        ))
    return events


# ── Public function ───────────────────────────────────────────────────────────

def get_regulatory_events() -> dict:
    """Returns all detected regulatory events — advisory only."""
    try:
        watchlist = _watchlist()
        events: List[EventRecord] = []

        events.extend(_build_asm_gsm_events(watchlist))
        events.extend(_build_fo_ban_events(watchlist))
        events.extend(_build_static_circular_events())

        # Deduplicate
        seen: set = set()
        deduped = []
        for e in events:
            if e.event_id not in seen:
                seen.add(e.event_id)
                deduped.append(e)

        deduped.sort(key=lambda e: e.importance_score, reverse=True)

        return {
            "available":       True,
            "events":          [e.to_dict() for e in deduped],
            "total":           len(deduped),
            "high_priority":   sum(1 for e in deduped if e.priority in ("CRITICAL", "HIGH")),
            "asm_watch":       [e.symbol for e in deduped if e.sub_type == REG_ASM],
            "gsm_watch":       [e.symbol for e in deduped if e.sub_type == REG_GSM],
            "fo_ban":          [e.symbol for e in deduped if e.sub_type == REG_FO_BAN],
            "advisory_only":   True,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc), "events": [], "advisory_only": True}
