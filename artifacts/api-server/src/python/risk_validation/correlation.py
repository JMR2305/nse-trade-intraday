"""
risk_validation/correlation.py — Phase 8.4
Correlation and diversification risk validation.

Without live price history we estimate intra-sector correlation (same sector
= higher correlation). Cross-sector positions are assumed lower correlation.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result, unavailable_result

_HIGH_CORR_WARN  = 0.65   # portfolio-level avg correlation warning
_HIGH_CORR_CRIT  = 0.80
_LOW_DIVERS_WARN = 0.30   # diversification score below this is warning
_LOW_DIVERS_CRIT = 0.15


def _load_positions() -> list[dict]:
    try:
        from portfolio_store import load_state
        state = load_state() or {}
        return state.get("positions", []) or []
    except Exception:
        return []


def _load_sector_map() -> dict[str, str]:
    """Return {symbol: sector} from known NSE sector classifications."""
    # Static classification for common NSE symbols
    _SECTORS: dict[str, str] = {
        "RELIANCE": "Energy",      "ONGC": "Energy",       "IOC": "Energy",
        "TCS": "IT",               "INFY": "IT",            "WIPRO": "IT",
        "HCLTECH": "IT",           "TECHM": "IT",
        "HDFCBANK": "Banking",     "ICICIBANK": "Banking",  "SBIN": "Banking",
        "KOTAKBANK": "Banking",    "AXISBANK": "Banking",   "BANKBARODA": "Banking",
        "BAJFINANCE": "Finance",   "BAJAJFINSV": "Finance",
        "HINDUNILVR": "FMCG",     "ITC": "FMCG",           "NESTLEIND": "FMCG",
        "TITAN": "Consumer",       "ASIANPAINT": "Consumer",
        "MARUTI": "Auto",          "TATAMOTORS": "Auto",    "HEROMOTOCO": "Auto",
        "SUNPHARMA": "Pharma",     "DRREDDY": "Pharma",     "CIPLA": "Pharma",
        "LTIM": "IT",              "PERSISTENT": "IT",
        "ADANIENT": "Conglomerate","TATASTEEL": "Metals",   "HINDALCO": "Metals",
    }
    return _SECTORS


def _estimate_portfolio_correlation(positions: list[dict]) -> float:
    """Estimate average pairwise correlation based on sector membership."""
    if len(positions) < 2:
        return 0.0

    sector_map = _load_sector_map()
    symbols = [p.get("symbol", "") for p in positions]
    sectors = [sector_map.get(sym, "Other") for sym in symbols]

    pairs = total = 0
    corr_sum = 0.0
    for i in range(len(sectors)):
        for j in range(i + 1, len(sectors)):
            total += 1
            # Same sector → assume 0.75 correlation; different → 0.20
            corr_sum += 0.75 if sectors[i] == sectors[j] else 0.20
    if total == 0:
        return 0.0
    return round(corr_sum / total, 3)


def _diversification_score(positions: list[dict]) -> float:
    """1 - HHI of sector weights (0=concentrated, 1=perfectly diversified)."""
    if not positions:
        return 0.0

    sector_map  = _load_sector_map()
    total_val   = sum(float(p.get("current_value", p.get("value", 0)) or 0)
                      for p in positions)
    if total_val <= 0:
        return 0.0

    sector_vals: dict[str, float] = {}
    for p in positions:
        sym = p.get("symbol", "")
        val = float(p.get("current_value", p.get("value", 0)) or 0)
        sec = sector_map.get(sym, "Other")
        sector_vals[sec] = sector_vals.get(sec, 0) + val

    hhi = sum((v / total_val) ** 2 for v in sector_vals.values())
    return round(1 - hhi, 3)


def get_correlation_validation() -> dict:
    positions = _load_positions()

    if not positions:
        return unavailable_result("correlation", "No position data for correlation")

    issues: list[Issue] = []
    run = passed = 0

    # Check 1: portfolio-level correlation estimate
    avg_corr = _estimate_portfolio_correlation(positions)
    run += 1
    if avg_corr >= _HIGH_CORR_CRIT:
        issues.append(Issue("CRITICAL", "HIGH_PORTFOLIO_CORRELATION",
                            "avg_correlation",
                            f"Estimated portfolio correlation {avg_corr:.2f} is critically high",
                            avg_corr, category="correlation"))
    elif avg_corr >= _HIGH_CORR_WARN:
        issues.append(Issue("WARNING", "ELEVATED_PORTFOLIO_CORRELATION",
                            "avg_correlation",
                            f"Estimated portfolio correlation {avg_corr:.2f} is elevated",
                            avg_corr, category="correlation"))
    else:
        passed += 1

    # Check 2: diversification score
    div_score = _diversification_score(positions)
    run += 1
    if div_score < _LOW_DIVERS_CRIT:
        issues.append(Issue("CRITICAL", "CRITICAL_LOW_DIVERSIFICATION",
                            "diversification_score",
                            f"Diversification score {div_score:.2f} is critically low",
                            div_score, category="diversification"))
    elif div_score < _LOW_DIVERS_WARN:
        issues.append(Issue("WARNING", "LOW_DIVERSIFICATION",
                            "diversification_score",
                            f"Diversification score {div_score:.2f} is low (recommend >{_LOW_DIVERS_WARN})",
                            div_score, category="diversification"))
    else:
        passed += 1

    # Check 3: single-sector dominance
    sector_map   = _load_sector_map()
    sector_count: dict[str, int] = {}
    for p in positions:
        sec = sector_map.get(p.get("symbol", ""), "Other")
        sector_count[sec] = sector_count.get(sec, 0) + 1
    if sector_count:
        dom_sector = max(sector_count, key=sector_count.get)
        dom_count  = sector_count[dom_sector]
        dom_ratio  = dom_count / len(positions)
        run += 1
        if dom_ratio > 0.60:
            issues.append(Issue("WARNING", "SECTOR_DOMINANCE",
                                f"sector.{dom_sector}",
                                f"{dom_count}/{len(positions)} positions in {dom_sector} "
                                f"({dom_ratio*100:.0f}%)",
                                dom_ratio, category="correlation"))
        else:
            passed += 1

    if run == 0:
        run = 1; passed = 1

    return domain_result(
        "correlation", run, passed, issues,
        extra={
            "avg_correlation":      avg_corr,
            "diversification_score": div_score,
            "positions_analysed":   len(positions),
        },
    )
