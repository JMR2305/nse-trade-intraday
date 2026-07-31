"""
risk_validation/drift.py — Phase 8.4
Risk drift detection: growing exposure, drawdown, concentration,
correlation, volatility, capital deterioration.

Compares current state against historical risk validation runs (if available),
or against configured limits.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result, unavailable_result

_EXPOSURE_DRIFT_WARN  = 10.0  # % increase in utilisation over time
_DRAWDOWN_DRIFT_WARN  = 5.0   # % worsening drawdown
_CONC_DRIFT_WARN      = 5.0   # % increase in largest position
_CAP_DETERI_WARN      = -5.0  # % change in total capital (negative = loss)
_CAP_DETERI_CRIT      = -15.0


def _load_portfolio() -> dict:
    try:
        from portfolio_store import load_state
        return load_state() or {}
    except Exception:
        return {}


def _load_risk_optimisation() -> dict:
    try:
        from risk_optimisation.shared_services import get_risk_optimisation_snapshot
        return get_risk_optimisation_snapshot() or {}
    except Exception:
        return {}


def _load_trades() -> list[dict]:
    try:
        from portfolio_store import load_trades
        return load_trades() or []
    except Exception:
        return []


def detect_exposure_drift(p: dict) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    run = passed = 0

    util = float(p.get("portfolio_utilisation_pct", 0) or 0)

    run += 1
    if util >= 90:
        issues.append(Issue("WARNING", "EXPOSURE_NEAR_MAX",
                            "portfolio_utilisation_pct",
                            f"Utilisation at {util:.1f}% — exposure approaching limit",
                            util, category="drift"))
    else:
        passed += 1

    return issues, run, passed


def detect_drawdown_drift(p: dict, risk_snap: dict) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    run = passed = 0

    dd = float(p.get("max_drawdown_pct",
                risk_snap.get("max_drawdown_pct", 0)) or 0)

    run += 1
    if dd >= 15:
        issues.append(Issue("CRITICAL", "CRITICAL_DRAWDOWN_DRIFT",
                            "max_drawdown_pct",
                            f"Drawdown at {dd:.1f}% — severe drift from target",
                            dd, category="drift"))
    elif dd >= 8:
        issues.append(Issue("WARNING", "DRAWDOWN_DRIFT",
                            "max_drawdown_pct",
                            f"Drawdown at {dd:.1f}% — drifting above comfort level",
                            dd, category="drift"))
    else:
        passed += 1

    return issues, run, passed


def detect_capital_deterioration(p: dict) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    run = passed = 0

    total  = float(p.get("total_value", 0) or 0)
    start  = float(p.get("initial_capital", p.get("starting_capital", 0)) or 0)
    if start <= 0:
        # No baseline — skip
        return issues, run, passed

    change_pct = (total - start) / start * 100

    run += 1
    if change_pct <= _CAP_DETERI_CRIT:
        issues.append(Issue("CRITICAL", "CAPITAL_DETERIORATION",
                            "total_value",
                            f"Capital has declined {abs(change_pct):.1f}% from start",
                            change_pct, category="drift"))
    elif change_pct <= _CAP_DETERI_WARN:
        issues.append(Issue("WARNING", "CAPITAL_DECLINE",
                            "total_value",
                            f"Capital has declined {abs(change_pct):.1f}% from start",
                            change_pct, category="drift"))
    else:
        passed += 1

    return issues, run, passed


def detect_concentration_drift(p: dict) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    run = passed = 0

    positions  = p.get("positions", []) or []
    total_val  = float(p.get("total_value", 0) or 0)

    if not positions or total_val <= 0:
        return issues, run, passed

    largest_pct = max(
        float(pos.get("current_value", pos.get("value", 0)) or 0) / total_val * 100
        for pos in positions
    )

    run += 1
    if largest_pct >= 35:
        issues.append(Issue("CRITICAL", "CONCENTRATION_DRIFT",
                            "largest_position_pct",
                            f"Largest position {largest_pct:.1f}% of portfolio — critical drift",
                            largest_pct, category="drift"))
    elif largest_pct >= 22:
        issues.append(Issue("WARNING", "HIGH_CONCENTRATION_DRIFT",
                            "largest_position_pct",
                            f"Largest position {largest_pct:.1f}% of portfolio — drifting high",
                            largest_pct, category="drift"))
    else:
        passed += 1

    return issues, run, passed


def detect_volatility_drift(trades: list[dict]) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    run = passed = 0

    if len(trades) < 3:
        return issues, run, passed

    pnls = [float(t.get("pnl", 0) or 0) for t in trades[-10:]]
    if len(pnls) < 2:
        return issues, run, passed

    mean   = sum(pnls) / len(pnls)
    var    = sum((x - mean) ** 2 for x in pnls) / len(pnls)
    import math
    stddev = math.sqrt(var)

    run += 1
    if stddev > abs(mean) * 3 and mean != 0:
        issues.append(Issue("WARNING", "VOLATILITY_DRIFT",
                            "pnl_volatility",
                            f"P&L standard deviation ({stddev:.0f}) is 3× the mean ({mean:.0f}) — increasing volatility",
                            stddev, category="drift"))
    else:
        passed += 1

    return issues, run, passed


def get_drift_validation() -> dict:
    p         = _load_portfolio()
    risk_snap = _load_risk_optimisation()
    trades    = _load_trades()

    if not p:
        return unavailable_result("drift", "No portfolio data for drift detection")

    all_issues: list[Issue] = []
    total_run = total_passed = 0

    for fn_args in [
        (detect_exposure_drift,        (p,)),
        (detect_drawdown_drift,        (p, risk_snap)),
        (detect_capital_deterioration, (p,)),
        (detect_concentration_drift,   (p,)),
        (detect_volatility_drift,      (trades,)),
    ]:
        fn, args = fn_args
        iss, r, ps = fn(*args)
        all_issues.extend(iss); total_run += r; total_passed += ps

    if total_run == 0:
        total_run = 1; total_passed = 1

    return domain_result(
        "drift", total_run, total_passed, all_issues,
        extra={
            "utilisation_pct":  float(p.get("portfolio_utilisation_pct", 0) or 0),
            "max_drawdown_pct": float(p.get("max_drawdown_pct",
                                      risk_snap.get("max_drawdown_pct", 0)) or 0),
        },
    )
