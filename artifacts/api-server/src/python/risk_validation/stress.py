"""
risk_validation/stress.py — Phase 8.4
Scenario stress-test simulation (advisory-only).

Scenarios: 5/10/15/20% market fall, Gap Up, Gap Down,
Volatility Spike, Sector Collapse, Flash Crash, Global Shock.

All results are hypothetical estimates. Never modifies positions.
READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result, unavailable_result, _now_iso

# ── Scenario definitions ───────────────────────────────────────────────────────

SCENARIOS: list[dict] = [
    {
        "id":      "fall_5",
        "label":   "Market Fall 5%",
        "shock":   -0.05,
        "note":    "Moderate correction; portfolio expected to fall proportionally.",
    },
    {
        "id":      "fall_10",
        "label":   "Market Fall 10%",
        "shock":   -0.10,
        "note":    "Significant correction; drawdown may approach warning levels.",
    },
    {
        "id":      "fall_15",
        "label":   "Market Fall 15%",
        "shock":   -0.15,
        "note":    "Sharp market decline; portfolio heat will be elevated.",
    },
    {
        "id":      "fall_20",
        "label":   "Market Fall 20%",
        "shock":   -0.20,
        "note":    "Severe bear market; mandatory risk review recommended.",
    },
    {
        "id":      "gap_up",
        "label":   "Gap Up 3%",
        "shock":   +0.03,
        "note":    "Positive gap; short positions (if any) would be stressed.",
    },
    {
        "id":      "gap_down",
        "label":   "Gap Down 5%",
        "shock":   -0.05,
        "note":    "Overnight gap; stop-losses may not trigger at expected price.",
    },
    {
        "id":      "volatility_spike",
        "label":   "Volatility Spike (VIX ×2)",
        "shock":   -0.08,
        "note":    "VIX doubling typically accompanies 6–10% intraday swings.",
    },
    {
        "id":      "sector_collapse",
        "label":   "Sector Collapse 40%",
        "shock":   -0.12,  # blended if 30 % of portfolio in sector
        "note":    "Dominant sector drops 40%; blended impact ~12% for concentrated portfolio.",
    },
    {
        "id":      "flash_crash",
        "label":   "Flash Crash 15%",
        "shock":   -0.15,
        "note":    "Rapid intraday plunge; liquidity may be unavailable for exits.",
    },
    {
        "id":      "global_shock",
        "label":   "Global Shock 20%",
        "shock":   -0.20,
        "note":    "Black swan event; correlations spike, diversification fails.",
    },
]

_CRITICAL_SHOCK = -0.15   # scenarios with shock ≤ this flag CRITICAL
_WARNING_SHOCK  = -0.08


def _load_portfolio_value() -> float:
    try:
        from portfolio_store import load_state
        state = load_state() or {}
        return float(state.get("total_value", 0) or 0)
    except Exception:
        return 0.0


def run_scenarios(portfolio_value: float) -> list[dict]:
    """Apply each scenario shock to the portfolio value (advisory estimate)."""
    results = []
    for sc in SCENARIOS:
        shock      = sc["shock"]
        impact_val = portfolio_value * shock
        value_after= portfolio_value + impact_val
        results.append({
            "id":                sc["id"],
            "label":             sc["label"],
            "shock_pct":         round(shock * 100, 1),
            "impact_value":      round(impact_val, 2),
            "portfolio_value_before": round(portfolio_value, 2),
            "portfolio_value_after":  round(max(value_after, 0), 2),
            "impact_pct":        round(shock * 100, 1),
            "advisory_note":     sc["note"],
        })
    return results


def get_stress_validation() -> dict:
    portfolio_value = _load_portfolio_value()

    if portfolio_value <= 0:
        return unavailable_result("stress",
                                  "Portfolio value unavailable for stress simulation")

    scenarios_results = run_scenarios(portfolio_value)

    issues: list[Issue] = []
    run = passed = 0

    for sc_r in scenarios_results:
        shock = sc_r["shock_pct"] / 100
        run += 1
        if shock <= _CRITICAL_SHOCK:
            issues.append(Issue(
                "CRITICAL", "SEVERE_STRESS_SCENARIO",
                f"scenario.{sc_r['id']}",
                f"{sc_r['label']}: estimated impact {sc_r['impact_pct']:.0f}% "
                f"(₹{abs(sc_r['impact_value']):,.0f} loss)",
                shock,
                category="stress",
            ))
        elif shock <= _WARNING_SHOCK:
            issues.append(Issue(
                "WARNING", "MODERATE_STRESS_SCENARIO",
                f"scenario.{sc_r['id']}",
                f"{sc_r['label']}: estimated impact {sc_r['impact_pct']:.0f}%",
                shock,
                category="stress",
            ))
        else:
            passed += 1

    if run == 0:
        run = 1; passed = 1

    return domain_result(
        "stress", run, passed, issues,
        extra={
            "portfolio_value":  round(portfolio_value, 2),
            "scenarios":        scenarios_results,
            "scenarios_count":  len(scenarios_results),
            "severe_count":     sum(1 for s in scenarios_results
                                    if s["shock_pct"] / 100 <= _CRITICAL_SHOCK),
        },
    )
