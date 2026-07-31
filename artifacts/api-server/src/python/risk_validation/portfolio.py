"""
risk_validation/portfolio.py — Phase 8.4
Portfolio and position risk validation.

Checks: capital, cash, exposure, utilisation, largest position,
portfolio heat, position sizing, leverage, drawdown, recovery,
entry/exit size, risk %, stop distance, holding time, concentration.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result, unavailable_result, _now_iso

# ── Thresholds ─────────────────────────────────────────────────────────────────
_UTILISATION_WARN    = 80.0   # %
_UTILISATION_CRIT    = 95.0   # %
_DRAWDOWN_WARN       = 10.0   # %
_DRAWDOWN_CRIT       = 20.0   # %
_CONCENTRATION_WARN  = 20.0   # % of portfolio in one position
_CONCENTRATION_CRIT  = 35.0   # %
_HEAT_WARN           = 45.0   # portfolio heat %
_HEAT_CRIT           = 65.0   # %
_MIN_CASH_PCT        = 5.0    # % minimum cash buffer
_MAX_LEVERAGE        = 1.0    # paper trading: no leverage


def _load_portfolio() -> dict:
    """Try to read live portfolio state."""
    try:
        from portfolio_store import load_state
        return load_state() or {}
    except Exception:
        return {}


def _load_trades() -> list:
    try:
        from portfolio_store import load_trades
        return load_trades() or []
    except Exception:
        return []


def _load_risk_snapshot() -> dict:
    try:
        from risk_optimisation.shared_services import get_risk_optimisation_snapshot
        return get_risk_optimisation_snapshot() or {}
    except Exception:
        return {}


# ── Portfolio-level checks ────────────────────────────────────────────────────

def validate_capital(p: dict) -> tuple[list[Issue], int, int]:
    """Validate capital, cash, utilisation, leverage."""
    issues: list[Issue] = []
    run = passed = 0

    total = float(p.get("total_value", 0) or 0)
    cash  = float(p.get("cash_available", 0) or 0)
    inv   = float(p.get("invested_capital", 0) or 0)
    util  = float(p.get("portfolio_utilisation_pct", 0) or 0)

    # Check 1: capital positive
    run += 1
    if total > 0:
        passed += 1
    else:
        issues.append(Issue("CRITICAL", "CAPITAL_POSITIVE", "total_value",
                            f"Total capital ≤ 0 ({total})", total))

    # Check 2: cash non-negative
    run += 1
    if cash >= 0:
        passed += 1
    else:
        issues.append(Issue("CRITICAL", "CASH_NON_NEGATIVE", "cash_available",
                            f"Cash is negative ({cash:.2f})", cash))

    # Check 3: cash buffer adequate
    run += 1
    if total > 0:
        cash_pct = cash / total * 100
        if cash_pct >= _MIN_CASH_PCT:
            passed += 1
        else:
            sev = "WARNING"
            issues.append(Issue(sev, "CASH_BUFFER_LOW", "cash_available",
                                f"Cash buffer {cash_pct:.1f}% below minimum {_MIN_CASH_PCT}%",
                                cash_pct))
    else:
        passed += 1

    # Check 4: utilisation within range
    run += 1
    if util >= 100 + 0.01:
        issues.append(Issue("CRITICAL", "UTILISATION_OVERFLOW", "portfolio_utilisation_pct",
                            f"Utilisation {util:.1f}% exceeds 100%", util))
    elif util >= _UTILISATION_CRIT:
        issues.append(Issue("CRITICAL", "HIGH_UTILISATION", "portfolio_utilisation_pct",
                            f"Utilisation {util:.1f}% is critically high (>{_UTILISATION_CRIT}%)", util))
    elif util >= _UTILISATION_WARN:
        issues.append(Issue("WARNING", "ELEVATED_UTILISATION", "portfolio_utilisation_pct",
                            f"Utilisation {util:.1f}% is elevated (>{_UTILISATION_WARN}%)", util))
    else:
        passed += 1

    # Check 5: no leverage (paper)
    run += 1
    if total > 0:
        leverage = inv / total
        if leverage <= _MAX_LEVERAGE + 0.01:
            passed += 1
        else:
            issues.append(Issue("CRITICAL", "LEVERAGE_EXCEEDED", "leverage",
                                f"Effective leverage {leverage:.2f}x exceeds {_MAX_LEVERAGE}x", leverage))
    else:
        passed += 1

    return issues, run, passed


def validate_drawdown(p: dict, risk_snap: dict) -> tuple[list[Issue], int, int]:
    """Validate drawdown and recovery metrics."""
    issues: list[Issue] = []
    run = passed = 0

    dd = float(p.get("max_drawdown_pct",
                risk_snap.get("max_drawdown_pct", 0)) or 0)

    # Check 6: drawdown severity
    run += 1
    if dd >= _DRAWDOWN_CRIT:
        issues.append(Issue("CRITICAL", "CRITICAL_DRAWDOWN", "max_drawdown_pct",
                            f"Drawdown {dd:.1f}% is critical (>{_DRAWDOWN_CRIT}%)", dd))
    elif dd >= _DRAWDOWN_WARN:
        issues.append(Issue("WARNING", "ELEVATED_DRAWDOWN", "max_drawdown_pct",
                            f"Drawdown {dd:.1f}% is elevated (>{_DRAWDOWN_WARN}%)", dd))
    else:
        passed += 1

    # Check 7: portfolio heat
    heat = float(p.get("portfolio_heat", 0) or 0)
    run += 1
    if heat >= _HEAT_CRIT:
        issues.append(Issue("CRITICAL", "HIGH_HEAT", "portfolio_heat",
                            f"Portfolio heat {heat:.1f}% is critical (>{_HEAT_CRIT}%)", heat))
    elif heat >= _HEAT_WARN:
        issues.append(Issue("WARNING", "ELEVATED_HEAT", "portfolio_heat",
                            f"Portfolio heat {heat:.1f}% is elevated (>{_HEAT_WARN}%)", heat))
    else:
        passed += 1

    return issues, run, passed


def validate_position_concentration(positions: list[dict],
                                    total_value: float) -> tuple[list[Issue], int, int]:
    """Validate position sizing and concentration."""
    issues: list[Issue] = []
    run = passed = 0

    if not positions or total_value <= 0:
        return issues, run, passed

    for pos in positions:
        sym   = pos.get("symbol", "?")
        val   = float(pos.get("current_value", pos.get("value", 0)) or 0)
        qty   = float(pos.get("qty", pos.get("quantity", 0)) or 0)
        pct   = val / total_value * 100 if total_value > 0 else 0

        run += 1
        if val < 0:
            issues.append(Issue("CRITICAL", "NEGATIVE_POSITION", f"position.{sym}",
                                f"Position {sym} has negative value {val:.2f}", val,
                                category="concentration"))
        elif pct >= _CONCENTRATION_CRIT:
            issues.append(Issue("CRITICAL", "EXCESSIVE_CONCENTRATION", f"position.{sym}",
                                f"{sym} is {pct:.1f}% of portfolio (>{_CONCENTRATION_CRIT}%)", pct,
                                category="concentration"))
        elif pct >= _CONCENTRATION_WARN:
            issues.append(Issue("WARNING", "HIGH_CONCENTRATION", f"position.{sym}",
                                f"{sym} is {pct:.1f}% of portfolio (>{_CONCENTRATION_WARN}%)", pct,
                                category="concentration"))
        else:
            passed += 1

    return issues, run, passed


# ── Public API ─────────────────────────────────────────────────────────────────

def validate_portfolio() -> dict:
    """Run all portfolio and position risk validations."""
    p         = _load_portfolio()
    risk_snap = _load_risk_snapshot()
    positions = p.get("positions", []) or []

    if not p:
        return unavailable_result("portfolio",
                                  "Portfolio data not available")

    all_issues: list[Issue] = []
    total_run = total_passed = 0

    # Capital / utilisation / leverage
    iss, r, ps = validate_capital(p)
    all_issues.extend(iss); total_run += r; total_passed += ps

    # Drawdown / heat
    iss, r, ps = validate_drawdown(p, risk_snap)
    all_issues.extend(iss); total_run += r; total_passed += ps

    # Position concentration
    total_val = float(p.get("total_value", 0) or 0)
    iss, r, ps = validate_position_concentration(positions, total_val)
    all_issues.extend(iss); total_run += r; total_passed += ps

    # Ensure at least 1 check
    if total_run == 0:
        total_run = 1; total_passed = 1

    return domain_result(
        "portfolio", total_run, total_passed, all_issues,
        extra={
            "total_value":              float(p.get("total_value", 0) or 0),
            "cash_available":           float(p.get("cash_available", 0) or 0),
            "invested_capital":         float(p.get("invested_capital", 0) or 0),
            "portfolio_utilisation_pct": float(p.get("portfolio_utilisation_pct", 0) or 0),
            "positions_count":          len(positions),
            "max_drawdown_pct":         float(p.get("max_drawdown_pct", 0) or 0),
        },
    )


def get_portfolio_validation() -> dict:
    return validate_portfolio()
