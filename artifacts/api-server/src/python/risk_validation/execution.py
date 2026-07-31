"""
risk_validation/execution.py — Phase 8.4
Execution risk validation: slippage, delay, missed opportunities,
order timing, price drift, paper execution quality.

Reads from execution_quality and paper analytics. Gracefully degrades
when data is unavailable.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result, unavailable_result

_SLIPPAGE_WARN_BPS   = 15    # basis points
_SLIPPAGE_CRIT_BPS   = 30
_FILL_RATE_WARN      = 0.85  # < 85 % fill rate
_FILL_RATE_CRIT      = 0.70
_EXEC_QUALITY_WARN   = 65.0  # execution quality score (0–100)


def _load_execution_quality() -> dict:
    try:
        from execution_quality.api import get_slippage
        return get_slippage() or {}
    except Exception:
        return {}


def _load_paper_execution() -> dict:
    try:
        from paper_analytics.shared_services import _load_execution
        return _load_execution() or {}
    except Exception:
        return {}


def _load_trades() -> list[dict]:
    try:
        from portfolio_store import load_trades
        return load_trades() or []
    except Exception:
        return []


def _compute_paper_quality(trades: list[dict]) -> dict:
    """Estimate execution quality from paper trade records."""
    if not trades:
        return {}
    total  = len(trades)
    fills  = sum(1 for t in trades if t.get("exit_price") or t.get("fill_price"))
    misses = total - fills
    avg_pnl= (sum(float(t.get("pnl", 0) or 0) for t in trades) / total
               if total else 0)
    return {
        "total_trades":   total,
        "filled_trades":  fills,
        "missed_trades":  misses,
        "fill_rate":      round(fills / max(total, 1), 3),
        "avg_pnl":        round(avg_pnl, 2),
    }


def get_execution_validation() -> dict:
    eq_data   = _load_execution_quality()
    pe_data   = _load_paper_execution()
    trades    = _load_trades()
    paper_qlt = _compute_paper_quality(trades)

    if not eq_data and not pe_data and not trades:
        return unavailable_result("execution",
                                  "No execution data available")

    issues: list[Issue] = []
    run = passed = 0

    # Check 1: slippage
    slippage_bps = float(eq_data.get("avg_slippage_bps",
                          pe_data.get("avg_slippage_bps", 0)) or 0)
    if slippage_bps > 0 or eq_data or pe_data:
        run += 1
        if slippage_bps >= _SLIPPAGE_CRIT_BPS:
            issues.append(Issue("CRITICAL", "HIGH_SLIPPAGE",
                                "avg_slippage_bps",
                                f"Average slippage {slippage_bps:.1f} bps exceeds {_SLIPPAGE_CRIT_BPS} bps",
                                slippage_bps, category="execution"))
        elif slippage_bps >= _SLIPPAGE_WARN_BPS:
            issues.append(Issue("WARNING", "ELEVATED_SLIPPAGE",
                                "avg_slippage_bps",
                                f"Average slippage {slippage_bps:.1f} bps is elevated",
                                slippage_bps, category="execution"))
        else:
            passed += 1

    # Check 2: fill rate
    fill_rate = float(paper_qlt.get("fill_rate",
                       eq_data.get("fill_rate", 1.0)) or 1.0)
    if fill_rate < 1.0 or paper_qlt:
        run += 1
        if fill_rate < _FILL_RATE_CRIT:
            issues.append(Issue("CRITICAL", "CRITICAL_FILL_RATE",
                                "fill_rate",
                                f"Fill rate {fill_rate*100:.0f}% below critical threshold {_FILL_RATE_CRIT*100:.0f}%",
                                fill_rate, category="execution"))
        elif fill_rate < _FILL_RATE_WARN:
            issues.append(Issue("WARNING", "LOW_FILL_RATE",
                                "fill_rate",
                                f"Fill rate {fill_rate*100:.0f}% below warning threshold {_FILL_RATE_WARN*100:.0f}%",
                                fill_rate, category="execution"))
        else:
            passed += 1

    # Check 3: missed trades
    if paper_qlt:
        missed = int(paper_qlt.get("missed_trades", 0))
        run += 1
        if missed > 0:
            issues.append(Issue("INFO", "MISSED_OPPORTUNITIES",
                                "missed_trades",
                                f"{missed} paper trade(s) have no fill/exit recorded",
                                float(missed), category="execution"))
        else:
            passed += 1

    if run == 0:
        run = 1; passed = 1

    return domain_result(
        "execution", run, passed, issues,
        extra={
            "avg_slippage_bps":  slippage_bps,
            "fill_rate":         fill_rate,
            "total_trades":      paper_qlt.get("total_trades", 0),
            "missed_trades":     paper_qlt.get("missed_trades", 0),
        },
    )
