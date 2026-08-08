"""
Phase 23.8B — Institutional Validation Engines (spec Parts G–M).

Six READ-ONLY validators over the canonical stores. Existing checkers are
ORCHESTRATED, never reimplemented:
  • replay integrity        — backtest_replay.replay_verify (called, not copied)
  • decision determinism    — the STORED validate_run verdict on the run record
                              (never re-evaluated live from here)
  • portfolio reconciliation— canonical_portfolio.build_canonical_portfolio
  • pipeline reconciliation — pipeline_events (the one event store)
  • metric math             — expectancy.compute_metrics (the single engine)

Result contract (every validator):
  { "ok": True, "domain": <str>, "verdict": PASS|WARN|FAIL|INSUFFICIENT_EVIDENCE,
    "checks": [ {check, status, detail, ...evidence} ], "generated_at": iso }

Verdict rules (strict — warnings are NEVER treated as pass):
  any FAIL -> FAIL;  else any WARN -> WARN;
  else no evaluable checks -> INSUFFICIENT_EVIDENCE;  else PASS.

All validators accept injected fixtures (candles / events / ledger rows) so
tests are seeded and deterministic; production callers pass nothing and the
canonical stores are read lazily.

STRICTLY READ-ONLY. PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
MIN_EVIDENCE = 5
TOL = 0.01          # exact-balance tolerance (rupee rounding)

ADVISORY = ("Read-only validation over canonical stores. Nothing is "
            "modified. PAPER TRADING / RESEARCH ONLY.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _check(name: str, status: str, detail: str, **evidence) -> Dict[str, Any]:
    row = {"check": name, "status": status, "detail": detail}
    if evidence:
        row["evidence"] = evidence
    return row


def _verdict(checks: List[Dict[str, Any]]) -> str:
    statuses = [c["status"] for c in checks]
    if FAIL in statuses:
        return FAIL
    if WARN in statuses:
        return WARN
    evaluable = [s for s in statuses if s in (PASS, WARN, FAIL)]
    if not evaluable:
        return INSUFFICIENT
    return PASS


def _result(domain: str, checks: List[Dict[str, Any]],
            verdict: Optional[str] = None, **extra) -> Dict[str, Any]:
    return {"ok": True, "domain": domain,
            "verdict": verdict or _verdict(checks),
            "checks": checks, "generated_at": _now_iso(),
            "note": ADVISORY, **extra}


def _parse_ts(ts: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


# ── Part G: Data validation ──────────────────────────────────────────────────

MAX_DAILY_MOVE_PCT = 25.0   # beyond this a split/dividend anomaly is likely


def _default_symbols() -> List[str]:
    try:
        import signals_store
        wl = signals_store.load_watchlist()
        if wl:
            return [str(s).upper() for s in wl][:10]
    except Exception:
        pass
    try:
        from config import DEFAULT_WATCHLIST
        return list(DEFAULT_WATCHLIST)[:10]
    except Exception:
        return []


def validate_data(symbols: Optional[List[str]] = None, interval: str = "1d",
                  start: Optional[str] = None, end: Optional[str] = None,
                  candles_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]]
                  = None) -> Dict[str, Any]:
    """Candle-cache integrity: missing / duplicate candles, timestamp order,
    corporate-action anomalies, price/volume integrity, completeness."""
    if candles_by_symbol is None:
        import historical_data_engine as hde
        symbols = symbols or _default_symbols()
        end = end or datetime.now(timezone.utc).date().isoformat()
        start = start or (datetime.now(timezone.utc).date()
                          - timedelta(days=90)).isoformat()
        candles_by_symbol = {}
        for sym in symbols:
            try:
                candles_by_symbol[sym] = hde.get_candles(sym, interval,
                                                         start, end) or []
            except Exception:
                candles_by_symbol[sym] = []

    checks: List[Dict[str, Any]] = []
    evaluated = 0
    missing: List[str] = []
    for sym, candles in sorted(candles_by_symbol.items()):
        if not candles:
            missing.append(sym)
            checks.append(_check(f"{sym}:candles_present", INSUFFICIENT,
                                 "no cached candles for the window"))
            continue
        evaluated += 1
        ts_list = [str(c.get("ts") or "") for c in candles]

        dupes = len(ts_list) - len(set(ts_list))
        checks.append(_check(f"{sym}:no_duplicate_candles",
                             PASS if dupes == 0 else FAIL,
                             f"{len(ts_list)} candles, {dupes} duplicate "
                             "timestamps"))

        ordered = all(ts_list[i] <= ts_list[i + 1]
                      for i in range(len(ts_list) - 1))
        checks.append(_check(f"{sym}:timestamps_ordered",
                             PASS if ordered else FAIL,
                             "timestamps monotonically non-decreasing"
                             if ordered else "out-of-order timestamps found"))

        bad_price = bad_vol = 0
        for c in candles:
            try:
                o, h, l, cl = (float(c["open"]), float(c["high"]),
                               float(c["low"]), float(c["close"]))
                v = float(c.get("volume") or 0)
            except Exception:
                bad_price += 1
                continue
            if not (h >= l and h >= o and h >= cl and l <= o and l <= cl
                    and cl > 0 and o > 0):
                bad_price += 1
            if v < 0:
                bad_vol += 1
        checks.append(_check(f"{sym}:price_integrity",
                             PASS if bad_price == 0 else FAIL,
                             f"{bad_price} candles violate OHLC bounds "
                             "or have non-positive prices"))
        checks.append(_check(f"{sym}:volume_integrity",
                             PASS if bad_vol == 0 else FAIL,
                             f"{bad_vol} candles have negative volume"))

        # corporate action / split / dividend anomaly: extreme close-to-close
        anomalies = []
        prev_close: Optional[float] = None
        for c in candles:
            try:
                cl = float(c["close"])
            except Exception:
                continue
            if prev_close and prev_close > 0:
                move = abs(cl - prev_close) / prev_close * 100.0
                if move > MAX_DAILY_MOVE_PCT:
                    anomalies.append({"ts": c.get("ts"),
                                      "move_pct": round(move, 1)})
            prev_close = cl
        checks.append(_check(
            f"{sym}:corporate_action_anomalies",
            PASS if not anomalies else WARN,
            f"{len(anomalies)} close-to-close moves > "
            f"{MAX_DAILY_MOVE_PCT}% (possible unadjusted split/dividend)",
            anomalies=anomalies[:10]))

        # completeness vs weekday count (daily interval only; holidays make
        # this advisory, so a shortfall is WARN not FAIL)
        if interval == "1d" and len(candles) >= 2:
            first = _parse_ts(ts_list[0])
            last = _parse_ts(ts_list[-1])
            if first and last and last > first:
                weekdays = sum(
                    1 for i in range((last.date() - first.date()).days + 1)
                    if (first.date() + timedelta(days=i)).weekday() < 5)
                ratio = len(candles) / weekdays if weekdays else 1.0
                checks.append(_check(
                    f"{sym}:completeness",
                    PASS if ratio >= 0.9 else WARN,
                    f"{len(candles)} bars over {weekdays} weekdays "
                    f"({round(ratio * 100.0, 1)}% — holidays expected)"))
    if evaluated == 0:
        return _result("data", checks, verdict=INSUFFICIENT,
                       symbols=sorted(candles_by_symbol),
                       missing_symbols=missing)
    # Missing symbols BLOCK the domain: partial coverage of the requested
    # universe must never certify as PASS (or WARN) — insufficient evidence
    # blocks READY. Hard FAILs on the available data still dominate.
    verdict = _verdict(checks)
    if missing and verdict != FAIL:
        verdict = INSUFFICIENT
    return _result("data", checks, verdict=verdict,
                   symbols=sorted(candles_by_symbol),
                   missing_symbols=missing)


# ── Part H: Pipeline validation ──────────────────────────────────────────────

_DECISION_TYPES = ("BUY_GENERATED", "WATCH_GENERATED", "IGNORE_GENERATED",
                   "SELL_GENERATED")


def validate_pipeline(run_id: Optional[str] = None, mode: str = "LIVE",
                      scan_id: Optional[str] = None,
                      events: Optional[List[Dict[str, Any]]] = None
                      ) -> Dict[str, Any]:
    """Every stage produces reconciled, conserved output in the canonical
    event store — scanner → … → execution → portfolio."""
    if events is None:
        from pipeline_events import query_events, latest_scan_id
        if run_id:
            mode = "BACKTEST"
        elif not scan_id:
            scan_id = latest_scan_id(mode=mode)
        events = query_events(run_id=run_id, scan_id=scan_id, mode=mode,
                              limit=2000)

    checks: List[Dict[str, Any]] = []
    if not events:
        checks.append(_check("events_present", INSUFFICIENT,
                             "no pipeline events for the selected scope"))
        return _result("pipeline", checks, verdict=INSUFFICIENT,
                       run_id=run_id, scan_id=scan_id, mode=mode)

    counts: Dict[str, int] = {}
    for e in events:
        counts[e.get("event_type") or ""] = \
            counts.get(e.get("event_type") or "", 0) + 1

    ids = [e.get("id") for e in events if e.get("id") is not None]
    checks.append(_check("no_duplicate_events",
                         PASS if len(ids) == len(set(ids)) else FAIL,
                         f"{len(ids)} events, "
                         f"{len(ids) - len(set(ids))} duplicate ids"))

    errors = sum(1 for e in events if (e.get("payload") or {}).get("error"))
    checks.append(_check("no_stage_errors", PASS if errors == 0 else WARN,
                         f"{errors} events carry an error payload"))

    # order conservation: reconcile each order LIFECYCLE, not aggregate
    # counts. Orders are keyed by (scan_id, symbol) — the stable identity
    # both the live executor and the backtest runner emit with. Every
    # ORDER_SUBMITTED must resolve exactly once (EXECUTED or CANCELLED);
    # ORDER_REJECTED is a valid terminal outcome without a submission;
    # resolutions without a submission and double-resolutions both FAIL.
    _ORDER_TYPES = ("ORDER_SUBMITTED", "ORDER_EXECUTED", "ORDER_CANCELLED",
                    "ORDER_REJECTED")
    lifecycles: Dict[tuple, Dict[str, int]] = {}
    uncorrelatable = 0
    for e in events:
        et = e.get("event_type")
        if et not in _ORDER_TYPES:
            continue
        sym = str(e.get("symbol") or "").upper()
        sid = e.get("scan_id")
        if not sym or not sid:
            uncorrelatable += 1
            continue
        lc = lifecycles.setdefault((sid, sym), {t: 0 for t in _ORDER_TYPES})
        lc[et] += 1
    unresolved, orphans, double = [], [], []
    for (sid, sym), lc in lifecycles.items():
        resolved = lc["ORDER_EXECUTED"] + lc["ORDER_CANCELLED"]
        if resolved < lc["ORDER_SUBMITTED"]:
            unresolved.append(f"{sym}@{sid}")
        elif resolved > lc["ORDER_SUBMITTED"]:
            (orphans if lc["ORDER_SUBMITTED"] == 0 else double).append(
                f"{sym}@{sid}")
    checks.append(_check(
        "order_events_correlatable", PASS if uncorrelatable == 0 else FAIL,
        f"{uncorrelatable} order events missing scan_id/symbol — "
        "uncorrelatable events cannot be reconciled"))
    checks.append(_check(
        "order_conservation",
        PASS if not (unresolved or orphans or double) else FAIL,
        f"{len(lifecycles)} order lifecycles; unresolved submissions: "
        f"{unresolved[:5] or 'none'}; resolutions without submission: "
        f"{orphans[:5] or 'none'}; double-resolved: {double[:5] or 'none'} "
        "(REJECTED is a valid terminal outcome without submission)"))

    # position conservation: closes never exceed opens
    opened = counts.get("POSITION_OPENED", 0)
    closed = counts.get("POSITION_CLOSED", 0)
    checks.append(_check(
        "position_conservation", PASS if closed <= opened else FAIL,
        f"opened={opened}, closed={closed} "
        "(cannot close more positions than were opened)"))

    # executions never exceed BUY decisions
    buys = counts.get("BUY_GENERATED", 0)
    executed = counts.get("ORDER_EXECUTED", 0)
    checks.append(_check(
        "execution_bounded_by_decisions",
        PASS if executed <= buys else FAIL,
        f"BUY decisions={buys}, executions={executed} "
        "(never more fills than BUY decisions)"))

    # determinism: duplicate decisions for the same (scan_id, symbol) agree
    seen: Dict[tuple, Dict[str, Any]] = {}
    nondet: List[str] = []
    for e in events:
        if e.get("event_type") not in _DECISION_TYPES:
            continue
        key = (e.get("scan_id"), str(e.get("symbol") or "").upper())
        prev = seen.get(key)
        if prev is None:
            seen[key] = e
        elif prev.get("event_type") != e.get("event_type"):
            nondet.append(f"{key[1]}@{key[0]}")
    checks.append(_check(
        "deterministic_decisions", PASS if not nondet else FAIL,
        f"{len(nondet)} (scan, symbol) pairs carry conflicting decision "
        f"events: {nondet[:5] or 'none'}"))

    stage_rows = sorted({e.get("stage") for e in events if e.get("stage")})
    checks.append(_check("stages_active", PASS,
                         f"stages with events: {', '.join(stage_rows)}"))
    return _result("pipeline", checks, run_id=run_id, scan_id=scan_id,
                   mode=mode, event_counts=counts,
                   total_events=len(events))


# ── Part I: Portfolio validation ─────────────────────────────────────────────

def validate_portfolio(ledger_rows: Optional[List[Dict[str, Any]]] = None,
                       snapshot: Optional[Dict[str, Any]] = None
                       ) -> Dict[str, Any]:
    """Independently re-derive cash / positions / PnL / exposure from the raw
    phase20 ledger and require the canonical portfolio module to balance
    EXACTLY against it."""
    if snapshot is None:
        from canonical_portfolio import build_canonical_portfolio
        snapshot = build_canonical_portfolio()
    if ledger_rows is None:
        import phase20_executor as p20
        ledger_rows = p20.get_ledger(limit=10_000)

    checks: List[Dict[str, Any]] = []
    open_statuses = ("OPEN", "EXIT_PENDING")
    open_rows = [r for r in ledger_rows if r.get("status") in open_statuses]
    closed_rows = [r for r in ledger_rows if r.get("status") == "CLOSED"]
    cap = float(snapshot.get("initial_capital") or 0.0)

    realized = round(sum(float(r.get("realized_pnl") or 0.0)
                         for r in closed_rows), 2)
    invested = round(sum(int(r.get("quantity") or 0)
                         * float(r.get("fill_price") or 0.0)
                         for r in open_rows), 2)
    expected_cash = round(cap - invested + realized, 2)

    def balance(name: str, expected: float, actual: Any, what: str):
        actual_f = float(actual or 0.0)
        ok = abs(actual_f - expected) <= TOL
        checks.append(_check(name, PASS if ok else FAIL,
                             f"{what}: ledger-derived {expected} vs "
                             f"canonical {actual_f}"))

    balance("cash_balances", expected_cash, snapshot.get("cash"),
            "cash = capital − invested + realized")
    balance("invested_value_balances", invested,
            snapshot.get("invested_value"), "Σ open cost")
    balance("realized_pnl_balances", realized,
            snapshot.get("realized_pnl"), "Σ realized PnL of CLOSED rows")

    checks.append(_check(
        "open_position_count",
        PASS if len(open_rows) == int(snapshot.get("open_position_count")
                                      or 0) else FAIL,
        f"ledger open rows {len(open_rows)} vs canonical "
        f"{snapshot.get('open_position_count')}"))
    checks.append(_check(
        "closed_trade_count",
        PASS if len(closed_rows) == int(snapshot.get("closed_trade_count")
                                        or 0) else FAIL,
        f"ledger closed rows {len(closed_rows)} vs canonical "
        f"{snapshot.get('closed_trade_count')}"))

    # per-position cost = qty × avg_price, and Σ costs == invested_value
    positions = snapshot.get("positions") or []
    bad_cost = [p.get("symbol") for p in positions
                if abs(float(p.get("cost") or 0)
                       - int(p.get("quantity") or 0)
                       * float(p.get("avg_price") or 0)) > TOL]
    checks.append(_check("position_costs_exact", PASS if not bad_cost else FAIL,
                         f"positions where cost ≠ qty × avg_price: "
                         f"{bad_cost or 'none'}"))
    pos_cost_sum = round(sum(float(p.get("cost") or 0) for p in positions), 2)
    balance("positions_sum_to_invested", pos_cost_sum,
            snapshot.get("invested_value"), "Σ position costs")

    # sector exposure sums to invested value
    sector_sum = round(sum(float(v or 0) for v in
                           (snapshot.get("sector_exposure") or {}).values()), 2)
    balance("sector_exposure_balances", sector_sum,
            snapshot.get("invested_value"), "Σ sector exposure")

    # equity identity (only exact when every mark is known)
    unreal = snapshot.get("unrealized_pnl")
    if snapshot.get("equity_complete") and unreal is not None:
        expected_equity = round(cap + realized + float(unreal), 2)
        balance("equity_identity", expected_equity, snapshot.get("equity"),
                "equity = capital + realized + unrealized")
        mv_sum = round(sum(float(p.get("market_value") or 0)
                           for p in positions), 2)
        balance("portfolio_value_identity",
                round(float(snapshot.get("cash") or 0) + mv_sum, 2),
                snapshot.get("equity"), "cash + Σ market value")
    else:
        checks.append(_check("equity_identity", WARN,
                             "marks missing for some symbols — equity is "
                             "computed with known MTM only "
                             "(equity_complete=false)"))
    return _result("portfolio", checks,
                   ledger_trades=len(ledger_rows),
                   portfolio_version=snapshot.get("portfolio_version"))


# ── Part J: Replay validation ────────────────────────────────────────────────

def validate_replay(run_id: Optional[str] = None,
                    verify_result: Optional[Dict[str, Any]] = None
                    ) -> Dict[str, Any]:
    """Orchestrates the existing replay integrity checker
    (backtest_replay.replay_verify) — replay ↔ ledger ↔ portfolio ↔ event
    store must agree with no missing, duplicate, or drifted events."""
    checks: List[Dict[str, Any]] = []
    if verify_result is None:
        import backtest_portfolio as bp
        if not run_id:
            runs = [r for r in bp.list_runs(limit=10)
                    if r.get("status") == "COMPLETED"]
            run_id = runs[0]["run_id"] if runs else None
        if not run_id:
            checks.append(_check("completed_run_available", INSUFFICIENT,
                                 "no completed backtest runs to verify"))
            return _result("replay", checks, verdict=INSUFFICIENT)
        from backtest_replay import replay_verify
        verify_result = replay_verify(run_id)

    if not verify_result.get("ok"):
        checks.append(_check("replay_verify", FAIL,
                             str(verify_result.get("error") or
                                 "replay_verify failed")))
        return _result("replay", checks, run_id=run_id)

    for c in verify_result.get("checks") or []:
        checks.append(_check(c.get("check") or "replay_check",
                             PASS if c.get("status") == PASS else FAIL,
                             str(c.get("detail") or "")))
    checks.append(_check("replay_verify_verdict",
                         PASS if verify_result.get("verdict") == PASS
                         else FAIL,
                         f"replay_verify verdict: "
                         f"{verify_result.get('verdict')}"))
    return _result("replay", checks,
                   run_id=run_id or verify_result.get("run_id"))


# ── Part K: AI decision validation ───────────────────────────────────────────

def validate_ai_decisions(run_id: Optional[str] = None,
                          events: Optional[List[Dict[str, Any]]] = None,
                          stored_validation: Optional[Dict[str, Any]] = None
                          ) -> Dict[str, Any]:
    """Decision determinism re-derived from STORED payloads only — never a
    live re-evaluation. The heavyweight pipeline re-execution proof is the
    STORED validate_run verdict on the run record (orchestrated, not rerun)."""
    checks: List[Dict[str, Any]] = []
    if events is None:
        import backtest_portfolio as bp
        from pipeline_events import query_events
        if not run_id:
            runs = [r for r in bp.list_runs(limit=10)
                    if r.get("status") == "COMPLETED"]
            run_id = runs[0]["run_id"] if runs else None
        if not run_id:
            checks.append(_check("decisions_available", INSUFFICIENT,
                                 "no completed backtest runs with stored "
                                 "decisions"))
            return _result("ai_decision", checks, verdict=INSUFFICIENT)
        events = query_events(run_id=run_id, mode="BACKTEST",
                              stage="AI_DECISION", limit=5000)
        if stored_validation is None:
            run = bp.get_run(run_id) or {}
            stored_validation = run.get("validation") or {}

    decisions = [e for e in events
                 if e.get("event_type") in _DECISION_TYPES]
    if not decisions:
        checks.append(_check("decisions_available", INSUFFICIENT,
                             "no stored decision events in scope"))
        return _result("ai_decision", checks, verdict=INSUFFICIENT,
                       run_id=run_id)

    # 1. determinism: same (scan_id, symbol) → identical decision + confidence
    seen: Dict[tuple, Dict[str, Any]] = {}
    conflicts: List[str] = []
    for e in decisions:
        key = (e.get("scan_id"), str(e.get("symbol") or "").upper())
        payload = e.get("payload") or {}
        prev = seen.get(key)
        if prev is None:
            seen[key] = e
            continue
        prev_p = prev.get("payload") or {}
        if (prev.get("event_type") != e.get("event_type")
                or prev_p.get("confidence") != payload.get("confidence")):
            conflicts.append(f"{key[1]}@{key[0]}")
    checks.append(_check(
        "same_input_same_decision", PASS if not conflicts else FAIL,
        f"{len(conflicts)} (scan, symbol) pairs with conflicting stored "
        f"decisions/confidence: {conflicts[:5] or 'none'}"))

    # 2. confidence bounds
    bad_conf = [e for e in decisions
                if (e.get("payload") or {}).get("confidence") is not None
                and not (0.0 <= float((e.get("payload") or {})["confidence"])
                         <= 100.0)]
    checks.append(_check("confidence_bounds", PASS if not bad_conf else FAIL,
                         f"{len(bad_conf)} decisions with confidence outside "
                         "[0, 100]"))

    # 3. stored pipeline re-execution proof (validate_run — never rerun here)
    sv = stored_validation or {}
    verdict = sv.get("verdict")
    if verdict in ("MATCH", "NO_DECISIONS"):
        checks.append(_check("stored_pipeline_validation", PASS,
                             f"stored validate_run verdict: {verdict}"))
    elif verdict:
        checks.append(_check("stored_pipeline_validation", FAIL,
                             f"stored validate_run verdict: {verdict} "
                             f"({len(sv.get('mismatches') or [])} mismatches)"))
    else:
        checks.append(_check("stored_pipeline_validation", WARN,
                             "no stored validate_run result — run the "
                             "backtest /validate endpoint to certify "
                             "decision ≡ pipeline"))
    return _result("ai_decision", checks, run_id=run_id,
                   decisions_checked=len(decisions))


# ── Part L: Performance validation ───────────────────────────────────────────

def validate_performance(source: str = "paper",
                         run_id: Optional[str] = None,
                         trades: Optional[List[Dict[str, Any]]] = None,
                         capital: Optional[float] = None) -> Dict[str, Any]:
    """Internal consistency of the performance metrics: Sharpe/Sortino/
    drawdown/win rate/expectancy/profit factor/recovery/capital growth/
    confidence calibration/strategy ranking, all from the single metrics
    engine (expectancy.compute_metrics) over the canonical trade records."""
    import strategy_lab as sl
    from expectancy import compute_metrics

    if trades is None:
        trades = sl._load_trades(source, run_id)
    if capital is None:
        capital = sl._capital_for(source, run_id)
    closed = sl._closed(trades)

    checks: List[Dict[str, Any]] = []
    if len(closed) < MIN_EVIDENCE:
        checks.append(_check("evidence", INSUFFICIENT,
                             f"only {len(closed)} closed trades "
                             f"(< {MIN_EVIDENCE})"))
        return _result("performance", checks, verdict=INSUFFICIENT,
                       source=source, run_id=run_id)

    m = compute_metrics(sl._as_metric_rows(trades))
    pnls = [float(t.get("realized_pnl") or 0.0) for t in closed]
    total_pnl = round(sum(pnls), 2)
    wins = sum(1 for p in pnls if p > 0)

    checks.append(_check("win_rate_bounds",
                         PASS if 0.0 <= float(m["win_rate"]) <= 100.0
                         else FAIL,
                         f"win_rate={m['win_rate']}%"))
    checks.append(_check(
        "trade_count_consistent",
        PASS if int(m["trades"]) == len(closed) else FAIL,
        f"metrics engine saw {m['trades']} trades; ledger has {len(closed)}"))

    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf_dir_ok = ((gross_win > gross_loss) == (float(m["profit_factor"]) > 1.0)
                 if gross_loss > 0 else True)
    checks.append(_check(
        "profit_factor_direction", PASS if pf_dir_ok else FAIL,
        f"gross win {round(gross_win, 2)} vs gross loss "
        f"{round(gross_loss, 2)}; profit_factor={m['profit_factor']}"))

    checks.append(_check("drawdown_non_negative",
                         PASS if float(m["max_drawdown"]) >= 0.0 else FAIL,
                         f"max_drawdown={m['max_drawdown']}"))
    finite = all(math.isfinite(float(m[k])) for k in
                 ("sharpe", "sortino", "expectancy", "recovery_factor"))
    checks.append(_check("ratios_finite", PASS if finite else FAIL,
                         "sharpe/sortino/expectancy/recovery_factor all "
                         "finite" if finite else "non-finite ratio detected"))

    if capital and capital > 0:
        growth = round(total_pnl / capital * 100.0, 2)
        checks.append(_check("capital_growth_consistent",
                             PASS if abs(growth) < 1000.0 else WARN,
                             f"capital growth {growth}% on capital "
                             f"{capital}"))
    else:
        checks.append(_check("capital_growth_consistent", WARN,
                             "portfolio capital unavailable — growth "
                             "unverifiable"))

    # confidence calibration: high-confidence trades should not win far less
    hi = [t for t in closed if float(t.get("confidence") or 0) >= 70.0]
    lo = [t for t in closed if t.get("confidence") is not None
          and float(t.get("confidence") or 0) < 70.0]
    if len(hi) >= MIN_EVIDENCE and len(lo) >= MIN_EVIDENCE:
        hi_wr = sum(1 for t in hi if float(t.get("realized_pnl") or 0) > 0) \
            / len(hi) * 100.0
        lo_wr = sum(1 for t in lo if float(t.get("realized_pnl") or 0) > 0) \
            / len(lo) * 100.0
        checks.append(_check(
            "confidence_calibration",
            PASS if hi_wr + 15.0 >= lo_wr else WARN,
            f"win rate ≥70% conf: {round(hi_wr, 1)}% vs <70% conf: "
            f"{round(lo_wr, 1)}% "
            "(inverted calibration is flagged, never auto-corrected)"))
    else:
        checks.append(_check("confidence_calibration", INSUFFICIENT,
                             f"need ≥{MIN_EVIDENCE} trades in both "
                             "confidence buckets"))

    # strategy ranking: per-strategy PnL must sum exactly to total PnL
    by_strategy: Dict[str, float] = {}
    for t in closed:
        key = str(t.get("strategy_name") or t.get("strategy_id") or "UNKNOWN")
        by_strategy[key] = by_strategy.get(key, 0.0) \
            + float(t.get("realized_pnl") or 0.0)
    strat_sum = round(sum(by_strategy.values()), 2)
    checks.append(_check(
        "strategy_ranking_conserved",
        PASS if abs(strat_sum - total_pnl) <= TOL else FAIL,
        f"Σ per-strategy PnL {strat_sum} vs total {total_pnl}"))
    ranking = sorted(({"strategy": k, "pnl": round(v, 2)}
                      for k, v in by_strategy.items()),
                     key=lambda r: -r["pnl"])
    return _result("performance", checks, source=source, run_id=run_id,
                   metrics={k: m[k] for k in
                            ("trades", "win_rate", "sharpe", "sortino",
                             "expectancy", "profit_factor", "max_drawdown",
                             "recovery_factor")},
                   total_pnl=total_pnl, wins=wins,
                   strategy_ranking=ranking[:10])


ALL_VALIDATORS = {
    "data": validate_data,
    "pipeline": validate_pipeline,
    "portfolio": validate_portfolio,
    "replay": validate_replay,
    "ai_decision": validate_ai_decisions,
    "performance": validate_performance,
}
