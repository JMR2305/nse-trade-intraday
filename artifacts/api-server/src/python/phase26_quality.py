"""
phase26_quality.py — Phase 26C: trading-quality validation.

Builds the per-session trading funnel and quality statistics purely from
canonical stores — NO business logic is recalculated here:

* Funnel — scanned → analysed → risk approved/rejected → BUY/SELL/WATCH
  signals → executed trades, counted from the pipeline event store
  (stage_summary + per-event-type counts) and the phase20 ledger (fill-based,
  same predicate the Phase 26B consistency validator uses).
* Quality stats — win rate, profit factor, expectancy, average holding time
  from the paper-analytics shared services (FIFO matching REUSED, never
  re-implemented). These are ALL-TIME PORTFOLIO statistics (the analytics
  snapshot covers every closed trade), reported alongside the latest-scan
  funnel — the scope field makes this explicit so the two are never
  conflated.
* Missed opportunities — advisory view of WATCH_GENERATED and RISK_REJECTED
  signals for the session (symbols and counts only; no hypothetical P&L is
  fabricated).

Evidence rule: with fewer than MIN_EVIDENCE closed trades the quality-stats
section reports INSUFFICIENT_EVIDENCE — the numbers are shown as evidence
but never graded (no extrapolation from tiny samples).

Structural checks feed the Phase 26 issue store (category QUALITY):
executed trades exceeding generated BUY signals is a CRITICAL funnel
violation (conservation break).

Results persist append-only via phase26c_store.

READ-ONLY / ADVISORY-ONLY. PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MIN_EVIDENCE = 5          # closed trades needed before stats are graded

SIGNAL_EVENT_TYPES = ("BUY_GENERATED", "SELL_GENERATED", "WATCH_GENERATED",
                      "IGNORE_GENERATED")
MISSED_EVENT_TYPES = ("WATCH_GENERATED", "RISK_REJECTED")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _is_executed(row: Dict[str, Any]) -> bool:
    """Fill-based executed predicate — identical semantics to the Phase 26B
    consistency validator / replay ledger contract."""
    try:
        if row.get("fill_price") is not None and float(row["fill_price"]) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return bool(row.get("fill_ts"))


# ── Input collection (live) ─────────────────────────────────────────────────

def collect_quality_inputs() -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    def _try(name, fn):
        try:
            out[name] = fn()
        except Exception as exc:
            out[name] = None
            out.setdefault("_errors", {})[name] = str(exc)[:200]

    def _scan_id():
        import scan_state_store
        meta = scan_state_store.load_latest_meta() or {}
        return meta.get("scan_id")

    _try("scan_id", _scan_id)
    scan_id = out.get("scan_id")

    def _stage_summary():
        if not scan_id:
            return None
        from pipeline_events import stage_summary
        return stage_summary(scan_id=scan_id)

    def _signal_events():
        if not scan_id:
            return None
        from pipeline_events import query_events
        evs: List[Dict[str, Any]] = []
        for et in set(SIGNAL_EVENT_TYPES) | set(MISSED_EVENT_TYPES):
            evs.extend(query_events(scan_id=scan_id, event_type=et,
                                    limit=2000))
        return evs

    def _ledger_rows():
        import phase20_executor as p20
        return p20.get_ledger(limit=10_000)

    def _analytics():
        from paper_analytics.shared_services import (
            get_paper_analytics_snapshot)
        return get_paper_analytics_snapshot()

    _try("stage_summary", _stage_summary)
    _try("signal_events", _signal_events)
    _try("ledger_rows", _ledger_rows)
    _try("analytics", _analytics)
    return out


# ── Report builder (pure, injectable) ────────────────────────────────────────

def _stage_counts(stage_summary: Optional[Dict[str, Any]],
                  stage: str) -> Dict[str, int]:
    for s in (stage_summary or {}).get("stages") or []:
        if s.get("stage") == stage:
            return {"completed": int(s.get("completed") or 0),
                    "rejected": int(s.get("rejected") or 0)}
    return {"completed": 0, "rejected": 0}


def build_quality_report(inputs: Dict[str, Any]) -> Dict[str, Any]:
    scan_id = inputs.get("scan_id")
    summary = inputs.get("stage_summary")
    events = inputs.get("signal_events")
    ledger = inputs.get("ledger_rows")
    analytics = inputs.get("analytics")

    report: Dict[str, Any] = {
        "area": "QUALITY",
        "generated_at": _now_iso(),
        "scan_id": scan_id,
        "advisory_only": True,
    }
    issues: List[tuple] = []

    # ── Funnel (event-derived; None sections stay None — never fabricated)
    funnel: Optional[Dict[str, Any]] = None
    if summary is not None and events is not None:
        by_type: Dict[str, int] = {}
        symbols_by_type: Dict[str, List[str]] = {}
        for e in events:
            et = str(e.get("event_type") or "")
            by_type[et] = by_type.get(et, 0) + 1
            if e.get("symbol"):
                symbols_by_type.setdefault(et, []).append(str(e["symbol"]))
        scanner = _stage_counts(summary, "SCANNER")
        research = _stage_counts(summary, "RESEARCH")
        risk = _stage_counts(summary, "RISK")
        executed_rows = [r for r in ledger or []
                         if r.get("scan_id") == scan_id and _is_executed(r)] \
            if ledger is not None else None
        funnel = {
            "scanned": scanner["completed"],
            "scan_rejected": scanner["rejected"],
            "analysed": research["completed"],
            "risk_approved": risk["completed"],
            "risk_rejected": risk["rejected"],
            "signals": {
                "buy": by_type.get("BUY_GENERATED", 0),
                "sell": by_type.get("SELL_GENERATED", 0),
                "watch": by_type.get("WATCH_GENERATED", 0),
                "ignore": by_type.get("IGNORE_GENERATED", 0),
            },
            "executed_trades": (len(executed_rows)
                                if executed_rows is not None else None),
        }
        # Conservation: executed trades can never exceed generated BUYs.
        if executed_rows is not None and \
                len(executed_rows) > funnel["signals"]["buy"]:
            issues.append((
                f"funnel_conservation:{scan_id}",
                f"{len(executed_rows)} executed trades exceed "
                f"{funnel['signals']['buy']} BUY signals for scan "
                f"{scan_id} — funnel conservation broken"))
        # Missed opportunities: advisory-only symbol view.
        missed = []
        for et in MISSED_EVENT_TYPES:
            for sym in sorted(set(symbols_by_type.get(et, []))):
                missed.append({"symbol": sym, "reason": et})
        funnel["missed_opportunities"] = missed[:100]
        funnel["missed_count"] = len(missed)
    report["funnel"] = funnel
    report["funnel_available"] = funnel is not None

    # ── Quality stats (reused from paper-analytics; FIFO matching inside)
    stats: Dict[str, Any] = {"available": False}
    evidence_verdict = "INSUFFICIENT_EVIDENCE"
    if isinstance(analytics, dict) and analytics.get("available"):
        n = int(analytics.get("total_trades") or 0)
        avg_hold = analytics.get("avg_hold_seconds")
        if avg_hold is None:                     # tolerate legacy key
            avg_hold = analytics.get("avg_holding_seconds")
        stats = {
            "available": True,
            # All-time portfolio analytics (every closed trade), NOT scoped
            # to the funnel's scan/session above.
            "scope": "all_time_portfolio",
            "total_trades": n,
            "win_rate": analytics.get("win_rate"),
            "profit_factor": analytics.get("profit_factor"),
            "expectancy": analytics.get("expectancy"),
            "total_pnl": analytics.get("total_pnl"),
            "avg_hold_seconds": avg_hold,
            "min_evidence": MIN_EVIDENCE,
        }
        if n >= MIN_EVIDENCE:
            evidence_verdict = "SUFFICIENT"
        else:
            stats["note"] = (f"Only {n} closed trades (< {MIN_EVIDENCE}) — "
                             "statistics reported as evidence only, not "
                             "graded (no extrapolation)")
    report["quality_stats"] = stats
    report["evidence"] = evidence_verdict

    # ── Verdict fold
    if issues:
        verdict = "FAIL"
    elif funnel is None or not stats.get("available"):
        verdict = "INSUFFICIENT"
    elif evidence_verdict == "INSUFFICIENT_EVIDENCE":
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "PASS"
    report["verdict"] = verdict
    # Structural funnel checks were only evaluable when funnel data existed.
    report["fully_evaluated"] = funnel is not None and \
        funnel.get("executed_trades") is not None
    report["_issues"] = issues
    return report


def run_quality_validation(persist: bool = True,
                           inputs: Optional[Dict[str, Any]] = None
                           ) -> Dict[str, Any]:
    if inputs is None:
        inputs = collect_quality_inputs()
    report = build_quality_report(inputs)
    issues = report.pop("_issues", [])
    try:
        from phase26_recovery import _feed_issues
        _feed_issues(report, category="QUALITY", items=issues)
    except Exception as exc:
        report["issue_reconcile"] = {"error": str(exc)[:200]}
    if persist:
        try:
            import phase26c_store as store
            stored = store.append_result(report["area"], report)
            report["result_id"] = stored.get("result_id")
            store.prune_results()   # bounded retention; never raises
        except Exception as exc:
            report["persist_error"] = str(exc)[:200]
    return report
