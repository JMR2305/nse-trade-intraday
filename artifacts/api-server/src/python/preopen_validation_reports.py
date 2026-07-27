"""
preopen_validation_reports.py — Phase 5B daily and 5-day report generator.

Produces:
  PreOpenAccuracy_<YYYYMMDD>.json
  PreOpenAccuracy_<YYYYMMDD>.md
  Phase5B_5Day_Validation_Report.json
  Phase5B_5Day_Validation_Report.md

PAPER TRADING / ADVISORY ONLY.
No order, execution, or trade-placement function exists in this module.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from preopen_validation_model import ValidationRecord, OutcomeClass, now_utc
from preopen_validation_metrics import (
    calculate_session_metrics,
    calculate_score_bands,
    calculate_factor_metrics,
    calculate_sector_breakdown,
    calculate_gap_breakdown,
    calculate_vix_breakdown,
)

_REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
_MIN_SESSIONS_FOR_GO = 5


def _ensure_report_dir() -> str:
    os.makedirs(_REPORT_DIR, exist_ok=True)
    return _REPORT_DIR


def _top_performers(records: List[ValidationRecord], n: int = 3) -> List[dict]:
    scored = sorted(
        [r for r in records if r.return_0930 is not None],
        key=lambda r: -(r.return_0930 or 0)
    )
    return [
        {"symbol": r.symbol, "return_0930": r.return_0930,
         "outcome": r.prediction_result, "score": r.opportunity_score}
        for r in scored[:n]
    ]


def _worst_performers(records: List[ValidationRecord], n: int = 3) -> List[dict]:
    scored = sorted(
        [r for r in records if r.return_0930 is not None],
        key=lambda r: (r.return_0930 or 0)
    )
    return [
        {"symbol": r.symbol, "return_0930": r.return_0930,
         "outcome": r.prediction_result, "score": r.opportunity_score}
        for r in scored[:n]
    ]


# ── Daily report ──────────────────────────────────────────────────────────────

def generate_daily_report(
    trading_date: str,
    session_id: str,
    records: List[ValidationRecord],
) -> Dict[str, Any]:
    """
    Generate the daily validation report.
    Returns a dict with full report data and writes JSON + MD files.
    """
    metrics      = calculate_session_metrics(records)
    score_bands  = calculate_score_bands(records)
    factor_met   = calculate_factor_metrics(records)
    sector_bd    = calculate_sector_breakdown(records)
    gap_bd       = calculate_gap_breakdown(records)
    vix_bd       = calculate_vix_breakdown(records)

    top_performers   = _top_performers(records)
    worst_performers = _worst_performers(records)

    data_quality_issues = _collect_quality_issues(records)
    recommendations     = _build_recommendations(metrics, score_bands)

    report = {
        "report_type":     "DAILY_VALIDATION",
        "trading_date":    trading_date,
        "session_id":      session_id,
        "generated_at":    now_utc(),
        "platform_mode":   "PAPER TRADING / ADVISORY ONLY",
        "session_summary": metrics,
        "top_performers":  top_performers,
        "worst_performers": worst_performers,
        "candidate_outcomes": [r.to_dict() for r in records],
        "factor_analysis":  factor_met,
        "score_band_analysis": score_bands,
        "sector_breakdown":  sector_bd,
        "gap_breakdown":     gap_bd,
        "vix_breakdown":     vix_bd,
        "data_quality_issues": data_quality_issues,
        "recommendations":   recommendations,
        "sample_size_warning": metrics.get("sample_size_warning", True),
        "note": (
            "This report is advisory only. No trade decisions are derived "
            "from pre-open validation data. Thresholds are fixed and must "
            "not be tuned on single-session results."
        ),
    }

    # Write files
    report_dir   = _ensure_report_dir()
    json_path    = os.path.join(report_dir, f"PreOpenAccuracy_{trading_date.replace('-','')}.json")
    md_path      = os.path.join(report_dir, f"PreOpenAccuracy_{trading_date.replace('-','')}.md")

    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    _write_daily_md(md_path, trading_date, metrics, score_bands, factor_met,
                    top_performers, worst_performers, data_quality_issues, recommendations)

    report["report_json_path"] = json_path
    report["report_md_path"]   = md_path

    # Persist to DB
    try:
        import preopen_validation_db as db
        db.save_daily_report(
            session_id, trading_date, metrics, score_bands, factor_met, sector_bd,
            json_path, md_path
        )
    except Exception:
        pass

    return report


def _collect_quality_issues(records: List[ValidationRecord]) -> List[dict]:
    issues = []
    for r in records:
        rec_issues = []
        if r.actual_open is None:
            rec_issues.append("missing_actual_open")
        if r.price_0930 is None:
            rec_issues.append("missing_price_0930")
        if r.closing_price is None:
            rec_issues.append("missing_close")
        if r.data_quality_status in ("STALE", "MISSING", "INVALID"):
            rec_issues.append(f"data_quality_{r.data_quality_status.lower()}")
        if r.executed_quantity == 0:
            rec_issues.append("zero_executed_quantity")
        if rec_issues:
            issues.append({"symbol": r.symbol, "issues": rec_issues})
    return issues


def _build_recommendations(metrics: dict, score_bands: list) -> List[str]:
    recs = []
    n = metrics.get("valid_candidates", 0)
    if n < 5:
        recs.append(f"INSUFFICIENT SAMPLE: only {n} valid candidates. Do not draw conclusions.")
    cont_rate = metrics.get("continuation_rate", 0) or 0
    if cont_rate >= 60:
        recs.append(f"Continuation rate {cont_rate:.1f}% is positive — monitor across more sessions.")
    elif cont_rate < 40 and n >= 5:
        recs.append(f"Continuation rate {cont_rate:.1f}% is weak — review signal quality.")
    top10 = metrics.get("top10_accuracy")
    if top10 is not None and top10 >= 60:
        recs.append(f"Top-10 accuracy {top10:.1f}% — ranking shows positive discriminatory power.")
    high_band = next((b for b in score_bands if b.get("band") in ("90-100", "80-89")
                      and not b.get("inconclusive")), None)
    if high_band:
        recs.append(
            f"High-score band ({high_band['band']}) continuation rate: "
            f"{high_band.get('continuation_rate')}% — "
            f"observe over more sessions before adjusting thresholds."
        )
    if not recs:
        recs.append("No actionable recommendations yet — more sessions required.")
    return recs


def _write_daily_md(path: str, date: str, metrics: dict, score_bands: list,
                     factors: list, top: list, worst: list,
                     quality_issues: list, recommendations: list) -> None:
    lines = [
        f"# Pre-Open Accuracy Report — {date}",
        "",
        "> **PAPER TRADING / ADVISORY ONLY** — No trade decisions derived from this report.",
        "",
        "## Session Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total candidates | {metrics.get('total_candidates', 0)} |",
        f"| Valid candidates | {metrics.get('valid_candidates', 0)} |",
        f"| Confirmed | {metrics.get('confirmed_candidates', 0)} |",
        f"| Continuation rate | {metrics.get('continuation_rate', 'N/A')}% |",
        f"| Reversal rate | {metrics.get('reversal_rate', 'N/A')}% |",
        f"| Avg 09:30 return | {metrics.get('avg_return_0930', 'N/A')}% |",
        f"| Avg 10:30 return | {metrics.get('avg_return_1030', 'N/A')}% |",
        f"| Top-5 accuracy | {metrics.get('top5_accuracy', 'N/A')}% |",
        f"| Top-10 accuracy | {metrics.get('top10_accuracy', 'N/A')}% |",
        f"| Data completeness | {metrics.get('data_completeness_pct', 0)}% |",
        "",
        "## Top Performers",
        "",
    ]
    for p in top:
        lines.append(f"- **{p['symbol']}**: {p['return_0930']}% at 09:30 ({p['outcome']})")
    lines += ["", "## Worst Performers", ""]
    for p in worst:
        lines.append(f"- **{p['symbol']}**: {p['return_0930']}% at 09:30 ({p['outcome']})")
    lines += ["", "## Score Band Analysis", "",
              "| Band | Candidates | Continuation | Reversal | Avg 09:30 | Avg 10:30 |",
              "|------|-----------|-------------|---------|-----------|-----------|"]
    for b in score_bands:
        lines.append(
            f"| {b['band']} | {b['candidates']} | "
            f"{b.get('continuation_rate', 'N/A')}% | {b.get('reversal_rate', 'N/A')}% | "
            f"{b.get('avg_return_0930', 'N/A')}% | {b.get('avg_return_1030', 'N/A')}% |"
        )
    lines += ["", "## Factor Analysis", "",
              "| Factor | Sample | Success Rate | Avg Return | Reliability |",
              "|--------|--------|-------------|-----------|------------|"]
    for f in factors:
        note = " *(inconclusive)*" if f.get("inconclusive") else ""
        lines.append(
            f"| {f['factor']} | {f['sample_size']} | "
            f"{f.get('factor_success_rate', 'N/A')}% | "
            f"{f.get('factor_avg_return', 'N/A')}% | "
            f"{f.get('factor_reliability_score', 'N/A')}{note} |"
        )
    lines += ["", "## Recommendations", ""]
    for r in recommendations:
        lines.append(f"- {r}")
    if quality_issues:
        lines += ["", "## Data Quality Issues", ""]
        for qi in quality_issues:
            lines.append(f"- **{qi['symbol']}**: {', '.join(qi['issues'])}")
    lines += [
        "", "---",
        "*This report is generated automatically and is advisory only. "
        "Do not recommend Trade Decisions integration with fewer than 5 valid sessions.*",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))


# ── Five-day consolidated report ──────────────────────────────────────────────

def generate_5day_report(daily_records: Dict[str, List[ValidationRecord]]) -> Dict[str, Any]:
    """
    Generate the 5-day consolidated report.
    daily_records: {trading_date: [ValidationRecord, ...]}
    Requires at least MIN_SESSIONS_FOR_GO completed sessions.
    """
    n_sessions = len(daily_records)
    all_records = [r for recs in daily_records.values() for r in recs]

    cumulative_metrics = calculate_session_metrics(all_records)
    cumulative_bands   = calculate_score_bands(all_records)
    cumulative_factors = calculate_factor_metrics(all_records)
    cumulative_sectors = calculate_sector_breakdown(all_records)

    # Per-day summaries
    daily_summaries = []
    for date in sorted(daily_records.keys()):
        recs = daily_records[date]
        m = calculate_session_metrics(recs)
        daily_summaries.append({"date": date, **m})

    # Verdict
    verdict, confidence_level = _compute_5day_verdict(cumulative_metrics, n_sessions)

    report = {
        "report_type":       "5DAY_CONSOLIDATED",
        "sessions_analysed": n_sessions,
        "trading_dates":     sorted(daily_records.keys()),
        "generated_at":      now_utc(),
        "platform_mode":     "PAPER TRADING / ADVISORY ONLY",
        "sufficient_data":   n_sessions >= _MIN_SESSIONS_FOR_GO,
        "cumulative_metrics": cumulative_metrics,
        "daily_summaries":   daily_summaries,
        "score_band_performance": cumulative_bands,
        "top_ranked_performance": _top_n_across_days(all_records, 10),
        "sector_performance":     cumulative_sectors,
        "gap_direction_analysis": calculate_gap_breakdown(all_records),
        "imbalance_analysis": {
            "buy_imbalance_success_rate":  cumulative_metrics.get("buy_imbalance_success_rate"),
            "sell_imbalance_success_rate": cumulative_metrics.get("sell_imbalance_success_rate"),
        },
        "factor_reliability":    cumulative_factors,
        "confidence_level":      confidence_level,
        "verdict":               verdict,
        "verdict_note": (
            "Verdict based on observed data only. "
            "Do not recommend Trade Decisions integration with fewer than 5 valid sessions."
        ),
        "note": "PAPER TRADING / ADVISORY ONLY. No trade decisions derived from this report.",
    }

    # Write files
    report_dir = _ensure_report_dir()
    json_path  = os.path.join(report_dir, "Phase5B_5Day_Validation_Report.json")
    md_path    = os.path.join(report_dir, "Phase5B_5Day_Validation_Report.md")

    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    _write_5day_md(md_path, report)

    report["report_json_path"] = json_path
    report["report_md_path"]   = md_path
    return report


def _compute_5day_verdict(metrics: dict, n_sessions: int) -> tuple:
    if n_sessions < _MIN_SESSIONS_FOR_GO:
        return "PRE-OPEN MODULE REQUIRES MORE DATA", "LOW"

    cont_rate = metrics.get("continuation_rate", 0) or 0
    top10     = metrics.get("top10_accuracy") or 0
    n_valid   = metrics.get("valid_candidates", 0)

    if n_valid < 20:
        return "PRE-OPEN MODULE REQUIRES MORE DATA", "LOW"
    if cont_rate >= 55 and top10 >= 55:
        return "PRE-OPEN MODULE SHOWS POSITIVE PREDICTIVE VALUE", "MODERATE"
    if cont_rate < 40 and top10 < 40:
        return "PRE-OPEN MODULE DOES NOT YET SHOW RELIABLE VALUE", "LOW"
    return "PRE-OPEN MODULE REQUIRES MORE DATA", "LOW"


def _top_n_across_days(records: List[ValidationRecord], n: int) -> List[dict]:
    ranked = sorted(
        [r for r in records if r.preopen_rank is not None],
        key=lambda r: r.preopen_rank or 999
    )[:n]
    return [
        {"symbol": r.symbol, "date": r.trading_date,
         "rank": r.preopen_rank, "outcome": r.prediction_result,
         "return_0930": r.return_0930, "score": r.opportunity_score}
        for r in ranked
    ]


def _write_5day_md(path: str, report: dict) -> None:
    cm = report.get("cumulative_metrics", {})
    lines = [
        "# Phase 5B — 5-Day Pre-Open Validation Report",
        "",
        "> **PAPER TRADING / ADVISORY ONLY**",
        "",
        f"Sessions analysed: **{report.get('sessions_analysed', 0)}**  ",
        f"Trading dates: {', '.join(report.get('trading_dates', []))}  ",
        f"Generated: {report.get('generated_at', '')}",
        "",
        "## Verdict",
        "",
        f"### **{report.get('verdict', 'N/A')}**",
        "",
        f"Confidence: {report.get('confidence_level', 'N/A')}  ",
        f"> {report.get('verdict_note', '')}",
        "",
        "## Cumulative Accuracy",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total candidates | {cm.get('total_candidates', 0)} |",
        f"| Valid candidates | {cm.get('valid_candidates', 0)} |",
        f"| Continuation rate | {cm.get('continuation_rate', 'N/A')}% |",
        f"| Reversal rate | {cm.get('reversal_rate', 'N/A')}% |",
        f"| Top-5 accuracy | {cm.get('top5_accuracy', 'N/A')}% |",
        f"| Top-10 accuracy | {cm.get('top10_accuracy', 'N/A')}% |",
        f"| Avg 09:30 return | {cm.get('avg_return_0930', 'N/A')}% |",
        f"| Avg closing return | {cm.get('avg_closing_return', 'N/A')}% |",
        "",
        "## Daily Comparison",
        "",
        "| Date | Candidates | Valid | Continuation | Avg 09:30 |",
        "|------|-----------|-------|-------------|-----------|",
    ]
    for d in report.get("daily_summaries", []):
        lines.append(
            f"| {d.get('date','')} | {d.get('total_candidates',0)} | "
            f"{d.get('valid_candidates',0)} | "
            f"{d.get('continuation_rate','N/A')}% | "
            f"{d.get('avg_return_0930','N/A')}% |"
        )
    lines += [
        "", "---",
        "*Report is advisory only. No trades are generated from pre-open validation data.*",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))
