"""
risk_validation/tail_risk.py — Phase 8.4
Tail risk estimation: worst-case loss, gap risk, volatility scenario,
market shock, liquidity shock, circuit limit, stress drawdown, recovery.

Uses parametric VaR / CVaR estimates assuming normal distribution
(conservative for equity portfolios). All outputs are advisory.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

import math

from .models import Issue, domain_result, unavailable_result

# z-scores for confidence levels
_Z_95  = 1.645
_Z_99  = 2.326
_Z_995 = 2.576

# Assumed daily volatility when we don't have live data (NSE large-cap estimate)
_DEFAULT_DAILY_VOL = 0.012   # 1.2 % per day

_CVAR_WARN  = 0.10   # CVaR as fraction of portfolio
_CVAR_CRIT  = 0.18


def _load_portfolio() -> dict:
    try:
        from portfolio_store import load_state
        return load_state() or {}
    except Exception:
        return {}


def _load_vix() -> float:
    """Best-effort India VIX reading."""
    try:
        from macro_intelligence.shared_services import _load_vix_safe
        vix_data = _load_vix_safe() or {}
        return float(vix_data.get("india_vix", vix_data.get("vix", 0)) or 0)
    except Exception:
        return 0.0


def _vol_from_vix(vix: float) -> float:
    """Convert VIX (annualised %) to daily volatility fraction."""
    if vix <= 0:
        return _DEFAULT_DAILY_VOL
    return vix / 100 / math.sqrt(252)


def _parametric_var(portfolio_val: float, daily_vol: float, z: float,
                    horizon_days: int = 1) -> float:
    """
    Parametric VaR = portfolio_val × daily_vol × z × √horizon
    Returns the loss amount (positive number).
    """
    return portfolio_val * daily_vol * z * math.sqrt(horizon_days)


def _parametric_cvar(portfolio_val: float, daily_vol: float, z: float,
                     horizon_days: int = 1) -> float:
    """CVaR (Expected Shortfall) ≈ VaR × φ(z) / (1−CL) for normal dist."""
    phi_z = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    cl = 0.99 if z >= _Z_99 - 0.01 else 0.95
    return portfolio_val * daily_vol * math.sqrt(horizon_days) * phi_z / (1 - cl)


def estimate_tail_risk(portfolio_val: float, daily_vol: float) -> dict:
    """Return a full tail risk estimate dict."""
    return {
        "portfolio_value": round(portfolio_val, 2),
        "daily_volatility_pct": round(daily_vol * 100, 3),
        "var_95_1d":  round(_parametric_var(portfolio_val, daily_vol, _Z_95),  2),
        "var_99_1d":  round(_parametric_var(portfolio_val, daily_vol, _Z_99),  2),
        "var_995_1d": round(_parametric_var(portfolio_val, daily_vol, _Z_995), 2),
        "cvar_99_1d": round(_parametric_cvar(portfolio_val, daily_vol, _Z_99), 2),
        "worst_case_5sigma": round(portfolio_val * daily_vol * 5, 2),
        "gap_risk_pct":   round(daily_vol * 100 * 1.5, 2),  # overnight gap ~1.5×daily vol
        "stress_drawdown_15pct": round(portfolio_val * 0.15, 2),
        "stress_drawdown_20pct": round(portfolio_val * 0.20, 2),
        "circuit_limit_loss":   round(portfolio_val * 0.10, 2),  # 10% circuit
        "recovery_estimate_days": max(1, round(0.20 / (daily_vol * 252 / 365))),
    }


def get_tail_risk_validation() -> dict:
    p = _load_portfolio()
    if not p:
        return unavailable_result("tail_risk", "Portfolio data unavailable for tail risk")

    portfolio_val = float(p.get("total_value", 0) or 0)
    if portfolio_val <= 0:
        return unavailable_result("tail_risk", "Portfolio value is zero")

    vix = _load_vix()
    daily_vol = _vol_from_vix(vix) if vix > 0 else _DEFAULT_DAILY_VOL

    estimates = estimate_tail_risk(portfolio_val, daily_vol)
    issues: list[Issue] = []
    run = passed = 0

    # Check 1: CVaR as fraction of portfolio
    cvar_frac = estimates["cvar_99_1d"] / portfolio_val
    run += 1
    if cvar_frac >= _CVAR_CRIT:
        issues.append(Issue("CRITICAL", "HIGH_CVAR",
                            "cvar_99_1d",
                            f"99% CVaR is {cvar_frac*100:.1f}% of portfolio — critical tail risk",
                            cvar_frac, category="tail"))
    elif cvar_frac >= _CVAR_WARN:
        issues.append(Issue("WARNING", "ELEVATED_CVAR",
                            "cvar_99_1d",
                            f"99% CVaR is {cvar_frac*100:.1f}% of portfolio — elevated tail risk",
                            cvar_frac, category="tail"))
    else:
        passed += 1

    # Check 2: 5-sigma loss vs portfolio
    five_sig_frac = estimates["worst_case_5sigma"] / portfolio_val
    run += 1
    if five_sig_frac >= 0.20:
        issues.append(Issue("WARNING", "HIGH_5SIGMA_LOSS",
                            "worst_case_5sigma",
                            f"5σ worst case = {five_sig_frac*100:.1f}% of portfolio",
                            five_sig_frac, category="tail"))
    else:
        passed += 1

    # Check 3: volatility elevated if VIX > 20
    run += 1
    if vix > 25:
        issues.append(Issue("CRITICAL", "CRITICAL_VIX",
                            "india_vix",
                            f"India VIX at {vix:.1f} — extreme volatility environment",
                            vix, category="market"))
    elif vix > 20:
        issues.append(Issue("WARNING", "ELEVATED_VIX",
                            "india_vix",
                            f"India VIX at {vix:.1f} — elevated volatility", vix, category="market"))
    else:
        passed += 1

    if run == 0:
        run = 1; passed = 1

    return domain_result(
        "tail_risk", run, passed, issues,
        extra={**estimates, "india_vix": vix},
    )
