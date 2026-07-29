"""
stress_tester.py — Phase 6.4
Advisory stress test simulations for portfolio impact estimation.

ADVISORY-ONLY. All scenarios are hypothetical.
No trades, orders, or portfolio state are modified.
Future-ready hook for Monte Carlo simulations (disabled by default).
"""
from __future__ import annotations
from typing import List
from .risk_models import StressScenario

DEFAULT_CAPITAL = 500_000.0


def run_stress_tests(records: list, starting_capital: float = DEFAULT_CAPITAL) -> dict:
    """
    Simulate advisory stress scenarios against the paper trading history.
    Returns estimated portfolio impact per scenario.
    """
    scenarios = _build_scenarios(records, starting_capital)

    # Summarise
    critical = [s for s in scenarios if s.severity == "CRITICAL"]
    high_risk = [s for s in scenarios if s.severity == "HIGH"]
    worst = min(scenarios, key=lambda s: s.estimated_portfolio_pnl) if scenarios else None

    # Overall stress resilience: 0–1 (higher = more resilient)
    avg_impact = sum(s.estimated_portfolio_pnl_pct for s in scenarios) / len(scenarios) if scenarios else 0.0
    resilience = max(0.0, min(1.0, 1.0 + avg_impact * 5.0))  # avg_impact is negative

    return {
        "total_scenarios": len(scenarios),
        "critical_scenarios": len(critical),
        "high_risk_scenarios": len(high_risk),
        "worst_scenario": worst.to_dict() if worst else None,
        "resilience_score": round(resilience, 4),
        "scenarios": [s.to_dict() for s in scenarios],
        "monte_carlo_simulation": {
            "enabled": False,
            "note": "Monte Carlo simulation is a future-ready hook. Enable by setting MONTE_CARLO_ENABLED=true and providing simulation parameters.",
        },
        "advisory_only": True,
    }


def _build_scenarios(records: list, starting_capital: float) -> List[StressScenario]:
    """Build all 7 advisory stress scenarios."""
    n_trades = len(records)
    current_equity = starting_capital + sum(r.get("pnl") or 0.0 for r in records)
    avg_position = (
        sum(_capital_for(r) for r in records) / n_trades if n_trades > 0 else starting_capital * 0.05
    )
    n_open_est = min(5, max(1, n_trades // 10))  # estimated open positions

    scenarios = [
        _scenario_correction(current_equity, avg_position, n_open_est),
        _scenario_gap_down(current_equity, avg_position, n_open_est),
        _scenario_gap_up(current_equity, avg_position, n_open_est),
        _scenario_high_volatility(current_equity, avg_position, n_open_est),
        _scenario_multi_loss(records, current_equity),
        _scenario_sector_collapse(current_equity, avg_position, n_open_est),
        _scenario_liquidity(current_equity, avg_position, n_open_est),
    ]
    return scenarios


def _scenario_correction(equity: float, avg_pos: float, n_pos: int) -> StressScenario:
    impact_pct = -0.20
    pnl = equity * impact_pct
    sev = "CRITICAL" if abs(pnl) > equity * 0.15 else "HIGH"
    return StressScenario(
        name="20% Market Correction",
        scenario_type="CORRECTION",
        assumed_impact_pct=impact_pct,
        estimated_portfolio_pnl=round(pnl, 2),
        estimated_portfolio_pnl_pct=round(impact_pct, 4),
        positions_affected=n_pos,
        severity=sev,
        advisory="Maintain cash buffer ≥ 20% to absorb broad market corrections.",
    )


def _scenario_gap_down(equity: float, avg_pos: float, n_pos: int) -> StressScenario:
    impact_pct = -0.08
    pnl = avg_pos * n_pos * impact_pct
    pnl_pct = pnl / equity if equity > 0 else impact_pct
    sev = _sev(abs(pnl_pct))
    return StressScenario(
        name="Gap Down Opening (-8%)",
        scenario_type="GAP_DOWN",
        assumed_impact_pct=impact_pct,
        estimated_portfolio_pnl=round(pnl, 2),
        estimated_portfolio_pnl_pct=round(pnl_pct, 4),
        positions_affected=n_pos,
        severity=sev,
        advisory="Use overnight stop-loss orders and limit overnight exposure to reduce gap-down risk.",
    )


def _scenario_gap_up(equity: float, avg_pos: float, n_pos: int) -> StressScenario:
    impact_pct = 0.08
    pnl = avg_pos * n_pos * impact_pct
    pnl_pct = pnl / equity if equity > 0 else impact_pct
    return StressScenario(
        name="Gap Up Opening (+8%)",
        scenario_type="GAP_UP",
        assumed_impact_pct=impact_pct,
        estimated_portfolio_pnl=round(pnl, 2),
        estimated_portfolio_pnl_pct=round(pnl_pct, 4),
        positions_affected=n_pos,
        severity="LOW",
        advisory="Capture gap-up gains with pre-open limit orders; avoid chasing the open.",
    )


def _scenario_high_volatility(equity: float, avg_pos: float, n_pos: int) -> StressScenario:
    impact_pct = -0.12
    pnl = avg_pos * n_pos * impact_pct
    pnl_pct = pnl / equity if equity > 0 else impact_pct
    sev = _sev(abs(pnl_pct))
    return StressScenario(
        name="High Volatility Session (VIX +50%)",
        scenario_type="HIGH_VOL",
        assumed_impact_pct=impact_pct,
        estimated_portfolio_pnl=round(pnl, 2),
        estimated_portfolio_pnl_pct=round(pnl_pct, 4),
        positions_affected=n_pos,
        severity=sev,
        advisory="Reduce position sizes by 30–50% during high-volatility sessions; widen stop distances.",
    )


def _scenario_multi_loss(records: list, equity: float) -> StressScenario:
    """Simulate 5 consecutive losing trades at average loss size."""
    losses = [abs(r.get("pnl") or 0.0) for r in records if (r.get("pnl") or 0.0) < 0]
    avg_loss = sum(losses) / len(losses) if losses else equity * 0.01
    pnl = -avg_loss * 5
    pnl_pct = pnl / equity if equity > 0 else -0.05
    sev = _sev(abs(pnl_pct))
    return StressScenario(
        name="5 Consecutive Losing Trades",
        scenario_type="MULTI_LOSS",
        assumed_impact_pct=round(pnl_pct, 4),
        estimated_portfolio_pnl=round(pnl, 2),
        estimated_portfolio_pnl_pct=round(pnl_pct, 4),
        positions_affected=5,
        severity=sev,
        advisory=f"Average loss per trade: ₹{avg_loss:,.0f}. If 5 consecutive losses breaches 5% of capital, reduce position size.",
    )


def _scenario_sector_collapse(equity: float, avg_pos: float, n_pos: int) -> StressScenario:
    impact_pct = -0.30
    affected = max(1, n_pos // 2)
    pnl = avg_pos * affected * impact_pct
    pnl_pct = pnl / equity if equity > 0 else -0.10
    sev = _sev(abs(pnl_pct))
    return StressScenario(
        name="Sector Collapse (-30% in dominant sector)",
        scenario_type="SECTOR_COLLAPSE",
        assumed_impact_pct=impact_pct,
        estimated_portfolio_pnl=round(pnl, 2),
        estimated_portfolio_pnl_pct=round(pnl_pct, 4),
        positions_affected=affected,
        severity=sev,
        advisory="Limit sector concentration to ≤30% of capital to contain sector-specific collapse risk.",
    )


def _scenario_liquidity(equity: float, avg_pos: float, n_pos: int) -> StressScenario:
    impact_pct = -0.05
    pnl = avg_pos * n_pos * impact_pct
    pnl_pct = pnl / equity if equity > 0 else impact_pct
    sev = _sev(abs(pnl_pct))
    return StressScenario(
        name="Liquidity Crunch (5% slippage)",
        scenario_type="LIQUIDITY",
        assumed_impact_pct=impact_pct,
        estimated_portfolio_pnl=round(pnl, 2),
        estimated_portfolio_pnl_pct=round(pnl_pct, 4),
        positions_affected=n_pos,
        severity=sev,
        advisory="Trade only NSE stocks with average daily volume > 5× your position size to avoid liquidity risk.",
    )


def _sev(abs_pct: float) -> str:
    if abs_pct > 0.10:
        return "CRITICAL"
    if abs_pct > 0.05:
        return "HIGH"
    if abs_pct > 0.02:
        return "MEDIUM"
    return "LOW"


def _capital_for(r: dict) -> float:
    cap = float(r.get("entry_price") or 0.0) * float(r.get("quantity") or 0.0)
    return cap if cap > 0 else 0.0
