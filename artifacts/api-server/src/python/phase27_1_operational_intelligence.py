"""
phase27_1_operational_intelligence.py — Phase 27.1: Operational Intelligence
Refinements.

STRICTLY READ-ONLY composition over the existing canonical stores:
  * Readiness store (phase27_readiness KV history + build_report)
  * Pipeline Event Store (pipeline_events.stage_summary)
  * Replay Store (replay_engine.get_replay_sessions)
  * Portfolio Store (canonical_portfolio.canonical_trades, phase20 ledger)
  * Operator Analytics (phase27_operator_analytics for timing/trends)

No trading logic, no strategy logic, no new probes, no duplicate
calculations — every number is a fold/regrouping of a canonical value, and
every unavailable source is surfaced as UNKNOWN/unavailable, never zeroed.

Sections (all in one report):
  1. Session readiness timeline   — transitions from the readiness history.
  2. Readiness history statistics — 7/30/90-day windows over the same log.
  3. Pre-market operator checklist — mapped from the readiness report +
     pipeline stage summary (PASS/WARNING/FAIL + remediation).
  4. Session comparison            — today / yesterday / previous trading
     day from replay sessions + canonical trades.
  5. Operator insights             — advisory deltas from (4) + readiness.
  6. Pipeline health score         — presentation fold of canonical
     statuses (READY=100, WARNING=60, UNKNOWN=40, BLOCKED=0).
  7. Investigation shortcuts       — link metadata for the frontend.
  8. Executive summary             — one-page composition of the above.

PAPER TRADING / RESEARCH ONLY. Advisory only.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

IST = timezone(timedelta(hours=5, minutes=30))

STATUS_SCORE = {"READY": 100, "WARNING": 60, "UNKNOWN": 40, "BLOCKED": 0}

# Where an operator investigates each kind of problem (Part 7) — frontend
# link metadata only; no logic.
SHORTCUTS = [
    {"id": "investigation", "label": "Open Investigation", "href": "/investigation"},
    {"id": "replay", "label": "Open Replay", "href": "/replay"},
    {"id": "explainability", "label": "Open Explainability", "href": "/explainability"},
    {"id": "strategy_optimization", "label": "Open Strategy Optimization", "href": "/strategy-optimization"},
    {"id": "mission_control", "label": "Open Mission Control", "href": "/mission-control"},
    {"id": "operator_analytics", "label": "Open Operator Analytics", "href": "/operator-analytics"},
]


def _stages_by_name(stage_summary: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """pipeline_events.stage_summary returns `stages` as a LIST of dicts
    keyed by their `stage` field — normalise to a name→dict map (accepts a
    dict form too, for constructed test inputs)."""
    raw = (stage_summary or {}).get("stages")
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        return {str(s.get("stage")): s for s in raw if isinstance(s, dict)}
    return {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _ist_date(value: Any) -> Optional[str]:
    ts = _parse_ts(value)
    return ts.astimezone(IST).date().isoformat() if ts else None


def _state(available: bool, error: Optional[str] = None) -> Dict[str, Any]:
    return {"available": available, "error": (error or None) and str(error)[:200]}


# ── Canonical source loaders (fail-soft, availability recorded) ─────────────

def _load_history() -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        from phase27_readiness import get_history
        h = get_history(limit=500)
        entries = list(h.get("entries") or [])
        entries.reverse()  # chronological
        return entries, _state(True, h.get("error"))
    except Exception as exc:
        return [], _state(False, exc)


def _load_readiness_report() -> "tuple[Optional[Dict[str, Any]], Dict[str, Any]]":
    try:
        from phase27_readiness import build_report
        return build_report(), _state(True)
    except Exception as exc:
        return None, _state(False, exc)


def _load_sessions() -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        from replay_engine import get_replay_sessions
        raw = list((get_replay_sessions() or {}).get("sessions") or [])
        real = [s for s in raw
                if s.get("source") != "demo" and s.get("scan_id") != "demo"]
        return real, _state(True)
    except Exception as exc:
        return [], _state(False, exc)


def _load_trades() -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        from canonical_portfolio import canonical_trades
        return list(canonical_trades(scope="all") or []), _state(True)
    except Exception as exc:
        return [], _state(False, exc)


def _load_stage_summary(scan_id: Optional[str]
                        ) -> "tuple[Optional[Dict[str, Any]], Dict[str, Any]]":
    if not scan_id:
        return None, _state(False, "no scan_id")
    try:
        import pipeline_events
        return pipeline_events.stage_summary(scan_id=scan_id), _state(True)
    except Exception as exc:
        return None, _state(False, exc)


# ── Part 1: Session readiness timeline ───────────────────────────────────────

def build_timeline(entries: List[Dict[str, Any]],
                   now: Optional[datetime] = None) -> Dict[str, Any]:
    """Transitions between consecutive readiness evaluations, newest first.

    Recovery time = minutes from entering a non-READY state until the next
    READY evaluation (None while unresolved)."""
    now = now or _now()
    events: List[Dict[str, Any]] = []
    prev: Optional[str] = None
    for i, e in enumerate(entries):
        cur = str(e.get("overall") or "UNKNOWN")
        if cur == prev:
            continue
        issues = list(e.get("issues") or [])
        recovery_min = None
        if cur != "READY":
            for later in entries[i + 1:]:
                if str(later.get("overall")) == "READY":
                    a, b = _parse_ts(e.get("at")), _parse_ts(later.get("at"))
                    if a and b:
                        recovery_min = round((b - a).total_seconds() / 60, 1)
                    break
        events.append({
            "at": e.get("at"),
            "from": prev,
            "to": cur,
            "reason": (issues[0].get("actual") if issues
                       else ("all checks READY" if cur == "READY"
                             else "no issue detail recorded")),
            "components": sorted({i.get("domain") for i in issues
                                  if i.get("domain")}),
            "issues": issues,
            "recovery_minutes": recovery_min,
            "operator_action": (
                "" if cur == "READY" else
                "Open System Readiness for per-check remediation"),
        })
        prev = cur
    today = now.astimezone(IST).date().isoformat()
    session_events = [ev for ev in events if _ist_date(ev["at"]) == today]
    return {
        "current_status": entries[-1].get("overall") if entries else "UNKNOWN",
        "session_date": today,
        "session_events": list(reversed(session_events)),
        "events": list(reversed(events))[:100],
        "evaluations_recorded": len(entries),
    }


# ── Part 2: Readiness history statistics ─────────────────────────────────────

def build_history_stats(entries: List[Dict[str, Any]],
                        now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    windows = {}
    for days in (7, 30, 90):
        cutoff = now - timedelta(days=days)
        rows = [e for e in entries
                if (_parse_ts(e.get("at")) or now) >= cutoff]
        counts = Counter(str(e.get("overall") or "UNKNOWN") for e in rows)
        scores = [STATUS_SCORE.get(str(e.get("overall")), 40) for e in rows]
        # longest consecutive READY streak (in evaluations)
        streak = best = 0
        for e in rows:
            streak = streak + 1 if str(e.get("overall")) == "READY" else 0
            best = max(best, streak)
        failures = Counter(f for e in rows
                           for f in (e.get("blocking_failures") or []))
        # recovery times from non-READY entry → next READY
        recoveries: List[float] = []
        for i, e in enumerate(rows):
            if str(e.get("overall")) in ("BLOCKED", "UNKNOWN", "WARNING") and \
                    (i == 0 or str(rows[i - 1].get("overall")) == "READY"):
                for later in rows[i + 1:]:
                    if str(later.get("overall")) == "READY":
                        a, b = _parse_ts(e.get("at")), _parse_ts(later.get("at"))
                        if a and b:
                            recoveries.append((b - a).total_seconds() / 60)
                        break
        # per-IST-day trend of average score, for the chart
        by_day: Dict[str, List[int]] = {}
        for e in rows:
            d = _ist_date(e.get("at"))
            if d:
                by_day.setdefault(d, []).append(
                    STATUS_SCORE.get(str(e.get("overall")), 40))
        trend = [{"date": d, "avg_score": round(sum(v) / len(v), 1),
                  "evaluations": len(v)}
                 for d, v in sorted(by_day.items())]
        windows[f"{days}d"] = {
            "evaluations": len(rows),
            "ready": counts.get("READY", 0),
            "warning": counts.get("WARNING", 0),
            "blocked": counts.get("BLOCKED", 0),
            "unknown": counts.get("UNKNOWN", 0),
            "avg_readiness_score": (round(sum(scores) / len(scores), 1)
                                    if scores else None),
            "longest_ready_streak": best,
            "most_common_failure": (failures.most_common(1)[0][0]
                                    if failures else None),
            "avg_recovery_minutes": (round(sum(recoveries) / len(recoveries), 1)
                                     if recoveries else None),
            "trend": trend,
            "insufficient_data": len(rows) < 5,
        }
    return windows


# ── Part 3: Pre-market operator checklist ────────────────────────────────────

# checklist item → readiness check ids (canonical) and/or pipeline stage
CHECKLIST_MAP: List[Dict[str, Any]] = [
    {"item": "Market Data", "checks": ["scan_freshness", "provider_coverage"]},
    {"item": "Scanner", "checks": ["last_scan_outcome"], "stage": "SCANNER"},
    {"item": "Research", "stage": "RESEARCH"},
    {"item": "Market Intelligence", "stage": "MARKET_INTELLIGENCE"},
    {"item": "Risk Engine", "checks": ["risk_config"], "stage": "RISK"},
    {"item": "Portfolio", "checks": ["portfolio_health"], "stage": "PORTFOLIO"},
    {"item": "Replay", "checks": ["pipeline_events"]},
    {"item": "Mission Control", "checks": ["pipeline_events"]},
    {"item": "Learning Engine", "checks": ["db_durability"], "stage": "AI_DECISION"},
    {"item": "Paper Mode", "checks": ["execution_mode"]},
    {"item": "Broker Session", "checks": ["broker_session"]},
    {"item": "Scheduler", "checks": ["scheduler_health"]},
    {"item": "Background Workers", "checks": ["scheduler_health", "system_resources"]},
]

_STATUS_TO_CHECKLIST = {"READY": "PASS", "WARNING": "WARNING",
                        "BLOCKED": "FAIL", "UNKNOWN": "WARNING"}


def build_checklist(readiness: Optional[Dict[str, Any]],
                    stage_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    checks_by_id: Dict[str, Dict[str, Any]] = {}
    for d in (readiness or {}).get("domains") or []:
        for c in d.get("checks") or []:
            checks_by_id[c["id"]] = c
    stages = _stages_by_name(stage_summary)
    items: List[Dict[str, Any]] = []
    for spec in CHECKLIST_MAP:
        mapped = [checks_by_id[i] for i in spec.get("checks", [])
                  if i in checks_by_id]
        detail: List[str] = []
        statuses: List[str] = []
        remediation = ""
        for c in mapped:
            statuses.append(_STATUS_TO_CHECKLIST.get(c["status"], "WARNING"))
            detail.append(f"{c['label']}: {c['actual']}")
            if c.get("remediation") and not remediation:
                remediation = c["remediation"]
        stage_name = spec.get("stage")
        if stage_name and isinstance(stages, dict):
            st = stages.get(stage_name)
            if isinstance(st, dict):
                ev, errs = int(st.get("events") or 0), int(st.get("errors") or 0)
                if errs > 0:
                    statuses.append("WARNING")
                    detail.append(f"{stage_name}: {errs} errors in last scan")
                    remediation = remediation or \
                        "Open Investigation for the failing stage events."
                elif ev > 0:
                    statuses.append("PASS")
                    detail.append(f"{stage_name}: {ev} events last scan")
                else:
                    statuses.append("WARNING")
                    detail.append(f"{stage_name}: no events in last scan")
                    remediation = remediation or \
                        "Run a fresh scan to exercise this stage."
        if not statuses:
            statuses = ["WARNING"]
            detail = ["no canonical evidence available"]
            remediation = "Source unavailable — investigate on System Readiness."
        status = ("FAIL" if "FAIL" in statuses
                  else "WARNING" if "WARNING" in statuses else "PASS")
        items.append({"item": spec["item"], "status": status,
                      "detail": detail, "remediation": remediation
                      if status != "PASS" else ""})
    counts = Counter(i["status"] for i in items)
    return {"items": items,
            "counts": {"PASS": counts.get("PASS", 0),
                       "WARNING": counts.get("WARNING", 0),
                       "FAIL": counts.get("FAIL", 0)},
            "overall": ("FAIL" if counts.get("FAIL") else
                        "WARNING" if counts.get("WARNING") else "PASS")}


# ── Part 4: Session comparison ───────────────────────────────────────────────

def build_session_comparison(sessions: List[Dict[str, Any]],
                             trades: List[Dict[str, Any]],
                             now: Optional[datetime] = None,
                             stage_summary: Optional[Dict[str, Any]] = None,
                             ) -> Dict[str, Any]:
    """Group canonical replay sessions + ledger fills by IST day.

    Labels are derived from the ACTUAL IST calendar relation to today —
    a historical day is never mislabelled "today". A today row is always
    present (all-None when no session ran today). Risk rejections /
    execution success / pipeline latency come from the canonical
    stage_summary and only for the day owning the latest scan. Missing
    values stay None — never fabricated."""
    now = now or _now()
    by_day: Dict[str, Dict[str, Any]] = {}
    for s in sessions:
        d = _ist_date(s.get("snapshot_ts"))
        if not d:
            continue
        day = by_day.setdefault(d, {"date": d, "scans": 0})
        day["scans"] += 1
        # prefer the richest (latest scan_state) row for the day
        if s.get("universe_size") is not None and "stocks_scanned" not in day:
            day["stocks_scanned"] = s.get("symbols_processed")
            day["universe_size"] = s.get("universe_size")
            day["signals"] = s.get("buy_signals")
            day["paper_orders"] = s.get("paper_orders")
            day["scan_duration_s"] = s.get("duration_s")
            day["scan_id"] = s.get("scan_id")
    for t in trades:
        d = _ist_date(t.get("timestamp"))
        if not d:
            continue
        day = by_day.setdefault(d, {"date": d, "scans": 0})
        day.setdefault("trades", 0)
        day["trades"] += 1
        if t.get("action") == "SELL":
            pnl = t.get("realized_pnl")
            if isinstance(pnl, (int, float)):
                day.setdefault("closed", 0)
                day.setdefault("wins", 0)
                day.setdefault("pnl", 0.0)
                day["closed"] += 1
                day["wins"] += 1 if pnl > 0 else 0
                day["pnl"] = round(day["pnl"] + float(pnl), 2)
    today_d = now.astimezone(IST).date()
    today = today_d.isoformat()
    yesterday = (today_d - timedelta(days=1)).isoformat()
    # today row always present (even empty); then the two most recent PRIOR
    # observed days — never relabelled as today.
    prior = sorted((d for d in by_day.values() if d["date"] < today),
                   key=lambda x: x["date"], reverse=True)[:2]
    days = [by_day.get(today, {"date": today, "scans": 0})] + prior

    # Canonical stage metrics for the latest scan only (per-day history of
    # rejections/latency is not stored — reported None, never estimated).
    latest_metrics: Dict[str, Any] = {}
    latest_scan_id = (stage_summary or {}).get("scan_id")
    stages = _stages_by_name(stage_summary)
    if stages:
        risk = stages.get("RISK") or {}
        exec_ = stages.get("EXECUTION") or {}
        ev = int(exec_.get("events") or 0)
        latest_metrics = {
            "risk_rejections": int(risk.get("rejected") or 0)
            if risk.get("events") else None,
            "execution_success_pct": (
                round(100.0 * int(exec_.get("completed") or 0) / ev, 1)
                if ev else None),
            "pipeline_latency_ms": exec_.get("avg_symbol_ms"),
        }

    rows = []
    for day in days:
        closed = day.get("closed") or 0
        d = day["date"]
        label = ("today" if d == today
                 else "yesterday" if d == yesterday
                 else f"previous session ({d})")
        owns_latest = bool(latest_scan_id and
                           day.get("scan_id") == latest_scan_id)
        rows.append({
            "label": label,
            "is_today": d == today,
            "date": d,
            "scan_id": day.get("scan_id"),
            "stocks_scanned": day.get("stocks_scanned"),
            "signals": day.get("signals"),
            "trades": day.get("trades", 0),
            "win_rate_pct": (round(100.0 * (day.get("wins") or 0) / closed, 1)
                             if closed else None),
            "pnl": day.get("pnl"),
            "portfolio_growth": day.get("pnl"),  # realized PnL for the day
            "paper_orders": day.get("paper_orders"),
            "scan_duration_s": day.get("scan_duration_s"),
            "risk_rejections": (latest_metrics.get("risk_rejections")
                                if owns_latest else None),
            "execution_success_pct": (latest_metrics.get("execution_success_pct")
                                      if owns_latest else None),
            "pipeline_latency_ms": (latest_metrics.get("pipeline_latency_ms")
                                    if owns_latest else None),
        })
    return {"days": rows,
            "note": ("Labels reflect actual IST dates; older sessions carry "
                     "limited metadata (historical snapshots) — missing "
                     "values shown as em-dash, never estimated.")}


# ── Part 5: Operator insights (advisory only) ───────────────────────────────

def build_insights(comparison: Dict[str, Any],
                   readiness: Optional[Dict[str, Any]],
                   history_stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []
    days = comparison.get("days") or []

    def pct_delta(a, b):
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) \
                or b == 0:
            return None
        return round(100.0 * (a - b) / abs(b), 1)

    if len(days) >= 2:
        cur, prev = days[0], days[1]
        for field, label_up, label_down in (
            ("stocks_scanned", "Scanner processed %s%% more stocks",
             "Scanner processed %s%% fewer stocks"),
            ("signals", "Signal count up %s%% vs previous session",
             "Signal count down %s%% vs previous session"),
            ("trades", "Trade activity up %s%%", "Trade activity down %s%%"),
        ):
            d = pct_delta(cur.get(field), prev.get(field))
            if d is not None and abs(d) >= 10:
                insights.append({
                    "kind": "comparison", "severity": "INFO",
                    "text": (label_up if d > 0 else label_down)
                            % abs(d)})
        c_pnl, p_pnl = cur.get("pnl"), prev.get("pnl")
        if isinstance(c_pnl, (int, float)) and isinstance(p_pnl, (int, float)):
            insights.append({
                "kind": "comparison", "severity": "INFO",
                "text": f"Realized PnL {'improved' if c_pnl >= p_pnl else 'declined'}"
                        f" vs previous session ({c_pnl:+.0f} vs {p_pnl:+.0f})"})
        d = pct_delta(cur.get("scan_duration_s"), prev.get("scan_duration_s"))
        if d is not None and abs(d) >= 15:
            insights.append({
                "kind": "comparison", "severity": "INFO",
                "text": f"Pipeline latency {'increased' if d > 0 else 'improved'}"
                        f" {abs(d)}% vs previous session"})
    w7 = history_stats.get("7d") or {}
    if w7.get("most_common_failure"):
        insights.append({
            "kind": "readiness", "severity": "WARNING",
            "text": f"Most frequent blocking issue this week: "
                    f"{w7['most_common_failure']}"})
    if readiness:
        blocked = [c for d in readiness.get("domains") or []
                   for c in d.get("checks") or []
                   if c.get("status") == "BLOCKED"]
        for c in blocked[:3]:
            insights.append({"kind": "readiness", "severity": "CRITICAL",
                             "text": f"{c['label']} is BLOCKED — {c['actual']}"})
    if not insights:
        insights.append({"kind": "none", "severity": "INFO",
                         "text": "No notable operational deltas detected."})
    for i in insights:
        i["advisory_only"] = True
    return insights


# ── Part 6: Pipeline health score ────────────────────────────────────────────

HEALTH_COMPONENTS = [
    ("Scanner", "SCANNER"), ("Research", "RESEARCH"),
    ("Market Intelligence", "MARKET_INTELLIGENCE"),
    ("Monitoring", "MONITORING"), ("Strategy", "STRATEGY"),
    ("Risk", "RISK"), ("Decision", "AI_DECISION"),
    ("Execution", "EXECUTION"), ("Portfolio", "PORTFOLIO"),
]


def build_health_score(readiness: Optional[Dict[str, Any]],
                       stage_summary: Optional[Dict[str, Any]],
                       entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    components: List[Dict[str, Any]] = []
    # Domain components — direct presentation fold of readiness statuses.
    for d in (readiness or {}).get("domains") or []:
        components.append({"component": d["domain"], "kind": "readiness",
                           "status": d["status"],
                           "score": STATUS_SCORE.get(d["status"], 40)})
    # Pipeline stage components from the canonical stage summary.
    stages = _stages_by_name(stage_summary)
    for label, stage in HEALTH_COMPONENTS:
        st = stages.get(stage)
        if isinstance(st, dict):
            ev, errs = int(st.get("events") or 0), int(st.get("errors") or 0)
            if ev <= 0:
                status = "UNKNOWN"
            elif errs > 0:
                status = "WARNING"
            else:
                status = "READY"
            components.append({"component": label, "kind": "stage",
                               "stage": stage, "status": status,
                               "score": STATUS_SCORE.get(status, 40),
                               "events": ev, "errors": errs})
        else:
            # Missing evidence must drag the composite down as UNKNOWN,
            # never be silently omitted (which would inflate the score).
            components.append({"component": label, "kind": "stage",
                               "stage": stage, "status": "UNKNOWN",
                               "score": STATUS_SCORE["UNKNOWN"],
                               "events": None, "errors": None})
    overall = (round(sum(c["score"] for c in components) / len(components), 1)
               if components else None)
    # Trend from history scores (same fold as history stats)
    hist = [{"at": e.get("at"),
             "score": STATUS_SCORE.get(str(e.get("overall")), 40)}
            for e in entries][-60:]
    trend = None
    if len(hist) >= 4:
        half = len(hist) // 2
        a = sum(h["score"] for h in hist[:half]) / half
        b = sum(h["score"] for h in hist[half:]) / (len(hist) - half)
        trend = "IMPROVING" if b > a + 2 else \
                "DECLINING" if b < a - 2 else "STABLE"
    return {"overall_score": overall, "trend": trend,
            "components": components, "history": hist,
            "score_legend": STATUS_SCORE}


# ── Part 8: Executive summary ────────────────────────────────────────────────

def build_executive_summary(readiness: Optional[Dict[str, Any]],
                            checklist: Dict[str, Any],
                            health: Dict[str, Any],
                            insights: List[Dict[str, Any]],
                            comparison: Dict[str, Any]) -> Dict[str, Any]:
    def domain_status(name: str) -> str:
        for d in (readiness or {}).get("domains") or []:
            if d["domain"] == name:
                return d["status"]
        return "UNKNOWN"

    outstanding = [
        {"check": c["label"], "domain": d["domain"], "status": c["status"],
         "blocking": c["blocking"], "remediation": c["remediation"]}
        for d in (readiness or {}).get("domains") or []
        for c in d.get("checks") or []
        if c.get("status") in ("BLOCKED", "UNKNOWN")
        or (c.get("status") == "WARNING" and c.get("blocking"))]
    today = next((r for r in comparison.get("days") or [] if r.get("is_today")),
                 None)
    return {
        "readiness": (readiness or {}).get("overall", "UNKNOWN"),
        "ai_health": domain_status("Pipeline"),
        "trading_health": domain_status("Execution"),
        "portfolio_health": domain_status("Portfolio"),
        "system_health": domain_status("Configuration"),
        "pipeline_health_score": health.get("overall_score"),
        "checklist": checklist.get("counts"),
        "today": today,
        "operator_alerts": [i for i in insights
                            if i.get("severity") in ("WARNING", "CRITICAL")],
        "recommendations": [i["text"] for i in insights
                            if i.get("severity") != "CRITICAL"][:5],
        "outstanding_issues": outstanding[:10],
    }


# ── Entry point ──────────────────────────────────────────────────────────────

def operational_intelligence_report() -> Dict[str, Any]:
    now = _now()
    entries, hist_state = _load_history()
    readiness, readiness_state = _load_readiness_report()
    sessions, sessions_state = _load_sessions()
    trades, trades_state = _load_trades()
    latest_scan_id = next((s.get("scan_id") for s in sessions
                           if s.get("is_latest")), None) or \
        (sessions[0].get("scan_id") if sessions else None)
    stage_summary, stage_state = _load_stage_summary(latest_scan_id)

    timeline = build_timeline(entries, now)
    history_stats = build_history_stats(entries, now)
    checklist = build_checklist(readiness, stage_summary)
    comparison = build_session_comparison(sessions, trades, now,
                                          stage_summary=stage_summary)
    insights = build_insights(comparison, readiness, history_stats)
    health = build_health_score(readiness, stage_summary, entries)
    executive = build_executive_summary(readiness, checklist, health,
                                        insights, comparison)

    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "timeline": timeline,
        "history_stats": history_stats,
        "checklist": checklist,
        "session_comparison": comparison,
        "insights": insights,
        "health_score": health,
        "executive_summary": executive,
        "shortcuts": SHORTCUTS,
        "sources": {
            "readiness_history": hist_state,
            "readiness_report": readiness_state,
            "replay_sessions": sessions_state,
            "canonical_trades": trades_state,
            "stage_summary": stage_state,
        },
        "read_only": True,
        "advisory_only": True,
        "paper_trading_only": True,
        "note": ("Phase 27.1 — read-only composition of canonical stores; "
                 "no trading or strategy logic; unavailable sources are "
                 "surfaced, never zeroed. PAPER TRADING / RESEARCH ONLY."),
    }
