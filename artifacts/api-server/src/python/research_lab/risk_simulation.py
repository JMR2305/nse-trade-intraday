"""Phase 7.5 – Risk simulation engine (advisory-only estimates, no execution)."""
from __future__ import annotations
import math
from typing import Any, Dict, List

from .models import RiskSimulation


_STRESS_SCENARIOS = [
    {
        "name":        "VIX spike above 25",
        "probability": 0.10,
        "drawdown_est": 0.15,
        "description": "Extreme volatility causes 15% portfolio drawdown; liquidity thins.",
    },
    {
        "name":        "FII exodus (3-day net sell)",
        "probability": 0.15,
        "drawdown_est": 0.08,
        "description": "Foreign outflows pressure large-caps; sector rotation accelerates.",
    },
    {
        "name":        "Gap-down > 2% at open",
        "probability": 0.20,
        "drawdown_est": 0.05,
        "description": "Pre-open signals stale; stop-losses may not fill at expected price.",
    },
    {
        "name":        "RBI surprise rate hike",
        "probability": 0.08,
        "drawdown_est": 0.12,
        "description": "Rate-sensitive sectors hit hard; banking/NBFC positions under pressure.",
    },
    {
        "name":        "Global tech sell-off",
        "probability": 0.12,
        "drawdown_est": 0.10,
        "description": "IT/tech sector rotation out; momentum strategies impacted.",
    },
    {
        "name":        "Sector-specific bad news",
        "probability": 0.25,
        "drawdown_est": 0.04,
        "description": "Concentrated positions in affected sector face sudden drawdown.",
    },
    {
        "name":        "Circuit breaker triggered",
        "probability": 0.03,
        "drawdown_est": 0.20,
        "description": "Market-wide circuit; no exits possible; maximum paper loss.",
    },
]


def simulate_risk(
    signals: List[Dict[str, Any]],
    risk_snap: Dict[str, Any],
    macro_snap: Dict[str, Any],
) -> RiskSimulation:
    """
    Generate advisory-only risk simulation estimates from cached snapshots.
    No Monte Carlo computation — deterministic heuristic estimates.
    """
    max_dd       = float(risk_snap.get("max_drawdown", 0.08) or 0.08)
    max_dd_pct   = max_dd * 100 if max_dd < 1.0 else max_dd
    cap_eff      = float(risk_snap.get("capital_efficiency", 60.0) or 60.0)
    vix          = float(macro_snap.get("india_vix", 16.0) or 16.0)

    total_signals = max(len(signals), 1)
    high_risk_cnt = sum(1 for s in signals if s.get("risk_level") == "HIGH")
    high_risk_pct = high_risk_cnt / total_signals

    # Expected drawdown: historical max scaled by VIX regime
    vix_mult = 1.0
    if vix > 20:   vix_mult = 1.4
    elif vix > 18: vix_mult = 1.2
    elif vix < 14: vix_mult = 0.8

    expected_dd   = round(min(max_dd_pct * vix_mult, 30.0), 2)
    max_dd_est    = round(expected_dd * 1.8, 2)

    # Capital usage: proportion of capacity consumed by open positions
    cap_usage     = round(min(100.0, (cap_eff / 100.0) * total_signals / 10 * 100), 1)

    # Risk distribution
    low_risk  = round(max(0, 1.0 - high_risk_pct - 0.3), 3)
    mid_risk  = round(min(0.5, 0.3 + high_risk_pct * 0.4), 3)
    high_risk = round(1.0 - low_risk - mid_risk, 3)
    risk_dist = {"LOW": low_risk, "MEDIUM": mid_risk, "HIGH": high_risk}

    # Reward distribution (inverse of risk, shifted positive)
    rew_low  = round(max(0, 0.25 - high_risk_pct * 0.1), 3)
    rew_high = round(min(0.60, 0.40 + (1 - high_risk_pct) * 0.2), 3)
    rew_mid  = round(1.0 - rew_low - rew_high, 3)
    reward_dist = {"LOW": rew_low, "MEDIUM": rew_mid, "HIGH": rew_high}

    # Volatility exposure: normalised
    vol_exposure = round(min(100.0, vix * 5), 1)

    # Stress scenarios enriched with current VIX
    stress = []
    for sc in _STRESS_SCENARIOS:
        dd_pct = sc["drawdown_est"] * vix_mult * 100
        stress.append({
            "name":             sc["name"],
            "probability":      sc["probability"],
            "drawdown_est_pct": round(dd_pct, 2),
            "description":      sc["description"],
        })

    return RiskSimulation(
        expected_drawdown=expected_dd,
        max_drawdown_estimate=max_dd_est,
        capital_usage_pct=cap_usage,
        risk_distribution=risk_dist,
        reward_distribution=reward_dist,
        volatility_exposure=vol_exposure,
        stress_scenarios=stress,
        monte_carlo_note=(
            "Full Monte Carlo simulation is a future capability. "
            "Current estimates are heuristic-based using cached risk and macro snapshots. "
            "Advisory only — do not use for position sizing decisions."
        ),
    )
