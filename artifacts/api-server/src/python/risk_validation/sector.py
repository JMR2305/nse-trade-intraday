"""
risk_validation/sector.py — Phase 8.4
Sector risk validation: concentration, exposure, diversification, drift.
READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result, unavailable_result

_SECTOR_CONC_WARN  = 35.0   # % of portfolio in one sector
_SECTOR_CONC_CRIT  = 55.0   # %
_MIN_SECTORS       = 2      # minimum sector count for diversification
_DOMINANT_THRESHOLD= 50.0   # % — sector is "dominant"


def _load_sector_data() -> dict:
    """Try paper analytics sector breakdown."""
    try:
        from paper_analytics.shared_services import _load_sector
        return _load_sector() or {}
    except Exception:
        pass
    try:
        from portfolio_store import load_state
        state = load_state() or {}
        return state.get("sectors", {})
    except Exception:
        return {}


def _load_market_sectors() -> dict:
    """Try market intelligence sector data."""
    try:
        from market_intelligence_hub.shared_services import get_sectors
        result = get_sectors() or {}
        return result
    except Exception:
        return {}


def _normalize_sectors(raw: dict) -> dict[str, float]:
    """Return {sector_name: pct_of_portfolio} — best-effort from various shapes."""
    if not raw:
        return {}
    # Shape 1: {sector: pct}
    if all(isinstance(v, (int, float)) for v in raw.values()):
        return {k: float(v) for k, v in raw.items() if float(v) > 0}
    # Shape 2: {sector: {pct: ..., value: ...}}
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            pct = v.get("pct", v.get("percentage", v.get("weight", 0)))
            if pct:
                out[k] = float(pct)
    return out


def validate_sector_concentration(sectors: dict[str, float]) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    run = passed = 0

    for sector, pct in sectors.items():
        run += 1
        if pct >= _SECTOR_CONC_CRIT:
            issues.append(Issue("CRITICAL", "SECTOR_OVER_CONCENTRATED", f"sector.{sector}",
                                f"{sector} is {pct:.1f}% of portfolio (>{_SECTOR_CONC_CRIT}%)", pct,
                                category="concentration"))
        elif pct >= _SECTOR_CONC_WARN:
            issues.append(Issue("WARNING", "SECTOR_HIGH_CONCENTRATION", f"sector.{sector}",
                                f"{sector} is {pct:.1f}% of portfolio (>{_SECTOR_CONC_WARN}%)", pct,
                                category="concentration"))
        else:
            passed += 1

    return issues, run, passed


def validate_diversification(sectors: dict[str, float]) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    run = passed = 0

    n = len(sectors)
    run += 1
    if n >= _MIN_SECTORS:
        passed += 1
    else:
        issues.append(Issue("WARNING", "LOW_DIVERSIFICATION", "sector_count",
                            f"Only {n} sector(s) represented; recommend ≥{_MIN_SECTORS}",
                            float(n), category="diversification"))

    # Dominant sector check
    for sector, pct in sectors.items():
        run += 1
        if pct >= _DOMINANT_THRESHOLD:
            issues.append(Issue("CRITICAL", "DOMINANT_SECTOR", f"sector.{sector}",
                                f"{sector} dominates portfolio at {pct:.1f}% (>{_DOMINANT_THRESHOLD}%)",
                                pct, category="diversification"))
        else:
            passed += 1

    return issues, run, passed


def validate_sector_drift(sectors: dict[str, float]) -> tuple[list[Issue], int, int]:
    """
    Detect sector drift by checking if the HHI (concentration index) is high,
    which signals over-concentration that may have drifted from balanced state.
    """
    issues: list[Issue] = []
    run = passed = 0

    if not sectors:
        return issues, run, passed

    total_pct = sum(sectors.values())
    if total_pct <= 0:
        return issues, run, passed

    # Herfindahl–Hirschman Index (normalised 0–1)
    hhi = sum((pct / total_pct) ** 2 for pct in sectors.values())
    run += 1
    if hhi > 0.50:
        issues.append(Issue("WARNING", "HIGH_HHI_DRIFT", "sector_hhi",
                            f"Sector HHI = {hhi:.2f} indicates high concentration drift",
                            hhi, category="drift"))
    else:
        passed += 1

    return issues, run, passed


def get_sector_validation() -> dict:
    raw = _load_sector_data()
    sectors = _normalize_sectors(raw)

    if not sectors:
        # Try market sectors as fallback
        mkt = _load_market_sectors()
        if isinstance(mkt, dict):
            sectors = _normalize_sectors(mkt.get("sectors", mkt))

    if not sectors:
        return unavailable_result("sector", "No sector data available")

    all_issues: list[Issue] = []
    total_run = total_passed = 0

    for fn in [validate_sector_concentration, validate_diversification,
               validate_sector_drift]:
        iss, r, ps = fn(sectors)
        all_issues.extend(iss); total_run += r; total_passed += ps

    if total_run == 0:
        total_run = 1; total_passed = 1

    dominant = max(sectors, key=sectors.get) if sectors else "—"

    return domain_result(
        "sector", total_run, total_passed, all_issues,
        extra={
            "sector_count":   len(sectors),
            "sectors":        sectors,
            "dominant_sector": dominant,
            "dominant_pct":   sectors.get(dominant, 0),
        },
    )
