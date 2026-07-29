"""Phase 7.5 – Scenario simulation engine (advisory-only, no production impact)."""
from __future__ import annotations
from typing import Any, Dict, List

from .models import (
    ScenarioResult, ALL_SCENARIOS,
    SCENARIO_BULL, SCENARIO_BEAR, SCENARIO_SIDEWAYS,
    SCENARIO_HIGH_VOL, SCENARIO_LOW_VOL,
    SCENARIO_GAP_OPEN, SCENARIO_NEWS_DRIVEN, SCENARIO_MACRO_SHOCK,
)

_SCENARIO_META: Dict[str, Dict[str, Any]] = {
    SCENARIO_BULL: {
        "label": "Bull Market",
        "description": "Broad market advance; FIIs buying; breadth positive.",
        "market_impact": "POSITIVE",
        "signal_shift": "BUY signals increase; confidence rises across Trend and Momentum strategies.",
        "risk_level": "LOW",
        "opp_base": 80.0, "threat_base": 20.0,
        "sectors": ["Banking", "IT", "Auto", "Metals"],
        "risks": ["Overvaluation risk", "Sudden macro reversal"],
        "opportunities": ["Trend-following entries", "Sector rotation into leaders"],
        "actions": ["Lean long on high-confidence BUY signals", "Widen targets conservatively"],
    },
    SCENARIO_BEAR: {
        "label": "Bear Market",
        "description": "Sustained decline; FIIs selling; breadth deteriorating.",
        "market_impact": "NEGATIVE",
        "signal_shift": "SELL signals increase; BUY confidence falls sharply.",
        "risk_level": "HIGH",
        "opp_base": 20.0, "threat_base": 85.0,
        "sectors": ["Defensives", "FMCG", "Pharma"],
        "risks": ["Stop-loss failures on gap-downs", "Correlation spike across positions"],
        "opportunities": ["Short setups in weak sectors", "Defensive rotation"],
        "actions": ["Reduce position sizes", "Tighten stop-losses", "Avoid new long entries"],
    },
    SCENARIO_SIDEWAYS: {
        "label": "Sideways Market",
        "description": "Consolidation phase; range-bound price action.",
        "market_impact": "NEUTRAL",
        "signal_shift": "Mean-reversion signals increase; trend signals reduce.",
        "risk_level": "MEDIUM",
        "opp_base": 50.0, "threat_base": 50.0,
        "sectors": ["Range-bound sectors", "FMCG", "Utilities"],
        "risks": ["Whipsaw signals", "Low reward-to-risk on breakout failures"],
        "opportunities": ["Support/resistance entries", "Mean-reversion plays"],
        "actions": ["Use tighter targets", "Prefer range-trading strategies"],
    },
    SCENARIO_HIGH_VOL: {
        "label": "High Volatility",
        "description": "VIX spike above 20; wide intraday swings.",
        "market_impact": "NEGATIVE",
        "signal_shift": "Signal confidence drops; risk levels elevate across all symbols.",
        "risk_level": "HIGH",
        "opp_base": 35.0, "threat_base": 75.0,
        "sectors": ["All sectors elevated risk"],
        "risks": ["Stop-loss gaps", "Liquidity drying up mid-session"],
        "opportunities": ["Volatility-based strategy entries", "Options premium selling (advisory)"],
        "actions": ["Reduce size by 50%", "Widen stops to avoid volatility wash-out"],
    },
    SCENARIO_LOW_VOL: {
        "label": "Low Volatility",
        "description": "Compressed VIX; steady trending price action.",
        "market_impact": "POSITIVE",
        "signal_shift": "Trend signals strengthen; breakout signals more reliable.",
        "risk_level": "LOW",
        "opp_base": 70.0, "threat_base": 25.0,
        "sectors": ["Momentum leaders", "Mid-cap"],
        "risks": ["Complacency risk", "Sudden vol expansion"],
        "opportunities": ["Full-size trend-following entries", "Breakout confirmation"],
        "actions": ["Trade full size on confirmed breakouts", "Monitor for vol expansion"],
    },
    SCENARIO_GAP_OPEN: {
        "label": "Gap Opening",
        "description": "Market gaps significantly up or down at open.",
        "market_impact": "NEUTRAL",
        "signal_shift": "Pre-open signals may be invalidated; risk recalculation required.",
        "risk_level": "HIGH",
        "opp_base": 40.0, "threat_base": 70.0,
        "sectors": ["All sectors — gap-dependent"],
        "risks": ["Pre-open signal staleness", "Execution slippage at open"],
        "opportunities": ["Gap-fill trades", "Momentum continuation after 09:20"],
        "actions": ["Skip first 5 minutes", "Re-evaluate signals after gap stabilisation"],
    },
    SCENARIO_NEWS_DRIVEN: {
        "label": "News Driven Market",
        "description": "Market reacting to corporate announcements or geopolitical events.",
        "market_impact": "NEUTRAL",
        "signal_shift": "Event intelligence score rises; affected-sector signals become unreliable.",
        "risk_level": "MEDIUM",
        "opp_base": 55.0, "threat_base": 60.0,
        "sectors": ["News-specific sectors"],
        "risks": ["Binary outcome risk", "Spread widening around announcements"],
        "opportunities": ["Post-announcement momentum", "Sector rotation away from affected names"],
        "actions": ["Avoid affected symbols until news digestion", "Monitor event intelligence tab"],
    },
    SCENARIO_MACRO_SHOCK: {
        "label": "Macro Shock",
        "description": "Unexpected macro event — RBI rate decision, global crisis, FII exodus.",
        "market_impact": "NEGATIVE",
        "signal_shift": "All signals invalidated temporarily; risk scores spike across the board.",
        "risk_level": "VERY_HIGH",
        "opp_base": 15.0, "threat_base": 95.0,
        "sectors": ["Rate-sensitive", "FII-heavy", "Export-oriented"],
        "risks": ["Portfolio-wide drawdown", "Extreme correlation", "Liquidity collapse"],
        "opportunities": ["Long-term entry points post-shock", "Defensive safe-havens"],
        "actions": ["Halt all auto-paper entries", "Review macro intelligence tab urgently"],
    },
}


def simulate_all_scenarios(
    signals: List[Dict[str, Any]],
    macro_snap: Dict[str, Any],
    market_snap: Dict[str, Any],
) -> List[ScenarioResult]:
    """Generate advisory scenario outcomes for all 8 scenarios."""
    results: List[ScenarioResult] = []
    total_signals = max(len(signals), 1)

    # Current market context adjustments
    vix      = float((macro_snap or {}).get("india_vix", 16.0) or 16.0)
    mkt_hlth = float((market_snap or {}).get("market_health_score", 50.0) or 50.0)

    for stype in ALL_SCENARIOS:
        meta = _SCENARIO_META[stype]

        opp_score    = meta["opp_base"]
        threat_score = meta["threat_base"]

        # Adjust based on current VIX
        if stype == SCENARIO_HIGH_VOL and vix > 18:
            opp_score    -= 10
            threat_score += 10
        if stype == SCENARIO_BULL and mkt_hlth >= 65:
            opp_score    += 8
            threat_score -= 5

        # Expected signal count under scenario
        multiplier = {
            SCENARIO_BULL:        1.4,
            SCENARIO_BEAR:        0.6,
            SCENARIO_SIDEWAYS:    0.8,
            SCENARIO_HIGH_VOL:    0.7,
            SCENARIO_LOW_VOL:     1.1,
            SCENARIO_GAP_OPEN:    0.5,
            SCENARIO_NEWS_DRIVEN: 0.9,
            SCENARIO_MACRO_SHOCK: 0.3,
        }.get(stype, 1.0)
        exp_signals = max(1, int(total_signals * multiplier))

        results.append(ScenarioResult(
            scenario_type=stype,
            label=meta["label"],
            description=meta["description"],
            market_impact=meta["market_impact"],
            expected_signals=exp_signals,
            signal_shift=meta["signal_shift"],
            risk_level=meta["risk_level"],
            opportunity_score=round(min(100.0, max(0.0, opp_score)), 1),
            threat_score=round(min(100.0, max(0.0, threat_score)), 1),
            affected_sectors=meta["sectors"],
            key_risks=meta["risks"],
            key_opportunities=meta["opportunities"],
            recommended_actions=meta["actions"],
        ))

    return results
