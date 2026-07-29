"""
breadth_analyser.py — Phase 7.1
Market breadth analysis: advancers, decliners, sector participation,
breadth strength, breadth momentum.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from .hub_models import clamp


def analyse_breadth(scan_items: list, regime: dict) -> dict:
    """
    Compute market breadth from scan items.
    Classifies each item as advancer (STRONG_BUY/BUY), neutral (WATCH),
    or decliner (IGNORE) based on final_action.
    """
    if not scan_items:
        return _empty_breadth()

    advancers    = 0
    decliners    = 0
    neutral      = 0
    sector_part: dict = {}

    for item in scan_items:
        action = str(item.get("final_action") or "IGNORE").upper()
        sector = str(item.get("sector") or "Unknown")
        if sector not in sector_part:
            sector_part[sector] = {"advancing": 0, "total": 0}

        sector_part[sector]["total"] += 1

        if action in ("STRONG_BUY", "BUY"):
            advancers += 1
            sector_part[sector]["advancing"] += 1
        elif action == "WATCH":
            neutral += 1
        else:
            decliners += 1

    total = advancers + decliners + neutral or 1
    ad_ratio = advancers / (advancers + decliners) if (advancers + decliners) > 0 else 0.5

    # Breadth strength: 0–100
    breadth_strength = clamp(ad_ratio * 100)

    # Breadth momentum: derive from regime trend alignment
    regime_trend = (regime.get("nifty_trend") or "SIDEWAYS").upper()
    if regime_trend == "UP":
        breadth_momentum = "IMPROVING" if ad_ratio > 0.6 else "STABLE"
    elif regime_trend == "DOWN":
        breadth_momentum = "WORSENING" if ad_ratio < 0.4 else "STABLE"
    else:
        breadth_momentum = "STABLE"

    # Sector participation
    sector_participation = []
    for sector, d in sorted(sector_part.items(), key=lambda x: -x[1]["total"]):
        part_rate = d["advancing"] / d["total"] if d["total"] > 0 else 0.0
        sector_participation.append({
            "sector": sector,
            "advancing": d["advancing"],
            "total": d["total"],
            "participation_rate": round(part_rate, 4),
            "participating": part_rate >= 0.5,
        })

    participating_sectors = sum(1 for s in sector_participation if s["participating"])

    return {
        "advancers": advancers,
        "decliners": decliners,
        "neutral": neutral,
        "total": total,
        "advance_decline_ratio": round(ad_ratio, 4),
        "breadth_strength": round(breadth_strength, 2),
        "breadth_momentum": breadth_momentum,
        "sector_participation": sector_participation,
        "participating_sectors": participating_sectors,
        "total_sectors_scanned": len(sector_part),
        "breadth_label": _breadth_label(breadth_strength),
    }


def _breadth_label(strength: float) -> str:
    if strength >= 75: return "VERY_BROAD"
    if strength >= 60: return "BROAD"
    if strength >= 45: return "NARROW"
    if strength >= 30: return "WEAK"
    return "VERY_WEAK"


def _empty_breadth() -> dict:
    return {
        "advancers": 0, "decliners": 0, "neutral": 0, "total": 0,
        "advance_decline_ratio": 0.5,
        "breadth_strength": 50.0, "breadth_momentum": "STABLE",
        "sector_participation": [], "participating_sectors": 0,
        "total_sectors_scanned": 0, "breadth_label": "NARROW",
    }
