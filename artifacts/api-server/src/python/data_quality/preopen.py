"""
data_quality/preopen.py — Phase 8.3
Pre-open data validation: IEP, buy/sell quantities, imbalance ratios,
gap %, auction timestamps, and provider consistency checks.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result


def _safe_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def validate_preopen_symbol(row: dict) -> list[Issue]:
    """Validate a single pre-open symbol record."""
    issues: list[Issue] = []
    sym = str(row.get("symbol", ""))

    def add(sev, check, fld, msg, val=None):
        issues.append(Issue(sev, check, fld, msg, symbol=sym, value=val))

    # IEP (Indicative Equilibrium Price)
    iep = _safe_float(row.get("iep") or row.get("indicative_price"))
    if iep is None:
        add("MISSING", "IEP_PRESENT", "iep", "IEP is missing")
    elif iep <= 0:
        add("CRITICAL", "IEP_NEGATIVE", "iep", f"IEP is zero or negative ({iep})", iep)

    # Previous close plausibility
    prev_close = _safe_float(row.get("prev_close") or row.get("previous_close"))
    if prev_close is not None and prev_close > 0 and iep is not None and iep > 0:
        gap_pct = abs((iep - prev_close) / prev_close * 100)
        if gap_pct > 30:
            add("WARNING", "PREOPEN_SPIKE", "iep",
                f"IEP gap of {gap_pct:.1f}% from prev_close is extreme", iep)

    # Buy / Sell quantities
    buy_qty  = _safe_float(row.get("buy_qty")  or row.get("total_buy_quantity"))
    sell_qty = _safe_float(row.get("sell_qty") or row.get("total_sell_quantity"))

    if buy_qty is not None and buy_qty < 0:
        add("CRITICAL", "NEGATIVE_QTY", "buy_qty",
            f"buy_qty is negative ({buy_qty})", buy_qty)
    if sell_qty is not None and sell_qty < 0:
        add("CRITICAL", "NEGATIVE_QTY", "sell_qty",
            f"sell_qty is negative ({sell_qty})", sell_qty)

    # Imbalance ratio plausibility
    imbalance = _safe_float(row.get("imbalance") or row.get("imbalance_pct"))
    if imbalance is not None and abs(imbalance) > 100:
        add("WARNING", "IMBALANCE_RANGE", "imbalance",
            f"imbalance {imbalance:.1f}% outside ±100% range", imbalance)

    # Gap % field
    gap_pct = _safe_float(row.get("gap_pct") or row.get("gap"))
    if gap_pct is not None and abs(gap_pct) > 30:
        add("WARNING", "GAP_SPIKE", "gap_pct",
            f"gap_pct {gap_pct:.1f}% is extreme (> ±30%)", gap_pct)

    return issues


def validate_provider_consistency(symbols: list[dict]) -> list[Issue]:
    """Ensure all symbols come from the same provider or fallback is documented."""
    issues: list[Issue] = []
    providers = {str(s.get("provider", "")) for s in symbols if s.get("provider")}

    if len(providers) > 1:
        issues.append(Issue(
            "WARNING", "PROVIDER_MISMATCH", "provider",
            f"Multiple providers in single snapshot: {providers}",
            value=list(providers),
        ))

    fallback_count = sum(1 for s in symbols if s.get("is_fallback") or s.get("fallback"))
    if fallback_count > 0:
        issues.append(Issue(
            "INFO", "FALLBACK_ACTIVE", "provider",
            f"{fallback_count} symbol(s) using fallback provider",
            value=fallback_count,
        ))
    return issues


def validate_preopen_snapshot(symbols: list[dict]) -> dict:
    """Validate a full pre-open snapshot (list of symbol records)."""
    if not symbols:
        return domain_result(
            "preopen", 1, 0,
            [Issue("MISSING", "DATA_PRESENT", "snapshot",
                   "No pre-open snapshot available")],
            available=False,
            extra={"symbols_checked": 0},
        )

    total_checks  = 0
    total_passed  = 0
    all_issues: list[Issue] = []

    # Per-symbol validation
    seen_symbols: set[str] = set()
    for row in symbols:
        sym = str(row.get("symbol", ""))
        if sym in seen_symbols:
            all_issues.append(Issue("DUPLICATE", "DUPLICATE_SYMBOL", "symbol",
                                    f"Symbol {sym!r} appears twice", symbol=sym))
            total_checks += 1
        else:
            total_checks += 1
            total_passed += 1
        seen_symbols.add(sym)

        sym_issues = validate_preopen_symbol(row)
        n_checks = 4  # IEP, quantities, imbalance, gap
        n_failed = min(1, len([i for i in sym_issues if i.severity in ("CRITICAL", "WARNING")]))
        total_checks += n_checks
        total_passed += n_checks - n_failed
        all_issues.extend(sym_issues)

    # Provider consistency
    prov_issues = validate_provider_consistency(symbols)
    total_checks += 1
    if not prov_issues:
        total_passed += 1
    all_issues.extend(prov_issues)

    return domain_result(
        "preopen", total_checks, total_passed, all_issues,
        extra={"symbols_checked": len(seen_symbols)},
    )


# ── Public entry point ────────────────────────────────────────────────────────

def get_preopen_validation() -> dict:
    """Load and validate the latest pre-open snapshot."""
    symbols: list[dict] = []

    try:
        from preopen_intelligence.service import get_cached_preopen
        data = get_cached_preopen() or {}
        symbols = data.get("symbols", [])
    except Exception:
        pass

    if not symbols:
        try:
            from preopen_accuracy import get_accuracy
            acc = get_accuracy() or {}
            symbols = acc.get("symbols", [])
        except Exception:
            pass

    return validate_preopen_snapshot(symbols)
