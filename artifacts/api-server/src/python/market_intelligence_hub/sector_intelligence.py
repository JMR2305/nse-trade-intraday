"""
sector_intelligence.py — Phase 7.1
Sector ranking by relative strength, momentum, participation, leadership,
weakness, and rotation. Builds on existing scan item sector data.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List, Dict
from .hub_models import SectorRank, clamp


def analyse_sectors(scan_items: list) -> dict:
    """
    Build sector intelligence from scan items.
    Returns ranked sectors with heat labels and rotation signals.
    """
    if not scan_items:
        return _empty_sectors()

    sector_map: Dict[str, dict] = {}
    for item in scan_items:
        sector = str(item.get("sector") or "Unknown")
        if sector not in sector_map:
            sector_map[sector] = {
                "stocks": [], "opp_scores": [], "confidences": [],
                "strong_buys": 0, "buys": 0, "watches": 0, "ignores": 0,
            }
        d = sector_map[sector]
        d["stocks"].append(str(item.get("stock") or item.get("symbol") or ""))
        d["opp_scores"].append(float(item.get("opportunity_score") or 0.0))
        d["confidences"].append(float(item.get("confidence") or 0.0))
        action = str(item.get("final_action") or "IGNORE").upper()
        if action == "STRONG_BUY":
            d["strong_buys"] += 1
        elif action == "BUY":
            d["buys"] += 1
        elif action == "WATCH":
            d["watches"] += 1
        else:
            d["ignores"] += 1

    # Compute per-sector scores
    sector_scores: list = []
    for sector, d in sector_map.items():
        n = len(d["opp_scores"])
        avg_opp = sum(d["opp_scores"]) / n if n > 0 else 0.0
        avg_conf = sum(d["confidences"]) / n if n > 0 else 0.0
        bull_ratio = (d["strong_buys"] + d["buys"]) / n if n > 0 else 0.0
        relative_strength = clamp(avg_opp * 0.6 + avg_conf * 0.4)
        momentum = clamp((bull_ratio - 0.5) * 200, -100.0, 100.0)
        sector_scores.append({
            "sector": sector, "relative_strength": relative_strength,
            "momentum": momentum, "participation": n,
            "strong_buys": d["strong_buys"], "buys": d["buys"],
            "watches": d["watches"], "ignores": d["ignores"],
            "stocks": d["stocks"],
        })

    # Sort by relative strength desc
    sector_scores.sort(key=lambda x: x["relative_strength"], reverse=True)
    n_sectors = len(sector_scores)

    ranks: List[SectorRank] = []
    for i, s in enumerate(sector_scores):
        rank = i + 1
        heat = _heat_label(s["relative_strength"], rank, n_sectors)
        rotation = _rotation_signal(s["momentum"])
        leadership = (rank == 1)
        ranks.append(SectorRank(
            rank=rank, sector=s["sector"],
            relative_strength=s["relative_strength"],
            momentum=s["momentum"],
            participation=s["participation"],
            strong_buys=s["strong_buys"], buys=s["buys"],
            watches=s["watches"], ignores=s["ignores"],
            heat=heat, rotation_signal=rotation, leadership=leadership,
        ))

    strongest = ranks[0].sector if ranks else "N/A"
    weakest   = ranks[-1].sector if ranks else "N/A"
    total_opp = sum(r.relative_strength for r in ranks)
    avg_strength = total_opp / len(ranks) if ranks else 0.0

    return {
        "sectors": [r.to_dict() for r in ranks],
        "total_sectors": n_sectors,
        "strongest_sector": strongest,
        "weakest_sector": weakest,
        "avg_sector_strength": round(avg_strength, 2),
        "sector_heat_leader": strongest,
        "leadership_sector": strongest,
        "rotation_leaders": [r.sector for r in ranks if r.rotation_signal == "INFLOW"][:3],
        "rotation_laggards": [r.sector for r in ranks if r.rotation_signal == "OUTFLOW"][:3],
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _heat_label(strength: float, rank: int, total: int) -> str:
    if total <= 1:
        return "NEUTRAL"
    percentile = 1.0 - (rank - 1) / total
    if percentile >= 0.8: return "HOT"
    if percentile >= 0.6: return "WARM"
    if percentile >= 0.4: return "NEUTRAL"
    if percentile >= 0.2: return "COOL"
    return "COLD"


def _rotation_signal(momentum: float) -> str:
    if momentum > 30:  return "INFLOW"
    if momentum < -30: return "OUTFLOW"
    return "STABLE"


def _empty_sectors() -> dict:
    return {
        "sectors": [], "total_sectors": 0,
        "strongest_sector": "N/A", "weakest_sector": "N/A",
        "avg_sector_strength": 0.0,
        "sector_heat_leader": "N/A", "leadership_sector": "N/A",
        "rotation_leaders": [], "rotation_laggards": [],
    }
