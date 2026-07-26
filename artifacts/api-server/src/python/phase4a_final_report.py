"""
phase4a_final_report.py — Phase 4A Final Report Generator.

Assembles all Phase 4A module outputs for a session date into a single
comprehensive report with a weighted readiness score (0–100):

  Safety    40% — pre-market checks + safety invariants
  Risk      25% — risk metrics quality (no kills, no CB trips, drawdown)
  AI        20% — AI performance (confidence, agreement rate)
  System    15% — system health (API latency, errors, uptime)

Outputs:
  docs/Phase4A_Final_Report_YYYYMMDD.json
  docs/Phase4A_Final_Report_YYYYMMDD.md

Usage:
    uv run python phase4a_final_report.py [--date YYYY-MM-DD]

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from typing import Any, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.join(_DIR, "..", "..", "docs")
os.makedirs(_DOCS, exist_ok=True)

LABEL = "PAPER TRADING / RESEARCH ONLY"

# Readiness score weights
WEIGHTS = {
    "safety": 0.40,
    "risk": 0.25,
    "ai": 0.20,
    "system": 0.15,
}


def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


# ── Component scores (0–100) ──────────────────────────────────────────────────

def _safety_score(premarket: dict, validation: dict) -> tuple[float, list[str]]:
    """Score: 100 if all checks pass; deduct per FAIL/WARN."""
    issues = []
    score = 100.0

    pm_checks = premarket.get("checks", [])
    pm_total = len(pm_checks)
    pm_failed = sum(1 for c in pm_checks if c.get("verdict") == "FAIL")
    pm_warned = sum(1 for c in pm_checks if c.get("verdict") == "WARN")
    if pm_failed > 0:
        deduct = pm_failed / max(pm_total, 1) * 60
        score -= deduct
        issues.append(f"{pm_failed} pre-market check(s) FAILED")
    if pm_warned > 0:
        deduct = pm_warned / max(pm_total, 1) * 20
        score -= deduct
        issues.append(f"{pm_warned} pre-market check(s) WARNED")

    inv_checks = validation.get("invariants", [])
    inv_failed = sum(1 for i in inv_checks if i.get("verdict") == "FAIL")
    inv_warned = sum(1 for i in inv_checks if i.get("verdict") == "WARN")
    if inv_failed > 0:
        score -= inv_failed * 15
        issues.append(f"{inv_failed} safety invariant(s) FAILED")
    if inv_warned > 0:
        score -= inv_warned * 5
        issues.append(f"{inv_warned} safety invariant(s) WARNED")

    return max(0.0, min(100.0, score)), issues


def _risk_score(risk: dict) -> tuple[float, list[str]]:
    """Score starts at 100; deduct for kills, CB trips, high drawdown, losses."""
    issues = []
    score = 100.0

    ks = risk.get("kill_switch_events", 0)
    cb = risk.get("circuit_breaker_events", 0)
    dd = risk.get("max_drawdown_pct", 0.0) or 0.0
    daily_risk = risk.get("daily_risk_pct", 0.0) or 0.0
    pf = risk.get("profit_factor", 0.0) or 0.0

    if ks > 0:
        score -= 25
        issues.append(f"{ks} kill switch event(s)")
    if cb > 0:
        score -= 20
        issues.append(f"{cb} circuit breaker trip(s)")
    if dd > 10.0:
        score -= 20
        issues.append(f"Max drawdown {dd:.1f}% exceeds 10%")
    elif dd > 5.0:
        score -= 10
        issues.append(f"Max drawdown {dd:.1f}% exceeds 5%")
    if daily_risk > 3.0:
        score -= 15
        issues.append(f"Daily risk {daily_risk:.2f}% exceeds 3%")
    if pf < 1.0 and risk.get("closed_trades", 0) >= 5:
        score -= 15
        issues.append(f"Profit factor {pf} < 1.0 (losing system)")

    return max(0.0, min(100.0, score)), issues


def _ai_score(ai: dict) -> tuple[float, list[str]]:
    """Score based on confidence, agreement rate, false positive rate."""
    issues = []
    score = 100.0

    conf = ai.get("avg_confidence") or 0.0
    agreement = ai.get("agreement_rate_pct")
    buy_count = ai.get("buy_count", 0)
    fp = ai.get("false_positives", 0)
    fn = ai.get("false_negatives", 0)

    if conf < 50.0 and conf > 0:
        score -= 20
        issues.append(f"Low avg AI confidence {conf:.1f}%")
    if agreement is not None and agreement < 50.0:
        score -= 15
        issues.append(f"Low AI/deterministic agreement {agreement:.1f}%")
    if buy_count > 0 and fp / buy_count > 0.5:
        score -= 20
        issues.append(f"High false positive rate {fp}/{buy_count}")
    # Penalise missing AI data
    if ai.get("signals_evaluated", 0) == 0:
        score -= 30
        issues.append("No signals evaluated (AI data unavailable)")

    return max(0.0, min(100.0, score)), issues


def _system_score(timeline_file: Optional[str]) -> tuple[float, list[str]]:
    """Score based on API latency, errors, uptime from session timeline."""
    issues = []
    score = 100.0

    if not timeline_file or not os.path.exists(timeline_file):
        return 70.0, ["No session timeline recorded"]

    events = []
    with open(timeline_file) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass

    if not events:
        return 70.0, ["Session timeline is empty"]

    lats = [e.get("api_latency_ms") for e in events if e.get("api_latency_ms")]
    errs = [e.get("errors", 0) for e in events]
    max_err = max(errs) if errs else 0

    avg_lat = sum(lats) / len(lats) if lats else 0
    if avg_lat > 500:
        score -= 20
        issues.append(f"High avg API latency {avg_lat:.0f}ms")
    elif avg_lat > 200:
        score -= 10
        issues.append(f"Elevated avg API latency {avg_lat:.0f}ms")

    if max_err > 10:
        score -= 25
        issues.append(f"High error count {max_err}")
    elif max_err > 3:
        score -= 10
        issues.append(f"Elevated error count {max_err}")

    if len(events) < 5:
        score -= 10
        issues.append(f"Only {len(events)} monitor ticks (low coverage)")

    return max(0.0, min(100.0, score)), issues


# ── Final report ──────────────────────────────────────────────────────────────

def generate_final_report(date_str: Optional[str] = None) -> dict:
    target_date = date_str or datetime.date.today().isoformat()
    date_compact = target_date.replace("-", "")

    print(f"\n{'=' * 62}")
    print(f"  Phase 4A Final Report — {target_date}")
    print(f"  {LABEL}")
    print(f"{'=' * 62}\n")

    # Load all components
    from phase4a_premarket import run_premarket_checks
    from phase4a_validate import run_validation
    from phase4a_risk_metrics import compute_risk_metrics
    from phase4a_ai_metrics import compute_ai_metrics
    from phase4a_trade_journal import build_journal

    print("  [1/5] Running pre-market checks…")
    premarket = run_premarket_checks()
    print("  [2/5] Running safety validation…")
    validation = run_validation()
    print("  [3/5] Computing risk metrics…")
    risk = compute_risk_metrics(target_date)
    print("  [4/5] Computing AI metrics…")
    ai = compute_ai_metrics(target_date)
    print("  [5/5] Building trade journal…")
    journal = build_journal(target_date)

    timeline_file = os.path.join(_DOCS, f"session_timeline_{date_compact}.jsonl")

    # Component scores
    s_safety, issues_safety = _safety_score(premarket, validation)
    s_risk, issues_risk = _risk_score(risk)
    s_ai, issues_ai = _ai_score(ai)
    s_system, issues_system = _system_score(timeline_file)

    # Weighted readiness score
    readiness_score = round(
        s_safety * WEIGHTS["safety"] +
        s_risk * WEIGHTS["risk"] +
        s_ai * WEIGHTS["ai"] +
        s_system * WEIGHTS["system"],
        1
    )

    all_issues = (
        [f"[safety] {i}" for i in issues_safety] +
        [f"[risk] {i}" for i in issues_risk] +
        [f"[ai] {i}" for i in issues_ai] +
        [f"[system] {i}" for i in issues_system]
    )

    # Recommendations
    recommendations = _recommendations(s_safety, s_risk, s_ai, s_system,
                                        issues_safety, issues_risk, issues_ai, issues_system)

    report = {
        "label": LABEL,
        "report_type": "phase4a_final_report",
        "date": target_date,
        "generated_at": _now_ist(),
        "readiness_score": readiness_score,
        "readiness_grade": _grade(readiness_score),
        "component_scores": {
            "safety": round(s_safety, 1),
            "risk": round(s_risk, 1),
            "ai": round(s_ai, 1),
            "system": round(s_system, 1),
        },
        "weights": WEIGHTS,
        # Operational summary
        "operational_summary": {
            "premarket_overall": premarket.get("overall"),
            "production_ready": validation.get("production_ready"),
            "trade_count": journal.get("trade_count", 0),
            "closed_trades": risk.get("closed_trades", 0),
            "win_rate_pct": risk.get("win_rate_pct"),
            "total_equity": risk.get("total_equity"),
            "realised_pnl": None,
            "max_drawdown_pct": risk.get("max_drawdown_pct"),
        },
        # Statistics
        "trade_statistics": {
            "total_trades": journal.get("trade_count", 0),
            "closed_trades": risk.get("closed_trades", 0),
            "win_rate_pct": risk.get("win_rate_pct"),
            "profit_factor": risk.get("profit_factor"),
            "expectancy": risk.get("expectancy"),
            "largest_win": risk.get("largest_win"),
            "largest_loss": risk.get("largest_loss"),
        },
        "risk_statistics": {
            "max_drawdown_pct": risk.get("max_drawdown_pct"),
            "daily_risk_pct": risk.get("daily_risk_pct"),
            "kill_switch_events": risk.get("kill_switch_events"),
            "circuit_breaker_events": risk.get("circuit_breaker_events"),
            "sector_exposure": risk.get("sector_exposure"),
        },
        "ai_statistics": {
            "signals_evaluated": ai.get("signals_evaluated"),
            "buy_count": ai.get("buy_count"),
            "watch_count": ai.get("watch_count"),
            "no_trade_count": ai.get("no_trade_count"),
            "false_positives": ai.get("false_positives"),
            "false_negatives": ai.get("false_negatives"),
            "avg_confidence": ai.get("avg_confidence"),
            "avg_explanation_latency_ms": ai.get("avg_explanation_latency_ms"),
            "agreement_rate_pct": ai.get("agreement_rate_pct"),
        },
        "remaining_issues": all_issues,
        "recommendations": recommendations,
    }

    # Persist
    json_path = os.path.join(_DOCS, f"Phase4A_Final_Report_{date_compact}.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    md_path = os.path.join(_DOCS, f"Phase4A_Final_Report_{date_compact}.md")
    with open(md_path, "w") as f:
        f.write(_build_md(report))

    print(f"\n{'=' * 62}")
    print(f"  Readiness Score: {readiness_score}/100 ({_grade(readiness_score)})")
    print(f"  Safety: {s_safety:.0f}  Risk: {s_risk:.0f}  AI: {s_ai:.0f}  System: {s_system:.0f}")
    if all_issues:
        print(f"\n  Issues ({len(all_issues)}):")
        for issue in all_issues[:6]:
            print(f"    • {issue}")
    print(f"\n  JSON:   {json_path}")
    print(f"  Report: {md_path}")
    print(f"{'=' * 62}\n")
    return report


def _grade(score: float) -> str:
    if score >= 90:
        return "EXCELLENT"
    if score >= 75:
        return "GOOD"
    if score >= 60:
        return "ACCEPTABLE"
    if score >= 45:
        return "NEEDS_IMPROVEMENT"
    return "CRITICAL"


def _recommendations(ss: float, sr: float, sa: float, sy: float,
                      is_: list, ir: list, ia: list, iy: list) -> list[str]:
    recs = []
    if ss < 80:
        recs.append("Fix failing pre-market checks before the next session.")
    if "kill switch" in " ".join(ir).lower():
        recs.append("Review kill switch events and acknowledge before resuming.")
    if "circuit breaker" in " ".join(ir).lower():
        recs.append("Review circuit breaker trip and perform manual review before resuming paper entries.")
    if sr < 70:
        recs.append("Risk metrics indicate poor performance — reduce position sizes or pause.")
    if sa < 60:
        recs.append("AI confidence is low — review signal quality and scanner data freshness.")
    if sy < 70:
        recs.append("System health is degraded — check API latency and error logs.")
    if not recs:
        recs.append("All systems operating within acceptable parameters.")
    return recs


def _build_md(r: dict) -> str:
    cs = r["component_scores"]
    opsumm = r["operational_summary"]
    ts = r["trade_statistics"]
    rs = r["risk_statistics"]
    ai = r["ai_statistics"]
    score = r["readiness_score"]
    grade = r["readiness_grade"]
    grade_icon = {"EXCELLENT": "🟢", "GOOD": "🟡", "ACCEPTABLE": "🟠",
                  "NEEDS_IMPROVEMENT": "🔴", "CRITICAL": "❌"}.get(grade, "")

    lines = [
        f"# Phase 4A Final Report — {r['date']}",
        "",
        f"**{r['label']}**  ",
        f"Generated: {r['generated_at']}",
        "",
        f"## Readiness Score: {score}/100 {grade_icon} {grade}",
        "",
        "| Category | Score | Weight |",
        "|----------|-------|--------|",
        f"| Safety | {cs['safety']:.0f}/100 | {int(WEIGHTS['safety']*100)}% |",
        f"| Risk | {cs['risk']:.0f}/100 | {int(WEIGHTS['risk']*100)}% |",
        f"| AI Performance | {cs['ai']:.0f}/100 | {int(WEIGHTS['ai']*100)}% |",
        f"| System Health | {cs['system']:.0f}/100 | {int(WEIGHTS['system']*100)}% |",
        "",
        "## Operational Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Pre-Market | {opsumm.get('premarket_overall', '?')} |",
        f"| Production Ready | {'✅ Yes' if opsumm.get('production_ready') else '❌ No'} |",
        f"| Total Trades | {opsumm.get('trade_count', 0)} |",
        f"| Closed Trades | {opsumm.get('closed_trades', 0)} |",
        f"| Win Rate | {opsumm.get('win_rate_pct', 0) or 0:.1f}% |",
        f"| Max Drawdown | {opsumm.get('max_drawdown_pct', 0) or 0:.2f}% |",
        f"| Total Equity | ₹{opsumm.get('total_equity', 0) or 0:.2f} |",
        "",
        "## Trade Statistics",
        "",
        f"| Win Rate | {ts.get('win_rate_pct', 0) or 0:.1f}% |",
        f"| Profit Factor | {ts.get('profit_factor', 0)} |",
        f"| Expectancy | ₹{ts.get('expectancy', 0) or 0:.2f} |",
        f"| Largest Win | ₹{ts.get('largest_win', 0) or 0:.2f} |",
        f"| Largest Loss | ₹{ts.get('largest_loss', 0) or 0:.2f} |",
        "",
        "## Risk Statistics",
        "",
        f"| Max Drawdown | {rs.get('max_drawdown_pct', 0) or 0:.2f}% |",
        f"| Daily Risk | {rs.get('daily_risk_pct', 0) or 0:.4f}% |",
        f"| Kill Switch Events | {rs.get('kill_switch_events', 0)} |",
        f"| Circuit Breaker Events | {rs.get('circuit_breaker_events', 0)} |",
        "",
        "## AI Statistics",
        "",
        f"| BUY / WATCH / NO_TRADE | {ai.get('buy_count',0)} / {ai.get('watch_count',0)} / {ai.get('no_trade_count',0)} |",
        f"| False Positives | {ai.get('false_positives', 0)} |",
        f"| False Negatives | {ai.get('false_negatives', 0)} |",
        f"| Avg Confidence | {ai.get('avg_confidence') or 'N/A'}% |",
        f"| Agreement Rate | {ai.get('agreement_rate_pct') or 'N/A'}% |",
        "",
        "## Issues",
        "",
    ]
    for issue in r.get("remaining_issues", []):
        lines.append(f"- {issue}")
    if not r.get("remaining_issues"):
        lines.append("- None identified.")
    lines += [
        "",
        "## Recommendations",
        "",
    ]
    for rec in r.get("recommendations", []):
        lines.append(f"- {rec}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4A final report")
    parser.add_argument("--date", type=str, default=None)
    args = parser.parse_args()
    generate_final_report(args.date)
