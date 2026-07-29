"""
intelligence_summary.py — Phase 7.1
Unified intelligence summary: Top Opportunities, Risk Areas, Strongest/Weakest
Sectors, Market Health Score, Overall Market Outlook.

GitHub-inspired: explainable intelligence summaries with evidence labels.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from .hub_models import health_grade, health_trend, clamp


def generate_summary(
    regime: dict,
    sectors: dict,
    breadth: dict,
    volatility: dict,
    watchlist: dict,
    timeframes: dict,
) -> dict:
    """
    Aggregate all sub-analyses into a unified intelligence summary.
    """
    health_score = _market_health_score(regime, sectors, breadth, volatility, timeframes)
    grade = health_grade(health_score)
    trend = _market_trend(regime, breadth, volatility)
    outlook = _market_outlook(regime, health_score, sectors, breadth)

    top_opportunities = watchlist.get("top_opportunities") or []
    highest_risk = watchlist.get("highest_risk") or []
    strongest_sectors = [
        s for s in (sectors.get("sectors") or [])
        if s.get("heat") in ("HOT", "WARM")
    ][:3]
    weakest_sectors = [
        s for s in reversed(sectors.get("sectors") or [])
        if s.get("heat") in ("COLD", "COOL")
    ][:3]

    # Build evidence-labelled explanation
    evidence = _build_evidence(regime, sectors, breadth, volatility, timeframes, health_score)

    return {
        "market_health_score": round(health_score, 2),
        "grade": grade,
        "trend": trend,
        "overall_outlook": outlook,
        "top_opportunities": top_opportunities[:5],
        "highest_risk_areas": highest_risk[:5],
        "strongest_sectors": [s["sector"] for s in strongest_sectors],
        "weakest_sectors": [s["sector"] for s in weakest_sectors],
        "evidence": evidence,
        "advisory_only": True,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _market_health_score(regime, sectors, breadth, volatility, timeframes) -> float:
    """
    Weighted composite score 0–100.
    Regime: 25%  | Breadth: 25%  | Volatility: 20%  | Sectors: 15% | TF alignment: 15%
    """
    # Regime sub-score
    regime_name = (regime.get("regime") or "SIDEWAYS").upper()
    trend_str   = float(regime.get("trend_strength") or 0.0)
    if "BULL" in regime_name:      regime_score = 75.0 + trend_str * 0.25
    elif "BEAR" in regime_name:    regime_score = 25.0 - trend_str * 0.15
    elif "HIGH_VOL" in regime_name: regime_score = 35.0
    elif "BREAKOUT" in regime_name: regime_score = 70.0
    elif "TRANSITION" in regime_name: regime_score = 50.0
    else:                          regime_score = 50.0 + trend_str * 0.2

    # Breadth sub-score
    breadth_score = float(breadth.get("breadth_strength") or 50.0)

    # Volatility sub-score (higher = better)
    vol_score = float(volatility.get("volatility_score") or 50.0)

    # Sector sub-score
    sector_avg = float(sectors.get("avg_sector_strength") or 50.0)

    # Timeframe alignment sub-score
    tf_score = float(timeframes.get("alignment_score") or 50.0)

    composite = (
        clamp(regime_score) * 0.25 +
        breadth_score       * 0.25 +
        vol_score           * 0.20 +
        sector_avg          * 0.15 +
        tf_score            * 0.15
    )
    return clamp(composite)


def _market_trend(regime, breadth, volatility) -> str:
    """Derive IMPROVING / STABLE / WEAKENING trend."""
    regime_name = (regime.get("regime") or "SIDEWAYS").upper()
    breadth_mom = (breadth.get("breadth_momentum") or "STABLE").upper()
    expansion   = (volatility.get("expansion") or "STABLE").upper()

    bull_signals = sum([
        "BULL" in regime_name or "BREAKOUT" in regime_name,
        breadth_mom == "IMPROVING",
        expansion == "CONTRACTING",  # falling volatility = more healthy
    ])
    bear_signals = sum([
        "BEAR" in regime_name or "HIGH_VOL" in regime_name,
        breadth_mom == "WORSENING",
        expansion == "EXPANDING",
    ])

    if bull_signals >= 2: return "IMPROVING"
    if bear_signals >= 2: return "WEAKENING"
    return "STABLE"


def _market_outlook(regime, health_score, sectors, breadth) -> str:
    """Generate a one-line advisory market outlook."""
    regime_name = (regime.get("regime") or "SIDEWAYS").upper()
    strongest   = sectors.get("strongest_sector") or "N/A"
    adv         = breadth.get("advancers") or 0
    dec         = breadth.get("decliners") or 0

    if health_score >= 75:
        return (
            f"Market conditions are favourable. {regime_name} regime with "
            f"{adv} advancing vs {dec} declining symbols. "
            f"Leading sector: {strongest}. Advisory analysis only."
        )
    if health_score >= 55:
        return (
            f"Mixed market conditions. {regime_name} regime. "
            f"Breadth: {adv} advancing, {dec} declining. "
            f"Exercise caution. Advisory analysis only."
        )
    return (
        f"Challenging market conditions. {regime_name} regime with "
        f"weak breadth ({adv} advancing, {dec} declining). "
        f"Risk management prioritised. Advisory analysis only."
    )


def _build_evidence(regime, sectors, breadth, volatility, timeframes, health_score) -> list:
    """Build evidence-labelled items explaining the health score."""
    evidence = []

    tf_agree = timeframes.get("agreement") or "MIXED"
    if "STRONG_BULLISH" in tf_agree or "BULLISH" in tf_agree:
        evidence.append({"label": "TIMEFRAME_ALIGNMENT", "weight": "+",
                         "detail": f"Multi-timeframe agreement: {tf_agree}"})
    elif "BEARISH" in tf_agree:
        evidence.append({"label": "TIMEFRAME_ALIGNMENT", "weight": "-",
                         "detail": f"Multi-timeframe agreement: {tf_agree}"})

    adv_dec = breadth.get("advance_decline_ratio") or 0.5
    if adv_dec > 0.6:
        evidence.append({"label": "MARKET_BREADTH", "weight": "+",
                         "detail": f"A/D ratio {adv_dec:.2f} — broad participation"})
    elif adv_dec < 0.4:
        evidence.append({"label": "MARKET_BREADTH", "weight": "-",
                         "detail": f"A/D ratio {adv_dec:.2f} — narrow market"})

    vix = volatility.get("vix_value") or 18.0
    if vix < 15:
        evidence.append({"label": "VOLATILITY", "weight": "+",
                         "detail": f"VIX {vix:.1f} — low volatility environment"})
    elif vix > 25:
        evidence.append({"label": "VOLATILITY", "weight": "-",
                         "detail": f"VIX {vix:.1f} — elevated risk"})

    strongest = sectors.get("strongest_sector") or "N/A"
    evidence.append({"label": "SECTOR_LEADERSHIP", "weight": "~",
                     "detail": f"Leading sector: {strongest}"})

    return evidence
