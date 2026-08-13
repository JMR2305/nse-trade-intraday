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

    # V4.3 — pipeline health, dependency violations, structured recommendations
    pipeline_health       = (raw or {}).get("pipeline_health") or {}
    dependency_violations = _lst((raw or {}).get("dependency_violations"))
    recommendations       = _lst((raw or {}).get("recommendations"))
    # pipeline_cold_start: True when no pipeline topic has ever published in this
    # process instance.  Forwarded to the UI so it can show "awaiting first scan"
    # instead of red violation banners.
    pipeline_cold_start   = bool((raw or {}).get("pipeline_cold_start", False))

    # Stale topics: only topics that were previously publishing but are now stale
    # (exclude never-published topics so cold-start doesn't flood the UI).
    # The supervisor now computes this correctly; prefer the pre-computed list
    # if present, otherwise fall back to local filtering.
    if "stale_topics" in (raw or {}):
        stale_topics = list((raw or {}).get("stale_topics") or [])
    else:
        stale_topics = [
            t for t, h in pipeline_health.items()
            if isinstance(h, dict) and h.get("stale") and not h.get("never_published")
        ]

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
            # V4.3 pipeline integrity
            "pipeline_health":          pipeline_health,
            "pipeline_cold_start":      pipeline_cold_start,
            "dependency_violations":    dependency_violations,
            "dependency_violation_count": len(dependency_violations),
            "stale_topics":             stale_topics,
            "stale_topic_count":        len(stale_topics),
            "recommendations":          recommendations,
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

    # Failure diagnostics from KV (P1 — shown in UI even when agent recovers)
    fail_info: Dict[str, Any] = {}
    try:
        from phase20_store import kv_get as _kv_get_research
        fail_info = _kv_get_research("research_agent_failure") or {}
    except Exception:
        pass

    last_success = (raw or {}).get("last_success_at") or fail_info.get("last_success_at")
    last_failure = (raw or {}).get("last_failure_at") or fail_info.get("last_failure_at")
    failure_reason  = str(
        (raw or {}).get("last_failure_reason") or fail_info.get("failure_reason") or "")
    recovery_action = str(
        (raw or {}).get("recovery_action") or fail_info.get("recovery_action") or "")

    # V4.3 — timeout/retry telemetry from the live snapshot OR KV cache
    timeout_count = _i((raw or {}).get("timeout_count",
                        fail_info.get("timeout_count", 0)))
    retry_count   = _i((raw or {}).get("retry_count",
                        fail_info.get("retry_count", 0)))

    # V4.3 — research_mode: NORMAL | MARKET_ONLY | PIPELINE_HALTED
    research_mode = str((raw or {}).get("research_mode", ""))
    if not research_mode:
        try:
            from phase20_store import kv_get as _kv_get_mode
            _mode_info = _kv_get_mode("research_agent_mode") or {}
            research_mode = str(_mode_info.get("mode", "NORMAL"))
        except Exception:
            research_mode = "NORMAL"

    # worker_status: derived from mode + telemetry
    if research_mode == "PIPELINE_HALTED":
        worker_status = "HALTED"
    elif research_mode == "MARKET_ONLY" or timeout_count > 0:
        worker_status = "DEGRADED"
    elif last_failure and not last_success:
        worker_status = "RECOVERING"
    else:
        worker_status = "OK"

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
            # P1 failure diagnostics
            "last_success_at":       last_success,
            "last_failure_at":       last_failure,
            "failure_reason":        failure_reason,
            "recovery_action":       recovery_action,
            # V4.3 telemetry
            "timeout_count":         timeout_count,
            "retry_count":           retry_count,
            "research_mode":         research_mode,
            "worker_status":         worker_status,
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

    # P7 — Execution verification: cross-reference with risk-approved candidate count
    candidates_received  = 0
    blocking_condition   = ""
    try:
        from phase20_gates import get_last_evaluation
        ev = get_last_evaluation() or {}
        candidates_received = int(ev.get("eligible_count", 0))
        if candidates_received > 0 and paper_buy == 0:
            if not ev.get("global_pass", True):
                failed_global = [
                    g["gate"] for g in ev.get("global_gates", []) if not g["passed"]
                ]
                blocking_condition = (
                    f"Global risk gates failing: {', '.join(failed_global[:3])}"
                )
            else:
                blocking_condition = (
                    "Risk-approved candidates present but no paper orders created — "
                    "check auto-paper trading is enabled in settings"
                )
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
            "paper_buy_orders":    paper_buy,
            "paper_sell_orders":   paper_sell,
            "open_positions":      open_pos,
            "closed_positions":    closed_pos,
            "capital_used":        round(capital_used, 2),
            "capital_available":   round(capital_avail, 2),
            "execution_errors":    exec_errors[:5],
            # P7 execution verification
            "candidates_received": candidates_received,
            "orders_created":      paper_buy,
            "orders_rejected":     max(0, candidates_received - paper_buy),
            "blocking_condition":  blocking_condition,
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

def _get_bottleneck_suggestion(agent_key: str) -> str:
    _suggestions: Dict[str, str] = {
        "supervisor":          "Check that all agents are initialised and registered correctly.",
        "market_data":         "Verify data provider connectivity and NSE symbol coverage.",
        "research":            "Research agent may be filtering too aggressively. Check news quality thresholds.",
        "market_intelligence": "Current market regime may be blocking stocks. Review regime conditions in Settings.",
        "monitoring":          "No technical signals detected. Confirm watchlist symbols and monitoring criteria.",
        "strategy":            "Confidence threshold may be too high. Review strategy parameters in Settings.",
        "risk":                "Risk thresholds may be too conservative. Review capital limits and sector exposure rules.",
        "ai_decision":         "AI not generating BUY/SELL signals. Check confidence floor and decision thresholds.",
        "execution":           "Execution agent idle. Confirm paper trading is enabled and a scan has run.",
        "learning":            "Insufficient completed trade history. Needs more paper trades to learn from.",
        "knowledge":           "Knowledge base update stalled. Check for errors in the learning cycle.",
        "operations":          "System resource pressure detected. Monitor CPU/memory in Operations Centre.",
    }
    return _suggestions.get(agent_key, "Review agent configuration and error logs.")


def _operator_summary(
    pipeline: Dict[str, Any],
    agents: Dict[str, Any],
    bottleneck: Optional[Dict[str, Any]],
) -> str:
    universe   = _i(pipeline.get("universe_loaded", 0))
    reviewed   = _i(pipeline.get("stocks_reviewed", universe))
    strat_pass = _i(pipeline.get("passed_strategy", 0))
    risk_pass  = _i(pipeline.get("passed_risk", 0))
    buy_recs   = _i(pipeline.get("buy_recommendations", 0))
    executed   = _i(pipeline.get("paper_orders_executed", 0))

    parts: List[str] = []
    if universe > 0:
        parts.append(f"The AI scanned {universe} stocks.")
    if reviewed > 0 and reviewed != universe:
        parts.append(f"{reviewed} were shortlisted for analysis.")
    if strat_pass > 0:
        parts.append(f"{strat_pass} passed strategy evaluation.")
    if risk_pass > 0 and risk_pass != strat_pass:
        parts.append(f"{risk_pass} passed risk validation.")
    if buy_recs > 0:
        parts.append(f"{buy_recs} BUY recommendation{'s' if buy_recs != 1 else ''} generated.")
    if executed > 0:
        parts.append(f"{executed} paper trade{'s' if executed != 1 else ''} executed.")

    if not parts:
        return "No pipeline activity recorded this session yet."

    summary = " ".join(parts)

    if bottleneck:
        summary += (f" The primary bottleneck was {bottleneck['agent']} "
                    f"({bottleneck['rejected_pct']}% of candidates blocked).")
    elif buy_recs == 0 and universe > 0:
        if strat_pass == 0:
            summary += " No stocks passed strategy evaluation this cycle."
        elif risk_pass == 0:
            summary += " All strategy candidates were blocked at the risk gate."
        else:
            summary += " No BUY recommendations were generated."

    return summary


def _pipeline_summary() -> Dict[str, Any]:
    # ── Phase-15 canonical scan context (single source of truth) ─────────────
    scan_id = "—"
    snapshot_ts = "—"
    pipeline_cycle = "—"
    avg_strategy_confidence = 0.0
    stale_reason = ""
    total = live_count = intel_count = scanner_candidates = 0

    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
        symbols = ctx.get("symbols") or {}
        total             = len(symbols)
        live_count        = sum(1 for r in symbols.values()
                               if str(r.get("data_quality","")).upper() in ("LIVE","NEAR_LIVE"))
        intel_count       = sum(1 for r in symbols.values()
                               if str(r.get("final_action","")).upper() != "IGNORE")
        # scanner_candidates: stocks the scanner scores as BUY/STRONG BUY
        # (uses opportunity_score threshold, ~62). These are NOT yet confirmed
        # by the decision service's stricter final_confidence + expectancy + PF + R:R checks.
        scanner_candidates = sum(1 for r in symbols.values()
                                if str(r.get("final_action","")).upper() in ("BUY","STRONG BUY"))
        scan_id            = str(ctx.get("scan_id") or "—")
        snapshot_ts        = str(ctx.get("snapshot_ts") or "—")
        pipeline_cycle     = scan_id
        # Strategy confidence exists in the scan even when Risk blocks all candidates.
        # Scan confidences may be stored as fractions (0–1) or percents (0–100);
        # normalise to percent WITHOUT double-scaling values already in percent.
        conf_vals = [
            (_f(r.get("confidence", 0)) * 100
             if _f(r.get("confidence", 0)) <= 1.5
             else _f(r.get("confidence", 0)))
            for r in symbols.values()
            if str(r.get("final_action","")).upper() in ("BUY","STRONG BUY","WATCH")
        ]
        avg_strategy_confidence = round(
            sum(conf_vals) / len(conf_vals), 1
        ) if conf_vals else 0.0
        if ctx.get("stale"):
            age_s      = _i(ctx.get("scan_age_seconds", 0))
            stale_secs = _i(ctx.get("stale_after_seconds", 5400))
            stale_reason = (
                f"Scan {age_s // 60}m {age_s % 60}s old "
                f"(stale after {stale_secs // 60}m) — "
                f"auto-scan may not be running or market is closed"
            )
    except Exception:
        pass

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

    # Phase-20 risk evaluation (uses same scan_id when pipeline is aligned)
    eligible   = 0
    ev_scan_id = ""
    try:
        from phase20_gates import get_last_evaluation
        ev = get_last_evaluation() or {}
        eligible   = int(ev.get("eligible_count", 0))
        ev_scan_id = str(ev.get("scan_id") or "")
    except Exception:
        eligible = paper_today

    # ── Confirmed BUY count from the decision service (matches Trade Decisions page) ──
    # decision_service.load_decision_summary() returns the validated counts written
    # by the last get_trade_decisions() call (the same API used by Trade Decisions).
    # BUY:        final_confidence 75–84, exp > 0, PF > 1.2, R:R ≥ 2
    # STRONG_BUY: final_confidence ≥ 85, exp > 1%, PF ≥ 1.5, R:R ≥ 2,
    #             ≥ 20 historical trades (reliable sample)
    # When no valid summary exists yet, confirmed_buy_count stays None —
    # callers MUST NOT substitute scanner_candidates in its place.
    confirmed_buy_count: Optional[int] = None   # None = not yet available
    decision_summary_ts  = ""
    decision_summary_ok  = False
    try:
        from decision_service import load_decision_summary as _load_dec_summary
        _summary = _load_dec_summary()
        if _summary is not None:
            confirmed_buy_count = int(_summary.get("confirmed_buy_count", 0))
            decision_summary_ts  = str(_summary.get("generated_at", "") or "")
            decision_summary_ok  = True
        # If summary is None (Trade Decisions page never loaded or file corrupt),
        # leave confirmed_buy_count as None — the UI renders it as "—".
    except Exception:
        pass   # leave as None — never substitute a proxy value

    # Snapshot consistency: scan context and risk evaluation must reference the
    # same scan_id so the funnel counts are coherent.
    consistency_ok = (not ev_scan_id) or (ev_scan_id == scan_id) or (scan_id == "—")
    consistency_note = "" if consistency_ok else (
        f"Scan context scan_id ({scan_id[:8]}) differs from Risk evaluation "
        f"scan_id ({ev_scan_id[:8]}) — widgets may reflect different pipeline cycles"
    )
    # Decision-layer freshness note — show when summary pre-dates the current scan.
    # We compare ISO timestamps: if decision_summary_ts is older than snapshot_ts,
    # the confirmed BUY count comes from a previous Trade Decisions page load.
    if decision_summary_ok and decision_summary_ts and snapshot_ts not in ("—", ""):
        try:
            _ds_dt = datetime.fromisoformat(decision_summary_ts.replace("Z", "+00:00"))
            _sc_dt = datetime.fromisoformat(snapshot_ts.replace("Z", "+00:00"))
            if (_sc_dt - _ds_dt).total_seconds() > 120:   # >2 min lag is notable
                _lag_min = int((_sc_dt - _ds_dt).total_seconds() / 60)
                if not consistency_note:
                    consistency_note = (
                        f"Confirmed BUY count is from a Trade Decisions result "
                        f"{_lag_min}m before the current scan — it will update "
                        f"on the next Trade Decisions page load."
                    )
        except Exception:
            pass
    elif not decision_summary_ok:
        # No Trade Decisions page has ever been loaded; confirmed count is not yet
        # authoritative. The funnel shows scanner_candidates as a proxy.
        if not consistency_note:
            consistency_note = (
                "Confirmed BUY count is not yet available — load the Trade "
                "Decisions page once to calibrate this figure."
            )

    # Pipeline trace — per-stage symbol counts for the Operations Centre flow diagram.
    # confirmed_buy_count may be None (no decision summary yet); use a sentinel of -1
    # inside the trace so arithmetic works, then strip it from the serialised stage.
    _cbc_int = confirmed_buy_count if confirmed_buy_count is not None else -1
    pipeline_trace = [
        {"stage": "Universe Loaded",     "input": total,              "output": total,
         "dropped": 0},
        {"stage": "Market Data",         "input": total,              "output": live_count,
         "dropped": max(0, total - live_count)},
        {"stage": "Research",            "input": live_count,         "output": live_count,
         "dropped": 0},
        {"stage": "Market Intelligence", "input": live_count,         "output": intel_count,
         "dropped": max(0, live_count - intel_count)},
        {"stage": "Stock Monitoring",    "input": intel_count,        "output": intel_count,
         "dropped": 0},
        {"stage": "Strategy",            "input": intel_count,        "output": scanner_candidates,
         "dropped": max(0, intel_count - scanner_candidates)},
        {"stage": "Risk",                "input": scanner_candidates, "output": eligible,
         "dropped": max(0, scanner_candidates - eligible)},
        # AI Decision: BUY confidence 75–84 (exp>0, PF>1.2, R:R≥2) or
        #              STRONG_BUY confidence ≥85 (exp>1%, PF≥1.5, R:R≥2, ≥20 trades)
        # output is None when the decision summary has not been written yet.
        {"stage": "AI Decision",
         "input": eligible,
         "output": confirmed_buy_count,      # None serialises as null in JSON
         "dropped": max(0, eligible - _cbc_int) if _cbc_int >= 0 else None},
        {"stage": "Execution",
         "input": confirmed_buy_count,       # None when not yet available
         "output": paper_today,
         "dropped": max(0, _cbc_int - paper_today) if _cbc_int >= 0 else None},
        {"stage": "Learning",            "input": paper_today,        "output": paper_today,
         "dropped": 0},
    ]

    summary = {
        "universe_loaded":            total,
        "stocks_reviewed":            total,
        "passed_market_data":         live_count,
        "passed_research":            live_count,
        "passed_intelligence":        intel_count,
        "passed_monitoring":          intel_count,
        "passed_strategy":            scanner_candidates,
        # passed_precheck: Portfolio Pre-Check output — only available from the
        # unified replay snapshot (event-derived); null in the legacy fallback.
        "passed_precheck":            None,
        # Funnel flow-through of the pre-check stage (approved + unevaluated
        # pass-through). Distinct from passed_precheck (approved only).
        "precheck_flow_out":          None,
        "passed_risk":                eligible or scanner_candidates,
        # scanner_candidates: raw scanner BUY/STRONG BUY count (opportunity_score ≥ ~62)
        "scanner_candidates":         scanner_candidates,
        # buy_recommendations: confirmed by decision service — null when not yet available.
        # BUY: confidence 75–84, exp>0, PF>1.2, R:R≥2
        # STRONG_BUY: confidence ≥85, exp>1%, PF≥1.5, R:R≥2, ≥20 historical trades
        "buy_recommendations":        confirmed_buy_count,   # int or null
        "paper_orders_executed":      paper_today,
        "open_positions":             open_pos,
        # Traceability (P4, P6)
        "scan_id":                    scan_id,
        "snapshot_ts":                snapshot_ts,
        "pipeline_cycle":             pipeline_cycle,
        "consistency_ok":             consistency_ok,
        "consistency_note":           consistency_note,
        # Confidence (P3) — strategy confidence is present even when Risk blocks all
        "avg_strategy_confidence":    avg_strategy_confidence,
        # Stale diagnosis (P5)
        "stale_reason":               stale_reason,
        # Pipeline trace (P6)
        "pipeline_trace":             pipeline_trace,
        # Decision summary freshness metadata
        "decision_summary_ok":        decision_summary_ok,
        "decision_summary_ts":        decision_summary_ts,
    }
    # ── Unified Replay Snapshot override (single source of truth) ────────────
    # The Operations Centre must display the EXACT same pipeline numbers as
    # the Replay page. When the replay snapshot for the same scan is
    # available, its stage counts replace the independently computed ones
    # above (which remain only as a fallback when replay data is missing).
    try:
        import replay_engine
        replay = replay_engine.build_replay(scan_id if scan_id not in ("", "—") else "latest")
        _same_scan = scan_id in ("", "—") or str(replay.get("scan_id") or "") == scan_id
        if "error" not in replay and _same_scan:
            pc = replay.get("pipeline_counts") or {}
            ps = replay.get("portfolio_state") or {}

            def _out(stage: str, default: int) -> int:
                d = pc.get(stage) or {}
                return int(d.get("out", default))

            summary["universe_loaded"]     = _out("supervisor", total)
            summary["stocks_reviewed"]     = _out("supervisor", total)
            summary["passed_market_data"]  = _out("market_data", live_count)
            summary["passed_research"]     = _out("research", live_count)
            summary["passed_intelligence"] = _out("market_intelligence", intel_count)
            summary["passed_monitoring"]   = _out("monitoring", intel_count)
            summary["passed_strategy"]     = _out("strategy", scanner_candidates)
            # Event-derived approvals only — never count symbols that were
            # never evaluated (no BUY attempt) as "Pre-Check Approved".
            summary["passed_precheck"]     = int(
                (pc.get("portfolio_precheck") or {}).get("approved", 0))
            summary["precheck_flow_out"]   = _out("portfolio_precheck",
                                                  _out("strategy", scanner_candidates))
            summary["passed_risk"]         = _out("risk", eligible or scanner_candidates)
            summary["buy_recommendations"] = _out("ai_decision",
                                                  confirmed_buy_count if confirmed_buy_count is not None else 0)
            summary["paper_orders_executed"] = _out("execution", paper_today)
            summary["open_positions"]      = int(ps.get("open_positions", open_pos))
            summary["replay_id"]           = replay.get("replay_id")
            summary["counts_source"]       = "replay_snapshot"
            # Rebuild the trace from the same unified counts.
            _order = ["supervisor", "market_data", "research", "market_intelligence",
                      "monitoring", "strategy", "portfolio_precheck", "risk",
                      "ai_decision", "execution", "portfolio"]
            summary["pipeline_trace"] = [
                {
                    "stage": (pc.get(k) or {}).get("label", k),
                    "input": int((pc.get(k) or {}).get("in", 0)),
                    "output": int((pc.get(k) or {}).get("out", 0)),
                    "dropped": int((pc.get(k) or {}).get("rejected", 0)),
                }
                for k in _order if k in pc
            ]
    except Exception:
        summary["counts_source"] = "legacy_fallback"
    return summary


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


def get_fast_platform_status() -> Dict[str, Any]:
    """
    Returns platform status + pipeline node states in < 1 s.

    Data sources (all sub-second Postgres/cache reads):
      - scan_state_store.load_latest_meta()   → scan_id, snapshot_ts, status
      - market_hours.market_status()          → market state (cached)
      - phase20_store KV:
          ops_last_health_pct   → last computed health % from a full snapshot
          ops_last_pipeline_nodes → last computed pipeline node statuses

    health_pct and pipeline_nodes are populated from the persisted KV values
    written by get_ops_centre_snapshot() after every full agent collection.
    On first call before any full snapshot has run, health_pct defaults to
    a rough estimate (100% if scan data is fresh, else 0), and pipeline_nodes
    default to UNKNOWN.
    """
    import json as _json

    # ── Scan + market metadata (always fresh) ────────────────────────────────
    from market_hours import market_status
    mstat = market_status()
    mstate = str(mstat.get("state") or mstat.get("market_state") or "UNKNOWN").upper()

    from scan_state_store import load_latest_meta
    meta = load_latest_meta() or {}
    scan_id   = str(meta.get("scan_id") or "—")
    snap_ts   = str(meta.get("snapshot_ts") or "—")
    _, snap_time = _ist(meta.get("snapshot_ts"))

    scan_count = 0
    interval_min = 5
    try:
        from phase20_store import kv_get, get_settings
        scan_count = int(kv_get("scan_run_count", 0) or 0)
        s = get_settings()
        interval_min = int(s.get("scan_interval_minutes", 5))
    except Exception:
        pass

    next_refresh_est = ""
    try:
        if meta.get("snapshot_ts"):
            last_dt = datetime.fromisoformat(
                str(meta["snapshot_ts"]).replace("Z", "+00:00"))
            nxt = last_dt + timedelta(minutes=interval_min)
            _, next_refresh_est = _ist(nxt.isoformat())
    except Exception:
        pass

    # ── Cached agent health from last full snapshot ──────────────────────────
    # Use None as the sentinel for "no cached value" so that a legitimately
    # computed 0% health is preserved exactly and never overridden by the
    # scan-age heuristic below.
    health_pct_cached: Optional[int] = None
    pipeline_nodes: List[Dict[str, Any]] = []
    cache_ts: Optional[str] = None
    try:
        from phase20_store import kv_get as _kv
        cached_health = _kv("ops_last_health_pct")
        if cached_health is not None:
            health_pct_cached = int(cached_health)
        cached_nodes = _kv("ops_last_pipeline_nodes")
        if cached_nodes:
            pipeline_nodes = _json.loads(str(cached_nodes))
        cached_ts = _kv("ops_last_snapshot_ts")
        if cached_ts:
            cache_ts = str(cached_ts)
    except Exception:
        pass

    # Default pipeline nodes when no full snapshot has run yet
    if not pipeline_nodes:
        _node_defs = [
            ("supervisor",          "Supervisor"),
            ("market_data",         "Market Data"),
            ("research",            "Research"),
            ("market_intelligence", "Market Intelligence"),
            ("monitoring",          "Monitoring"),
            ("strategy",            "Strategy"),
            ("risk",                "Risk"),
            ("ai_decision",         "AI Decision"),
            ("execution",           "Execution"),
            ("learning",            "Learning"),
            ("knowledge",           "Knowledge"),
            ("operations",          "Operations"),
        ]
        pipeline_nodes = [
            {"id": k, "label": l, "agent_key": k,
             "status": "UNKNOWN", "health_pct": 0, "stocks_out": 0}
            for k, l in _node_defs
        ]

    # Derive health_pct:
    # - If a real cached value exists (including 0), use it exactly.
    # - Only apply the scan-age heuristic when no cached value is present at
    #   all (i.e. no full snapshot has run since the server started).
    if health_pct_cached is not None:
        health_pct: int = health_pct_cached
    elif meta.get("snapshot_ts"):
        # Provisional estimate: a recent scan suggests the system was healthy
        # when it last ran.  Operators see this only until the first full
        # snapshot completes and writes a real cached value.
        try:
            last_dt = datetime.fromisoformat(
                str(meta["snapshot_ts"]).replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            health_pct = 95 if age_min < interval_min * 2 else 50
        except Exception:
            health_pct = 0
    else:
        health_pct = 0

    scan_status = str(meta.get("status") or "COMPLETE")

    return {
        "generated_at":      _now_iso(),
        "fast":              True,
        "advisory_only":     True,
        "cache_ts":          cache_ts,       # ISO timestamp of the full snapshot that set the cache
        "platform": {
            "health_pct":        health_pct,
            "status":            "OPERATIONAL",
            "scan_id":           scan_id[:16],
            "scan_number":       scan_count,
            "scan_status":       scan_status,
            "market_state":      mstate,
            "trading_session":   "Intraday NSE" if mstate == "OPEN" else f"Market {mstate.title()}",
            "current_time_ist":  _ist(_now_iso())[1],
            "last_refresh_ist":  snap_time,
            "next_refresh_est":  next_refresh_est,
            "scan_interval_min": interval_min,
        },
        "pipeline_nodes":    pipeline_nodes,
    }


def _load_ai_decisions_safe() -> List[Dict[str, Any]]:
    """Load the ai_decisions cache — returns [] on any error."""
    try:
        import signals_store as _ss
        raw = _ss.load_ai_decisions()
        if isinstance(raw, dict):
            return list(raw.get("recommendations", []) or [])
        if isinstance(raw, list):
            return list(raw)
    except Exception:
        pass
    try:
        import json, os as _os
        _p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "ai_decisions_cache.json")
        if _os.path.exists(_p):
            with open(_p) as _f:
                _d = json.load(_f)
            if isinstance(_d, dict):
                return list(_d.get("recommendations", []) or [])
            if isinstance(_d, list):
                return list(_d)
    except Exception:
        pass
    return []


def get_v3_enrichment(agents: Dict[str, Any], pipeline: Dict[str, Any]) -> Dict[str, Any]:
    """
    V3 — derive investigation data from existing caches.
    No new agent calls; runs after all agent collectors have finished.
    """
    recs = _load_ai_decisions_safe()

    PASS_DEC = {"BUY", "STRONG_BUY"}

    # ── Missed Opportunities (Section 4) ──────────────────────────────────────
    missed: List[Dict[str, Any]] = []
    for r in recs:
        if r.get("decision_type") not in PASS_DEC:
            exp = r.get("explanation", {})
            exp_str = exp.get("summary", "") if isinstance(exp, dict) else str(exp or "")
            missed.append({
                "symbol":          str(r.get("symbol", "—")),
                "decision_type":   str(r.get("decision_type", "—")),
                "confidence":      round(_f(r.get("confidence", 0)) * 100),
                "reason":          str(r.get("rejection_reason") or exp_str or "—"),
                "expected_return": round(_f(r.get("expected_return", 0)) * 100, 1),
            })
    missed.sort(key=lambda x: x["confidence"], reverse=True)

    # ── Confidence Distribution (Section 5) ───────────────────────────────────
    dist: Dict[str, int] = {"90_100": 0, "80_90": 0, "70_80": 0, "60_70": 0, "below_60": 0}
    for r in recs:
        c = _f(r.get("confidence", 0)) * 100
        if   c >= 90: dist["90_100"] += 1
        elif c >= 80: dist["80_90"]  += 1
        elif c >= 70: dist["70_80"]  += 1
        elif c >= 60: dist["60_70"]  += 1
        else:          dist["below_60"] += 1

    # ── Recommendation Leaderboard (Section 6) ────────────────────────────────
    def _entry(r: Dict[str, Any]) -> Dict[str, Any]:
        sc = r.get("scores", {}) or {}
        exp = r.get("explanation", {})
        exp_str = exp.get("summary", "") if isinstance(exp, dict) else str(exp or "")
        return {
            "symbol":          str(r.get("symbol", "—")),
            "decision_type":   str(r.get("decision_type", "—")),
            "confidence":      round(_f(r.get("confidence", 0)) * 100),
            "expected_return": round(_f(r.get("expected_return", 0)) * 100, 1),
            "explanation":     exp_str[:120],
            "scores":          {k: round(_f(v) * 100) for k, v in sc.items()},
        }

    top_buy   = sorted([_entry(r) for r in recs if r.get("decision_type") in PASS_DEC],
                       key=lambda x: x["confidence"], reverse=True)[:8]
    top_watch = sorted([_entry(r) for r in recs if r.get("decision_type") in ("WATCH", "HOLD")],
                       key=lambda x: x["confidence"], reverse=True)[:8]
    top_sell  = sorted([_entry(r) for r in recs if r.get("decision_type") in ("SELL", "STRONG_SELL", "AVOID")],
                       key=lambda x: x["confidence"], reverse=True)[:8]

    # ── Pipeline Heatmap (Section 12) ────────────────────────────────────────
    AGENT_ORDER_V3 = [
        "supervisor","market_data","research","market_intelligence",
        "monitoring","strategy","risk","ai_decision",
        "execution","learning","knowledge","operations",
    ]
    heatmap: List[Dict[str, Any]] = []
    for key in AGENT_ORDER_V3:
        a = agents.get(key, {})
        ms = _i(a.get("avg_processing_ms", 0))
        st = str(a.get("status", "UNKNOWN"))
        colour = ("green" if ms < 2000 else "yellow" if ms < 5000 else "red") if ms > 0 else (
            "red" if st == "ERROR" else "yellow" if st == "WAITING" else "grey"
        )
        heatmap.append({
            "agent_key":  key,
            "label":      str(a.get("name", key)),
            "ms":         ms,
            "colour":     colour,
            "status":     st,
            "stocks_out": _i(a.get("stocks_out", 0)),
            "health_pct": _i(a.get("health_pct", 0)),
        })

    # ── Smart Insights (Section 13) ───────────────────────────────────────────
    enabled_agents = [a for a in agents.values() if a.get("enabled")]
    strongest = max(enabled_agents, key=lambda a: _i(a.get("health_pct", 0)), default=None)
    weakest   = min(enabled_agents, key=lambda a: _i(a.get("health_pct", 0)), default=None)

    rej_counts: Dict[str, int] = {}
    for a in agents.values():
        rr = str(a.get("rejection_reason", "") or "").strip()
        if rr and rr not in ("—", "None", ""):
            rej_counts[rr] = rej_counts.get(rr, 0) + _i(a.get("stocks_rejected", 0))
    most_common_rej = (max(rej_counts, key=rej_counts.get) if rej_counts else "None detected")[:80]

    strat_det  = agents.get("strategy", {}).get("details", {}) or {}
    most_active_strat = str(strat_det.get("top_strategy") or strat_det.get("best_strategy") or "N/A")

    best_opp      = top_buy[0]["symbol"]  if top_buy  else "None"
    biggest_missed = missed[0]["symbol"]  if missed   else "None"

    # Bottleneck stage (biggest absolute drop in pipeline)
    prev = _i(pipeline.get("universe_loaded", 0))
    stage_pairs = [
        ("stocks_reviewed","Reviewed"), ("passed_market_data","Market Data"),
        ("passed_research","Research"), ("passed_intelligence","Intelligence"),
        ("passed_monitoring","Monitoring"), ("passed_strategy","Strategy"),
        ("passed_precheck","Portfolio Pre-Check"),
        ("passed_risk","Risk"), ("buy_recommendations","BUY Recs"),
        ("paper_orders_executed","Executed"),
    ]
    bottleneck_stage = "None"
    worst_drop_v3 = 0
    for pkey, plabel in stage_pairs:
        cur = _i(pipeline.get(pkey, 0))
        drop = prev - cur
        if drop > worst_drop_v3:
            worst_drop_v3 = drop
            bottleneck_stage = plabel
        prev = cur

    smart_insights: List[Dict[str, str]] = [
        {"label": "Today's Strongest Agent",   "value": strongest["name"] if strongest else "N/A", "icon": "trophy"},
        {"label": "Today's Weakest Agent",     "value": weakest["name"]   if weakest   else "N/A", "icon": "alert"},
        {"label": "Biggest Bottleneck",        "value": bottleneck_stage,                           "icon": "funnel"},
        {"label": "Most Common Rejection",     "value": most_common_rej,                            "icon": "x-circle"},
        {"label": "Best Opportunity",          "value": best_opp,                                   "icon": "star"},
        {"label": "Biggest Missed Opportunity","value": biggest_missed,                              "icon": "trending-down"},
        {"label": "Most Active Strategy",      "value": most_active_strat,                          "icon": "zap"},
    ]

    # ── End-of-Day Executive Summary (Section 14) ────────────────────────────
    universe   = _i(pipeline.get("universe_loaded", 0))
    strat_pass = _i(pipeline.get("passed_strategy", 0))
    risk_pass  = _i(pipeline.get("passed_risk", 0))
    buy_count  = _i(pipeline.get("buy_recommendations", 0))
    exec_count = _i(pipeline.get("paper_orders_executed", 0))
    open_pos   = _i(pipeline.get("open_positions", 0))
    buy_recs_list = [r for r in recs if r.get("decision_type") in PASS_DEC]
    avg_conf_pct = (
        sum(_f(r.get("confidence", 0)) * 100 for r in buy_recs_list) / len(buy_recs_list)
        if buy_recs_list else 0.0
    )
    parts: List[str] = []
    if universe > 0: parts.append(f"The AI scanned {universe} stocks.")
    if strat_pass > 0: parts.append(f"{strat_pass} reached Strategy.")
    if risk_pass > 0: parts.append(f"{risk_pass} passed Risk.")
    if buy_count > 0:
        parts.append(f"{buy_count} BUY recommendation{'s were' if buy_count!=1 else ' was'} generated.")
    if exec_count > 0:
        parts.append(f"{exec_count} paper trade{'s' if exec_count!=1 else ''} executed.")
    if open_pos > 0:
        parts.append(f"{open_pos} position{'s' if open_pos!=1 else ''} currently open.")
    if avg_conf_pct > 0:
        parts.append(f"Average confidence was {avg_conf_pct:.0f}%.")
    if bottleneck_stage != "None":
        parts.append(f"Largest bottleneck was {bottleneck_stage}.")
    executive_summary = " ".join(parts) or "No pipeline activity recorded today."

    # ── Agent Load Monitor (Section 7) ────────────────────────────────────────
    agent_load: Dict[str, Any] = {}
    for key in AGENT_ORDER_V3:
        a = agents.get(key, {})
        ms = _i(a.get("avg_processing_ms", 0))
        agent_load[key] = {
            "name":              str(a.get("name", key)),
            "queue_size":        _i(a.get("stocks_in", 0)),
            "items_processed":   _i(a.get("stocks_out", 0)),
            "items_rejected":    _i(a.get("stocks_rejected", 0)),
            "avg_processing_ms": ms,
            "max_processing_ms": ms,  # max not separately tracked; same as avg here
            "utilisation_pct":   min(100, _i(a.get("health_pct", 0))),
            "capacity_pct":      100,
            "status":            str(a.get("status", "UNKNOWN")),
        }

    return {
        "missed_opportunities":       missed[:25],
        "confidence_distribution":    dist,
        "recommendation_leaderboard": {"top_buy": top_buy, "top_watch": top_watch, "top_sell": top_sell},
        "pipeline_heatmap":           heatmap,
        "smart_insights":             smart_insights,
        "executive_summary":          executive_summary,
        "agent_load_monitor":         agent_load,
    }


def _journey_conf_pct(value: Any) -> int:
    """Normalise a confidence that may be 0-1 or already 0-100 into a percent."""
    f = _f(value)
    if 0 < f <= 1.5:
        f *= 100
    return round(f)


def get_stock_journey(symbol: str) -> Dict[str, Any]:
    """
    On-demand only — traces a single symbol's journey through all agents.
    Called only when the operator searches, never polled.

    Sources (in order of authority):
      • the canonical scan snapshot (scan_state_store) — authoritative for
        "was this symbol scanned" plus real gate reasons, and
      • the ai_decisions cache — decision-layer detail when present. Rows in
        that cache key the symbol as either `symbol` (legacy) or `stock`.
    """
    symbol = symbol.upper().strip()
    recs = _load_ai_decisions_safe()
    rec = next((r for r in recs
                if str(r.get("symbol") or r.get("stock") or "").upper() == symbol),
               None)

    canon: Optional[Dict[str, Any]] = None
    try:
        from scan_state_store import load_latest_snapshot
        _snap = load_latest_snapshot() or {}
        canon = next((r for r in (_snap.get("recommendations") or [])
                      if str(r.get("symbol", "")).upper() == symbol), None)
    except Exception:
        canon = None

    found = rec is not None or canon is not None
    stages: List[Dict[str, Any]] = []

    # Supervisor
    stages.append({
        "agent": "Supervisor", "agent_id": "supervisor",
        "decision": "Selected" if found else "Not in universe",
        "reason": ("Symbol included in canonical scan" if canon else
                   "Symbol present in AI decision cache" if rec else
                   "Not in current watchlist or scan"),
        "timestamp": "—", "processing_ms": 0,
        "status": "PASS" if found else "INFO",
    })

    if not found:
        return {
            "symbol": symbol, "found": False,
            "decision_type": "NOT_IN_SCAN", "confidence": 0,
            "stages": stages, "factor_breakdown": [],
            "explanation": f"{symbol} was not found in the most recent scan results.",
            "scores": {}, "why_not": None,
        }

    sc = (rec or {}).get("scores") if isinstance((rec or {}).get("scores"), dict) else {}
    sc = sc or {}
    exp = (rec or {}).get("explanation")
    exp_str = (exp.get("summary", "") if isinstance(exp, dict) else str(exp or "")) \
        or str((rec or {}).get("plain_english") or "")
    canon_action = str((canon or {}).get("final_action") or "").replace(" ", "_")
    decision_type = str((rec or {}).get("decision_type")
                        or (rec or {}).get("decision")
                        or canon_action or "—").replace(" ", "_")
    conf_pct = _journey_conf_pct((rec or {}).get("confidence")
                                 or (canon or {}).get("calibrated_confidence") or 0)

    # Market Data — real quality/source from the canonical scan when available
    if canon:
        dq = str(canon.get("data_quality") or "—")
        src_name = str(canon.get("data_source") or "—")
        stages.append({
            "agent": "Market Data", "agent_id": "market_data",
            "decision": "Updated",
            "reason": f"Data quality {dq} · source {src_name}",
            "timestamp": "—", "processing_ms": 0,
            "status": "PASS" if dq not in ("STALE", "UNAVAILABLE") else "WARN",
        })
        # Scanner gates — real reasons from the canonical scan
        gate_labels = [("gate_price", "Price"), ("gate_rr", "Risk/Reward"),
                       ("gate_volume", "Volume"), ("gate_data_quality", "Data quality")]
        gate_bits, gates_ok = [], True
        for key, label in gate_labels:
            g = canon.get(key)
            if isinstance(g, dict) and "passed" in g:
                ok = bool(g.get("passed"))
                gates_ok = gates_ok and ok
                gate_bits.append(f"{label}: {g.get('reason') or ('pass' if ok else 'fail')}")
        if gate_bits:
            stages.append({
                "agent": "Scanner", "agent_id": "scanner",
                "decision": "All gates passed" if gates_ok else "Gate(s) failed",
                "reason": " · ".join(gate_bits)[:300],
                "timestamp": "—", "processing_ms": 0,
                "status": "PASS" if gates_ok else "FAIL",
            })
    else:
        stages.append({
            "agent": "Market Data", "agent_id": "market_data",
            "decision": "Updated", "reason": "Live price data retrieved successfully",
            "timestamp": "—", "processing_ms": 0, "status": "PASS",
        })

    # Score-derived stages — only when the decision cache carries real scores
    rs = round(_f(sc.get("research", 0)) * 100)
    regsc = round(_f(sc.get("regime", sc.get("market_intelligence", 0))) * 100)
    momsc = round(_f(sc.get("momentum", 0)) * 100)
    if sc:
        stages.append({
            "agent": "Research", "agent_id": "research",
            "decision": "Positive" if rs >= 50 else "Negative",
            "reason": f"Research score: {rs}%",
            "timestamp": "—", "processing_ms": 0,
            "status": "PASS" if rs >= 50 else "WARN",
        })
        stages.append({
            "agent": "Market Intelligence", "agent_id": "market_intelligence",
            "decision": "Bullish" if regsc >= 60 else "Neutral" if regsc >= 40 else "Bearish",
            "reason": f"Regime score: {regsc}%",
            "timestamp": "—", "processing_ms": 0,
            "status": "PASS" if regsc >= 50 else "WARN",
        })
        stages.append({
            "agent": "Monitoring", "agent_id": "monitoring",
            "decision": "Signal detected" if momsc >= 50 else "No signal",
            "reason": f"Momentum score: {momsc}%",
            "timestamp": "—", "processing_ms": 0,
            "status": "PASS" if momsc >= 50 else "WARN",
        })
    elif canon and canon.get("regime"):
        stages.append({
            "agent": "Market Intelligence", "agent_id": "market_intelligence",
            "decision": str(canon.get("regime")),
            "reason": f"Regime from canonical scan: {canon.get('regime')}",
            "timestamp": "—", "processing_ms": 0, "status": "PASS",
        })

    # Strategy
    ovsc = round(_f(sc.get("overall", 0)) * 100)
    if sc:
        strat_reason = f"Overall score: {ovsc}% · Decision: {decision_type}"
    else:
        strat_name = (canon or {}).get("strategy_name") or (canon or {}).get("strategy_id") or "—"
        tech = (canon or {}).get("technical_score")
        strat_reason = f"Strategy: {strat_name}" + (
            f" · Technical score: {round(_f(tech))}%" if tech is not None else "")
    stages.append({
        "agent": "Strategy", "agent_id": "strategy",
        "decision": f"Confidence {conf_pct}%",
        "reason": strat_reason,
        "timestamp": "—", "processing_ms": 0,
        "status": "PASS" if conf_pct >= 70 else "WARN",
    })

    # Risk
    risksc = round(_f(sc.get("risk", 0)) * 100)
    risk_pass_v3 = decision_type not in ("AVOID", "IGNORE", "NO_ACTION")
    if sc:
        risk_reason = str((rec or {}).get("rejection_reason") or f"Risk score: {risksc}%")
    else:
        rr = (canon or {}).get("rr_ratio")
        risk_level = (rec or {}).get("risk_level")
        bits = []
        if rr is not None:
            bits.append(f"RR ratio {rr}")
        if risk_level:
            bits.append(f"Risk level {risk_level}")
        risk_reason = str((rec or {}).get("rejection_reason") or " · ".join(bits) or
                          f"Decision: {decision_type}")
    stages.append({
        "agent": "Risk", "agent_id": "risk",
        "decision": "Approved" if risk_pass_v3 else "Rejected",
        "reason": risk_reason,
        "timestamp": "—", "processing_ms": 0,
        "status": "PASS" if risk_pass_v3 else "FAIL",
    })

    # AI Decision
    stages.append({
        "agent": "AI Decision", "agent_id": "ai_decision",
        "decision": decision_type,
        "reason": exp_str[:200] or "Decision generated",
        "timestamp": "—", "processing_ms": 0,
        "status": ("PASS" if decision_type in ("BUY", "STRONG_BUY")
                   else "WARN" if decision_type in ("WATCH", "HOLD")
                   else "FAIL"),
    })

    # Execution
    executed = decision_type in ("BUY", "STRONG_BUY")
    paper_order_id = (canon or {}).get("paper_order_id")
    if paper_order_id:
        exec_decision, exec_reason, exec_status = (
            "Paper order placed", f"Paper order {paper_order_id}", "PASS")
    elif executed:
        note = (canon or {}).get("paper_order_note")
        paper_elig = bool((canon or {}).get("paper_eligible"))
        exec_decision = "Paper Eligible" if paper_elig else "Not executed"
        exec_reason = str(note or (
            "Paper-eligible — no order recorded for this scan" if paper_elig
            else "Not paper-eligible for this scan"
        ))
        exec_status = "PASS" if paper_elig else "INFO"
    else:
        exec_decision, exec_reason, exec_status = (
            "Not executed", f"Decision was {decision_type}", "INFO")
    stages.append({
        "agent": "Execution", "agent_id": "execution",
        "decision": exec_decision, "reason": exec_reason,
        "timestamp": "—", "processing_ms": 0, "status": exec_status,
    })

    # Factor Breakdown for Decision Breakdown (Section 2)
    if sc:
        factor_map = {
            "Momentum":      sc.get("momentum", 0),
            "Research":      sc.get("research", 0),
            "Market Regime": sc.get("regime", sc.get("market_intelligence", 0)),
            "Volume":        sc.get("volume", 0),
            "Risk":          sc.get("risk", 0),
            "Technical":     sc.get("technical", 0),
        }
        total_w = sum(_f(v) for v in factor_map.values() if _f(v) > 0)
        factor_breakdown = [
            {
                "factor":     k,
                "weight_pct": round(_f(v) / total_w * 100) if total_w > 0 else 0,
                "score_pct":  round(_f(v) * 100),
            }
            for k, v in factor_map.items() if _f(v) > 0
        ]
    else:
        factor_breakdown = []

    # Why Not This Trade — thresholds (score-based path only; canonical gate
    # reasons already surface in the Scanner stage)
    why_not: Optional[Dict[str, Any]] = None
    if decision_type not in ("BUY", "STRONG_BUY") and sc:
        failing = []
        if conf_pct < 70:
            failing.append({"field": "Confidence", "current": f"{conf_pct}%", "threshold": "≥ 70%"})
        if momsc < 50:
            failing.append({"field": "Momentum", "current": f"{momsc}%", "threshold": "≥ 50%"})
        if regsc < 50:
            failing.append({"field": "Regime", "current": f"{regsc}%", "threshold": "≥ 50%"})
        if risksc < 50:
            failing.append({"field": "Risk Score", "current": f"{risksc}%", "threshold": "≥ 50%"})
        rejected_by = "Risk" if decision_type in ("AVOID",) else "AI Decision"
        why_not = {
            "rejected_by":      rejected_by,
            "reason":           str((rec or {}).get("rejection_reason") or exp_str or "Below threshold"),
            "failing_criteria": failing,
            "alternative":      "Increase confidence above 70% and ensure risk score above 50%.",
        }
    elif decision_type not in ("BUY", "STRONG_BUY") and rec is not None:
        reasons = (rec or {}).get("downgrade_reasons")
        reason_str = "; ".join(str(x) for x in reasons) if isinstance(reasons, list) and reasons \
            else str((rec or {}).get("rejection_reason") or exp_str or "Below threshold")
        why_not = {
            "rejected_by":      "AI Decision",
            "reason":           reason_str,
            "failing_criteria": [],
            "alternative":      "Symbol is re-evaluated automatically on the next scan.",
        }

    return {
        "symbol": symbol, "found": True,
        "decision_type": decision_type, "confidence": conf_pct,
        "stages": stages, "factor_breakdown": factor_breakdown,
        "explanation": exp_str[:300],
        "scores": {k: round(_f(v) * 100) for k, v in sc.items()},
        "why_not": why_not,
    }


def get_ops_centre_agents() -> Dict[str, Any]:
    """
    Lightweight canonical agent status — runs the same 12 parallel collectors
    as the full snapshot but skips V3 enrichment (smart_insights, heatmap, etc.).
    Wall time ≈ 5-8 s (vs 22-30 s for the full snapshot).
    All four dashboard pages consume this endpoint for consistent agent counts.
    """
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

    statuses   = [a.get("status", "UNKNOWN") for a in agents.values()]
    total      = len(agents)
    active     = sum(1 for s in statuses if s == "ACTIVE")
    error      = sum(1 for s in statuses if s == "ERROR")
    disabled   = sum(1 for s in statuses if s == "DISABLED")

    health_scores = [a["health_pct"] for a in agents.values()
                     if a.get("enabled", True) and a.get("status") != "DISABLED"]
    health_pct = round(sum(health_scores) / len(health_scores)) if health_scores else 0

    generated_at = _now_iso()

    # Persist to KV so platform bar reflects updated health without a full snapshot
    try:
        from phase20_store import kv_set as _kv_set
        _kv_set("ops_last_health_pct", str(health_pct))
        _kv_set("ops_agents_ts", generated_at)
        _kv_set("ops_active_agents", str(active))   # read by get_framework_diagnostics()
    except Exception:
        pass

    return {
        "generated_at":  generated_at,
        "advisory_only": True,
        "paper_only":    True,
        "agents":        agents,
        "agent_count": {
            "total":    total,
            "active":   active,
            "error":    error,
            "disabled": disabled,
        },
        "health_pct": health_pct,
    }


def get_agent_list_canonical() -> Dict[str, Any]:
    """
    Agent list in supervisor format sourced from the canonical ops_centre
    collectors — not AgentRegistry (which requires lazy-init per subprocess).
    Used by /api/agent-framework/agents so Agent Operations shows live data.
    """
    result = get_ops_centre_agents()
    agents_raw = result.get("agents", {})

    def _to_row(key: str, a: Dict[str, Any]) -> Dict[str, Any]:
        status    = a.get("status", "UNKNOWN")
        health    = a.get("health_pct", 0)
        enabled   = a.get("enabled", True)
        errors    = list(a.get("errors") or [])

        if not enabled or status == "DISABLED":
            state, hb = "STOPPED", "NEVER"
        elif status == "ACTIVE":
            state, hb = "RUNNING", "OK"
        elif status == "ERROR":
            state, hb = "ERROR", "MISSED"
        else:
            state, hb = "UNKNOWN", "NEVER"

        overall_status = (
            "healthy"  if health >= 70  else
            "degraded" if health >= 40  else
            "critical" if health > 0    else
            "unknown"
        )

        return {
            "agent_id":              a.get("agent_id", key),
            "name":                  a.get("name", key.replace("_", " ").title()),
            "state":                 state,
            "health_score":          float(health),
            "heartbeat_status":      hb,
            "heartbeat_elapsed_s":   0,
            "current_activity":      a.get("current_activity", ""),
            "registered":            enabled and status != "DISABLED",
            "enabled":               enabled,
            "last_error":            errors[0] if errors else None,
            "stocks_in":             a.get("stocks_in", 0),
            "stocks_out":            a.get("stocks_out", 0),
            "stocks_rejected":       a.get("stocks_rejected", 0),
            "rejection_reason":      a.get("rejection_reason", ""),
            # Fields expected by AgentOperations.tsx DataTable columns
            "queue_depth":           a.get("queue_depth", 0),
            "processing_time_ms":    a.get("processing_time_ms", 0.0),
            "snapshots_published":   a.get("snapshots_published", 0),
            "dependencies":          a.get("dependencies", []),
            "overall_health": {
                "status": overall_status,
                "score":  float(health),
            },
        }

    rows = [_to_row(k, v) for k, v in agents_raw.items()]
    active = sum(1 for r in rows if r["state"] == "RUNNING")

    return {
        "available":     True,
        "advisory_only": True,
        "agents":        rows,
        "count":         len(rows),
        "healthy_count": active,
        "overall_health": {
            "status": "healthy" if active == len(rows) else "degraded" if active > 0 else "critical",
            "score":  float(result.get("health_pct", 0)),
        },
    }


def get_ops_centre_diagnostics() -> Dict[str, Any]:
    """
    Backend diagnostics: Agent Registry, Snapshot Bus, feature flags, last snapshot.
    Priority 2 — read-only, never blocks or spawns.
    """
    import os as _os

    # ── Agent Registry ────────────────────────────────────────────────────────
    registry_error: Optional[str] = None
    registered: List[Dict[str, Any]] = []
    try:
        from agent_framework.agent_registry import AgentRegistry as _AR
        _reg = _AR.instance()
        for _a in _reg.all():
            registered.append({
                "id":    getattr(_a, "agent_id", str(_a)),
                "name":  getattr(_a, "name", str(_a)),
                "state": str(getattr(_a, "state", "UNKNOWN")),
            })
    except Exception as _e:
        registry_error = f"{type(_e).__name__}: {_e}"

    # ── Snapshot Bus ──────────────────────────────────────────────────────────
    bus_error: Optional[str] = None
    bus_topics: List[str] = []
    bus_count = 0
    try:
        from agent_framework.snapshot_bus import SnapshotBus as _SB
        _bus = _SB.instance()
        _snaps = getattr(_bus, "_snapshots", {})
        bus_topics = list(_snaps.keys())
        bus_count  = len(bus_topics)
    except Exception as _e:
        bus_error = f"{type(_e).__name__}: {_e}"

    # ── Last snapshot from KV ─────────────────────────────────────────────────
    last_ts     = None
    last_health = None
    try:
        from phase20_store import kv_get as _kv_get
        last_ts     = _kv_get("ops_last_snapshot_ts") or _kv_get("ops_agents_ts")
        last_health = _kv_get("ops_last_health_pct")
    except Exception:
        pass

    # ── Feature flags ─────────────────────────────────────────────────────────
    flag_names = [
        "AGENT_FRAMEWORK_ENABLED", "SUPERVISOR_AGENT_ENABLED",
        "MARKET_DATA_AGENT_ENABLED", "RESEARCH_AGENT_ENABLED",
        "MARKET_INTELLIGENCE_AGENT_ENABLED", "RISK_AGENT_ENABLED",
        "STRATEGY_AGENT_ENABLED", "AI_DECISION_AGENT_ENABLED",
        "EXECUTION_AGENT_ENABLED", "LEARNING_AGENT_ENABLED",
        "KNOWLEDGE_AGENT_ENABLED", "OPERATIONS_AGENT_ENABLED",
        "OPERATIONS_CENTER_ENABLED", "COMMAND_CENTER_ENABLED",
        "PAPER_EXECUTION_ENABLED", "LIVE_EXECUTION_ENABLED",
        "AUTO_PAPER_ENTRIES_ENABLED",
    ]
    flags: Dict[str, bool] = {}
    for _fn in flag_names:
        _default = "true"  # agent flags default ON; execution safety defaults OFF
        if _fn in ("LIVE_EXECUTION_ENABLED", "AUTO_PAPER_ENTRIES_ENABLED"):
            _default = "false"
        flags[_fn] = _os.environ.get(_fn, _default).lower() in ("1", "true", "yes")

    # Active = any non-STOPPED, non-ERROR state in the registry
    _active_ids = [a["id"] for a in registered
                   if not any(s in a["state"] for s in ("STOPPED", "ERROR", "UNKNOWN"))]

    # Note: AgentRegistry and SnapshotBus are per-process singletons.
    # This diagnostics command runs in a fresh subprocess, so registered_count
    # will be 0 here — agents self-register lazily in the running API process.
    # Use /ops-centre/agents for live agent status (calls each agent's snapshot fn).
    return {
        "generated_at": _now_iso(),
        "note": (
            "agent_registry and snapshot_bus reflect this diagnostics subprocess only. "
            "Agents self-register lazily in the API server process. "
            "See /ops-centre/agents for live status."
        ),
        "agent_registry": {
            "status":             "OK" if registry_error is None else "ERROR",
            "error":              registry_error,
            "registered_count":   len(registered),
            "registered_agents":  registered,
            "runtime_note":       "0 in diagnostics subprocess — agents register in the API server process",
        },
        "snapshot_bus": {
            "status":       "OK" if bus_error is None else "ERROR",
            "error":        bus_error,
            "topic_count":  bus_count,
            "topics":       bus_topics,
            "runtime_note": "0 topics in diagnostics subprocess — topics exist in the API server process",
        },
        "active_agents":  _active_ids,
        "active_count":   len(_active_ids),
        "last_snapshot": {
            "timestamp":  last_ts,
            "health_pct": (int(last_health) if last_health else None),
            "scan_id":    None,   # populated by scan_state_store in future
        },
        "snapshot_version": last_ts,
        "feature_flags": flags,
        "connected_pages": [
            "AI Operations Centre (/ai-operations-centre)",
            "AI Paper Trader (/ai-paper-trader)",
            "Agent Operations (/agent-operations)",
            "Command Centre (/command-centre)",
        ],
    }


def get_ops_centre_snapshot() -> Dict[str, Any]:
    """
    Collect all 12 agent snapshots in parallel plus full V3 enrichment.
    Total wall time is typically 22-30 s. Use get_ops_centre_agents() for
    fast canonical status; this full snapshot is for the AI Operations Centre.
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

    # ── Per-agent staleness (V2) ──────────────────────────────────────────────
    try:
        from phase20_store import get_settings as _gs2
        scan_interval_min = int((_gs2() or {}).get("scan_interval_minutes", 5))
    except Exception:
        scan_interval_min = 5

    now_utc = datetime.now(timezone.utc)
    for _ad in agents.values():
        _lts = _ad.get("last_refresh_ts")
        if _lts:
            try:
                _ldt = datetime.fromisoformat(str(_lts).replace("Z", "+00:00"))
                _age = (now_utc - _ldt).total_seconds() / 60
                _ad["data_age_minutes"] = round(_age, 1)
                _ad["is_stale"] = _age > (scan_interval_min * 2)
            except Exception:
                _ad["data_age_minutes"] = None
                _ad["is_stale"] = False
        else:
            _ad["data_age_minutes"] = None
            _ad["is_stale"] = False

    # ── Rejection summary (V2 — Section 5) ───────────────────────────────────
    rejection_summary: List[Dict[str, Any]] = []
    for _ak, _ad in agents.items():
        _rej = _i(_ad.get("stocks_rejected", 0))
        if _rej > 0:
            rejection_summary.append({
                "agent":    _ad.get("name", _ak),
                "agent_id": _ak,
                "reason":   str(_ad.get("rejection_reason") or "Unknown reason"),
                "count":    _rej,
            })
    rejection_summary.sort(key=lambda x: x["count"], reverse=True)

    # ── Performance metrics (V2 — Section 9) ─────────────────────────────────
    _latencies = [(n, _i(a.get("avg_processing_ms", 0)))
                  for n, a in agents.items() if _i(a.get("avg_processing_ms", 0)) > 0]
    _lat_vals = [v for _, v in _latencies]
    _slowest  = max(_latencies, key=lambda x: x[1]) if _latencies else (None, 0)
    _statuses = [a.get("status", "UNKNOWN") for a in agents.values() if a.get("enabled")]
    _healthy  = sum(1 for s in _statuses if s == "ACTIVE")
    _errors   = sum(1 for s in _statuses if s == "ERROR")
    _waiting  = sum(1 for s in _statuses if s == "WAITING")
    _stale    = sum(1 for a in agents.values() if a.get("is_stale"))
    _warning  = sum(1 for a in agents.values()
                    if a.get("status") == "ACTIVE" and a.get("is_stale"))
    _univ     = _i(pipeline.get("universe_loaded", 0))
    _exec     = _i(pipeline.get("paper_orders_executed", 0))
    performance_metrics: Dict[str, Any] = {
        "avg_agent_latency_ms":    round(sum(_lat_vals) / len(_lat_vals)) if _lat_vals else 0,
        "slowest_agent":           agents.get(_slowest[0], {}).get("name") if _slowest[0] else None,
        "slowest_agent_ms":        _slowest[1] if _slowest[0] else 0,
        "enabled_agent_count":     len(_statuses),
        "healthy_count":           _healthy,
        "warning_count":           _warning,
        "error_count":             _errors,
        "waiting_count":           _waiting,
        "stale_count":             _stale,
        "pipeline_efficiency_pct": round(_exec / _univ * 100, 1) if _univ > 0 else 0.0,
    }

    # ── Bottleneck detection (V2 — Section 8) ────────────────────────────────
    bottleneck: Optional[Dict[str, Any]] = None
    _worst_rate = 0.0
    for _ak, _ad in agents.items():
        _si = _i(_ad.get("stocks_in", 0))
        _so = _i(_ad.get("stocks_out", 0))
        if _si > 0:
            _rate = (_si - _so) / _si
            if _rate > _worst_rate and _rate > 0.5:
                _worst_rate = _rate
                bottleneck = {
                    "agent":        _ad.get("name", _ak),
                    "agent_id":     _ak,
                    "rejected_pct": round(_rate * 100),
                    "suggestion":   _get_bottleneck_suggestion(_ak),
                }

    # ── Operator summary (V2 — Section 11) ───────────────────────────────────
    operator_summary = _operator_summary(pipeline, agents, bottleneck)

    # ── Persist fast-access cache so get_fast_platform_status() can serve
    # the platform bar + pipeline flow in < 1 s on the next page load.
    # ops_last_health_pct is always written — even if 0 — so the fast endpoint
    # can distinguish "cached 0%" from "no cache yet" (None sentinel).
    try:
        import json as _json
        from phase20_store import kv_set as _kv_set
        _kv_set("ops_last_health_pct", str(platform["health_pct"]))
        _kv_set("ops_last_pipeline_nodes", _json.dumps(pipeline_nodes))
        _kv_set("ops_last_snapshot_ts", _now_iso())
    except Exception:
        pass  # never block the main snapshot on cache persistence failure

    # ── V3 Enrichment ─────────────────────────────────────────────────────────
    v3 = get_v3_enrichment(agents, pipeline)

    return {
        "generated_at":      _now_iso(),
        "advisory_only":     True,
        "paper_only":        True,
        "platform":          platform,
        "pipeline":          pipeline,
        "pipeline_nodes":    pipeline_nodes,
        "agents":            agents,
        # P4/P6 — pipeline trace and consistency at top level for easy UI access
        "pipeline_trace":        pipeline.get("pipeline_trace", []),
        "pipeline_cycle":        pipeline.get("pipeline_cycle", "—"),
        "scan_id":               pipeline.get("scan_id", "—"),
        "snapshot_ts":           pipeline.get("snapshot_ts", "—"),
        "consistency_ok":        pipeline.get("consistency_ok", True),
        "consistency_note":      pipeline.get("consistency_note", ""),
        "avg_strategy_confidence": pipeline.get("avg_strategy_confidence", 0.0),
        "stale_reason":          pipeline.get("stale_reason", ""),
        # V2 additions
        "rejection_summary":   rejection_summary,
        "performance_metrics": performance_metrics,
        "bottleneck":          bottleneck,
        "operator_summary":    operator_summary,
        # V3 additions
        "missed_opportunities":       v3["missed_opportunities"],
        "confidence_distribution":    v3["confidence_distribution"],
        "recommendation_leaderboard": v3["recommendation_leaderboard"],
        "pipeline_heatmap":           v3["pipeline_heatmap"],
        "smart_insights":             v3["smart_insights"],
        "executive_summary":          v3["executive_summary"],
        "agent_load_monitor":         v3["agent_load_monitor"],
    }


# ── P9: Pipeline Integrity Check ─────────────────────────────────────────────

def get_pipeline_integrity_check() -> Dict[str, Any]:
    """
    9-component automatic integrity check.
    Returns per-component status (PASS / WARN / FAIL), failure reasons,
    and suggested operator actions for any degraded component.
    READ-ONLY · ADVISORY-ONLY
    """
    checks: List[Dict[str, Any]] = []

    def _chk(name: str, status: str, reason: str, action: str = "") -> None:
        checks.append({
            "component":        name,
            "status":           status,
            "reason":           reason,
            "suggested_action": action,
        })

    # 1. Research Agent
    try:
        fn = _get_fn("research_agent.shared_services", "get_research_snapshot")
        snap = fn() if fn else None
        if snap and snap.get("available"):
            last_fail = snap.get("last_failure_at")
            if last_fail:
                _chk("Research Agent", "WARN",
                     f"Active (last failure at {last_fail}): "
                     f"{snap.get('last_failure_reason', '')}",
                     "Previous failures recovered — monitor for recurrence")
            else:
                _chk("Research Agent", "PASS", "Snapshot available and healthy")
        else:
            err = (snap or {}).get("error", "Unavailable")
            _chk("Research Agent", "FAIL", err,
                 "Research data is falling back to cache; restart may help")
    except Exception as exc:
        _chk("Research Agent", "FAIL", str(exc), "Check server logs")

    # 2. Risk Agent
    try:
        from phase20_gates import get_last_evaluation
        ev = get_last_evaluation()
        if ev:
            gc    = bool(ev.get("global_pass", False))
            cands = len(ev.get("candidates", []))
            elig  = int(ev.get("eligible_count", 0))
            if not gc:
                failed_g = [g["gate"] for g in ev.get("global_gates", [])
                            if not g["passed"]]
                _chk("Risk Agent", "WARN",
                     f"Global gates failing: {', '.join(failed_g)}",
                     "Check scan freshness, market open status, and Kite connection")
            else:
                _chk("Risk Agent", "PASS",
                     f"Evaluated {cands} candidates · {elig} approved")
        else:
            _chk("Risk Agent", "WARN",
                 "No entry evaluation available yet",
                 "Wait for first scan or trigger a manual scan")
    except Exception as exc:
        _chk("Risk Agent", "FAIL", str(exc), "Check phase20_gates module")

    # 3. AI Decision Agent
    try:
        fn = _get_fn("ai_decision_agent.shared_services", "get_ai_decision_snapshot")
        snap = fn() if fn else None
        avg_conf = _f((snap or {}).get("avg_confidence", 0)) * 100
        if snap and snap.get("available") and avg_conf > 0:
            _chk("AI Decision Agent", "PASS",
                 f"Active · avg confidence {avg_conf:.0f}%")
        elif snap and snap.get("available"):
            _chk("AI Decision Agent", "WARN",
                 "Active but avg confidence 0% — no BUY candidates reaching this stage",
                 "Check Risk Agent approval rate and strategy confidence thresholds")
        else:
            _chk("AI Decision Agent", "WARN",
                 "No AI decision snapshot (normal when Risk blocks all candidates)",
                 "Ensure Risk Agent is approving candidates")
    except Exception as exc:
        _chk("AI Decision Agent", "FAIL", str(exc), "Check ai_decision_agent module")

    # 4. Execution Agent (paper portfolio)
    try:
        from paper_trader import get_portfolio
        pf   = get_portfolio()
        cash = float(pf.get("cash", 0))
        pos  = len(pf.get("positions") or [])
        _chk("Execution Agent", "PASS",
             f"Portfolio active · ₹{cash:,.0f} cash · {pos} open positions")
    except Exception as exc:
        _chk("Execution Agent", "FAIL", str(exc),
             "Check paper_trader module and DB connection")

    # 5. Scheduler / Auto-scan
    try:
        from scan_state_store import load_latest_meta
        meta    = load_latest_meta() or {}
        snap_ts = meta.get("snapshot_ts")
        if snap_ts:
            try:
                dt      = datetime.fromisoformat(str(snap_ts).replace("Z", "+00:00"))
                age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
                if age_min <= 90:
                    _chk("Scheduler", "PASS", f"Last scan {age_min:.0f}m ago")
                elif age_min <= 480:
                    _chk("Scheduler", "WARN",
                         f"Last scan {age_min:.0f}m ago (stale after 90m)",
                         "Market may be closed; verify auto-scan is enabled in settings")
                else:
                    _chk("Scheduler", "FAIL",
                         f"No scan in {age_min:.0f}m — scheduler likely not running",
                         "Enable auto-scan in settings or trigger a manual scan now")
            except Exception:
                _chk("Scheduler", "WARN",
                     "Cannot parse last scan timestamp", "")
        else:
            _chk("Scheduler", "WARN",
                 "No scan has run yet",
                 "Trigger a manual scan from the Scanner page")
    except Exception as exc:
        _chk("Scheduler", "FAIL", str(exc),
             "Check scan_state_store and DB connection")

    # 6. Market Data
    try:
        fn   = _get_fn("market_data_agent.shared_services", "get_market_data_snapshot")
        snap = fn() if fn else None
        cov  = _f((snap or {}).get("coverage_pct", 0))
        if snap and snap.get("available") and cov >= 50:
            _chk("Market Data", "PASS", f"Coverage {cov:.0f}%")
        elif snap and snap.get("available"):
            _chk("Market Data", "WARN", f"Low coverage {cov:.0f}%",
                 "Check Kite session; it may have expired")
        else:
            _chk("Market Data", "FAIL",
                 "Market data snapshot unavailable",
                 "Check Kite session and data provider configuration")
    except Exception as exc:
        _chk("Market Data", "FAIL", str(exc),
             "Check market_data_agent module")

    # 7. Snapshot Consistency
    try:
        from phase15_scan_context import build_scan_context
        ctx     = build_scan_context()
        from phase20_gates import get_last_evaluation
        ev      = get_last_evaluation() or {}
        ctx_sid = str(ctx.get("scan_id") or "")
        ev_sid  = str(ev.get("scan_id") or "")
        if ctx_sid and ev_sid and ctx_sid != ev_sid:
            _chk("Snapshot Consistency", "WARN",
                 f"Scan context scan_id ({ctx_sid[:8]}) ≠ "
                 f"Risk evaluation scan_id ({ev_sid[:8]})",
                 "Trigger a fresh scan to re-align all pipeline stages")
        elif not ctx_sid:
            _chk("Snapshot Consistency", "WARN",
                 "No canonical scan_id found — scan may not have run",
                 "Trigger a manual scan")
        else:
            _chk("Snapshot Consistency", "PASS",
                 "All pipeline stages using the same scan_id")
    except Exception as exc:
        _chk("Snapshot Consistency", "WARN", str(exc), "")

    # 8. Confidence Flow
    try:
        from phase15_scan_context import build_scan_context
        ctx      = build_scan_context()
        symbols  = ctx.get("symbols") or {}
        buy_recs = [r for r in symbols.values()
                    if str(r.get("final_action", "")).upper() in ("BUY", "STRONG BUY")]
        if buy_recs:
            avg_c = sum(_f(r.get("confidence", 0)) * 100 for r in buy_recs) / len(buy_recs)
            _chk("Confidence Flow", "PASS",
                 f"Strategy generating BUY confidence · "
                 f"avg {avg_c:.0f}% across {len(buy_recs)} candidates")
        else:
            _chk("Confidence Flow", "WARN",
                 "No BUY recommendations — confidence not flowing to AI Decision",
                 "Check strategy thresholds and current market regime conditions")
    except Exception as exc:
        _chk("Confidence Flow", "WARN", str(exc),
             "Check phase15_scan_context module")

    # 9. Circuit Breaker
    try:
        from phase20_store import kv_get as _cb_kv
        cb      = _cb_kv("circuit_breaker_state") or {}
        tripped = bool(cb.get("tripped"))
        if tripped:
            _chk("Circuit Breaker", "FAIL",
                 f"TRIPPED: {cb.get('reason', 'unknown reason')}",
                 "Manual review required before entries can resume")
        else:
            _chk("Circuit Breaker", "PASS", "Circuit breaker clear — entries permitted")
    except Exception as exc:
        _chk("Circuit Breaker", "WARN", str(exc),
             "Check phase20_store module")

    # 10. Evidence Coverage — warns when too many symbols have fewer than
    #     5 backtest trades, since this structurally caps their confidence
    #     below the BUY threshold and operators may mistake IGNORE for a fault.
    try:
        from scan_state_store import load_latest_snapshot
        _snap = load_latest_snapshot()
        if _snap:
            _recs = _snap.get("recommendations") or []
            _valid = [r for r in _recs if not r.get("error")]
            if _valid:
                _low_ev = sum(1 for r in _valid if int(r.get("total_trades", 0) or 0) < 5)
                _low_pct = _low_ev / len(_valid) * 100
                if _low_pct > 30:
                    _chk("Evidence Coverage", "WARN",
                         f"{_low_ev}/{len(_valid)} symbols ({_low_pct:.0f}%) have <5 backtest trades — "
                         f"confidence scores are capped; IGNORE is expected for thin-evidence stocks",
                         "Continue running paper trades to accumulate evidence; "
                         "BUY recommendations will appear naturally as sample size grows")
                else:
                    _chk("Evidence Coverage", "PASS",
                         f"{_low_ev}/{len(_valid)} symbols ({_low_pct:.0f}%) low-evidence — "
                         f"within acceptable range")
            else:
                _chk("Evidence Coverage", "WARN",
                     "No valid scan items to assess evidence coverage",
                     "Trigger a manual scan")
        else:
            _chk("Evidence Coverage", "WARN",
                 "No scan snapshot available to check evidence coverage",
                 "Trigger a manual scan")
    except Exception as exc:
        _chk("Evidence Coverage", "WARN", str(exc),
             "Check scan_state_store module")

    overall = (
        "PASS" if all(c["status"] == "PASS" for c in checks)
        else "WARN" if all(c["status"] in ("PASS", "WARN") for c in checks)
        else "FAIL"
    )

    return {
        "generated_at":  _now_iso(),
        "advisory_only": True,
        "paper_only":    True,
        "overall":       overall,
        "checks":        checks,
        "pass_count":    sum(1 for c in checks if c["status"] == "PASS"),
        "warn_count":    sum(1 for c in checks if c["status"] == "WARN"),
        "fail_count":    sum(1 for c in checks if c["status"] == "FAIL"),
    }


# ── P8: Pipeline Cycle Log ────────────────────────────────────────────────────

def get_pipeline_cycle_log() -> Dict[str, Any]:
    """
    Returns structured per-pipeline-cycle logs written to KV by phase20_gates
    after each evaluation.  Keeps the last 50 cycles.
    READ-ONLY · ADVISORY-ONLY
    """
    try:
        from phase20_store import kv_get
        cycles = kv_get("pipeline_cycle_log") or []
    except Exception:
        cycles = []

    return {
        "generated_at":  _now_iso(),
        "advisory_only": True,
        "cycles":        list(reversed(cycles)),   # newest first
        "total_cycles":  len(cycles),
    }
