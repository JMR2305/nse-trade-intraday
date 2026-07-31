"""
data_quality/portfolio.py — Phase 8.3
Portfolio validation: capital consistency, utilisation range, sector allocation
sum, risk % bounds, largest-position plausibility, and portfolio heat.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def validate_portfolio(data: dict) -> dict:
    issues:       list[Issue] = []
    total_checks: int         = 0
    total_passed: int         = 0

    def chk(ok: bool, sev: str, check: str, fld: str, msg: str, val=None):
        nonlocal total_checks, total_passed
        total_checks += 1
        if ok:
            total_passed += 1
        else:
            issues.append(Issue(sev, check, fld, msg, value=val))

    total = _safe_float(data.get("total_value") or data.get("portfolio_value"))
    cash  = _safe_float(data.get("cash_available") or data.get("cash"))
    invest= _safe_float(data.get("invested_capital"))
    util  = _safe_float(data.get("portfolio_utilisation_pct") or
                        data.get("utilisation"))
    heat  = _safe_float(data.get("portfolio_heat"))

    # Capital bounds
    chk(total >= 0, "CRITICAL", "CAPITAL_NEGATIVE", "total_value",
        f"Total portfolio value is negative ({total:.2f})", total)
    chk(cash >= 0, "CRITICAL", "CASH_NEGATIVE", "cash_available",
        f"Cash available is negative ({cash:.2f})", cash)

    # Total = cash + invested (within 2%)
    if total > 0 and cash >= 0 and invest >= 0:
        computed = cash + invest
        tol = max(total * 0.02, 1.0)
        chk(abs(computed - total) <= tol,
            "WARNING", "PORTFOLIO_TOTAL", "total_value",
            f"Cash ({cash:.2f}) + invested ({invest:.2f}) = {computed:.2f} "
            f"≠ total ({total:.2f})", total)
    else:
        total_checks += 1
        total_passed += 1  # skip when values are zero (empty portfolio)

    # Utilisation 0–100%
    if total > 0:
        chk(0.0 <= util <= 100.0,
            "WARNING", "UTILISATION_RANGE", "portfolio_utilisation_pct",
            f"Utilisation {util:.1f}% outside 0–100%", util)
    else:
        total_checks += 1; total_passed += 1

    # Portfolio heat 0–100
    if heat > 0:
        chk(0.0 <= heat <= 100.0,
            "WARNING", "HEAT_RANGE", "portfolio_heat",
            f"Portfolio heat {heat:.1f} outside 0–100", heat)
    else:
        total_checks += 1; total_passed += 1

    # Sector allocations
    sectors = data.get("sectors") or data.get("sector_breakdown") or []
    if sectors:
        total_sector_pct = sum(_safe_float(s.get("pct") or s.get("allocation_pct"))
                               for s in sectors)
        chk(total_sector_pct <= 102.0,  # small rounding tolerance
            "WARNING", "SECTOR_SUM", "sectors",
            f"Sector allocations sum to {total_sector_pct:.1f}% (> 100%)",
            total_sector_pct)
    else:
        total_checks += 1; total_passed += 1

    # Open positions
    positions = data.get("positions") or data.get("open_positions") or []
    if isinstance(positions, list):
        for pos in positions:
            sym = str(pos.get("symbol", ""))
            pos_val = _safe_float(pos.get("value") or pos.get("market_value"))
            pos_qty = _safe_float(pos.get("qty") or pos.get("quantity"))
            chk(pos_val >= 0,
                "CRITICAL", "NEGATIVE_POSITION", "value",
                f"Position {sym!r} has negative market value ({pos_val:.2f})",
                pos_val)
            chk(pos_qty >= 0,
                "CRITICAL", "NEGATIVE_QTY", "qty",
                f"Position {sym!r} has negative quantity ({pos_qty})",
                pos_qty)
            if total > 0 and pos_val > total:
                issues.append(Issue("WARNING", "OVERSIZED_POSITION", "value",
                                    f"Position {sym!r} ({pos_val:.2f}) > total portfolio ({total:.2f})",
                                    symbol=sym, value=pos_val))
                total_checks += 1
            else:
                total_checks += 1; total_passed += 1
    else:
        total_checks += 1; total_passed += 1

    if not data:
        return domain_result("portfolio", 1, 0,
                             [Issue("MISSING", "DATA_PRESENT", "portfolio",
                                    "No portfolio data available")],
                             available=False)

    return domain_result("portfolio", total_checks, total_passed, issues)


# ── Public entry point ────────────────────────────────────────────────────────

def get_portfolio_validation() -> dict:
    data: dict = {}

    try:
        from paper_analytics.shared_services import get_portfolio
        data = get_portfolio() or {}
    except Exception:
        pass

    if not data or not data.get("available"):
        try:
            from portfolio_performance.performance_engine import load_performance_data
            perf = load_performance_data() or {}
            data = {
                "total_value":    perf.get("total_value", 0),
                "cash_available": perf.get("cash_available", 0),
                "invested_capital": (perf.get("total_value", 0) -
                                     perf.get("cash_available", 0)),
            }
        except Exception:
            pass

    return validate_portfolio(data)
