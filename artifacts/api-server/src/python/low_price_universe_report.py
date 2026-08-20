"""Operator-facing report for the low-price sector universe."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

REPORT_NAME = "APEXQUANT_CUSTOM_LOW_PRICE_IT_INFRA_BANK_UNIVERSE_REPORT.md"
REPORT_PATH = Path(__file__).resolve().parent / REPORT_NAME


def build_report(status: Dict[str, Any], rows: list[Dict[str, Any]]) -> str:
    included = [row for row in rows if row.get("is_active")]
    excluded = [row for row in rows if not row.get("is_active")]
    split = status.get("sector_counts") or {}
    sector_lines = [f"- {sector}: {count}" for sector, count in sorted(split.items())]
    inclusion_lines = [
        f"- {row.get('symbol')}: {row.get('reason_included') or 'eligible'}"
        for row in included
    ]
    exclusion_lines = [
        f"- {row.get('symbol')}: {row.get('reason_excluded') or 'not eligible'}"
        for row in excluded
    ]
    lines = [
        "# ApexQuant AI — Custom Low-Price IT/Infra/Bank Universe Report",
        "",
        "## 1. Purpose", "Paper-only intraday learning universe for lower-priced NSE EQ securities.",
        "",
        "## 2. Active Universe Mode", f"`{status.get('active_universe')}`",
        "",
        "## 3. Eligibility Price Band", "₹20.00 to ₹200.00 inclusive.",
        "",
        "## 4. Eligible Sector Buckets", "IT, INFRA, BANK (provider aliases normalised).",
        "",
        "## 5. NSE EQ Instrument Filter", "Only NSE instruments marked as EQ are considered.",
        "",
        "## 6. Liquidity Filters", "≥500,000 average 20-day volume and ≥₹5 crore average 20-day turnover.",
        "",
        "## 7. OHLCV Evidence Requirement", "At least 120 cached daily bars are required.",
        "",
        "## 8. Active Symbol Count", str(status.get("active_count", 0)),
        "",
        "## 9. Sector Breakdown", *(sector_lines or ["- No active symbols"]),
        "",
        "## 10. Inclusion Evidence", *(inclusion_lines or ["- No included symbols"]),
        "",
        "## 11. Exclusion Evidence", *(exclusion_lines or ["- No excluded symbols"]),
        "",
        "## 12. Data Sources and Coverage",
        f"- OHLCV cache hit rate: {status.get('ohlcv_cache_hit_rate_pct', 0)}%",
        f"- Kite LTP status: {(status.get('kite_ltp') or {}).get('status', 'UNKNOWN')}",
        "- ASM/GSM ingestion: unavailable, skip.",
        "",
        "## 13. Safety and Governance",
        "- PAPER TRADING ONLY. No live broker order API is called.",
        "- Existing per-stock, sector, portfolio, and daily-loss caps are unchanged.",
        "- Historical backtests resolve verified symbols as-of the requested date to avoid look-ahead.",
        "",
        f"Last refresh: {status.get('last_refresh') or 'not yet refreshed'}",
    ]
    return "\n".join(lines) + "\n"


def generate_report() -> Dict[str, Any]:
    from custom_universe_store import get_all_symbols, get_status
    status = get_status()
    markdown = build_report(status, get_all_symbols())
    REPORT_PATH.write_text(markdown, encoding="utf-8")
    return {"success": True, "path": str(REPORT_PATH), "markdown": markdown}


def get_report() -> Dict[str, Any]:
    if not REPORT_PATH.exists():
        return generate_report()
    return {
        "success": True,
        "path": str(REPORT_PATH),
        "markdown": REPORT_PATH.read_text(encoding="utf-8"),
    }