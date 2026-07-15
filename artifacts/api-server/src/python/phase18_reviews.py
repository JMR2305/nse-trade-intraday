"""
phase18_reviews.py — Phase 18: Daily / Weekly / Monthly reviews and the
Evidence Accumulation Tracker.

All summaries are computed from stored platform data only (notebook entries,
paper trades, trade replay, phase17 validation history). Nothing is invented;
sections without enough data are marked "Insufficient Data".

Advisory only — no trading actions, no model changes, no auto-promotion.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, timedelta, datetime, timezone
from typing import Any, Dict, List, Optional

import market_hours
import phase18_notebook as nb

_DIR = os.path.dirname(os.path.abspath(__file__))
INSUFFICIENT = "Insufficient Data"
LABEL = "PAPER / RESEARCH ONLY"


def _entries() -> Dict[str, Any]:
    return nb._notebook()["entries"]


def _replay() -> List[Dict[str, Any]]:
    import paper_trader
    try:
        return paper_trader.get_trade_replay()
    except Exception:
        return []


def _closed_between(d1: str, d2: str) -> List[Dict[str, Any]]:
    return [r for r in _replay() if d1 <= str(r.get("exit_time") or "")[:10] <= d2]


def _win_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"trades": 0, "win_rate": INSUFFICIENT, "profit_factor": INSUFFICIENT,
                "expectancy": INSUFFICIENT, "max_drawdown": INSUFFICIENT}
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) <= 0]
    gross_win = sum(float(t.get("pnl") or 0) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl") or 0) for t in losses))
    pnls = [float(t.get("pnl") or 0) for t in trades]
    # simple equity-curve drawdown over the closed trades in order
    eq, peak, mdd = 0.0, 0.0, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return {
        "trades": len(trades),
        "win_rate": round(100 * len(wins) / len(trades), 1),
        "profit_factor": (round(gross_win / gross_loss, 2) if gross_loss > 0
                          else (INSUFFICIENT if not wins else "All wins")),
        "expectancy": round(sum(pnls) / len(pnls), 2),
        "total_pnl": round(sum(pnls), 2),
        "max_drawdown": round(mdd, 2),
    }


def _group_stats(trades: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in trades:
        k = str(t.get(key) or "UNKNOWN")
        groups[k].append(t)
    out = []
    for k, ts in groups.items():
        s = _win_stats(ts)
        out.append({key: k, **s})
    out.sort(key=lambda g: (g["total_pnl"] if isinstance(g.get("total_pnl"), (int, float)) else 0),
             reverse=True)
    return out


def _sector_for(symbol: str) -> str:
    for d in sorted(_entries(), reverse=True):
        for row in _entries()[d].get("decisions", []):
            if row.get("symbol") == symbol and row.get("sector"):
                return row["sector"]
    return "UNKNOWN"


def _best_worst(rows: List[Dict[str, Any]], key: str):
    valid = [r for r in rows if r.get("trades", 0) > 0]
    if not valid:
        return INSUFFICIENT, INSUFFICIENT
    return valid[0][key], valid[-1][key]


# ── daily review (spec §6) ───────────────────────────────────────────────────

def daily_review(date_iso: Optional[str] = None) -> Dict[str, Any]:
    date_iso = date_iso or nb.ist_today()
    e = _entries().get(date_iso)
    if not e:
        return {"success": True, "available": False, "date": date_iso,
                "reason": "No notebook entry for this date.", "label": LABEL}
    decisions = e.get("decisions", [])
    recommended = [r for r in decisions if r.get("raw_signal") in ("STRONG BUY", "BUY")]
    taken = [r for r in decisions if r.get("decision_state") == "PAPER TRADE TAKEN"
             or r.get("user_action") == "PAPER TRADE TAKEN"]
    skipped = [r for r in decisions if r.get("decision_state") == "SKIPPED"
               or r.get("user_action") == "SKIPPED"]
    closed = [r for r in decisions if r.get("outcome")]
    worked = [r["symbol"] for r in closed if float((r["outcome"] or {}).get("pnl") or 0) > 0]
    failed = [r["symbol"] for r in closed if float((r["outcome"] or {}).get("pnl") or 0) < 0]

    conf_alignment = INSUFFICIENT
    with_conf = [r for r in closed if isinstance(r.get("confidence"), (int, float))]
    if with_conf:
        hi = [r for r in with_conf if r["confidence"] >= 70]
        hi_wins = [r for r in hi if float((r["outcome"] or {}).get("pnl") or 0) > 0]
        conf_alignment = (f"{len(hi_wins)}/{len(hi)} high-confidence (>=70) decisions won"
                          if hi else "No high-confidence closed trades today")

    dq = e.get("data_quality") or {}
    issues = []
    if dq.get("scan_stale"):
        issues.append("Canonical scan was stale.")
    if dq.get("symbol_errors"):
        issues.append(f"{dq['symbol_errors']} symbol(s) had data errors.")
    val = e.get("validation") or {}
    if isinstance(val.get("failed"), int) and val["failed"] > 0:
        issues.append(f"QA reported {val['failed']} failed check(s).")

    strat_rows = _group_stats(
        [r for r in _closed_between(date_iso, date_iso)], "strategy_name")
    best_s, worst_s = _best_worst(strat_rows, "strategy_name")

    return {
        "success": True, "available": True, "date": date_iso,
        "market_summary": {
            "regime": (e.get("market") or {}).get("market_regime"),
            "nifty_trend": (e.get("market") or {}).get("nifty_trend"),
            "banknifty_trend": (e.get("market") or {}).get("banknifty_trend"),
            "vix": (e.get("market") or {}).get("india_vix"),
            "breadth": (e.get("market") or {}).get("breadth_label"),
        },
        "ai_recommended": [r["symbol"] for r in recommended] or [],
        "paper_trades_taken": [r["symbol"] for r in taken] or [],
        "skipped": [r["symbol"] for r in skipped] or [],
        "what_worked": worked or ([] if closed else [INSUFFICIENT]),
        "what_failed": failed or ([] if closed else [INSUFFICIENT]),
        "strongest_strategy_today": best_s,
        "weakest_strategy_today": worst_s,
        "best_sectors": (e.get("market") or {}).get("strongest_sectors"),
        "worst_sectors": (e.get("market") or {}).get("weakest_sectors"),
        "confidence_alignment": conf_alignment,
        "risk_or_data_issues": issues or ["None recorded"],
        "watch_next_session": ([r["symbol"] for r in skipped if
                                isinstance(r.get("confidence"), (int, float)) and r["confidence"] >= 65][:5]
                               or ["No high-confidence skips to monitor"]),
        "source": {"scan_id": (e.get("scan") or {}).get("scan_id"),
                   "notebook_state": e.get("state")},
        "label": LABEL,
    }


# ── weekly review (spec §7) ──────────────────────────────────────────────────

def _week_bounds(ref: Optional[str] = None) -> tuple[str, str]:
    d = date.fromisoformat(ref) if ref else market_hours.now_ist().date()
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


def weekly_review(ref_date: Optional[str] = None) -> Dict[str, Any]:
    d1, d2 = _week_bounds(ref_date)
    entries = {d: e for d, e in _entries().items() if d1 <= d <= d2}
    closed = _closed_between(d1, d2)
    for t in closed:
        t["sector"] = _sector_for(str(t.get("symbol")))
    stats = _win_stats(closed)
    strat = _group_stats(closed, "strategy_name")
    sector = _group_stats(closed, "sector")
    regime = _group_stats(closed, "regime")
    best_strat, worst_strat = _best_worst(strat, "strategy_name")
    best_sector, worst_sector = _best_worst(sector, "sector")
    best_regime, worst_regime = _best_worst(regime, "regime")

    with_conf = [t for t in closed if isinstance(t.get("signal_confidence"), (int, float))]
    hc_win = max((t for t in with_conf if float(t.get("pnl") or 0) > 0),
                 key=lambda t: t["signal_confidence"], default=None)
    hc_loss = max((t for t in with_conf if float(t.get("pnl") or 0) < 0),
                  key=lambda t: t["signal_confidence"], default=None)

    dq_incidents = sum(1 for e in entries.values()
                       if (e.get("data_quality") or {}).get("scan_stale")
                       or (e.get("data_quality") or {}).get("symbol_errors"))
    qa_failures = sum(1 for e in entries.values()
                      if isinstance((e.get("validation") or {}).get("failed"), int)
                      and e["validation"]["failed"] > 0)

    failure_patterns, success_patterns = [], []
    stop_hits = [t for t in closed if t.get("exit_type") == "STOP_HIT"]
    target_hits = [t for t in closed if t.get("exit_type") == "TARGET_HIT"]
    if stop_hits:
        failure_patterns.append(f"{len(stop_hits)} stop-loss exit(s)")
    if [t for t in closed if float(t.get("pnl") or 0) < 0 and float(t.get("signal_confidence") or 0) >= 70]:
        failure_patterns.append("High-confidence losers present — review calibration evidence")
    if target_hits:
        success_patterns.append(f"{len(target_hits)} target exit(s)")

    questions = []
    if worst_strat not in (INSUFFICIENT,) and stats["trades"] >= 3:
        questions.append(f"Why did strategy '{worst_strat}' underperform this week?")
    if dq_incidents:
        questions.append("Investigate data-quality incidents recorded this week.")
    if not closed:
        questions.append("No completed paper trades this week — is the workflow being exercised daily?")
    questions.append("Which skipped high-confidence signals would have worked? (advisory review only)")

    def _tr(t):
        return None if not t else {"symbol": t.get("symbol"), "pnl": t.get("pnl"),
                                   "confidence": t.get("signal_confidence"),
                                   "trade_id": t.get("id"), "exit_type": t.get("exit_type")}

    return {
        "success": True, "week_start": d1, "week_end": d2,
        "trading_days_completed": len(entries),
        "finalized_days": sum(1 for e in entries.values() if e.get("state") == "FINALIZED"),
        "completed_paper_trades": len(closed),
        "open_paper_trades": len(nb._open_positions()),
        "weekly_pnl": stats.get("total_pnl", 0 if closed else INSUFFICIENT),
        "win_rate": stats["win_rate"], "profit_factor": stats["profit_factor"],
        "expectancy": stats["expectancy"], "max_drawdown": stats["max_drawdown"],
        "best_strategy": best_strat, "worst_strategy": worst_strat,
        "best_sector": best_sector, "worst_sector": worst_sector,
        "best_regime": best_regime, "worst_regime": worst_regime,
        "highest_confidence_winner": _tr(hc_win),
        "highest_confidence_loser": _tr(hc_loss),
        "common_failure_patterns": failure_patterns or [INSUFFICIENT if not closed else "None identified"],
        "common_success_patterns": success_patterns or [INSUFFICIENT if not closed else "None identified"],
        "data_quality_incidents": dq_incidents,
        "qa_failures": qa_failures,
        "cross_page_consistency_issues": sum(
            1 for e in entries.values()
            for i in (e.get("checklist") or {}).get("during_market", [])
            if i.get("item") == "No cross-page mismatches" and i.get("status") == "WARNING"),
        "research_questions_next_week": questions,
        "strategy_breakdown": strat, "sector_breakdown": sector,
        "regime_breakdown": regime,
        "note": "All recommendations are advisory. No automatic changes are made.",
        "label": LABEL,
    }


# ── monthly review (spec §8) ─────────────────────────────────────────────────

def monthly_review(month: Optional[str] = None) -> Dict[str, Any]:
    """month = 'YYYY-MM' (defaults to current IST month)."""
    m = month or market_hours.now_ist().date().isoformat()[:7]
    d1, d2 = f"{m}-01", f"{m}-31"
    entries = {d: e for d, e in _entries().items() if d.startswith(m)}
    closed = _closed_between(d1, d2)
    for t in closed:
        t["sector"] = _sector_for(str(t.get("symbol")))
    stats = _win_stats(closed)

    import paper_trader
    portfolio = paper_trader.get_portfolio()

    # Confidence calibration from closed trades.
    bands = {"<50": [0, 0], "50-70": [0, 0], ">=70": [0, 0]}  # [wins, total]
    for t in closed:
        c = t.get("signal_confidence")
        if not isinstance(c, (int, float)):
            continue
        band = "<50" if c < 50 else ("50-70" if c < 70 else ">=70")
        bands[band][1] += 1
        if float(t.get("pnl") or 0) > 0:
            bands[band][0] += 1
    calibration = {b: (f"{w}/{n} wins" if n else INSUFFICIENT) for b, (w, n) in bands.items()}

    hist = nb._load_json_file("phase17_history.json", [])
    month_runs = [h for h in hist if str(h.get("generated_at", ""))[:7] == m]
    qa_trend = ([{"run_id": h.get("run_id"), "health_score": h.get("health_score"),
                  "verdict": h.get("verdict")} for h in month_runs[-10:]]
                or INSUFFICIENT)

    issues = nb.list_issues()
    month_issues = [i for i in issues["issues"] if str(i.get("date", "")).startswith(m)]

    ev = evidence_tracker()
    return {
        "success": True, "month": m,
        "portfolio_value": portfolio.get("total_value"),
        "portfolio_growth_pct": portfolio.get("total_pnl_pct"),
        "paper_trades_completed": len(closed),
        "win_rate": stats["win_rate"], "profit_factor": stats["profit_factor"],
        "expectancy": stats["expectancy"], "max_drawdown": stats["max_drawdown"],
        "strategy_ranking": _group_stats(closed, "strategy_name"),
        "sector_ranking": _group_stats(closed, "sector"),
        "regime_performance": _group_stats(closed, "regime"),
        "confidence_calibration": calibration,
        "opportunity_score_validation": (
            "Requires closed trades with stored opportunity scores — "
            + (f"{len(closed)} closed this month" if closed else INSUFFICIENT)),
        "risk_metrics": {"max_drawdown": stats["max_drawdown"],
                         "open_positions": len(nb._open_positions())},
        "data_provider_reliability": {
            "stale_scan_days": sum(1 for e in entries.values()
                                   if (e.get("data_quality") or {}).get("scan_stale")),
            "days_with_symbol_errors": sum(1 for e in entries.values()
                                           if (e.get("data_quality") or {}).get("symbol_errors")),
            "notebook_days": len(entries),
        },
        "qa_trend": qa_trend,
        "validation_trend": {"runs_this_month": len(month_runs)},
        "learning_progress": {
            "notebook_days": len(entries),
            "notes_recorded": sum(len(e.get("user_notes") or []) for e in entries.values()),
            "lessons_recorded": sum(1 for e in entries.values() if e.get("lessons_learned")),
        },
        "open_research_questions": weekly_review()["research_questions_next_week"],
        "human_approved_changes": "Tracked via issue log and notes — no automatic changes exist.",
        "issues_this_month": month_issues,
        "production_readiness_progress": ev["progress"],
        "note": "Live deployment is never recommended automatically. Advisory only.",
        "label": LABEL,
    }


# ── evidence accumulation tracker (spec §9) ──────────────────────────────────

def evidence_tracker() -> Dict[str, Any]:
    entries = _entries()
    closed = _replay()
    targets = nb.get_targets()
    regimes = {str(t.get("regime")) for t in closed if t.get("regime")} | {
        str((e.get("market") or {}).get("market_regime"))
        for e in entries.values()
        if (e.get("market") or {}).get("market_regime") not in (None, INSUFFICIENT)}

    strat_counts: Dict[str, int] = defaultdict(int)
    for t in closed:
        strat_counts[str(t.get("strategy_name") or "UNKNOWN")] += 1
    sector_counts: Dict[str, int] = defaultdict(int)
    for t in closed:
        sector_counts[_sector_for(str(t.get("symbol")))] += 1
    band_counts = {"<50": 0, "50-70": 0, ">=70": 0}
    for t in closed:
        c = t.get("signal_confidence")
        if isinstance(c, (int, float)):
            band_counts["<50" if c < 50 else ("50-70" if c < 70 else ">=70")] += 1

    hist = nb._load_json_file("phase17_history.json", [])
    ok_runs = sum(1 for h in hist if h.get("verdict") == "PASS")
    crit_fails = sum(1 for h in hist if h.get("verdict") == "FAIL")

    stale_days = sum(1 for e in entries.values()
                     if (e.get("data_quality") or {}).get("scan_stale"))
    mismatch_days = sum(
        1 for e in entries.values()
        for i in (e.get("checklist") or {}).get("during_market", [])
        if i.get("item") == "No cross-page mismatches" and i.get("status") == "WARNING")

    issues = nb.list_issues()
    open_critical = issues["open_critical"]
    last_critical_date = None
    for i in issues["issues"]:
        if i["severity"] == "CRITICAL":
            last_critical_date = max(last_critical_date or i["date"], i["date"])
    days_since_critical = (
        (market_hours.now_ist().date() - date.fromisoformat(last_critical_date)).days
        if last_critical_date else "No critical issues recorded")

    sessions = len(entries)
    trades = len(closed)

    def _pct(value: float, target: Any, cap: bool = False) -> float:
        try:
            target = float(target)
        except (TypeError, ValueError):
            return 0.0
        if target <= 0:
            return 0.0
        pct = 100 * value / target
        return round(min(100.0, pct) if cap else pct, 1)

    progress = {
        "trading_sessions": {"value": sessions, "target": targets["trading_sessions"],
                             "pct": _pct(sessions, targets["trading_sessions"])},
        "completed_paper_trades": {"value": trades, "target": targets["completed_paper_trades"],
                                   "pct": _pct(trades, targets["completed_paper_trades"])},
        "market_regimes_covered": {"value": len(regimes), "target": targets["market_regimes"],
                                   "regimes": sorted(regimes),
                                   "pct": _pct(len(regimes), targets["market_regimes"], cap=True)},
        "unresolved_critical_issues": {"value": open_critical,
                                       "target": targets["max_unresolved_critical_issues"],
                                       "ok": open_critical <= targets["max_unresolved_critical_issues"]},
    }
    return {
        "success": True,
        "trading_sessions_completed": sessions,
        "completed_paper_trades": trades,
        "minimum_target_trades": targets["completed_paper_trades"],
        "market_regimes_covered": sorted(regimes),
        "strategy_sample_sizes": dict(strat_counts),
        "sector_sample_sizes": dict(sector_counts),
        "confidence_band_sample_sizes": band_counts,
        "successful_validation_runs": ok_runs,
        "critical_qa_failures": crit_fails,
        "stale_data_incidents": stale_days,
        "cross_page_mismatch_days": mismatch_days,
        "days_since_last_critical_issue": days_since_critical,
        "targets": targets,
        "progress": progress,
        "readiness_note": ("Evidence targets are advisory and configurable. "
                           "Meeting them never triggers automatic live deployment."),
        "label": LABEL,
    }
