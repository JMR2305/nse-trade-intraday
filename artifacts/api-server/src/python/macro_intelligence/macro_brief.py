"""
macro_brief.py — Phase 7.3
Daily Macro Brief: concise operator-facing macro intelligence summary.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List

from .models import MacroEvent, macro_grade, PRI_CRITICAL, PRI_HIGH, DIR_BULLISH, DIR_BEARISH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _market_outlook(global_score: float, vix_regime: str, fii_flow: str,
                    commodity_risk: float) -> dict:
    """Derive overall market outlook from four macro pillars."""
    bullish_signals = 0
    bearish_signals = 0
    notes = []

    if global_score >= 60:
        bullish_signals += 1
        notes.append("Positive global cues")
    elif global_score <= 40:
        bearish_signals += 1
        notes.append("Weak global cues")

    if vix_regime == "CONTRACTION":
        bullish_signals += 1
        notes.append("VIX contracting — improving risk environment")
    elif vix_regime == "EXPANSION":
        bearish_signals += 1
        notes.append("VIX expanding — elevated uncertainty")

    if fii_flow == "NET_BUYER":
        bullish_signals += 1
        notes.append("FII inflow inferred")
    elif fii_flow == "NET_SELLER":
        bearish_signals += 1
        notes.append("FII outflow inferred")

    if commodity_risk >= 65:
        bearish_signals += 1
        notes.append("Rising crude — inflation headwind")
    elif commodity_risk <= 35:
        bullish_signals += 1
        notes.append("Falling crude — positive for margin")

    if bullish_signals >= 3:
        label = "BULLISH"
        description = "Macro environment broadly supportive. Global cues positive, liquidity intact."
    elif bearish_signals >= 3:
        label = "BEARISH"
        description = "Macro headwinds dominating. Caution on new long positions."
    elif bullish_signals > bearish_signals:
        label = "CAUTIOUSLY_BULLISH"
        description = "More supportive than not, but some macro risks remain."
    elif bearish_signals > bullish_signals:
        label = "CAUTIOUSLY_BEARISH"
        description = "More headwinds than tailwinds. Defensive posture preferred."
    else:
        label = "NEUTRAL"
        description = "Mixed macro signals — wait for clarity before aggressive positioning."

    return {
        "label":            label,
        "description":      description,
        "bullish_signals":  bullish_signals,
        "bearish_signals":  bearish_signals,
        "notes":            notes,
    }


def _build_risk_alerts(events: List[MacroEvent], vix_level: float,
                       fii_flow: str, global_score: float,
                       crude_chg: float) -> list:
    alerts = []

    # VIX alert
    if vix_level >= 25:
        alerts.append({
            "type":     "VIX_SPIKE",
            "severity": "HIGH",
            "message":  f"India VIX at {vix_level:.1f} — elevated fear. Reduce intraday position size.",
        })
    elif vix_level >= 20:
        alerts.append({
            "type":     "VIX_ELEVATED",
            "severity": "MEDIUM",
            "message":  f"India VIX at {vix_level:.1f} — above normal. Use wider stops.",
        })

    # FII sell-off alert
    if fii_flow == "NET_SELLER":
        alerts.append({
            "type":     "FII_OUTFLOW",
            "severity": "HIGH",
            "message":  "Inferred FII selling — large-cap pullback risk. Reduce beta.",
        })

    # Global cues weak
    if global_score <= 40:
        alerts.append({
            "type":     "WEAK_GLOBAL",
            "severity": "MEDIUM",
            "message":  "Weak global cues — watch for gap-down open. Avoid overnight positions.",
        })

    # Crude spike
    if crude_chg >= 2.5:
        alerts.append({
            "type":     "CRUDE_SPIKE",
            "severity": "HIGH",
            "message":  f"Crude oil up {crude_chg:.1f}% — inflation risk. Negative for Aviation, Paints.",
        })

    # Critical economic events today
    today = _today_str()
    critical_today = [
        e for e in events
        if e.event_date == today and e.priority == PRI_CRITICAL
    ]
    for e in critical_today:
        alerts.append({
            "type":     "HIGH_IMPACT_EVENT",
            "severity": "CRITICAL",
            "message":  f"{e.title} — high-impact macro event today. Avoid naked positions.",
        })

    return alerts


def _trading_considerations(outlook_label: str, vix_level: float,
                             top_inflow_sectors: list) -> list:
    considerations = []

    if outlook_label in ("BULLISH", "CAUTIOUSLY_BULLISH"):
        considerations.append(
            "Global + macro backdrop supportive — focus on momentum setups with tight stops."
        )
    elif outlook_label in ("BEARISH", "CAUTIOUSLY_BEARISH"):
        considerations.append(
            "Macro headwinds — prefer defensive stocks (FMCG, Pharma, IT with strong dollar)."
        )
    else:
        considerations.append(
            "Mixed signals — reduce position size, wait for directional clarity post-10:00 IST."
        )

    if vix_level >= 22:
        considerations.append(
            "High VIX: options premiums elevated — avoid naked short option strategies."
        )
    elif vix_level <= 14:
        considerations.append(
            "Low VIX: options cheap for directional bets; debit spreads favoured."
        )

    if top_inflow_sectors:
        sectors_str = ", ".join(top_inflow_sectors[:3])
        considerations.append(
            f"Sector rotation inflows to {sectors_str} — consider sector ETF or top picks."
        )

    return considerations


def generate_daily_brief(
    events:           List[MacroEvent],
    global_score:     float,
    vix_data:         dict,
    fii_data:         dict,
    commodity_data:   dict,
    currency_data:    dict,
    sector_rotation:  list,
) -> dict:
    """
    Assemble the full Daily Macro Brief from pre-loaded module outputs.
    """
    today     = _today_str()
    today_events = [e for e in events if e.event_date == today]
    upcoming7d   = [
        e for e in events
        if e.is_upcoming and e.event_date and e.event_date > today
    ][:5]

    vix_level    = float(vix_data.get("india_vix", {}).get("current", 18.0))
    vix_regime   = vix_data.get("regime", "STABLE")
    fii_flow     = fii_data.get("fii", {}).get("flow", "NEUTRAL")
    crude_chg    = float(commodity_data.get("crude_oil", {}).get("change_pct", 0))
    commodity_risk = float(commodity_data.get("commodity_risk_score", 50))
    usd_inr_chg  = float(currency_data.get("usd_inr", {}).get("change_pct", 0))
    top_inflow   = sector_rotation[:3] if sector_rotation else []

    outlook = _market_outlook(global_score, vix_regime, fii_flow, commodity_risk)

    # Compute brief score (0–100)
    score_components = [
        global_score,                                    # global cues
        float(vix_data.get("vix_score", 50.0)),         # low VIX = high score
        50.0 + (fii_data.get("fii", {}).get("score", 50) - 50),  # FII
        max(0, 100 - commodity_risk),                    # commodity headwind
    ]
    brief_score = round(sum(score_components) / len(score_components), 1)
    brief_grade = macro_grade(brief_score)

    risk_alerts = _build_risk_alerts(
        events, vix_level, fii_flow, global_score, crude_chg
    )
    top_sectors = [s.get("sector", "") for s in top_inflow if isinstance(s, dict)]
    considerations = _trading_considerations(outlook["label"], vix_level, top_sectors)

    return {
        "available":            True,
        "advisory_only":        True,
        "date":                 today,
        "generated_at":         _now_iso(),
        "brief_score":          brief_score,
        "brief_grade":          brief_grade,
        "market_outlook":       outlook,
        "today_events":         [e.to_dict() for e in today_events],
        "today_event_count":    len(today_events),
        "upcoming_7d":          [e.to_dict() for e in upcoming7d],
        "global_summary": {
            "score":   global_score,
            "label":   ("POSITIVE" if global_score >= 60 else
                        "NEGATIVE" if global_score <= 40 else "MIXED"),
            "detail":  f"Global sentiment score {global_score}/100 across 9 major indices.",
        },
        "economic_summary": {
            "upcoming_critical": sum(1 for e in events if e.is_upcoming and e.priority == PRI_CRITICAL),
            "today_high_impact": sum(1 for e in today_events if e.importance_score >= 75),
            "detail": (
                f"{sum(1 for e in events if e.is_upcoming and e.priority == PRI_CRITICAL)} "
                "critical economic events upcoming."
            ),
        },
        "currency_summary": {
            "usd_inr_change": usd_inr_chg,
            "impact":         currency_data.get("usd_inr_impact", ""),
            "dxy_impact":     currency_data.get("dxy_impact", ""),
            "risk":           currency_data.get("currency_volatility", "LOW"),
        },
        "commodity_summary": {
            "crude_change":   crude_chg,
            "crude_impact":   commodity_data.get("crude_impact", ""),
            "gold_signal":    commodity_data.get("gold_signal", ""),
            "inflation_risk": commodity_data.get("inflation_risk", "LOW"),
        },
        "fii_dii_summary": {
            "fii_posture":    fii_flow,
            "dii_posture":    fii_data.get("dii", {}).get("flow", "NEUTRAL"),
            "top_sectors":    [s.get("sector", "") for s in top_inflow if isinstance(s, dict)],
            "liquidity":      fii_data.get("liquidity", {}).get("trend", "NORMAL_LIQUIDITY"),
        },
        "vix_summary": {
            "level":          vix_level,
            "regime":         vix_regime,
            "risk_level":     vix_data.get("risk_level", "MEDIUM"),
            "interpretation": vix_data.get("interpretation", ""),
        },
        "risk_alerts":         risk_alerts,
        "trading_considerations": considerations,
    }
