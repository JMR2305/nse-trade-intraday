"""
phase26_live_monitor.py — Phase 26B: live subsystem-liveness validation.

Every 5 minutes during NSE sessions (hooked into the phase20 scheduler tick,
KV-guarded so exactly one snapshot per 5-minute bucket across processes),
judge each pipeline subsystem's liveness from CANONICAL store timestamps —
never from any derived cache:

  scanner              — scan_state_store latest scan meta (today's session)
  research / market_intelligence / monitoring / strategy / risk / decision
                       — pipeline_events stage last-event timestamps for the
                         current scan (canonical event stream)
  execution / portfolio / pnl
                       — event-driven: only required to update when trades
                         actually happened this scan; otherwise IDLE (ok)
  mission_control      — any pipeline event for the current scan (the page
                         renders exclusively from the event stream)
  replay               — replay snapshot builds and matches the current scan
  learning             — every trade CLOSED this session has a phase24
                         learning record (30-minute grace after close)

Off-session behaviour is quiet by design: outside OPEN, the monitor reports
in_session=False, every subsystem OFF_SESSION, verdict PASS, and raises no
issues (IST calendar rules from market_hours are authoritative).

Detected anomalies are normalized into the phase26_live_store issue store
(dedup by category+key, lifecycle OPEN/RESOLVED with auto-resolve sweeps).

STRICTLY READ-ONLY over trading state. PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

LIVE_VALIDATION_INTERVAL_MIN = 5     # one snapshot per 5-minute bucket

# Subsystems judged from per-stage pipeline events (scan-driven: they MUST
# emit every scan cycle).
_STAGE_SUBSYSTEMS = {
    "research": "RESEARCH",
    "market_intelligence": "MARKET_INTELLIGENCE",
    "monitoring": "MONITORING",
    "strategy": "STRATEGY",
    "risk": "RISK",
    "decision": "AI_DECISION",
}

# Event-driven subsystems: required to update only when executions happened.
_EVENT_DRIVEN = ("execution", "portfolio", "pnl")

ACTIVE, IDLE, STALE, DOWN, OFF_SESSION, UNKNOWN = \
    "ACTIVE", "IDLE", "STALE", "DOWN", "OFF_SESSION", "UNKNOWN"

# Minutes after MARKET OPEN (09:15 IST) during which a missing first scan is
# expected, not an outage (the scheduler runs the first scan of the day on
# its own cadence). Judged as IDLE, never DOWN, inside this window.
_OPEN_GRACE_FACTOR = 2               # grace = 2 × scan interval past open

LEARNING_GRACE_S = 30 * 60           # learning record due 30 min after close

ADVISORY = ("Live subsystem validation over canonical stores. Nothing is "
            "modified. PAPER TRADING / RESEARCH ONLY.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _age_s(ts: Any, now: datetime) -> Optional[float]:
    dt = _parse_ts(ts)
    return (now - dt).total_seconds() if dt else None


# ── Input collection (every source injectable for tests) ────────────────────

def collect_inputs() -> Dict[str, Any]:
    """Gather live inputs from the canonical stores. Each source is
    fail-safe — a collection failure is recorded, never raised."""
    inputs: Dict[str, Any] = {"collection_errors": {}}

    def _try(name, fn, default=None):
        try:
            inputs[name] = fn()
        except Exception as exc:
            inputs[name] = default
            inputs["collection_errors"][name] = str(exc)[:200]

    def _market():
        import market_hours
        ms = market_hours.market_status()
        now = market_hours.now_ist()
        session_start = now.replace(
            hour=market_hours.PRE_OPEN_START.hour,
            minute=market_hours.PRE_OPEN_START.minute,
            second=0, microsecond=0)
        market_open = now.replace(
            hour=market_hours.MARKET_OPEN.hour,
            minute=market_hours.MARKET_OPEN.minute,
            second=0, microsecond=0)
        return {"state": str(ms.get("state") or "UNKNOWN").upper(),
                "session_start_utc":
                    session_start.astimezone(timezone.utc).isoformat(),
                "market_open_utc":
                    market_open.astimezone(timezone.utc).isoformat()}

    _try("market", _market, {"state": "UNKNOWN", "session_start_utc": None})

    def _interval():
        import phase20_store
        return int(phase20_store.get_settings()
                   .get("scan_interval_minutes", 5))
    _try("scan_interval_min", _interval, 5)

    def _scan_meta():
        import scan_state_store
        return scan_state_store.load_latest_meta() or {}
    _try("scan_meta", _scan_meta, {})

    scan_id = (inputs.get("scan_meta") or {}).get("scan_id")

    def _stage_events():
        from pipeline_events import stage_summary
        return stage_summary(scan_id=scan_id) if scan_id else {}
    _try("stage_events", _stage_events, {})

    def _exec_events():
        from pipeline_events import query_events
        return query_events(scan_id=scan_id, stage="EXECUTION",
                            limit=2000) if scan_id else []
    _try("execution_events", _exec_events, [])

    def _replay():
        from replay_engine import build_replay
        r = build_replay("latest") or {}
        return {"error": r.get("error"), "scan_id": r.get("scan_id"),
                "snapshot_ts": r.get("snapshot_ts")}
    _try("replay", _replay, {"error": "unavailable"})

    def _ledger():
        import phase20_executor as p20
        return p20.get_ledger(limit=10_000)
    _try("ledger_rows", _ledger, [])

    def _learning_ids():
        import phase24_store
        return [str(r.get("trade_id") or "")
                for r in phase24_store.list_trade_records(limit=500)]
    _try("learning_trade_ids", _learning_ids, [])

    return inputs


# ── Liveness snapshot ────────────────────────────────────────────────────────

def build_liveness_snapshot(inputs: Optional[Dict[str, Any]] = None,
                            now: Optional[datetime] = None) -> Dict[str, Any]:
    """Judge every subsystem's liveness from canonical timestamps.
    All logic is server-side; the browser applies no session rules."""
    if inputs is None:
        inputs = collect_inputs()
    now = now or datetime.now(timezone.utc)

    market = inputs.get("market") or {}
    state = str(market.get("state") or "UNKNOWN").upper()
    in_session = state == "OPEN"
    interval_min = max(1, int(inputs.get("scan_interval_min") or 5))
    stale_after_s = 2 * interval_min * 60
    down_after_s = 6 * interval_min * 60

    errs = inputs.get("collection_errors") or {}

    def unavailable(src: str) -> bool:
        return src in errs

    subsystems: Dict[str, Dict[str, Any]] = {}
    issues: List[Dict[str, Any]] = []

    def sub(name: str, status: str, detail: str,
            last_update: Any = None, age_s: Any = None) -> None:
        subsystems[name] = {
            "subsystem": name, "status": status, "detail": detail,
            "last_update": last_update,
            "age_s": round(age_s, 1) if isinstance(age_s, (int, float))
            else None,
        }
        if status in (STALE, DOWN):
            issues.append({
                "category": "SUBSYSTEM", "key": name,
                "severity": "CRITICAL" if status == DOWN else "WARNING",
                "title": f"{name} subsystem {status}",
                "detail": detail, "source": "live_monitor",
            })

    if not in_session:
        # Quiet off-session: no staleness judgements, no issues, no alarms.
        names = (["scanner"] + list(_STAGE_SUBSYSTEMS) + list(_EVENT_DRIVEN)
                 + ["mission_control", "replay", "learning"])
        for n in names:
            sub(n, OFF_SESSION, f"market state {state} — liveness not judged"
                " outside the session")
        return _finish(subsystems, issues, in_session, state, inputs, now)

    session_start = _parse_ts(market.get("session_start_utc"))
    market_open = _parse_ts(market.get("market_open_utc"))
    # Opening grace: right after 09:15 the first scan of the day may simply
    # not have run yet — expected, not an outage.
    in_open_grace = bool(
        market_open is not None and
        (now - market_open).total_seconds()
        < _OPEN_GRACE_FACTOR * interval_min * 60)

    # ── scanner: latest scan must exist, be from TODAY's session, and fresh ──
    meta = inputs.get("scan_meta") or {}
    scan_ts = meta.get("completed_at") or meta.get("snapshot_ts")
    scan_dt = _parse_ts(scan_ts)
    scan_age = _age_s(scan_ts, now)
    scan_id = meta.get("scan_id")
    no_today_scan = (not meta or scan_dt is None
                     or (session_start is not None
                         and scan_dt < session_start))
    if unavailable("scan_meta"):
        # Store could not be read — confirmed absence is NOT established.
        sub("scanner", UNKNOWN, "scan state store unavailable this cycle: "
            f"{errs.get('scan_meta')}", None, None)
    elif no_today_scan and in_open_grace:
        sub("scanner", IDLE, "awaiting the first scan of today's session "
            "(inside the market-open grace window)", scan_ts, scan_age)
    elif not meta or scan_dt is None:
        sub("scanner", DOWN, "no completed scan snapshot found during "
            "market hours", scan_ts, scan_age)
    elif session_start and scan_dt < session_start:
        sub("scanner", DOWN,
            f"latest scan {scan_id} predates today's session "
            f"({scan_ts}) — a previous-session scan never confirms today's "
            "pipeline", scan_ts, scan_age)
    elif scan_age is not None and scan_age > down_after_s:
        sub("scanner", DOWN, f"latest scan is {round(scan_age / 60)} min old "
            f"(interval {interval_min}m)", scan_ts, scan_age)
    elif scan_age is not None and scan_age > stale_after_s:
        sub("scanner", STALE, f"latest scan is {round(scan_age / 60)} min old"
            f" (interval {interval_min}m)", scan_ts, scan_age)
    else:
        sub("scanner", ACTIVE, f"scan {scan_id} fresh "
            f"({round((scan_age or 0) / 60, 1)} min old)", scan_ts, scan_age)

    scanner_status = subsystems["scanner"]["status"]
    scanner_ok = scanner_status == ACTIVE
    scanner_idle = scanner_status in (IDLE, UNKNOWN)

    # ── scan-driven stages: must have emitted events for the current scan ────
    stage_map = {str(s.get("stage") or "").upper(): s
                 for s in (inputs.get("stage_events") or {})
                 .get("stages") or []}
    stage_events_unavailable = unavailable("stage_events")
    for name, stage in _STAGE_SUBSYSTEMS.items():
        row = stage_map.get(stage) or {}
        events = int(row.get("events") or 0)
        last_ts = row.get("last_ts")
        age = _age_s(last_ts, now)
        if stage_events_unavailable:
            sub(name, UNKNOWN, "pipeline event store unavailable this "
                f"cycle: {errs.get('stage_events')}", None, None)
        elif scanner_idle and events == 0:
            sub(name, IDLE, f"no {stage} events yet — scanner is "
                f"{scanner_status} (awaiting/undetermined)", None, None)
        elif events == 0:
            if scanner_ok:
                sub(name, DOWN, f"no {stage} events for current scan "
                    f"{scan_id} — subsystem did not run", None, None)
            else:
                # Scanner itself is stale/down — root cause already flagged.
                sub(name, STALE, f"no {stage} events; scanner is "
                    f"{subsystems['scanner']['status']} (root cause)",
                    None, None)
        elif age is not None and age > down_after_s:
            sub(name, DOWN, f"last {stage} event {round(age / 60)} min old",
                last_ts, age)
        elif age is not None and age > stale_after_s:
            sub(name, STALE, f"last {stage} event {round(age / 60)} min old",
                last_ts, age)
        else:
            sub(name, ACTIVE, f"{events} events, last "
                f"{round((age or 0) / 60, 1)} min ago", last_ts, age)

    # ── event-driven: execution / portfolio / pnl ────────────────────────────
    exec_events = inputs.get("execution_events") or []
    # Only canonical P20- trade IDs count as real executions in the live monitor;
    # BTT-/replay events must not show as live paper executions.
    executed = [
        e for e in exec_events
        if e.get("event_type") == "ORDER_EXECUTED"
        and (
            not str((e.get("payload") or {}).get("trade_id") or "")
            or str((e.get("payload") or {}).get("trade_id") or "").startswith("P20-")
        )
    ]
    exec_row = stage_map.get("EXECUTION") or {}
    port_row = stage_map.get("PORTFOLIO") or {}
    if unavailable("execution_events") or stage_events_unavailable:
        for n in _EVENT_DRIVEN:
            sub(n, UNKNOWN, "event store unavailable this cycle — "
                "execution liveness not established", None, None)
    elif executed:
        last = max((e.get("ts") or "" for e in executed), default=None)
        sub("execution", ACTIVE,
            f"{len(executed)} executions this scan", last, _age_s(last, now))
        # portfolio + pnl MUST have followed each execution
        port_events = int(port_row.get("events") or 0)
        p_ts = port_row.get("last_ts")
        if port_events:
            sub("portfolio", ACTIVE, f"{port_events} portfolio events this "
                "scan", p_ts, _age_s(p_ts, now))
            sub("pnl", ACTIVE, "PnL updates ride the portfolio event stream",
                p_ts, _age_s(p_ts, now))
        else:
            sub("portfolio", DOWN, f"{len(executed)} executions but no "
                f"PORTFOLIO-stage events for scan {scan_id} — missing "
                "portfolio update", None, None)
            sub("pnl", DOWN, "no PNL/PORTFOLIO update after executions",
                None, None)
    else:
        for n in _EVENT_DRIVEN:
            sub(n, IDLE, "no executions this scan — nothing to update")

    # ── mission control: renders purely from the event stream ───────────────
    total_events = int((inputs.get("stage_events") or {})
                       .get("total_events") or 0)
    if stage_events_unavailable:
        sub("mission_control", UNKNOWN, "pipeline event store unavailable "
            "this cycle", None, None)
    elif scanner_idle and total_events == 0:
        sub("mission_control", IDLE, f"no events yet — scanner is "
            f"{scanner_status}", None, None)
    elif total_events > 0:
        last_any = max((s.get("last_ts") or "" for s in stage_map.values()),
                       default=None) or None
        sub("mission_control", ACTIVE,
            f"{total_events} pipeline events for scan {scan_id}",
            last_any, _age_s(last_any, now))
    elif scanner_ok:
        sub("mission_control", DOWN,
            f"no pipeline events at all for current scan {scan_id} — "
            "mission control has nothing to render", None, None)
    else:
        sub("mission_control", STALE,
            "no events; scanner is the root cause", None, None)

    # ── replay: must build and reference the current scan ───────────────────
    replay = inputs.get("replay") or {}
    if unavailable("replay"):
        sub("replay", UNKNOWN, "replay engine unavailable this cycle: "
            f"{errs.get('replay')}", None, None)
    elif scanner_idle and replay.get("error"):
        sub("replay", IDLE, "no replay yet — awaiting first scan of the "
            "session", None, None)
    elif replay.get("error"):
        sub("replay", DOWN,
            f"replay snapshot unavailable: {replay.get('error')}",
            None, None)
    elif scan_id and replay.get("scan_id") and \
            str(replay.get("scan_id")) != str(scan_id):
        sub("replay", STALE,
            f"replay shows scan {replay.get('scan_id')} but canonical latest "
            f"is {scan_id} — missing replay update", replay.get("snapshot_ts"),
            _age_s(replay.get("snapshot_ts"), now))
    else:
        sub("replay", ACTIVE, f"replay tracks scan {replay.get('scan_id')}",
            replay.get("snapshot_ts"), _age_s(replay.get("snapshot_ts"), now))

    # ── learning: CLOSED-today trades need phase24 records (30 min grace) ───
    learning_ids = {str(t) for t in inputs.get("learning_trade_ids") or []}
    overdue: List[str] = []
    closed_today = 0
    for r in inputs.get("ledger_rows") or []:
        if str(r.get("status") or "").upper() != "CLOSED":
            continue
        close_ts = _parse_ts(r.get("exit_ts") or r.get("closed_at")
                             or r.get("close_ts") or r.get("updated_at"))
        if close_ts is None or (session_start and close_ts < session_start):
            continue
        closed_today += 1
        if (now - close_ts).total_seconds() > LEARNING_GRACE_S and \
                str(r.get("trade_id") or "") not in learning_ids:
            overdue.append(str(r.get("trade_id") or r.get("symbol") or "?"))
    if unavailable("ledger_rows") or unavailable("learning_trade_ids"):
        sub("learning", UNKNOWN, "ledger or learning store unavailable this "
            "cycle — coverage not established", None, None)
    elif closed_today == 0:
        sub("learning", IDLE, "no trades closed this session — no learning "
            "records due")
    elif overdue:
        sub("learning", DOWN,
            f"{len(overdue)}/{closed_today} closed trades have no learning "
            f"record 30+ min after close: {overdue[:5]}", None, None)
    else:
        sub("learning", ACTIVE,
            f"all {closed_today} closed trades have learning records")

    return _finish(subsystems, issues, in_session, state, inputs, now)


def _finish(subsystems: Dict[str, Dict[str, Any]],
            issues: List[Dict[str, Any]], in_session: bool, state: str,
            inputs: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    counts = {s: 0 for s in (ACTIVE, IDLE, STALE, DOWN, OFF_SESSION, UNKNOWN)}
    for s in subsystems.values():
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    if not in_session:
        verdict = "PASS"
    elif counts[DOWN]:
        verdict = "FAIL"
    elif counts[STALE] or counts[UNKNOWN]:
        verdict = "WARN"
    else:
        verdict = "PASS"
    return {
        "kind": "live_validation",
        "generated_at": now.isoformat(),
        "in_session": in_session,
        "market_state": state,
        "scan_id": (inputs.get("scan_meta") or {}).get("scan_id"),
        "verdict": verdict,
        "subsystems": [subsystems[k] for k in subsystems],
        "subsystem_counts": counts,
        "issues": issues,
        "collection_errors": inputs.get("collection_errors") or {},
        "note": ADVISORY,
    }


# ── Scheduled entry point (KV-guarded, once per 5-min bucket) ────────────────

def _bucket_key(now_ist: datetime) -> str:
    minute = (now_ist.minute // LIVE_VALIDATION_INTERVAL_MIN) \
        * LIVE_VALIDATION_INTERVAL_MIN
    return (f"live_validation:{now_ist.strftime('%Y-%m-%d')}:"
            f"{now_ist.hour:02d}{minute:02d}")


def maybe_run_live_validation(mstate: str) -> Optional[Dict[str, Any]]:
    """Called from the phase20 scheduler tick. Generates + persists one
    liveness snapshot per 5-minute bucket during OPEN sessions (atomic KV
    claim — exactly one snapshot per bucket across concurrent processes).
    Never raises."""
    if str(mstate or "").upper() != "OPEN":
        return None
    try:
        import market_hours
        import phase20_store as store

        key = _bucket_key(market_hours.now_ist())
        if not store.kv_claim_once(key):
            return {"ran": False, "reason": "bucket already validated"}
        return run_live_validation(persist=True)
    except Exception as exc:          # never break the scheduler tick
        return {"ran": False, "error": str(exc)[:200]}


def run_live_validation(persist: bool = True,
                        inputs: Optional[Dict[str, Any]] = None,
                        consistency: Optional[Dict[str, Any]] = None
                        ) -> Dict[str, Any]:
    """Build the liveness snapshot, run the cross-page consistency validator,
    normalize all findings into the issue store, persist append-only."""
    snap = build_liveness_snapshot(inputs=inputs)

    # Cross-page consistency (only meaningful in session; still safe anytime)
    if consistency is None and snap["in_session"]:
        try:
            from phase26_consistency import run_cross_page_consistency
            consistency = run_cross_page_consistency()
        except Exception as exc:
            consistency = {"available": False, "error": str(exc)[:200]}
    if consistency is not None:
        snap["consistency"] = {
            k: consistency.get(k)
            for k in ("verdict", "scan_id", "mismatch_count",
                      "hard_mismatch_count", "available", "error")}
        if consistency.get("verdict") == "FAIL":
            snap["verdict"] = "FAIL"
        elif consistency.get("verdict") == "WARN" and snap["verdict"] == "PASS":
            snap["verdict"] = "WARN"

    # ── Issue normalization (dedup by category+key) ─────────────────────────
    # A FULLY evaluated cycle reconciles atomically (report + auto-resolve
    # in one lock/transaction). A partially evaluated cycle (collection
    # errors) only upserts the issues it did confirm — it must NEVER
    # auto-resolve anything it could not re-check.
    try:
        import phase26_live_store as live_store
        if snap["in_session"]:
            opened: List[Dict[str, Any]] = []
            resolved: List[Dict[str, str]] = []

            def _track(category: str, res: Dict[str, Any]) -> None:
                opened.extend(res.get("opened") or [])
                resolved.extend({"category": category, "key": k}
                                for k in res.get("resolved_keys") or [])

            sub_issues = [i for i in snap["issues"]
                          if i["category"] == "SUBSYSTEM"]
            fully = not snap.get("collection_errors")
            # The cycle counts as FULLY evaluated for verdict recovery only
            # when the consistency validator actually ran too — an
            # unavailable/errored consistency check is a partial cycle even
            # if liveness collection succeeded.
            cons_evaluated = (consistency is None
                              or (consistency.get("available", True)
                                  and not consistency.get("error")))
            if fully:
                _track("SUBSYSTEM",
                       live_store.reconcile_category("SUBSYSTEM", sub_issues))
            else:
                # Partial cycle: upsert only — never auto-resolve.
                for i in sub_issues:
                    res = live_store.report_issue(**i)
                    if res.get("transition") == "OPENED":
                        opened.append(dict(i))
            if consistency is not None and consistency.get("available", True) \
                    and not consistency.get("error"):
                _track("CONSISTENCY",
                       live_store.reconcile_category(
                           "CONSISTENCY", consistency.get("issues") or []))

            # ── Overall verdict tracked through the same issue lifecycle ────
            # (category VERDICT, key live_validation) so the FAIL alert fires
            # exactly once on the PASS/WARN→FAIL transition and stays quiet
            # while FAIL persists. Recovery follows the partial-cycle rule:
            # the FAIL issue resolves (and the all-clear fires) ONLY on a
            # FULLY evaluated cycle with a confirmed PASS verdict — a
            # collection-error/WARN cycle never clears an open outage.
            if snap["verdict"] == "FAIL":
                down = [s["subsystem"] for s in snap["subsystems"]
                        if s["status"] == DOWN]
                cons_fail = (snap.get("consistency") or {}) \
                    .get("verdict") == "FAIL"
                parts = []
                if down:
                    parts.append(f"subsystems DOWN: {', '.join(down)}")
                if cons_fail:
                    parts.append("cross-page consistency FAIL")
                res = live_store.report_issue(
                    category="VERDICT", key="live_validation",
                    severity="CRITICAL",
                    title="Live validation verdict FAIL",
                    detail="; ".join(parts) or "verdict FAIL",
                    source="live_monitor")
                if res.get("transition") == "OPENED":
                    opened.append({"category": "VERDICT",
                                   "key": "live_validation",
                                   "severity": "CRITICAL",
                                   "detail": "; ".join(parts)
                                   or "verdict FAIL"})
            elif fully and cons_evaluated and snap["verdict"] == "PASS":
                _track("VERDICT",
                       live_store.reconcile_category("VERDICT", []))

            _raise_alerts(snap, opened, resolved)
    except Exception as exc:
        snap.setdefault("collection_errors", {})["issue_store"] = \
            str(exc)[:200]

    if persist:
        try:
            import phase26_live_store as live_store
            stored = live_store.append_snapshot(snap)
            # Surface the persisted ID so a scheduler tick can be correlated
            # with its append-only snapshot record.
            snap["snapshot_id"] = stored.get("snapshot_id")
        except Exception as exc:
            snap.setdefault("collection_errors", {})["persist"] = \
                str(exc)[:200]
    snap["ran"] = True
    return snap


def _raise_alerts(snap: Dict[str, Any], opened: List[Dict[str, Any]],
                  resolved: List[Dict[str, str]]) -> None:
    """Notify operators through the phase20 notification hook (which already
    emails critical kinds). Called only for in-session cycles; alerts fire on
    issue OPEN transitions only — a persisting FAIL stays quiet after the
    first alert, and issue auto-resolution raises an all-clear info note.
    Never raises."""
    try:
        import phase20_store as store

        for iss in opened:
            if iss.get("category") == "VERDICT":
                store.add_notification(
                    kind="LIVE_VALIDATION_FAIL", severity="CRITICAL",
                    title="Live validation FAILED mid-session",
                    body=str(iss.get("detail") or "verdict FAIL"),
                    context={"scan_id": snap.get("scan_id"),
                             "snapshot_generated_at": snap.get("generated_at"),
                             "subsystem_counts": snap.get("subsystem_counts")})
            elif str(iss.get("severity") or "").upper() == "CRITICAL":
                store.add_notification(
                    kind="LIVE_VALIDATION_ISSUE", severity="CRITICAL",
                    title=str(iss.get("title") or
                              f"Live validation issue: {iss.get('key')}"),
                    body=str(iss.get("detail") or ""),
                    context={"category": iss.get("category"),
                             "key": iss.get("key"),
                             "scan_id": snap.get("scan_id")})

        if any(r.get("category") == "VERDICT" for r in resolved):
            store.add_notification(
                kind="LIVE_VALIDATION_RECOVERED", severity="INFO",
                title="Live validation recovered",
                body=f"Verdict is back to {snap.get('verdict')} — the "
                     "previous mid-session FAIL condition has cleared.",
                context={"scan_id": snap.get("scan_id"),
                         "verdict": snap.get("verdict")})
    except Exception:
        pass


def live_summary(limit: int = 20) -> Dict[str, Any]:
    """Latest snapshot + recent history + open issues, for the API."""
    import phase26_live_store as live_store
    return {
        "ok": True,
        "latest": live_store.latest_snapshot(),
        "history": live_store.list_snapshots(limit=limit),
        "open_issues": live_store.list_issues(status="OPEN"),
        "generated_at": _now_iso(),
        "note": ADVISORY,
    }
