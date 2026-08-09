"""
phase26_validation.py — Phase 26A: End-to-End Validation Engine.

Validates every trading cycle across the full canonical pipeline. VALIDATION
ONLY — no new business logic, no duplicated calculations. All checks consume
the existing canonical stores:

  • replay_engine.build_replay()      — the ONLY pipeline-count source
  • pipeline_events                   — canonical append-only event store
  • phase20_executor ledger           — paper trades (via injected rows or
                                        canonical_portfolio's source)
  • canonical_portfolio               — cash / positions / equity / PnL
  • validation_engines.validate_portfolio — existing ledger cross-check
  • phase24_store                     — learning records for CLOSED trades

Three validators, one orchestrator:
  validate_pipeline_cycle()   — per-stage counts, conservation, chaining,
                                duplicates/missing symbols, latency, timestamps
  validate_execution_chain()  — decision → execution → paper trade →
                                portfolio → PnL → replay → mission control →
                                learning, per BUY decision
  validate_portfolio_alignment() — canonical portfolio vs raw phase20 ledger

  run_e2e_validation()        — runs all three, persists append-only via
                                phase26_store, returns the full run record.

STRICTLY READ-ONLY over trading state. PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from validation_engines import (PASS, WARN, FAIL, INSUFFICIENT,
                                _check, _verdict, _result)

BUY_ACTIONS = ("BUY", "STRONG BUY", "STRONG_BUY")
OPEN_STATUSES = ("OPEN", "EXIT_PENDING")

ADVISORY = ("End-to-end validation over canonical stores. Nothing is "
            "modified. PAPER TRADING / RESEARCH ONLY.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_buy(action: Any) -> bool:
    return str(action or "").upper().replace("_", " ") in ("BUY", "STRONG BUY")


# ── 1. Pipeline cycle validator ──────────────────────────────────────────────

def validate_pipeline_cycle(scan_id: Optional[str] = None,
                            replay: Optional[Dict[str, Any]] = None,
                            stage_events: Optional[Dict[str, Any]] = None
                            ) -> Dict[str, Any]:
    """Per-stage input/output/rejected/pending counts, latency and timestamp,
    with conservation (in = out + rejected + pending + cancelled) enforced and
    duplicate / missing symbols flagged.

    Counts come exclusively from replay_engine.build_replay() — the unified
    replay snapshot — never re-derived a second way. `replay` and
    `stage_events` are injectable for tests.
    """
    if replay is None:
        from replay_engine import build_replay
        replay = build_replay(scan_id or "latest")

    checks: List[Dict[str, Any]] = []
    if not replay or replay.get("error"):
        checks.append(_check(
            "replay_available", INSUFFICIENT,
            f"no replay snapshot for scan '{scan_id or 'latest'}': "
            f"{(replay or {}).get('error') or 'empty'}"))
        return _result("pipeline_cycle", checks, verdict=INSUFFICIENT,
                       scan_id=scan_id, stage_report=[])

    resolved_scan = replay.get("scan_id") or scan_id
    if stage_events is None:
        try:
            from pipeline_events import stage_summary
            stage_events = stage_summary(scan_id=resolved_scan)
        except Exception:
            stage_events = {}
    event_stage_map = {str(s.get("stage") or "").upper(): s
                       for s in (stage_events or {}).get("stages") or []}

    stages = replay.get("stages") or []
    stage_by_id = {s.get("id"): s for s in stages}
    counts: Dict[str, Dict[str, Any]] = replay.get("pipeline_counts") or {}

    if not counts:
        checks.append(_check("pipeline_counts_present", INSUFFICIENT,
                             "replay snapshot carries no pipeline_counts"))
        return _result("pipeline_cycle", checks, verdict=INSUFFICIENT,
                       scan_id=resolved_scan, stage_report=[])

    # Per-stage report + conservation
    stage_report: List[Dict[str, Any]] = []
    broken: List[str] = []
    for sid, c in counts.items():
        n_in = int(c.get("in") or 0)
        n_out = int(c.get("out") or 0)
        n_rej = int(c.get("rejected") or 0)
        n_pend = int(c.get("pending") or 0)
        n_canc = int(c.get("cancelled") or 0)
        conserved = n_in == n_out + n_rej + n_pend + n_canc
        if not conserved:
            broken.append(f"{sid}({n_in}≠{n_out}+{n_rej}+{n_pend}+{n_canc})")
        srow = stage_by_id.get(sid) or {}
        ev = event_stage_map.get(str(sid).upper()) or {}
        stage_report.append({
            "stage": sid,
            "label": c.get("label") or srow.get("label"),
            "input": n_in, "output": n_out, "rejected": n_rej,
            "pending": n_pend, "cancelled": n_canc,
            "conserved": conserved,
            "latency_ms": srow.get("duration_ms"),
            "last_event_ts": ev.get("last_ts"),
            "event_count": ev.get("events"),
        })
    checks.append(_check(
        "stage_conservation", PASS if not broken else FAIL,
        "every stage conserves symbols (in = out + rejected + pending + "
        f"cancelled); violations: {broken or 'none'}"))

    # Stage chaining: each stage's input equals the previous stage's output
    # (chained-subset contract of the replay reconstruction). The PORTFOLIO
    # row tracks ledger totals, not the symbol funnel — excluded.
    chain_breaks: List[str] = []
    funnel = [s for s in stages if s.get("id") in counts]
    for prev, nxt in zip(funnel, funnel[1:]):
        p_out = int(prev.get("stocks_out") or 0)
        n_in = int(nxt.get("stocks_in") or 0)
        if p_out != n_in:
            chain_breaks.append(
                f"{prev.get('id')}→{nxt.get('id')} ({p_out}→{n_in})")
    checks.append(_check(
        "stage_chaining", PASS if not chain_breaks else FAIL,
        f"stage handoffs where next input ≠ previous output: "
        f"{chain_breaks or 'none'}"))

    # Duplicate symbols — surfaced by the replay reconstruction as anomalies.
    anomalies: List[str] = []
    for s in stages:
        for a in s.get("anomalies") or []:
            anomalies.append(f"{s.get('id')}: {a}")
    checks.append(_check(
        "no_stage_anomalies", PASS if not anomalies else FAIL,
        f"duplicate-symbol / ledger-overage anomalies: "
        f"{anomalies[:5] or 'none'}", anomaly_count=len(anomalies)))

    # Missing symbols at market data (requested but never received)
    md = stage_by_id.get("market_data") or {}
    missing = list(md.get("rejected_symbols") or [])
    checks.append(_check(
        "missing_symbols_accounted", PASS,
        f"market-data stage rejected {len(missing)} symbols "
        f"(accounted as rejections): {missing[:10] or 'none'}"))

    # Timestamp sanity: snapshot has a parseable, non-future timestamp
    snap_ts = replay.get("snapshot_ts")
    ts_ok = False
    try:
        dt = datetime.fromisoformat(str(snap_ts).replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        ts_ok = dt <= datetime.now(timezone.utc)
    except Exception:
        ts_ok = False
    checks.append(_check(
        "snapshot_timestamp_valid", PASS if ts_ok else WARN,
        f"snapshot_ts = {snap_ts!r} "
        + ("(parseable, not in the future)" if ts_ok
           else "(missing, unparseable, or future-dated)")))

    return _result("pipeline_cycle", checks, scan_id=resolved_scan,
                   snapshot_ts=snap_ts, stage_report=stage_report,
                   total_symbols=replay.get("total_symbols"))


# ── 2. Execution chain validator ─────────────────────────────────────────────

_CHAIN_LINKS = ("decision", "execution_submitted", "paper_trade_created",
                "portfolio_updated", "pnl_updated", "replay_event",
                "mission_control_visible", "learning_record")


def validate_execution_chain(scan_id: Optional[str] = None,
                             replay: Optional[Dict[str, Any]] = None,
                             ledger_rows: Optional[List[Dict[str, Any]]] = None,
                             execution_events: Optional[List[Dict[str, Any]]] = None,
                             learning_trade_ids: Optional[List[str]] = None,
                             portfolio_snapshot: Optional[Dict[str, Any]] = None
                             ) -> Dict[str, Any]:
    """For every BUY decision in the cycle, confirm the full downstream chain
    exists in the canonical stores. Every missing link is an ERROR item.

    A BUY decision that was NOT paper-eligible (or was cancelled/blocked by
    the executor with recorded evidence) is a legitimately terminated chain —
    reported as blocked, never as a missing link.
    """
    if replay is None:
        from replay_engine import build_replay
        replay = build_replay(scan_id or "latest")

    checks: List[Dict[str, Any]] = []
    if not replay or replay.get("error"):
        checks.append(_check(
            "replay_available", INSUFFICIENT,
            f"no replay snapshot for scan '{scan_id or 'latest'}'"))
        return _result("execution_chain", checks, verdict=INSUFFICIENT,
                       scan_id=scan_id, chains=[], errors=[])

    resolved_scan = replay.get("scan_id") or scan_id

    if ledger_rows is None:
        import phase20_executor as p20
        ledger_rows = p20.get_ledger(limit=10_000)
    scan_ledger = {str(r.get("symbol") or "").upper(): r
                   for r in ledger_rows
                   if r.get("scan_id") == resolved_scan}

    if execution_events is None:
        try:
            from pipeline_events import query_events
            execution_events = query_events(
                scan_id=resolved_scan, stage="EXECUTION", limit=2000)
        except Exception:
            execution_events = []
    event_symbols = {str(e.get("symbol") or "").upper()
                     for e in execution_events if e.get("symbol")}

    replay_exec_symbols = {str(t.get("symbol") or "").upper()
                           for t in replay.get("execution_trades") or []}
    evidence_symbols: set = set()
    for s in replay.get("stages") or []:
        if s.get("id") == "execution":
            for b in s.get("blocked_entries") or []:
                sym = b.get("symbol") if isinstance(b, dict) else b
                if sym:
                    evidence_symbols.add(str(sym).upper())

    if portfolio_snapshot is None:
        try:
            from canonical_portfolio import build_canonical_portfolio
            portfolio_snapshot = build_canonical_portfolio()
        except Exception:
            portfolio_snapshot = {}
    positions_by_tid = {str(p.get("trade_id") or ""): p
                        for p in portfolio_snapshot.get("positions") or []}
    positions_by_sym = {str(p.get("symbol") or "").upper(): p
                        for p in portfolio_snapshot.get("positions") or []}

    def _has_learning(trade_id: Any) -> bool:
        tid = str(trade_id or "")
        if not tid:
            return False
        if learning_trade_ids is not None:
            return tid in {str(t) for t in learning_trade_ids}
        try:
            import phase24_store
            return bool(phase24_store.has_trade_record(tid))
        except Exception:
            return False

    decisions = replay.get("decisions") or []
    buys = [d for d in decisions if _is_buy(d.get("final_action"))]

    chains: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    blocked_no_evidence: List[str] = []

    def err(symbol: str, link: str, detail: str) -> None:
        errors.append({"severity": "ERROR", "symbol": symbol,
                       "link": link, "detail": detail})

    for d in buys:
        sym = str(d.get("symbol") or "").upper()
        links: Dict[str, str] = {k: "MISSING" for k in _CHAIN_LINKS}
        links["decision"] = "OK"
        row = scan_ledger.get(sym)

        if row is None:
            # No ledger row: the replay reconstruction counts every
            # paper-eligible BUY without a ledger order as CANCELLED (auto
            # entries default OFF, gates, market closed…). That is a
            # legitimately terminated chain — never a missing link. We only
            # distinguish whether the executor recorded WHY (evidence).
            eligible = bool(d.get("paper_eligible"))
            if not eligible:
                reason = "not paper-eligible"
            elif sym in evidence_symbols:
                reason = "blocked by executor (evidence recorded)"
            else:
                reason = ("not executed — counted cancelled in replay; "
                          "no block evidence recorded")
                blocked_no_evidence.append(sym)
            chains.append({"symbol": sym, "status": "BLOCKED",
                           "reason": reason, "links": links})
            continue

        status = str(row.get("status") or "")
        tid = row.get("trade_id")

        # execution submitted + paper trade created (the ledger row IS the
        # paper trade; a fill proves submission reached the executor)
        if row.get("fill_ts") and row.get("fill_price") is not None:
            links["execution_submitted"] = "OK"
            links["paper_trade_created"] = "OK"
        else:
            err(sym, "execution_submitted",
                f"ledger row {tid} has no fill_ts/fill_price "
                f"(status={status})")

        # portfolio updated: an OPEN/EXIT_PENDING row must appear as a
        # canonical position with matching quantity and cost; a CLOSED row
        # must NOT still be an open position.
        pos = positions_by_tid.get(str(tid or "")) or positions_by_sym.get(sym)
        if status in OPEN_STATUSES:
            if pos is None:
                err(sym, "portfolio_updated",
                    f"open ledger row {tid} has no matching position in the "
                    "canonical portfolio snapshot")
            else:
                qty_ok = int(pos.get("quantity") or 0) == \
                    int(row.get("quantity") or 0)
                cost_ok = abs(float(pos.get("cost") or 0.0)
                              - int(row.get("quantity") or 0)
                              * float(row.get("fill_price") or 0.0)) <= 0.01
                if qty_ok and cost_ok:
                    links["portfolio_updated"] = "OK"
                else:
                    err(sym, "portfolio_updated",
                        f"position for {tid} disagrees with ledger: "
                        f"qty {pos.get('quantity')} vs {row.get('quantity')}, "
                        f"cost {pos.get('cost')} vs qty×fill")
        elif status == "CLOSED":
            if pos is not None and str(pos.get("trade_id") or "") == \
                    str(tid or ""):
                err(sym, "portfolio_updated",
                    f"CLOSED ledger row {tid} still appears as an open "
                    "canonical position")
            else:
                links["portfolio_updated"] = "OK"
        else:
            err(sym, "portfolio_updated",
                f"ledger row {tid} in unrecognised status {status!r} — "
                "portfolio cannot account for it")

        # PnL updated
        if status == "CLOSED":
            if row.get("realized_pnl") is not None:
                links["pnl_updated"] = "OK"
            else:
                err(sym, "pnl_updated",
                    f"CLOSED ledger row {tid} has no realized_pnl")
        elif status in OPEN_STATUSES and pos is not None:
            # open: MTM must be present when a mark exists, else mark-pending
            if pos.get("mark_price") is None or \
                    pos.get("unrealized_pnl") is not None:
                links["pnl_updated"] = "OK"
            else:
                err(sym, "pnl_updated",
                    f"position {tid} has a mark but no unrealized_pnl")
        else:
            links["pnl_updated"] = "OK"   # unmatched rows already errored

        # replay event: trade visible in the unified replay snapshot
        if sym in replay_exec_symbols:
            links["replay_event"] = "OK"
        else:
            err(sym, "replay_event",
                "executed trade missing from replay execution_trades")

        # mission-control visibility: canonical EXECUTION-stage event exists
        if sym in event_symbols:
            links["mission_control_visible"] = "OK"
        else:
            err(sym, "mission_control_visible",
                "no EXECUTION-stage pipeline event for this symbol — "
                "mission control cannot show it")

        # learning record: required once the trade has CLOSED
        if status == "CLOSED":
            if _has_learning(tid):
                links["learning_record"] = "OK"
            else:
                err(sym, "learning_record",
                    f"CLOSED trade {tid} has no phase24 learning record")
        else:
            links["learning_record"] = "PENDING"  # captured after close

        broken = any(v == "MISSING" for v in links.values())
        chains.append({"symbol": sym, "trade_id": tid,
                       "status": "BROKEN" if broken else "COMPLETE",
                       "ledger_status": status, "links": links})

    checks.append(_check(
        "buy_decisions_present",
        PASS if buys else INSUFFICIENT,
        f"{len(buys)} BUY decisions in scan {resolved_scan}"))
    if buys:
        checks.append(_check(
            "execution_chains_complete", PASS if not errors else FAIL,
            f"{len(chains)} chains validated; "
            f"{sum(1 for c in chains if c['status'] == 'COMPLETE')} complete, "
            f"{sum(1 for c in chains if c['status'] == 'BLOCKED')} blocked, "
            f"{len(errors)} missing links"))
        checks.append(_check(
            "blocked_entries_have_evidence",
            PASS if not blocked_no_evidence else WARN,
            f"{len(blocked_no_evidence)} eligible BUYs were not executed "
            "and carry no block evidence (expected when auto paper entries "
            f"are OFF): {blocked_no_evidence[:10] or 'none'}"))

    return _result("execution_chain", checks, scan_id=resolved_scan,
                   chains=chains, errors=errors,
                   buy_decision_count=len(buys))


# ── 3. Portfolio validator ───────────────────────────────────────────────────

def validate_portfolio_alignment(ledger_rows: Optional[List[Dict[str, Any]]] = None,
                                 snapshot: Optional[Dict[str, Any]] = None
                                 ) -> Dict[str, Any]:
    """Cross-check cash, capital, exposure, positions, sector allocation and
    realized/unrealized PnL against the canonical phase20 ledger.

    Delegates to the existing validation_engines.validate_portfolio — the
    established ledger↔canonical cross-check — never re-implements it."""
    from validation_engines import validate_portfolio
    result = validate_portfolio(ledger_rows=ledger_rows, snapshot=snapshot)
    result["domain"] = "portfolio_alignment"
    return result


# ── Orchestrator ─────────────────────────────────────────────────────────────

_VERDICT_RANK = {PASS: 0, INSUFFICIENT: 1, WARN: 2, FAIL: 3}


def _worst(verdicts: List[str]) -> str:
    return max(verdicts, key=lambda v: _VERDICT_RANK.get(v, 3)) if verdicts \
        else INSUFFICIENT


def run_e2e_validation(scan_id: Optional[str] = None,
                       persist: bool = True,
                       replay: Optional[Dict[str, Any]] = None,
                       ledger_rows: Optional[List[Dict[str, Any]]] = None,
                       snapshot: Optional[Dict[str, Any]] = None,
                       stage_events: Optional[Dict[str, Any]] = None,
                       execution_events: Optional[List[Dict[str, Any]]] = None,
                       learning_trade_ids: Optional[List[str]] = None
                       ) -> Dict[str, Any]:
    """Run all Phase 26A validators for one scan cycle and persist the run
    append-only. All data sources are injectable for tests."""
    if replay is None:
        from replay_engine import build_replay
        replay = build_replay(scan_id or "latest")

    pipeline = validate_pipeline_cycle(scan_id=scan_id, replay=replay,
                                       stage_events=stage_events)
    chain = validate_execution_chain(scan_id=scan_id, replay=replay,
                                     ledger_rows=ledger_rows,
                                     execution_events=execution_events,
                                     learning_trade_ids=learning_trade_ids,
                                     portfolio_snapshot=snapshot)
    portfolio = validate_portfolio_alignment(ledger_rows=ledger_rows,
                                             snapshot=snapshot)

    sections = {"pipeline_cycle": pipeline, "execution_chain": chain,
                "portfolio_alignment": portfolio}
    all_checks = [c for s in sections.values() for c in s.get("checks") or []]
    verdict = _worst([s.get("verdict") for s in sections.values()])

    import phase26_store
    run = {
        "run_id": phase26_store.new_run_id(),
        "scan_id": pipeline.get("scan_id") or chain.get("scan_id") or scan_id,
        "verdict": verdict,
        "generated_at": _now_iso(),
        "sections": sections,
        "totals": {
            "checks": len(all_checks),
            "pass": sum(1 for c in all_checks if c["status"] == PASS),
            "warn": sum(1 for c in all_checks if c["status"] == WARN),
            "fail": sum(1 for c in all_checks if c["status"] == FAIL),
            "errors": len(chain.get("errors") or []),
        },
        "note": ADVISORY,
    }
    if persist:
        phase26_store.append_run(run)
    return run


def e2e_summary(limit: int = 20) -> Dict[str, Any]:
    """Latest run verdict + recent history counts, for the API summary."""
    import phase26_store
    runs = phase26_store.list_runs(limit=limit)
    latest = phase26_store.get_run(runs[0]["run_id"]) if runs else None
    return {
        "ok": True,
        "latest": latest,
        "history": runs,
        "history_verdicts": {
            v: sum(1 for r in runs if r.get("verdict") == v)
            for v in (PASS, WARN, FAIL, INSUFFICIENT)
        },
        "generated_at": _now_iso(),
        "note": ADVISORY,
    }
