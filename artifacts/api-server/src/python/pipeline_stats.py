"""
pipeline_stats.py — Phase 20 paper-trading execution pipeline diagnostics.

Returns a single snapshot that shows exactly how many candidates survive
each stage of the pipeline, so operators can see at a glance where the
funnel is blocked.

Pipeline stages
---------------
1. stocks_scanned          — universe size (e.g. 50 NIFTY 50 symbols)
2. live_data               — symbols with LIVE / NEAR_LIVE data quality
3. passed_intelligence     — action ≠ IGNORE (WATCH or better)
4. buy_signals             — action ∈ {BUY, STRONG BUY}  (paper_eligible at scan level)
5. global_gates_passed     — phase20 global gates all green
6. candidates_evaluated    — per-candidate gate evaluation count
7. candidates_eligible     — passed every per-candidate gate
8. paper_orders_today      — ledger entries created today
9. open_positions          — currently open positions

Advisory-only, read-only — never modifies any state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_pipeline_stats() -> Dict[str, Any]:
    """
    Collect one snapshot of every pipeline stage and return a dict suitable
    for the Pipeline Statistics UI panel.  Non-blocking: errors in individual
    stages are captured and surfaced in the `stage_errors` list.
    """
    stage_errors: List[str] = []

    # ── Stage 1-4: Scan snapshot ─────────────────────────────────────────────
    scan_total          = 0
    scan_live           = 0
    scan_passed_intel   = 0   # action != IGNORE
    scan_buy_signals    = 0   # action in BUY / STRONG BUY
    scan_paper_eligible = 0
    scan_id             = None
    snapshot_ts         = None
    scan_available      = False
    top_candidates: List[Dict[str, Any]] = []

    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
        scan_available = bool(ctx.get("available"))
        scan_id        = ctx.get("scan_id")
        snapshot_ts    = ctx.get("snapshot_ts")
        symbols_ctx    = ctx.get("symbols") or {}

        scan_total = len(symbols_ctx)
        for sym, rec in symbols_ctx.items():
            dq     = str(rec.get("data_quality") or "").upper()
            action = str(rec.get("final_action") or "").upper()
            opp    = float(rec.get("opportunity_score") or 0)
            conf   = float(rec.get("confidence") or 0)

            if dq in ("LIVE", "NEAR_LIVE"):
                scan_live += 1
            if action != "IGNORE":
                scan_passed_intel += 1
            if action in ("BUY", "STRONG BUY"):
                scan_buy_signals += 1
                if rec.get("paper_eligible"):
                    scan_paper_eligible += 1
                top_candidates.append({
                    "symbol":            sym,
                    "action":            action,
                    "opportunity_score": opp,
                    "confidence":        conf,
                    "technical_score":   float(rec.get("technical_score") or 0),
                    "rr_ratio":          float(rec.get("rr_ratio") or 0),
                    "regime":            rec.get("regime", ""),
                    "data_quality":      dq,
                })
        top_candidates.sort(key=lambda x: x["opportunity_score"], reverse=True)

    except Exception as exc:
        stage_errors.append(f"scan_context: {exc}")

    # ── Stage 5-7: Phase20 gate evaluation ───────────────────────────────────
    global_pass            = False
    global_gates: List[Dict[str, Any]] = []
    candidates_evaluated   = 0
    candidates_eligible    = 0
    candidate_details: List[Dict[str, Any]] = []
    eval_available         = False

    # Whether auto-paper entries are currently enabled (for per-candidate
    # "auto_entry_attempted" display in the UI).
    _auto_entries_on = False
    try:
        from phase20_store import get_settings as _gs
        _auto_entries_on = bool(_gs().get("auto_paper_entries", False))
    except Exception:
        pass

    # Last run_auto_entries outcome (persisted by the executor) — lets us
    # distinguish "gate failed before executor" (SKIPPED_GATE_FAILED) from
    # "executor attempted and order was created" (ORDER_CREATED).
    _last_run: Dict[str, Any] = {}
    try:
        from phase20_store import kv_get as _kv
        _last_run = _kv("last_auto_entries_result") or {}
    except Exception:
        pass
    _last_created_syms: set = {
        c["symbol"] for c in (_last_run.get("created") or [])
    }

    try:
        from phase20_gates import evaluate_entries
        ev = evaluate_entries()
        eval_available       = True
        global_pass          = bool(ev.get("global_pass"))
        global_gates         = ev.get("global_gates") or []
        candidates_evaluated = len(ev.get("candidates") or [])
        candidates_eligible  = int(ev.get("eligible_count") or 0)

        for c in (ev.get("candidates") or []):
            sym = c.get("symbol") or ""
            is_eligible = bool(c.get("eligible"))
            # Build a {gate_name: reason_text} map for every gate that failed,
            # so the UI can display the human-readable reason alongside the gate
            # pill (e.g. "per_stock_cap: Post-trade DRREDDY exposure 21.5% (cap 20%)").
            # Only failed gates are included — passing gates are not shown.
            failed_gate_reasons: Dict[str, str] = {
                g["gate"]: str(g.get("reason") or "")
                for g in (c.get("gates") or [])
                if not g.get("passed")
            }
            # Determine auto-entry outcome:
            # SKIPPED_GATE_FAILED — failed evaluate_entries(); executor never ran
            # ORDER_CREATED       — executor ran and confirmed a paper trade
            # ELIGIBLE            — passed gates; executor would run (auto ON)
            #                       or would have run (auto OFF / market closed)
            if is_eligible:
                _outcome = "ORDER_CREATED" if sym in _last_created_syms else "ELIGIBLE"
                _auto_attempted = _auto_entries_on
            else:
                _outcome = "SKIPPED_GATE_FAILED"
                _auto_attempted = False  # executor never ran for this candidate

            candidate_details.append({
                "symbol":               sym,
                "eligible":             is_eligible,
                "failed_gates":         c.get("failed_gates") or [],
                "failed_gate_reasons":  failed_gate_reasons,
                "auto_entry_attempted": _auto_attempted,
                "entry_outcome":        _outcome,
                "opportunity_score": float(c.get("opportunity_score") or 0),
                "confidence":        float(c.get("confidence") or 0),
            })

    except Exception as exc:
        stage_errors.append(f"evaluate_entries: {exc}")

    # ── Consecutive-block counts from buy_pipeline_eval_history ──────────────
    # For each blocked candidate, count how many consecutive BUY-candidate
    # pipeline evaluations it has appeared in as blocked.  We read from the
    # dedicated buy_pipeline_eval_history key (written only by the canonical
    # default evaluate_entries() call — not by ad-hoc audit callers that pass
    # an explicit candidate_symbols list).  This prevents audit invocations for
    # the same scan_id from contaminating the streak via the dedup guard.
    #
    # Walk newest → oldest; the first entry where the symbol is absent
    # terminates the streak so a single clean scan correctly resets it to zero.
    consecutive_blocks: Dict[str, int] = {}
    try:
        from phase20_store import kv_get
        _bp_hist: List[Dict[str, Any]] = kv_get("buy_pipeline_eval_history") or []
        # Symbols of interest: only those currently blocked in candidate_details
        _blocked_now = {
            c["symbol"] for c in candidate_details
            if c.get("symbol") and not c.get("eligible")
        }
        if _blocked_now and _bp_hist:
            for sym in _blocked_now:
                count = 0
                # Walk history newest → oldest; stop when symbol not blocked
                for entry in reversed(_bp_hist):
                    if sym in set(entry.get("blocked_symbols") or []):
                        count += 1
                    else:
                        break
                if count > 0:
                    consecutive_blocks[sym] = count
    except Exception as exc:
        stage_errors.append(f"consecutive_blocks: {exc}")

    # Attach consecutive_blocks to candidate_details
    for det in candidate_details:
        sym = det.get("symbol")
        if sym and sym in consecutive_blocks:
            det["consecutive_blocks"] = consecutive_blocks[sym]

    # ── Stage 8-9: Paper trade ledger ────────────────────────────────────────
    paper_orders_today = 0
    open_positions     = 0
    recent_trades: List[Dict[str, Any]] = []

    try:
        from phase20_executor import get_ledger, get_open_trades
        today = datetime.now(timezone.utc).date().isoformat()
        for t in get_ledger(200):
            if str(t.get("simulated_order_ts") or "").startswith(today):
                paper_orders_today += 1
        open_positions = len(get_open_trades())

        for t in get_ledger(10):
            recent_trades.append({
                "trade_id":    t.get("trade_id"),
                "symbol":      t.get("symbol"),
                "status":      t.get("status"),
                "fill_price":  t.get("fill_price"),
                "quantity":    t.get("quantity"),
                "created_at":  t.get("simulated_order_ts"),
            })
    except Exception as exc:
        stage_errors.append(f"ledger: {exc}")

    # ── Settings snapshot ─────────────────────────────────────────────────────
    settings_snapshot: Dict[str, Any] = {}
    try:
        from phase20_store import get_settings
        s = get_settings()
        settings_snapshot = {
            "min_confidence":       s.get("min_confidence"),
            "min_opportunity_score":s.get("min_opportunity_score"),
            "min_trade_quality":    s.get("min_trade_quality_score"),
            "min_risk_reward":      s.get("min_risk_reward"),
            "max_trades_per_day":   s.get("max_trades_per_day"),
            "auto_paper_entries":   s.get("auto_paper_entries"),
        }
    except Exception as exc:
        stage_errors.append(f"settings: {exc}")

    # ── Gate blocked-count summary ────────────────────────────────────────────
    # Total BUY signals plus, per gate, how many candidates that gate blocks.
    # Failed GLOBAL gates block every BUY candidate; per-candidate gate counts
    # come from each candidate's failed_gates list.
    failed_global = [g["gate"] for g in global_gates if not g.get("passed")]
    scan_stale    = "scan_fresh" in failed_global
    market_closed = "market_open" in failed_global

    per_gate_counts: Dict[str, int] = {}
    _global_set = set(failed_global)
    for c in candidate_details:
        for g in c.get("failed_gates") or []:
            if g in _global_set:
                continue  # already counted as a global block — avoid double display
            per_gate_counts[g] = per_gate_counts.get(g, 0) + 1

    gate_summary = {
        "total_buy_signals": scan_buy_signals,
        "scan_stale":        scan_stale,
        "market_closed":     market_closed,
        "failed_global_gates": failed_global,
        # A failed global gate blocks ALL buy signals
        "global_blocked_counts": {g: scan_buy_signals for g in failed_global},
        "candidate_blocked_counts": per_gate_counts,
    }

    # ── Funnel stages for UI ──────────────────────────────────────────────────
    funnel = [
        {
            "stage":  "stocks_scanned",
            "label":  "Stocks Scanned",
            "count":  scan_total,
            "detail": f"{scan_live} with LIVE data",
            "passed": scan_total > 0,
        },
        {
            "stage":  "passed_intelligence",
            "label":  "Passed Intelligence",
            "count":  scan_passed_intel,
            "detail": f"action ≠ IGNORE  ({scan_total - scan_passed_intel} ignored)",
            "passed": scan_passed_intel > 0,
        },
        {
            "stage":  "buy_signals",
            "label":  "BUY Signals Generated",
            "count":  scan_buy_signals,
            "detail": (f"{scan_buy_signals} BUY / STRONG BUY out of {scan_total}"
                       if scan_buy_signals > 0
                       else "⚠ No BUY signals — opportunity scores below threshold"),
            "passed": scan_buy_signals > 0,
            "blocker": scan_buy_signals == 0,
        },
        {
            "stage":  "global_gates",
            "label":  "Global Gates Passed",
            "count":  1 if global_pass else 0,
            "detail": (
                "All global gates green"
                if global_pass
                else ("⚠ " + "; ".join(
                    f"{g['gate']}: {g['reason']}"
                    for g in global_gates if not g.get("passed")
                )[:200])
            ),
            "passed": global_pass,
            "blocker": not global_pass,
            "gates":  [
                {"gate": g["gate"], "passed": g["passed"], "reason": g["reason"]}
                for g in global_gates
            ],
        },
        {
            "stage":  "candidates_evaluated",
            "label":  "Candidates Evaluated",
            "count":  candidates_evaluated,
            "detail": (f"{candidates_eligible} eligible of {candidates_evaluated} evaluated"
                       if candidates_evaluated > 0
                       else "0 candidates in pool (upstream stage blocked)"),
            "passed": candidates_evaluated > 0,
        },
        {
            "stage":  "candidates_eligible",
            "label":  "Passed All Entry Gates",
            "count":  candidates_eligible,
            "detail": (
                f"{candidates_eligible} ready for paper execution"
                if candidates_eligible > 0
                else (
                    "⚠ " + "; ".join(
                        f"{c['symbol']}: {', '.join(c['failed_gates'][:3])}"
                        for c in candidate_details[:5] if not c["eligible"]
                    )[:200]
                    if candidate_details
                    else "No candidates reached per-entry gate evaluation"
                )
            ),
            "passed": candidates_eligible > 0,
            "blocker": candidates_evaluated > 0 and candidates_eligible == 0,
        },
        {
            "stage":  "paper_orders_today",
            "label":  "Paper Orders Executed Today",
            "count":  paper_orders_today,
            "detail": f"{open_positions} position(s) currently open",
            "passed": paper_orders_today > 0 or open_positions > 0,
        },
    ]

    # Identify where pipeline first stops
    first_blocker: Optional[str] = None
    for f in funnel:
        if f.get("blocker") or (not f["passed"] and f["stage"] not in
                                ("paper_orders_today",)):
            first_blocker = f["stage"]
            break

    return {
        "generated_at":        _now(),
        "scan_id":             scan_id,
        "snapshot_ts":         snapshot_ts,
        "scan_available":      scan_available,
        "eval_available":      eval_available,
        "funnel":              funnel,
        "first_blocker":       first_blocker,
        "top_buy_candidates":  top_candidates[:10],
        "candidate_gate_details": candidate_details[:10],
        "gate_summary":        gate_summary,
        "recent_trades":       recent_trades,
        "settings":            settings_snapshot,
        "stage_errors":        stage_errors,
        "advisory_only":       True,
        "paper_only":          True,
        # Flat summary for quick reads
        "summary": {
            "stocks_scanned":        scan_total,
            "live_data_count":       scan_live,
            "passed_intelligence":   scan_passed_intel,
            "buy_signals":           scan_buy_signals,
            "global_pass":           global_pass,
            "candidates_evaluated":  candidates_evaluated,
            "candidates_eligible":   candidates_eligible,
            "paper_orders_today":    paper_orders_today,
            "open_positions":        open_positions,
        },
    }
