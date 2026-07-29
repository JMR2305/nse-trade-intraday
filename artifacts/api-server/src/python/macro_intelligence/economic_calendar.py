"""
economic_calendar.py — Phase 7.3
Static economic calendar: RBI policy, inflation, GDP, IIP, PMI, trade balance,
fiscal data, and major global macro events.

READ-ONLY. ADVISORY-ONLY. No live API calls.
Dates are anchored to the calendar year in which this module runs.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import List

from .models import (
    MacroEvent,
    CAT_ECONOMIC, CAT_CENTRAL_BANK,
    ECO_RBI_POLICY, ECO_CPI, ECO_WPI, ECO_GDP, ECO_IIP,
    ECO_PMI, ECO_TRADE_BALANCE, ECO_BUDGET, ECO_GLOBAL_EVENT,
    DIR_NEUTRAL, RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_EXTREME,
    PRI_CRITICAL, PRI_HIGH, PRI_MEDIUM, PRI_LOW,
)

_NOW = datetime.now(timezone.utc)
_TODAY_STR = _NOW.strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_upcoming(date_str: str) -> bool:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return d > _NOW
    except Exception:
        return False


def _month_label(year: int, month: int) -> str:
    return datetime(year, month, 1).strftime("%B %Y")


# ── RBI MPC events ────────────────────────────────────────────────────────────

def _rbi_events() -> List[MacroEvent]:
    y = _NOW.year
    # Six MPC meetings per year — approximate dates per 2026 schedule
    dates = [
        f"{y}-02-05", f"{y}-04-09", f"{y}-06-04",
        f"{y}-08-06", f"{y}-10-08", f"{y}-12-03",
    ]
    events = []
    for d in dates:
        upcoming = _is_upcoming(d)
        events.append(MacroEvent(
            event_id           = f"rbi_mpc_{d}",
            category           = CAT_CENTRAL_BANK,
            sub_type           = ECO_RBI_POLICY,
            title              = f"RBI MPC Policy Decision — {d}",
            description        = (
                "Reserve Bank of India Monetary Policy Committee meeting. "
                "Decisions on Repo Rate, Reverse Repo Rate, CRR, SLR, and monetary stance."
            ),
            event_date         = d,
            discovered_at      = _now_iso(),
            importance_score   = 95.0,
            confidence_score   = 95.0,
            direction          = DIR_NEUTRAL,
            expected_volatility = RISK_HIGH,
            expected_duration  = "2D",
            priority           = PRI_CRITICAL,
            affected_sectors   = ["Banking", "NBFC", "Real Estate", "Auto", "IT"],
            affected_industries = ["Lending", "Insurance", "Mortgage", "Auto Loans"],
            historical_context = (
                "RBI MPC announcements historically cause 0.5–1.5% Nifty intraday move. "
                "Repo rate cuts benefit Banking, NBFC, Real Estate. Hikes weigh on same."
            ),
            trading_risk       = "Reduce position size before policy announcement. IV spike expected.",
            opportunity        = (
                "Rate cut → Banking/NBFC/Real Estate rally opportunity. "
                "Status quo with dovish commentary → gradual accumulation."
            ),
            source             = "RBI_MPC_SCHEDULE",
            is_upcoming        = upcoming,
        ))
    return events


# ── CPI / WPI inflation ───────────────────────────────────────────────────────

def _inflation_events() -> List[MacroEvent]:
    y = _NOW.year
    events = []
    for m in range(1, 13):
        cpi_date = f"{y}-{m:02d}-12"
        wpi_date = f"{y}-{m:02d}-14"
        lbl      = _month_label(y, m)

        events.append(MacroEvent(
            event_id           = f"cpi_{y}_{m:02d}",
            category           = CAT_ECONOMIC,
            sub_type           = ECO_CPI,
            title              = f"CPI Inflation Release — {lbl}",
            description        = "Consumer Price Index monthly release. Key RBI policy input.",
            event_date         = cpi_date,
            discovered_at      = _now_iso(),
            importance_score   = 80.0,
            confidence_score   = 90.0,
            direction          = DIR_NEUTRAL,
            expected_volatility = RISK_MEDIUM,
            expected_duration  = "1D",
            priority           = PRI_HIGH,
            affected_sectors   = ["Banking", "NBFC", "FMCG", "Consumer Durables"],
            affected_industries = ["Consumer Staples", "Lending"],
            historical_context = "CPI > 6% (RBI upper band) → hawkish tilt → rate-sensitive sector underperformance.",
            trading_risk       = "Upside CPI surprise bearish for Banking and Real Estate.",
            opportunity        = "CPI within target → rate cut expectation → positive for interest-rate sensitives.",
            source             = "MOSPI",
            is_upcoming        = _is_upcoming(cpi_date),
        ))
        events.append(MacroEvent(
            event_id           = f"wpi_{y}_{m:02d}",
            category           = CAT_ECONOMIC,
            sub_type           = ECO_WPI,
            title              = f"WPI Inflation Release — {lbl}",
            description        = "Wholesale Price Index. Leads CPI by 1–2 months; signals producer-level inflation.",
            event_date         = wpi_date,
            discovered_at      = _now_iso(),
            importance_score   = 65.0,
            confidence_score   = 88.0,
            direction          = DIR_NEUTRAL,
            expected_volatility = RISK_LOW,
            expected_duration  = "1D",
            priority           = PRI_MEDIUM,
            affected_sectors   = ["Manufacturing", "Metals", "Chemicals", "Cement"],
            source             = "MOSPI",
            is_upcoming        = _is_upcoming(wpi_date),
        ))
    return events


# ── GDP ───────────────────────────────────────────────────────────────────────

def _gdp_events() -> List[MacroEvent]:
    y = _NOW.year
    releases = [
        (f"{y}-05-31",   f"Q4 FY{y}"),
        (f"{y}-08-31",   f"Q1 FY{y+1}"),
        (f"{y}-11-29",   f"Q2 FY{y+1}"),
        (f"{y+1}-02-28", f"Q3 FY{y+1}"),
    ]
    events = []
    for d, lbl in releases:
        events.append(MacroEvent(
            event_id           = f"gdp_{d}",
            category           = CAT_ECONOMIC,
            sub_type           = ECO_GDP,
            title              = f"India GDP Growth — {lbl}",
            description        = f"India quarterly GDP growth estimate ({lbl}).",
            event_date         = d,
            discovered_at      = _now_iso(),
            importance_score   = 88.0,
            confidence_score   = 85.0,
            direction          = DIR_NEUTRAL,
            expected_volatility = RISK_HIGH,
            expected_duration  = "2D",
            priority           = PRI_CRITICAL,
            affected_sectors   = ["All"],
            affected_industries = ["All"],
            historical_context = "GDP > 7% → broad rally. < 6% → defensive rotation, FII risk-off.",
            trading_risk       = "Weak GDP surprise triggers FII outflow from rate-sensitive sectors.",
            opportunity        = "Strong GDP → Infrastructure, Capital Goods outperform.",
            source             = "MOSPI",
            is_upcoming        = _is_upcoming(d),
        ))
    return events


# ── IIP + PMI ─────────────────────────────────────────────────────────────────

def _iip_pmi_events() -> List[MacroEvent]:
    y = _NOW.year
    events = []
    for m in range(1, 13):
        # IIP released with ~6-week lag
        iip_m = m + 1 if m < 12 else 1
        iip_y = y if m < 12 else y + 1
        iip_d = f"{iip_y}-{iip_m:02d}-12"
        lbl   = _month_label(y, m)

        events.append(MacroEvent(
            event_id           = f"iip_{y}_{m:02d}",
            category           = CAT_ECONOMIC,
            sub_type           = ECO_IIP,
            title              = f"IIP Industrial Output — {lbl}",
            description        = "Index of Industrial Production: manufacturing, mining, electricity output.",
            event_date         = iip_d,
            discovered_at      = _now_iso(),
            importance_score   = 70.0,
            confidence_score   = 85.0,
            direction          = DIR_NEUTRAL,
            expected_volatility = RISK_MEDIUM,
            expected_duration  = "1D",
            priority           = PRI_HIGH,
            affected_sectors   = ["Manufacturing", "Capital Goods", "Metals"],
            source             = "MOSPI",
            is_upcoming        = _is_upcoming(iip_d),
        ))

        pmi_d = f"{y}-{m:02d}-05"
        events.append(MacroEvent(
            event_id           = f"pmi_{y}_{m:02d}",
            category           = CAT_ECONOMIC,
            sub_type           = ECO_PMI,
            title              = f"India PMI Composite — {lbl}",
            description        = "S&P Global PMI Composite. Above 50 = expansion; below 50 = contraction.",
            event_date         = pmi_d,
            discovered_at      = _now_iso(),
            importance_score   = 72.0,
            confidence_score   = 88.0,
            direction          = DIR_NEUTRAL,
            expected_volatility = RISK_MEDIUM,
            expected_duration  = "1D",
            priority           = PRI_HIGH,
            affected_sectors   = ["Manufacturing", "IT Services", "FMCG"],
            historical_context = "PMI > 55 historically correlated with 2-3% market outperformance in same quarter.",
            source             = "SP_GLOBAL",
            is_upcoming        = _is_upcoming(pmi_d),
        ))
    return events


# ── Trade balance + budget ────────────────────────────────────────────────────

def _trade_fiscal_events() -> List[MacroEvent]:
    y = _NOW.year
    events = []
    for m in range(1, 13):
        tb_m = m + 1 if m < 12 else 1
        tb_y = y if m < 12 else y + 1
        tb_d = f"{tb_y}-{tb_m:02d}-20"
        events.append(MacroEvent(
            event_id           = f"trade_balance_{y}_{m:02d}",
            category           = CAT_ECONOMIC,
            sub_type           = ECO_TRADE_BALANCE,
            title              = f"Trade Balance — {_month_label(y, m)}",
            description        = "India monthly trade balance (exports vs imports). Affects INR and CAD.",
            event_date         = tb_d,
            discovered_at      = _now_iso(),
            importance_score   = 65.0,
            confidence_score   = 80.0,
            direction          = DIR_NEUTRAL,
            expected_volatility = RISK_LOW,
            expected_duration  = "1D",
            priority           = PRI_MEDIUM,
            affected_sectors   = ["Export IT", "Pharma", "Metals", "Auto"],
            source             = "DGCI",
            is_upcoming        = _is_upcoming(tb_d),
        ))

    # Union Budget (Feb 1)
    budget_d = f"{y}-02-01"
    events.append(MacroEvent(
        event_id           = f"union_budget_{y}",
        category           = CAT_ECONOMIC,
        sub_type           = ECO_BUDGET,
        title              = f"Union Budget {y}",
        description        = "Annual Union Budget: tax policy, capex allocation, sector duties, fiscal targets.",
        event_date         = budget_d,
        discovered_at      = _now_iso(),
        importance_score   = 98.0,
        confidence_score   = 95.0,
        direction          = DIR_NEUTRAL,
        expected_volatility = RISK_EXTREME if True else RISK_HIGH,
        expected_duration  = "5D",
        priority           = PRI_CRITICAL,
        affected_sectors   = ["All"],
        affected_industries = ["All"],
        historical_context = "Budget day is the highest-volatility day of the year; 3–5% Nifty intraday swings common.",
        trading_risk       = "Avoid naked positions on Budget day — gap risk beyond circuit limits.",
        opportunity        = "Sector allocation boosts drive 3–5 day sector momentum post-announcement.",
        source             = "MINISTRY_OF_FINANCE",
        is_upcoming        = _is_upcoming(budget_d),
    ))
    return events


# ── Global macro events (US Fed, ECB, BoJ) ────────────────────────────────────

def _global_events() -> List[MacroEvent]:
    y = _NOW.year
    events = []
    # US FOMC — 8 meetings per year, approximate mid-month dates
    fomc_months = [1, 3, 5, 6, 7, 9, 11, 12]
    for m in fomc_months:
        d = f"{y}-{m:02d}-15"
        events.append(MacroEvent(
            event_id           = f"fomc_{y}_{m:02d}",
            category           = CAT_ECONOMIC,
            sub_type           = ECO_GLOBAL_EVENT,
            title              = f"US Fed FOMC Decision — {_month_label(y, m)}",
            description        = "US Federal Reserve FOMC rate decision. Key global liquidity driver affecting FII flows.",
            event_date         = d,
            discovered_at      = _now_iso(),
            importance_score   = 88.0,
            confidence_score   = 90.0,
            direction          = DIR_NEUTRAL,
            expected_volatility = RISK_HIGH,
            expected_duration  = "2D",
            priority           = PRI_HIGH,
            affected_sectors   = ["Banking", "IT", "Metals", "Pharma"],
            historical_context = "Fed rate hike → DXY strengthens → FII outflow from India. Rate cut → reverse.",
            trading_risk       = "FOMC surprises cause 1–2% GIFT Nifty gap; wait for post-announcement clarity.",
            opportunity        = "Fed pause/cut → EM rally; rotate into rate-sensitive sectors.",
            source             = "US_FED",
            is_upcoming        = _is_upcoming(d),
        ))
    # ECB quarterly (approx. March, June, Sept, Dec)
    ecb_months = [3, 6, 9, 12]
    for m in ecb_months:
        d = f"{y}-{m:02d}-12"
        events.append(MacroEvent(
            event_id           = f"ecb_{y}_{m:02d}",
            category           = CAT_ECONOMIC,
            sub_type           = ECO_GLOBAL_EVENT,
            title              = f"ECB Rate Decision — {_month_label(y, m)}",
            description        = "European Central Bank rate decision. Affects EUR/INR and global liquidity.",
            event_date         = d,
            discovered_at      = _now_iso(),
            importance_score   = 70.0,
            confidence_score   = 85.0,
            direction          = DIR_NEUTRAL,
            expected_volatility = RISK_MEDIUM,
            expected_duration  = "1D",
            priority           = PRI_HIGH,
            affected_sectors   = ["IT", "Pharma", "Metals"],
            source             = "ECB",
            is_upcoming        = _is_upcoming(d),
        ))
    return events


# ── Public API ────────────────────────────────────────────────────────────────

def get_economic_calendar() -> dict:
    """Full economic calendar with upcoming/recent bucketing."""
    events: List[MacroEvent] = []
    events.extend(_rbi_events())
    events.extend(_inflation_events())
    events.extend(_gdp_events())
    events.extend(_iip_pmi_events())
    events.extend(_trade_fiscal_events())
    events.extend(_global_events())

    def _sort_key(e: MacroEvent):
        try:
            return datetime.strptime(e.event_date or "2099-12-31", "%Y-%m-%d")
        except Exception:
            return datetime(2099, 12, 31)

    events.sort(key=_sort_key)

    cutoff_past = (_NOW - timedelta(days=90)).strftime("%Y-%m-%d")
    upcoming = [e for e in events if e.is_upcoming]
    recent   = [e for e in events if not e.is_upcoming
                and (e.event_date or "1900-01-01") >= cutoff_past]

    next_critical = next(
        (e for e in upcoming if e.priority == PRI_CRITICAL), None
    )
    next_event = upcoming[0] if upcoming else None

    return {
        "available":       True,
        "advisory_only":   True,
        "total":           len(events),
        "upcoming_count":  len(upcoming),
        "recent_count":    len(recent),
        "events":          [e.to_dict() for e in events],
        "upcoming":        [e.to_dict() for e in upcoming[:20]],
        "recent":          [e.to_dict() for e in recent[-10:]],
        "next_critical":   next_critical.to_dict() if next_critical else None,
        "next_event":      next_event.to_dict() if next_event else None,
        "categories":      sorted({e.sub_type for e in events}),
        "high_importance": [
            e.to_dict() for e in events
            if e.importance_score >= 80.0 and e.is_upcoming
        ][:5],
    }
