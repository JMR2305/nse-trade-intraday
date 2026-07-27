"""
signal_validation_reports.py — Phase 5C daily and five-day reports.

Daily:  SignalValidation_YYYYMMDD.json + .md
5-day:  Phase5C_5Day_Signal_Validation.json + .md
        (generated after 5 valid sessions; paper_trades > 0)

Verdict options:
  SIGNAL PIPELINE SHOWS POSITIVE OPERATIONAL VALUE
  SIGNAL PIPELINE REQUIRES MORE DATA
  SIGNAL PIPELINE REQUIRES CORRECTIVE WORK

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from signal_validation_model import SignalValidationRecord, OutcomeClass, LifecycleState
from signal_validation_outcomes import is_success, is_failure
from signal_validation_attribution import (
    calculate_strategy_attribution,
    calculate_ai_attribution,
    calculate_preopen_attribution,
    calculate_regime_attribution,
    calculate_funnel,
    calculate_summary,
)

_IST = timezone(timedelta(hours=5, minutes=30))
_REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "phase5c")


def _ensure_dir() -> str:
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    return _REPORTS_DIR


def _now_ist() -> str:
    return datetime.now(_IST).isoformat()


def _to_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


# ── Daily report ───────────────────────────────────────────────────────────────

def generate_daily_report(
    trading_date: str,
    session_id: str,
    records: List[SignalValidationRecord],
) -> Dict[str, Any]:
    """
    Generate SignalValidation_YYYYMMDD.json + .md.
    Returns {report_json_path, report_md_path, report}.
    """
    summary    = calculate_summary(records)
    funnel     = calculate_funnel(records)
    strategies = calculate_strategy_attribution(records, trading_date, session_id)
    ai_attr    = calculate_ai_attribution(records, trading_date, session_id)
    preopen    = calculate_preopen_attribution(records, trading_date, session_id)
    regime     = calculate_regime_attribution(records, trading_date, session_id)

    closed = [r for r in records if r.validation_status == LifecycleState.CLOSED_POSITION]
    wins   = [r for r in closed if is_success(r.outcome_class or "")]
    fails  = [r for r in closed if is_failure(r.outcome_class or "")]
    rejected = [r for r in records if r.validation_status == LifecycleState.RISK_REJECTED]
    missed   = [r for r in records if r.validation_status == LifecycleState.MISSED]
    stale    = [r for r in records if r.validation_status == LifecycleState.STALE_DATA]

    report = {
        "report_type":    "DAILY",
        "trading_date":   trading_date,
        "session_id":     session_id,
        "generated_at":   _now_ist(),
        "label":          "PAPER TRADING / ADVISORY ONLY",
        "operational_summary": summary,
        "signal_funnel":  funnel,
        "strategy_results": strategies,
        "ai_attribution": ai_attr,
        "preopen_attribution": preopen,
        "risk_attribution": {
            "total_rejected": len(rejected),
            "rejection_reasons": _count_field(rejected, "risk_rejection_reason"),
            "rejection_justified_rate": _calc_rejection_justified(rejected),
        },
        "regime_attribution": regime,
        "successful_signals": [_signal_summary(r) for r in wins[:20]],
        "failed_signals":     [_signal_summary(r) for r in fails[:20]],
        "rejected_signals":   [_signal_summary(r) for r in rejected[:20]],
        "missed_opportunities": [_signal_summary(r) for r in missed[:20]],
        "data_quality_issues": {
            "stale_data_count": len(stale),
            "incomplete_count": sum(1 for r in records
                                    if r.outcome_class == OutcomeClass.DATA_INCOMPLETE),
            "completeness_pct": summary.get("data_completeness_pct"),
        },
        "incidents": [],
        "recommendations": _generate_recommendations(records, summary),
        "sample_size_warnings": _sample_size_warnings(strategies),
    }

    d = _ensure_dir()
    date_str = trading_date.replace("-", "")
    json_path = os.path.join(d, f"SignalValidation_{date_str}.json")
    md_path   = os.path.join(d, f"SignalValidation_{date_str}.md")

    try:
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        with open(md_path, "w") as f:
            f.write(_render_daily_md(report))
    except Exception:
        pass

    return {
        "report_json_path": json_path,
        "report_md_path":   md_path,
        "report":           report,
    }


def _signal_summary(r: SignalValidationRecord) -> dict:
    return {
        "validation_id":    r.validation_id,
        "signal_id":        r.signal_id,
        "symbol":           r.symbol,
        "strategy":         r.strategy_name,
        "direction":        r.signal_direction,
        "outcome":          r.outcome_class,
        "r_multiple":       str(r.R_multiple) if r.R_multiple else None,
        "realised_pnl":     str(r.realised_pnl) if r.realised_pnl else None,
        "is_hypothetical":  r.is_hypothetical,
        "label":            r.hypothetical_label or None,
    }


def _count_field(records, field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in records:
        v = getattr(r, field, None) or "unknown"
        counts[v] = counts.get(v, 0) + 1
    return counts


def _calc_rejection_justified(rejected: List[SignalValidationRecord]) -> Optional[float]:
    with_data = [r for r in rejected if r.hyp_rejection_justified is not None]
    if not with_data:
        return None
    justified = sum(1 for r in with_data if r.hyp_rejection_justified)
    return justified / len(with_data)


def _generate_recommendations(records: List[SignalValidationRecord],
                               summary: dict) -> List[str]:
    recs = []
    wr = summary.get("win_rate")
    if wr is not None and wr < 0.4:
        recs.append("Win rate below 40% — review signal generation thresholds.")
    exp = summary.get("expectancy")
    if exp is not None and exp < 0:
        recs.append("Negative expectancy — review risk/reward ratios.")
    comp = summary.get("data_completeness_pct", 100)
    if comp < 80:
        recs.append(f"Data completeness at {comp:.1f}% — check price checkpoint collection.")
    if not recs:
        recs.append("No corrective actions required for this session.")
    recs.append("NOTE: Recommendations are advisory only. Do not modify strategy parameters.")
    return recs


def _sample_size_warnings(strategies: List[dict]) -> List[str]:
    warnings = []
    for s in strategies:
        if s.get("confidence_level") in ("INSUFFICIENT_DATA", "LOW_SAMPLE"):
            warnings.append(
                f"Strategy '{s.get('strategy_id')}': "
                f"only {s.get('sample_size', 0)} closed trades — INSUFFICIENT DATA for comparison."
            )
    return warnings


def _render_daily_md(report: dict) -> str:
    d  = report["trading_date"]
    s  = report["operational_summary"]
    fn = report["signal_funnel"]

    lines = [
        f"# Signal Validation Report — {d}",
        f"\n> Generated: {report['generated_at']}",
        f"\n> {report['label']}",
        "\n## Operational Summary",
        f"- Signals Generated: {s.get('signals_generated', 0)}",
        f"- Signals Approved: {s.get('signals_approved', 0)}",
        f"- Paper Trades: {s.get('paper_trades', 0)}",
        f"- Risk Rejections: {s.get('risk_rejections', 0)}",
        f"- Win Rate: {_fmt_pct(s.get('win_rate'))}",
        f"- Expectancy: {_fmt_dec(s.get('expectancy'))}",
        f"- False Positives: {s.get('false_positives', 0)}",
        f"- Missed Opportunities: {s.get('missed_opportunities', 0)}",
        f"- Data Completeness: {s.get('data_completeness_pct', 0):.1f}%",
        "\n## Signal Funnel",
    ]
    for step, data in fn.items():
        lines.append(f"- {step.replace('_', ' ').title()}: {data['count']} ({data['pct']}%)")

    lines.append("\n## Recommendations")
    for rec in report.get("recommendations", []):
        lines.append(f"- {rec}")

    if report.get("sample_size_warnings"):
        lines.append("\n## Sample Size Warnings")
        for w in report["sample_size_warnings"]:
            lines.append(f"- ⚠️ {w}")

    lines.append(f"\n---\n*PAPER TRADING / ADVISORY ONLY. Not financial advice.*")
    return "\n".join(lines)


def _fmt_pct(v) -> str:
    return f"{float(v)*100:.1f}%" if v is not None else "N/A"


def _fmt_dec(v) -> str:
    return f"{float(v):.2f}" if v is not None else "N/A"


# ── Five-day consolidated report ──────────────────────────────────────────────

def generate_five_day_report(
    sessions: List[dict],
    all_records_by_date: Dict[str, List[SignalValidationRecord]],
) -> Dict[str, Any]:
    """
    Generate Phase5C_5Day_Signal_Validation.json + .md after ≥5 valid sessions.
    Verdict is one of three strings.
    """
    if len(sessions) < 5:
        return {
            "error": "INSUFFICIENT_SESSIONS",
            "message": f"Need 5 valid sessions, have {len(sessions)}",
        }

    daily_summaries = []
    all_records: List[SignalValidationRecord] = []
    for sess in sessions[-5:]:
        date = str(sess.get("trading_date", ""))[:10]
        recs = all_records_by_date.get(date, [])
        all_records.extend(recs)
        daily_summaries.append({
            "trading_date": date,
            "summary": calculate_summary(recs),
        })

    overall = calculate_summary(all_records)
    strategies = calculate_strategy_attribution(all_records, "5day", "consolidated")
    ai_attr    = calculate_ai_attribution(all_records, "5day", "consolidated")
    preopen    = calculate_preopen_attribution(all_records, "5day", "consolidated",
                                               valid_phase5b_sessions=len(sessions))
    regime     = calculate_regime_attribution(all_records, "5day", "consolidated")
    funnel     = calculate_funnel(all_records)

    verdict = _determine_verdict(overall, strategies, all_records)

    report = {
        "report_type":       "FIVE_DAY",
        "sessions_analysed": len(sessions),
        "date_range":        f"{sessions[0].get('trading_date')} to {sessions[-1].get('trading_date')}",
        "generated_at":      _now_ist(),
        "label":             "PAPER TRADING / ADVISORY ONLY",
        "daily_comparison":  daily_summaries,
        "total_signals":     len(all_records),
        "overall_summary":   overall,
        "strategy_performance": strategies,
        "ai_agreement_performance": ai_attr,
        "preopen_attribution": preopen,
        "risk_rejection_quality": {
            "total_rejected": sum(1 for r in all_records
                                  if r.validation_status == LifecycleState.RISK_REJECTED),
        },
        "regime_performance": regime,
        "signal_funnel":     funnel,
        "expectancy":        overall.get("expectancy"),
        "profit_factor":     _calc_profit_factor(all_records),
        "false_positives":   overall.get("false_positives"),
        "missed_opportunities": overall.get("missed_opportunities"),
        "system_incidents":  [],
        "data_completeness": overall.get("data_completeness_pct"),
        "sample_size_confidence": _confidence_from_n(overall.get("paper_trades", 0)),
        "verdict":           verdict,
        "verdict_note":      "Do not recommend strategy modification automatically.",
    }

    d = _ensure_dir()
    json_path = os.path.join(d, "Phase5C_5Day_Signal_Validation.json")
    md_path   = os.path.join(d, "Phase5C_5Day_Signal_Validation.md")

    try:
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        with open(md_path, "w") as f:
            f.write(_render_five_day_md(report))
    except Exception:
        pass

    return {
        "report_json_path": json_path,
        "report_md_path":   md_path,
        "verdict":          verdict,
        "report":           report,
    }


def _determine_verdict(summary: dict, strategies: List[dict],
                       records: List[SignalValidationRecord]) -> str:
    wr  = summary.get("win_rate") or 0
    exp = summary.get("expectancy") or 0
    n   = summary.get("paper_trades") or 0

    if n < 10:
        return "SIGNAL PIPELINE REQUIRES MORE DATA"

    if wr >= 0.5 and exp > 0:
        return "SIGNAL PIPELINE SHOWS POSITIVE OPERATIONAL VALUE"

    if wr < 0.35 or exp < -50:
        return "SIGNAL PIPELINE REQUIRES CORRECTIVE WORK"

    return "SIGNAL PIPELINE REQUIRES MORE DATA"


def _calc_profit_factor(records: List[SignalValidationRecord]) -> Optional[float]:
    from decimal import Decimal
    gross_profit = sum(
        float(r.realised_pnl) for r in records
        if r.realised_pnl and float(r.realised_pnl) > 0
    )
    gross_loss = abs(sum(
        float(r.realised_pnl) for r in records
        if r.realised_pnl and float(r.realised_pnl) < 0
    ))
    return (gross_profit / gross_loss) if gross_loss > 0 else None


def _confidence_from_n(n: int) -> str:
    if n >= 30:
        return "HIGH"
    if n >= 10:
        return "MODERATE"
    return "LOW"


def _render_five_day_md(report: dict) -> str:
    lines = [
        "# Phase 5C — Five-Day Signal Validation Report",
        f"\n> Period: {report['date_range']}",
        f"\n> Sessions: {report['sessions_analysed']}",
        f"\n> Generated: {report['generated_at']}",
        f"\n> {report['label']}",
        f"\n## ✅ Verdict\n\n**{report['verdict']}**",
        "\n## Overall Performance",
        f"- Total Signals: {report.get('total_signals', 0)}",
        f"- Paper Trades: {report['overall_summary'].get('paper_trades', 0)}",
        f"- Win Rate: {_fmt_pct(report['overall_summary'].get('win_rate'))}",
        f"- Expectancy: {_fmt_dec(report.get('expectancy'))}",
        f"- Profit Factor: {_fmt_dec(report.get('profit_factor'))}",
        f"- Data Completeness: {report.get('data_completeness', 0):.1f}%",
        f"- Sample Confidence: {report.get('sample_size_confidence', 'LOW')}",
        "\n## Daily Comparison",
    ]
    for day in report.get("daily_comparison", []):
        s = day.get("summary", {})
        wr = _fmt_pct(s.get("win_rate"))
        lines.append(f"- {day['trading_date']}: {s.get('paper_trades', 0)} trades, WR={wr}")

    lines.append("\n---")
    lines.append("*PAPER TRADING / ADVISORY ONLY. Strategy modification requires operator approval.*")
    return "\n".join(lines)
