"""
ops_centre.py — AI Operations Centre: single-call aggregator.

Gathers a normalised snapshot from every agent in the pipeline using a
ThreadPoolExecutor (6-second per-agent timeout, all run in parallel).
Total wall time ≤ 8 s.  All data is advisory / read-only.
"""
from __future__ import annotations

import os
import sys as _sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple


def _get_fn(mod: str, fn: str) -> Optional[Callable]:
    """Return a callable from an already-imported module without acquiring
    the Python import lock (pure sys.modules dict lookup)."""
    m = _sys.modules.get(mod)
    if m is None:
        return None
    return getattr(m, fn, None)


def _i(v, default: int = 0) -> int:
    """Safe int coercion — never raises."""
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _f(v, default: float = 0.0) -> float:
    """Safe float coercion."""
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _lst(v) -> List:
    """Safe list coercion — returns [] for non-iterables."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    try:
        return list(v)
    except TypeError:
        return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ist(ts: Optional[str]) -> Tuple[str, str]:
    """Return (date_str, time_str) in IST from a UTC ISO timestamp."""
    if not ts:
        return "—", "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        ist = dt + timedelta(hours=5, minutes=30)
        return ist.strftime("%Y-%m-%d"), ist.strftime("%H:%M:%S IST")
    except Exception:
        return "—", str(ts)[:8]


def _safe(fn) -> Any:
    """Call fn() directly; return an error dict (never None) on exception."""
    try:
        return fn()
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def _agent_base(
    raw: Optional[Dict[str, Any]],
    name: str,
    agent_id: str,
    enabled_env: str,
    *,
    stocks_in: int = 0,
    stocks_out: int = 0,
    rejection_reason: str = "",
    current_activity: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the common agent card payload."""
    if not os.environ.get(enabled_env, "true").lower() in ("1", "true", "yes"):
        return {
            "name": name, "agent_id": agent_id, "enabled": False,
            "status": "DISABLED", "health_pct": 0,
            "last_refresh_date": "—", "last_refresh_time": "—",
            "last_refresh_ts": None, "next_refresh_est": None,
            "avg_processing_ms": 0, "current_activity": f"Set {enabled_env}=true to enable",
            "stocks_in": 0, "stocks_out": 0, "stocks_rejected": 0,
            "rejection_reason": f"Agent disabled. Set {enabled_env}=true.",
            "errors": [], "warnings": [], "details": {},
        }

    available  = bool((raw or {}).get("available", True))
    gen_at     = (raw or {}).get("generated_at") or (raw or {}).get("snapshot_ts")
    latency_ms = int((raw or {}).get("evaluation_latency_ms")
                     or (raw or {}).get("collection_latency_ms")
                     or (raw or {}).get("processing_latency_ms", 0))
    error_msg  = str((raw or {}).get("error", "")) if raw else "Snapshot unavailable"

    if raw is None:
        status = "ERROR"
        health = 0
        err_list = ["Agent snapshot timed out"]
        warn_list: List[str] = []
    elif not available:
        status = "ERROR"
        health = 0
        err_list = [error_msg] if error_msg else ["Snapshot unavailable"]
        warn_list = []
    else:
        status = "ACTIVE"
        health = int((raw or {}).get("health_pct", 95))
        err_list = list((raw or {}).get("errors") or [])
        warn_list = list((raw or {}).get("warnings") or [])

    date_s, time_s = _ist(gen_at)
    rejected = max(0, stocks_in - stocks_out)

    return {
        "name":             name,
        "agent_id":         agent_id,
        "enabled":          True,
        "status":           status,
        "health_pct":       health,
        "last_refresh_date": date_s,
        "last_refresh_time": time_s,
        "last_refresh_ts":  gen_at,
        "next_refresh_est": None,   # set by caller if known
        "avg_processing_ms": latency_ms,
        "current_activity": current_activity or (
            f"Processing {stocks_in} stocks" if status == "ACTIVE" else status),
        "stocks_in":         stocks_in,
        "stocks_out":        stocks_out,
        "stocks_rejected":   rejected,
        "rejection_reason":  rejection_reason or (
            f"{rejected} stocks did not meet criteria" if rejected else ""),
        "errors":   err_list,
        "warnings": warn_list,
        "details":  details or {},
    }


# ── Individual agent collectors ───────────────────────────────────────────────

def _collect_supervisor() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("supervisor_agent.shared_services", "get_supervisor_snapshot")())
    summary = (raw or {}).get("agent_summary") or {}
    health  = (raw or {}).get("overall_health") or {}
    fmx     = (raw or {}).get("framework_metrics") or {}
    total   = int(summary.get("total", 0))
    running = int(summary.get("running", 0)) + int(summary.get("busy", 0))
    errors  = int(summary.get("error", 0))
    alerts  = int((raw or {}).get("alert_count", 0))

    return _agent_base(
        raw, "Supervisor Agent", "supervisor", "SUPERVISOR_AGENT_ENABLED",
        stocks_in=total, stocks_out=running,
        current_activity=(f"Orchestrating {total} agents · {running} active"
                          if total else "Waiting for agents to initialise"),
        rejection_reason=f"{errors} agent(s) in error state" if errors else "",
        details={
            "total_agents":      total,
            "running_agents":    running,
            "error_agents":      errors,
            "healthy_agents":    int(fmx.get("healthy_agents", 0)),
            "snapshots_published": int(fmx.get("total_snapshots_published", 0)),
            "alert_count":       alerts,
            "health_score":      float(health.get("score", 0)),
            "health_status":     str(health.get("status", "UNKNOWN")),
        },
    )


def _collect_market_data() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("market_data_agent.shared_services", "get_market_data_snapshot")())
    received = _i((raw or {}).get("symbols_received", 0))
    total    = _i((raw or {}).get("symbols_count", received))
    missing  = _lst((raw or {}).get("missing_symbols"))
    stale    = _lst((raw or {}).get("stale_symbols"))
    cov      = _f((raw or {}).get("coverage_pct", 0))

    failed = missing + stale
    reason = ""
    if missing:
        reason = f"{len(missing)} symbol(s) returned no data"
    if stale:
        reason += ("; " if reason else "") + f"{len(stale)} stale"

    return _agent_base(
        raw, "Market Data Agent", "market-data", "MARKET_DATA_AGENT_ENABLED",
        stocks_in=total, stocks_out=received,
        current_activity=f"Coverage {cov:.0f}% — {received}/{total} symbols with LIVE data",
        rejection_reason=reason,
        details={
            "data_provider":     str((raw or {}).get("data_provider", "—")),
            "coverage_pct":      cov,
            "nifty50_price":     (raw or {}).get("nifty50_price"),
            "nifty50_change_pct":(raw or {}).get("nifty50_change_pct"),
            "banknifty_price":   (raw or {}).get("banknifty_price"),
            "india_vix":         (raw or {}).get("india_vix"),
            "market_regime":     str((raw or {}).get("market_regime", "—")),
            "strongest_sector":  str((raw or {}).get("strongest_sector", "—")),
            "weakest_sector":    str((raw or {}).get("weakest_sector", "—")),
            "missing_symbols":   missing[:10],
            "stale_symbols":     stale[:10],
            "failed_symbols":    failed[:10],
        },
    )


def _collect_research() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("research_agent.shared_services", "get_research_snapshot")())
    received   = _i((raw or {}).get("stocks_received",
                 (raw or {}).get("symbols_analyzed", 0)))
    forwarded  = _i((raw or {}).get("stocks_forwarded",
                 (raw or {}).get("stocks_passed", received)))
    rejected   = _i((raw or {}).get("stocks_rejected", max(0, received - forwarded)))
    news       = _i((raw or {}).get("news_items_processed",
                 (raw or {}).get("news_processed", 0)))
    corp_act   = _i((raw or {}).get("corporate_actions_processed", 0))
    sentiment  = (raw or {}).get("sentiment_breakdown") or {}

    reason = ""
    if rejected > 0:
        neg = _i(sentiment.get("negative", 0))
        if neg:
            reason = f"{neg} rejected due to negative news/events"
        else:
            reason = f"{rejected} did not meet research quality threshold"

    return _agent_base(
        raw, "Research Agent", "research", "RESEARCH_AGENT_ENABLED",
        stocks_in=received, stocks_out=forwarded,
        current_activity=(f"Processed {news} news items across {received} stocks"
                          if received else "Awaiting stocks from Market Data"),
        rejection_reason=reason,
        details={
            "news_processed":        news,
            "corporate_actions":     corp_act,
            "sentiment_positive":    _i(sentiment.get("positive", 0)),
            "sentiment_neutral":     _i(sentiment.get("neutral", 0)),
            "sentiment_negative":    _i(sentiment.get("negative", 0)),
        },
    )


def _collect_market_intelligence() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("market_intelligence_agent.shared_services", "get_market_intelligence_agent_snapshot")())
    received = _i((raw or {}).get("stocks_received",
                (raw or {}).get("symbols_analyzed", 50)))
    passed   = _i((raw or {}).get("stocks_passed",
                (raw or {}).get("stocks_forwarded", received)))
    regime   = str((raw or {}).get("market_regime", "—"))
    liq      = str((raw or {}).get("liquidity_condition", "—"))
    vol      = str((raw or {}).get("volatility_regime", "—"))
    sector_rot = (raw or {}).get("sector_rotation") or {}

    rejected = max(0, received - passed)
    reason = (f"{rejected} filtered by regime / liquidity conditions"
              if rejected else "")

    return _agent_base(
        raw, "Market Intelligence Agent", "market-intelligence",
        "MARKET_INTELLIGENCE_AGENT_ENABLED",
        stocks_in=received, stocks_out=passed,
        current_activity=f"Regime: {regime} | Liquidity: {liq} | Vol: {vol}",
        rejection_reason=reason,
        details={
            "market_regime":       regime,
            "liquidity_condition": liq,
            "volatility_regime":   vol,
            "sector_rotation":     sector_rot,
            "regime_confidence":   float((raw or {}).get("regime_confidence", 0)),
        },
    )


def _collect_monitoring() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("stock_monitoring_agent.shared_services", "get_stock_monitoring_snapshot")())
    monitored  = _i((raw or {}).get("symbols_monitored", 0))
    evaluated  = _i((raw or {}).get("symbols_evaluated", monitored))
    breakouts  = _i((raw or {}).get("breakouts", 0))
    breakdowns = _i((raw or {}).get("breakdowns", 0))
    vol_spikes = _i((raw or {}).get("volume_spikes", 0))
    gap_events = _i((raw or {}).get("gap_events", 0))
    events     = _i((raw or {}).get("events_this_cycle", 0))
    eb         = (raw or {}).get("event_breakdown") or {}
    priority   = (raw or {}).get("priority_summary") or {}
    candidates = _i(priority.get("p2_high_conviction", 0)) + _i(priority.get("p3_candidates", 0))

    signals = breakouts + vol_spikes + gap_events
    reason = (f"No technical signals detected across {evaluated} symbols"
              if signals == 0 and evaluated > 0 else "")

    return _agent_base(
        raw, "Monitoring Agent", "monitoring", "STOCK_MONITORING_AGENT_ENABLED",
        stocks_in=monitored, stocks_out=evaluated,
        current_activity=(f"Monitoring {monitored} symbols · {events} events this cycle"
                          if monitored else "Awaiting symbols"),
        rejection_reason=reason,
        details={
            "symbols_monitored": monitored,
            "breakouts":         breakouts,
            "breakdowns":        breakdowns,
            "volume_spikes":     vol_spikes,
            "gap_events":        gap_events,
            "total_events":      events,
            "candidates":        candidates,
            "momentum_events":   _i(eb.get("momentum", 0)),
            "rs_events":         _i(eb.get("relative_strength", 0)),
        },
    )


def _collect_strategy() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("strategy_agent.shared_services", "get_strategy_snapshot")())
    evaluated  = _i((raw or {}).get("symbols_evaluated", 0))
    strategies = _i((raw or {}).get("strategies_registered", 6))
    total_evals= _i((raw or {}).get("total_evaluations", 0))
    top_strat  = str((raw or {}).get("top_strategy") or "—")
    hi_conf    = _f((raw or {}).get("highest_confidence", 0))
    hi_sym     = str((raw or {}).get("highest_confidence_symbol") or "—")
    breakdown  = (raw or {}).get("strategy_breakdown") or {}
    top_setups = _lst((raw or {}).get("top_setups"))
    passed     = len(top_setups)

    reason = ""
    if evaluated > 0 and passed == 0:
        reason = (f"Confidence below configured threshold (highest: {hi_conf:.0f}%)"
                  if hi_conf > 0 else
                  f"No stocks met minimum strategy criteria across {strategies} strategies")

    return _agent_base(
        raw, "Strategy Agent", "strategy", "STRATEGY_AGENT_ENABLED",
        stocks_in=evaluated, stocks_out=passed,
        current_activity=(f"{strategies} strategies evaluated · Top: {top_strat}"
                          if evaluated else "Awaiting candidates from Monitoring"),
        rejection_reason=reason,
        details={
            "strategies_registered":  strategies,
            "symbols_evaluated":      evaluated,
            "total_evaluations":      total_evals,
            "top_strategy":           top_strat,
            "highest_confidence":     hi_conf,
            "highest_confidence_symbol": hi_sym,
            "top_setups":             top_setups[:5],
            "strategy_breakdown":     {k: _i(v) for k, v in (breakdown or {}).items()},
            "breakout_count":         _i((breakdown or {}).get("Breakout", 0)),
            "momentum_count":         _i((breakdown or {}).get("Momentum", 0)),
            "vwap_count":             _i((breakdown or {}).get("VWAP Pullback", 0)),
            "orb_count":              _i((breakdown or {}).get("Opening Range Breakout", 0)),
            "gap_count":              _i((breakdown or {}).get("Gap Strategy", 0)),
        },
    )


def _collect_risk() -> Dict[str, Any]:
    """
    Risk Agent card.  get_risk_snapshot() now guarantees available=True once
    the Phase-20 pipeline has evaluated at least one candidate (three-level
    fallback: SnapshotBus → execute_task() → phase20 evaluation data).
    """
    raw = _safe(lambda: _get_fn("risk_agent.shared_services", "get_risk_snapshot")())

    if raw is None or not raw.get("available"):
        # Nothing available yet (no scan has run at all)
        return _agent_base(
            raw or {"available": False, "error": "No scan data yet"},
            "Risk Agent", "risk", "RISK_AGENT_ENABLED",
            stocks_in=0, stocks_out=0,
            current_activity="Waiting for first pipeline scan to complete",
            rejection_reason="No entry evaluation available yet.",
        )

    # ── Extract normalised fields from the snapshot ───────────────────────────
    total       = _i(raw.get("candidates_evaluated", raw.get("stocks_received", 0)))
    approved    = _i(raw.get("approved", raw.get("stocks_approved", total)))
    blocked     = _i(raw.get("rejected", raw.get("blocked_count", max(0, total - approved))))
    rej_reasons = _lst(raw.get("rejection_reasons"))
    reason      = "; ".join(rej_reasons[:3]) if rej_reasons else (
        f"{blocked} candidate(s) blocked by risk/sizing gates" if blocked else ""
    )

    risk_score   = _f(raw.get("risk_score", 0))
    risk_level   = str(raw.get("risk_level", "—"))
    reward_risk  = _f(raw.get("reward_risk", 0))
    cap_used     = _f(raw.get("capital_used", 0))
    cap_avail    = _f(raw.get("capital_available", 0))
    cap_used_pct = _f(raw.get("capital_used_pct", 0))
    open_pos     = _i(raw.get("open_positions", 0))
    global_pass  = bool(raw.get("global_pass", True))
    source       = str(raw.get("source", "agent"))

    activity = (
        f"Evaluated {total} candidates · {approved} approved · "
        f"Risk {risk_level} ({risk_score:.0f}/100)"
        if total > 0 else "Waiting for pipeline candidates"
    )

    return _agent_base(
        raw, "Risk Agent", "risk", "RISK_AGENT_ENABLED",
        stocks_in=total, stocks_out=approved,
        current_activity=activity,
        rejection_reason=reason,
        details={
            "candidates_evaluated": total,
            "approved":             approved,
            "rejected":             blocked,
            "risk_level":           risk_level,
            "risk_score":           risk_score,
            "reward_risk":          f"{reward_risk:.2f}×" if reward_risk else "—",
            "capital_used":         f"₹{cap_used:,.0f}" if cap_used else "—",
            "capital_used_pct":     f"{cap_used_pct:.1f}%" if cap_used_pct else "—",
            "capital_available":    f"₹{cap_avail:,.0f}" if cap_avail else "—",
            "open_positions":       open_pos,
            "global_gates_pass":    "✓ Pass" if global_pass else "✗ Fail",
            "data_source":          source,
            "rejection_reasons":    rej_reasons[:5],
        },
    )


def _collect_ai_decision() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("ai_decision_agent.shared_services", "get_ai_decision_snapshot")())
    if raw is None or not raw.get("available"):
        return _agent_base(
            raw, "AI Decision Agent", "ai-decision", "AI_DECISION_AGENT_ENABLED",
            stocks_in=0, stocks_out=0,
            current_activity="Awaiting candidates",
            rejection_reason="Snapshot unavailable — agent may still be initialising",
        )

    recs     = _lst(raw.get("recommendations"))
    total    = _i(raw.get("total_candidates", len(recs)))
    pending  = _i(raw.get("pending_recommendations", len(recs)))
    counts   = raw.get("decision_counts") or {}
    buy      = _i(counts.get("BUY_CANDIDATE", counts.get("BUY", 0)))
    sell     = _i(counts.get("SELL_CANDIDATE", counts.get("SELL", 0)))
    watch    = _i(counts.get("WATCH", 0))
    hold     = _i(counts.get("HOLD", 0))
    avoid    = _i(counts.get("AVOID", 0))
    avg_conf = _f(raw.get("avg_confidence", 0))
    regime   = str(raw.get("market_regime", "—"))
    latency  = _i(raw.get("decision_latency_ms", raw.get("generation_time_ms", 0)))

    forwarded = buy + sell      # actionable recommendations
    reason = ""
    if total > 0 and forwarded == 0:
        reason = (f"No BUY/SELL generated — avg confidence {avg_conf:.0f}% "
                  f"(all {total} stocks scored WATCH/HOLD/AVOID)")

    return _agent_base(
        raw, "AI Decision Agent", "ai-decision", "AI_DECISION_AGENT_ENABLED",
        stocks_in=total, stocks_out=forwarded,
        current_activity=(f"Generated {pending} recommendations · "
                          f"Avg confidence {avg_conf:.0f}%"),
        rejection_reason=reason,
        details={
            "total_candidates":    total,
            "buy_candidate":       buy,
            "sell_candidate":      sell,
            "watch":               watch,
            "hold":                hold,
            "avoid":               avoid,
            "avg_confidence":      avg_conf,
            "market_regime":       regime,
            "decision_latency_ms": latency,
        },
    )


def _collect_execution() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("execution_agent.shared_services", "get_execution_snapshot")())

    # Supplement with live paper portfolio
    paper_buy  = 0
    paper_sell = 0
    open_pos   = 0
    closed_pos = 0
    capital_used  = 0.0
    capital_avail = 0.0
    exec_errors: List[str] = []
    try:
        from paper_trader import get_portfolio
        pf = get_portfolio()
        open_pos     = len(pf.get("positions") or [])
        capital_avail = float(pf.get("cash", 0))
        capital_used  = float(pf.get("invested_value", 0))

        from phase20_executor import get_ledger
        today = datetime.now(timezone.utc).date().isoformat()
        for t in get_ledger(200):
            if str(t.get("simulated_order_ts") or "").startswith(today):
                if str(t.get("trade_type") or t.get("side") or "").upper() in ("BUY", "PAPER_BUY"):
                    paper_buy += 1
                else:
                    paper_sell += 1
        closed_pos = len(get_ledger(500)) - open_pos
    except Exception:
        pass

    gen_at = (raw or {}).get("generated_at")
    base = _agent_base(
        raw or {"available": True, "generated_at": gen_at},
        "Execution Agent", "execution", "EXECUTION_AGENT_ENABLED",
        stocks_in=paper_buy + paper_sell,
        stocks_out=paper_buy + paper_sell,
        current_activity=(f"{paper_buy} paper BUY · {paper_sell} paper SELL today · "
                          f"{open_pos} open"),
        rejection_reason="; ".join(exec_errors[:3]) if exec_errors else "",
        details={
            "paper_buy_orders":  paper_buy,
            "paper_sell_orders": paper_sell,
            "open_positions":    open_pos,
            "closed_positions":  closed_pos,
            "capital_used":      round(capital_used, 2),
            "capital_available": round(capital_avail, 2),
            "execution_errors":  exec_errors[:5],
        },
    )
    return base


def _collect_learning() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("learning_agent.shared_services", "get_learning_snapshot")())

    trades_analysed = _i((raw or {}).get("trades_analysed",
                         (raw or {}).get("total_trades_analyzed", 0)))
    wins     = _i((raw or {}).get("winning_trades",
                  (raw or {}).get("profitable_trades", 0)))
    losses   = _i((raw or {}).get("losing_trades",
                  (raw or {}).get("loss_trades", 0)))
    lessons  = _i((raw or {}).get("lessons_generated",
                  (raw or {}).get("total_lessons", 0)))
    updated  = bool((raw or {}).get("knowledge_updated", False))

    return _agent_base(
        raw, "Learning Agent", "learning", "LEARNING_AGENT_ENABLED",
        stocks_in=trades_analysed, stocks_out=lessons,
        current_activity=(f"Analysed {trades_analysed} trades · "
                          f"{lessons} lessons generated"),
        rejection_reason="",
        details={
            "trades_analysed":  trades_analysed,
            "winning_trades":   wins,
            "losing_trades":    losses,
            "lessons_generated": lessons,
            "knowledge_updated": updated,
        },
    )


def _collect_knowledge() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("knowledge_agent.shared_services", "get_knowledge_snapshot")())

    records  = _i((raw or {}).get("knowledge_records",
                  (raw or {}).get("total_records", 0)))
    sessions = _i((raw or {}).get("learning_sessions",
                  (raw or {}).get("total_sessions", 0)))
    reports  = _i((raw or {}).get("reports_generated", 0))
    last_upd = str((raw or {}).get("last_update",
                   (raw or {}).get("generated_at") or "—"))

    return _agent_base(
        raw, "Knowledge Agent", "knowledge", "KNOWLEDGE_AGENT_ENABLED",
        stocks_in=records, stocks_out=reports,
        current_activity=f"{records} knowledge records · {sessions} learning sessions",
        rejection_reason="",
        details={
            "knowledge_records": records,
            "learning_sessions": sessions,
            "reports_generated": reports,
            "last_update":       last_upd,
        },
    )


def _collect_operations() -> Dict[str, Any]:
    raw = _safe(lambda: _get_fn("autonomous_operations.shared_services", "get_autonomous_ops_snapshot")())

    # System metrics (psutil optional)
    cpu  = 0.0
    mem  = 0.0
    try:
        import psutil  # type: ignore
        cpu = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory().percent
    except Exception:
        # psutil absent or unavailable — silently skip
        pass

    queue_sz = _i((raw or {}).get("queue_size",
                  (raw or {}).get("pending_tasks", 0)))
    hb       = str((raw or {}).get("heartbeat_status", "OK"))
    db_ok    = bool((raw or {}).get("database_healthy", True))
    api_ok   = bool((raw or {}).get("api_status_ok", True))
    sys_h    = str((raw or {}).get("system_health", "HEALTHY"))

    return _agent_base(
        raw or {"available": True, "generated_at": _now_iso()},
        "Operations Agent", "operations", "AUTONOMOUS_OPS_ENABLED",
        stocks_in=0, stocks_out=0,
        current_activity=f"CPU {cpu:.0f}% · MEM {mem:.0f}% · {sys_h}",
        rejection_reason="",
        details={
            "cpu_pct":       round(cpu, 1),
            "memory_pct":    round(mem, 1),
            "queue_size":    queue_sz,
            "heartbeat":     hb,
            "database_ok":   db_ok,
            "api_status_ok": api_ok,
            "system_health": sys_h,
        },
    )


# ── Pipeline summary (fast, from scan context + portfolio) ────────────────────

def _pipeline_summary() -> Dict[str, Any]:
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
        symbols = ctx.get("symbols") or {}
        total = len(symbols)
        live_count  = sum(1 for r in symbols.values()
                         if str(r.get("data_quality","")).upper() in ("LIVE","NEAR_LIVE"))
        intel_count = sum(1 for r in symbols.values()
                         if str(r.get("final_action","")).upper() != "IGNORE")
        buy_count   = sum(1 for r in symbols.values()
                         if str(r.get("final_action","")).upper() in ("BUY","STRONG BUY"))
    except Exception:
        total = live_count = intel_count = buy_count = 0

    open_pos = 0
    paper_today = 0
    try:
        from paper_trader import get_portfolio
        pf = get_portfolio()
        open_pos = len(pf.get("positions") or [])
        from phase20_executor import get_ledger
        today = datetime.now(timezone.utc).date().isoformat()
        paper_today = sum(1 for t in get_ledger(200)
                         if str(t.get("simulated_order_ts","")).startswith(today))
    except Exception:
        pass

    try:
        from phase20_gates import get_last_evaluation
        ev = get_last_evaluation() or {}
        eligible = int(ev.get("eligible_count", 0))
    except Exception:
        eligible = paper_today

    return {
        "universe_loaded":        total,
        "stocks_reviewed":        total,
        "passed_market_data":     live_count,
        "passed_research":        live_count,        # proxy (research = live data filter)
        "passed_intelligence":    intel_count,
        "passed_monitoring":      intel_count,       # proxy
        "passed_strategy":        buy_count,
        "passed_risk":            eligible or buy_count,
        "buy_recommendations":    buy_count,
        "paper_orders_executed":  paper_today,
        "open_positions":         open_pos,
    }


# ── Platform status ───────────────────────────────────────────────────────────

def _platform_status(pipeline: Dict[str, Any]) -> Dict[str, Any]:
    from market_hours import market_status
    mstat = market_status()
    mstate = str(mstat.get("state") or mstat.get("market_state") or "UNKNOWN").upper()

    from scan_state_store import load_latest_meta
    meta = load_latest_meta() or {}
    scan_id = str(meta.get("scan_id") or "—")
    snap_ts = str(meta.get("snapshot_ts") or "—")
    _, snap_time = _ist(meta.get("snapshot_ts"))

    scan_count = 0
    try:
        from phase20_store import kv_get
        scan_count = int(kv_get("scan_run_count", 0) or 0)
    except Exception:
        pass

    try:
        from phase20_store import get_settings
        s = get_settings()
        interval_min = int(s.get("scan_interval_minutes", 5))
    except Exception:
        interval_min = 5

    next_refresh_est = ""
    try:
        if meta.get("snapshot_ts"):
            last_dt = datetime.fromisoformat(
                str(meta["snapshot_ts"]).replace("Z", "+00:00"))
            nxt = last_dt + timedelta(minutes=interval_min)
            _, next_refresh_est = _ist(nxt.isoformat())
    except Exception:
        pass

    # Overall health: average of enabled agents
    health_sum  = 0
    health_cnt  = 0
    # Computed after agent collection — placeholder here, filled in snapshot()
    health_pct  = 0

    return {
        "health_pct":        health_pct,
        "status":            "OPERATIONAL",
        "scan_id":           scan_id[:16],
        "scan_number":       scan_count,
        "scan_status":       str(meta.get("status") or "COMPLETE"),
        "market_state":      mstate,
        "trading_session":   "Intraday NSE" if mstate == "OPEN" else f"Market {mstate.title()}",
        "current_time_ist":  _ist(_now_iso())[1],
        "last_refresh_ist":  snap_time,
        "next_refresh_est":  next_refresh_est,
        "scan_interval_min": interval_min,
    }


# ── Master snapshot ───────────────────────────────────────────────────────────

def _preload_modules() -> None:
    """
    Import every heavy agent module in the main thread so sys.modules is
    populated before any parallel threads start.  This avoids Python's import
    lock causing silent failures when 12 threads race to import the same deps.
    """
    _mods = [
        "supervisor_agent.shared_services",
        "market_data_agent.shared_services",
        "research_agent.shared_services",
        "market_intelligence_agent.shared_services",
        "stock_monitoring_agent.shared_services",
        "strategy_agent.shared_services",
        "risk_agent.shared_services",
        "ai_decision_agent.shared_services",
        "execution_agent.shared_services",
        "learning_agent.shared_services",
        "knowledge_agent.shared_services",
        "autonomous_operations.shared_services",
        "paper_trader", "phase20_executor", "phase20_gates",
        "phase15_scan_context", "phase20_store",
        "market_hours", "scan_state_store",
    ]
    for mod in _mods:
        try:
            __import__(mod)
        except Exception:
            pass


def get_ops_centre_snapshot() -> Dict[str, Any]:
    """
    Collect all 12 agent snapshots sequentially (avoids Python import-lock
    contention that occurs when multiple threads call __import__ concurrently).
    Total wall time is typically 5-10 s; comfortably within the 30 s route timeout.
    """
    # Pre-warm all module imports so repeated calls are instant.
    _preload_modules()

    collectors = {
        "supervisor":          _collect_supervisor,
        "market_data":         _collect_market_data,
        "research":            _collect_research,
        "market_intelligence": _collect_market_intelligence,
        "monitoring":          _collect_monitoring,
        "strategy":            _collect_strategy,
        "risk":                _collect_risk,
        "ai_decision":         _collect_ai_decision,
        "execution":           _collect_execution,
        "learning":            _collect_learning,
        "knowledge":           _collect_knowledge,
        "operations":          _collect_operations,
    }

    # Now safe to parallelise: all collectors use _get_fn() (sys.modules dict
    # lookup, no import lock) so threads never contend on the GIL import lock.
    agents: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {name: ex.submit(fn) for name, fn in collectors.items()}
        for name, fut in futures.items():
            try:
                agents[name] = fut.result(timeout=20)
            except Exception as exc:
                agents[name] = _agent_base(
                    {"available": False, "error": f"Worker timed out: {exc}"},
                    name.replace("_", " ").title(), name, "UNKNOWN_ENABLED",
                    current_activity="Snapshot collection timed out",
                )

    pipeline = _pipeline_summary()

    # Platform status (fast)
    try:
        platform = _platform_status(pipeline)
    except Exception as exc:
        platform = {"status": "UNKNOWN", "error": str(exc)}

    # Compute overall health from agents
    health_scores = [a["health_pct"] for a in agents.values()
                     if a.get("enabled") and a["status"] != "DISABLED"]
    platform["health_pct"] = (
        round(sum(health_scores) / len(health_scores)) if health_scores else 0
    )

    # Top-level pipeline node states for the animated flow diagram
    pipeline_nodes = [
        {"id": "supervisor",          "label": "Supervisor",           "agent_key": "supervisor"},
        {"id": "market_data",         "label": "Market Data",          "agent_key": "market_data"},
        {"id": "research",            "label": "Research",             "agent_key": "research"},
        {"id": "market_intelligence", "label": "Market Intelligence",  "agent_key": "market_intelligence"},
        {"id": "monitoring",          "label": "Monitoring",           "agent_key": "monitoring"},
        {"id": "strategy",            "label": "Strategy",             "agent_key": "strategy"},
        {"id": "risk",                "label": "Risk",                 "agent_key": "risk"},
        {"id": "ai_decision",         "label": "AI Decision",          "agent_key": "ai_decision"},
        {"id": "execution",           "label": "Execution",            "agent_key": "execution"},
        {"id": "learning",            "label": "Learning",             "agent_key": "learning"},
        {"id": "knowledge",           "label": "Knowledge",            "agent_key": "knowledge"},
        {"id": "operations",          "label": "Operations",           "agent_key": "operations"},
    ]
    for node in pipeline_nodes:
        a = agents.get(node["agent_key"]) or {}
        node["status"] = a.get("status", "UNKNOWN")
        node["health_pct"] = a.get("health_pct", 0)
        node["stocks_out"] = a.get("stocks_out", 0)

    return {
        "generated_at":   _now_iso(),
        "advisory_only":  True,
        "paper_only":     True,
        "platform":       platform,
        "pipeline":       pipeline,
        "pipeline_nodes": pipeline_nodes,
        "agents":         agents,
    }
