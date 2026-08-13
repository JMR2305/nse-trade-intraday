"""
replay_engine.py — Feature 11-16: Operations Centre Replay Mode

Reconstructs the full AI agent pipeline from scan_state.snapshot so operators
can watch the AI "thinking" step-by-step, inspect per-symbol journeys, compare
AI decisions against actual market outcomes, and get an executive summary.

Design principles
-----------------
• Deterministic — identical scan_id always produces identical output.
• Read-only — never modifies stored data.
• Extensible — replay_events table stub ready for live instrumentation in v2.
• Graceful — missing fields surface as None / empty lists, never crash.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_conn():
    url = os.environ.get("DATABASE_URL", "")
    if not url or not PSYCOPG2_AVAILABLE:
        return None
    try:
        return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    except Exception:
        return None


def _q(conn, sql: str, params=()) -> List[Dict]:
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def _q1(conn, sql: str, params=()) -> Optional[Dict]:
    rows = _q(conn, sql, params)
    return rows[0] if rows else None


def _is_buy_action(action) -> bool:
    """Canonical BUY classification — the scanner emits both 'BUY' and
    'STRONG BUY' (space) as buy decisions; normalise before comparing."""
    return str(action or "").upper().replace("_", " ") in ("BUY", "STRONG BUY")


def _today_ist() -> str:
    """Return today's date in IST (UTC+5:30) as YYYY-MM-DD."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:
        return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def _snapshot_date_ist(snapshot_ts: str) -> Optional[str]:
    """Return the IST date of a snapshot timestamp as YYYY-MM-DD, or None."""
    if not snapshot_ts:
        return None
    try:
        dt = datetime.fromisoformat(str(snapshot_ts).replace("Z", "+00:00"))
        ist_dt = dt + timedelta(hours=5, minutes=30)
        return ist_dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def _is_today_session(snapshot_ts: str) -> bool:
    """Return True when the snapshot's IST date equals today's IST date."""
    date_ist = _snapshot_date_ist(snapshot_ts)
    return bool(date_ist and date_ist == _today_ist())


# ---------------------------------------------------------------------------
# Stage definitions — order matches the live pipeline
# ---------------------------------------------------------------------------

STAGES = [
    {"id": "supervisor",          "label": "Supervisor",         "order": 0},
    {"id": "market_data",         "label": "Market Data",        "order": 1},
    {"id": "research",            "label": "Research",           "order": 2},
    {"id": "market_intelligence", "label": "Market Intelligence","order": 3},
    {"id": "monitoring",          "label": "Monitoring",         "order": 4},
    {"id": "strategy",            "label": "Strategy",           "order": 5},
    {"id": "portfolio_precheck",  "label": "Portfolio Pre-Check","order": 6},
    {"id": "risk",                "label": "Risk",               "order": 7},
    {"id": "ai_decision",         "label": "AI Decision",        "order": 8},
    {"id": "execution",           "label": "Execution",          "order": 9},
]


# ---------------------------------------------------------------------------
# Configured paper-trading capital (single source of truth)
# ---------------------------------------------------------------------------

def _configured_capital() -> float:
    """
    Return the configured paper-trading starting capital.
    Single source of truth: portfolio_store.INITIAL_CAPITAL (₹50,000).
    Never hardcode capital values elsewhere in this module.
    """
    try:
        from portfolio_store import INITIAL_CAPITAL
        return float(INITIAL_CAPITAL)
    except Exception:
        return 50_000.0


# ---------------------------------------------------------------------------
# Helpers — snapshot parsing
# ---------------------------------------------------------------------------

def _data_quality_score(dq: Any) -> float:
    """Map data_quality label to 0-100 score."""
    mapping = {"EXCELLENT": 95, "GOOD": 80, "FAIR": 60, "POOR": 35, "UNAVAILABLE": 0}
    if isinstance(dq, (int, float)):
        return float(dq)
    if isinstance(dq, str):
        return float(mapping.get(dq.upper(), 50))
    return 50.0


def _str(v: Any, fallback: str = "—") -> str:
    if v is None:
        return fallback
    return str(v)


def _pct(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Core — reconstruct stages from snapshot.recommendations
# ---------------------------------------------------------------------------

def _get_precheck_decisions(scan_id: str) -> Dict[str, Dict]:
    """
    Latest Portfolio Pre-Check decision per symbol for a scan, reconstructed
    PURELY from canonical pipeline events (PRECHECK_APPROVED /
    PRECHECK_REJECTED). Returns {} on any failure — replay must never break
    because the event store is unavailable.
    """
    out: Dict[str, Dict] = {}
    if not scan_id:
        return out
    try:
        import pipeline_events
        events = pipeline_events.query_events(
            scan_id=scan_id, stage="PORTFOLIO_PRECHECK", limit=2000)
        for e in events:  # ascending id — the last decision per symbol wins
            et = e.get("event_type")
            if et not in ("PRECHECK_APPROVED", "PRECHECK_REJECTED"):
                continue
            sym = e.get("symbol")
            if not sym:
                continue
            payload = e.get("payload") or {}
            out[sym] = {
                "approved": et == "PRECHECK_APPROVED",
                "reasons": list(payload.get("reasons") or []),
                "blocking_limit": payload.get("blocking_limit"),
            }
    except Exception:
        return {}
    return out


def _build_stages_from_snapshot(snapshot: Dict,
                                precheck_decisions: Optional[Dict[str, Dict]] = None) -> List[Dict]:
    """
    Reconstruct the pipeline stages from a Phase7ScanResult snapshot dict.
    Returns a list of stage dicts ordered by pipeline position.

    `precheck_decisions` ({symbol: {approved, reasons, ...}}) is replayed from
    canonical pipeline events only (see _get_precheck_decisions) — the replay
    NEVER re-evaluates portfolio rules.
    """
    raw_recs: List[Dict] = snapshot.get("recommendations") or []
    provider = snapshot.get("provider_health") or {}
    audit = snapshot.get("scan_audit") or {}
    timings = snapshot.get("timings") or {}

    # ── Canonicalize: one record per symbol (first wins), track duplicates ──
    # Duplicate rows in a snapshot must never fabricate duplicate orders/counts.
    recs: List[Dict] = []
    _seen: set = set()
    duplicate_symbols: List[str] = []
    for r in raw_recs:
        sym = r.get("symbol")
        if not sym:
            continue
        if sym in _seen:
            duplicate_symbols.append(sym)
            continue
        _seen.add(sym)
        recs.append(r)

    universe_size: int = int(snapshot.get("universe_size") or len(recs) or 0)

    # ── Reconstruct per-stage symbol sets ──────────────────────────────────

    # Stage 0 — Supervisor: all universe symbols
    supervisor_symbols = [r["symbol"] for r in recs if r.get("symbol")]
    # Try to get universe from provider_health for true universe size
    universe_symbols_count = int(provider.get("symbols_requested") or universe_size)

    # Stage 1 — Market Data: symbols that actually received data.
    # Clamp provider counts so an inconsistent snapshot (received > requested,
    # or requested < deduped record count) can never produce negative rejected
    # counts — validate and surface, never fabricate.
    provider_count_anomaly = False
    _received_raw = int(provider.get("symbols_received") or len(recs))
    if universe_symbols_count < len(recs):
        provider_count_anomaly = True
        universe_symbols_count = len(recs)
    market_data_received = _received_raw
    if market_data_received > universe_symbols_count:
        provider_count_anomaly = True
        market_data_received = universe_symbols_count
    market_data_symbols = [r["symbol"] for r in recs if r.get("symbol") and not (r.get("error") or "").startswith("MARKET_DATA")]

    # CONSERVATION: every stage's output must be a subset of its input.
    # Each stage filters the PREVIOUS stage's symbols by its own criterion —
    # never re-derives from the full record set (which could "create" records).

    # Stage 2 — Research: global; all market_data symbols proceed (research is not per-symbol gating)
    research_symbols = market_data_symbols
    _research_set = set(research_symbols)

    # Stage 3 — Market Intelligence: filter research output by data quality
    mi_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") in _research_set and _data_quality_score(r.get("data_quality")) >= 35
    ]
    _mi_set = set(mi_symbols)

    # Stage 4 — Monitoring: pass-through of market intelligence
    monitoring_symbols = mi_symbols
    _monitoring_set = _mi_set

    # Stage 5 — Strategy: monitoring symbols that have a strategy assigned
    strategy_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") in _monitoring_set and (r.get("strategy_id") or r.get("strategy_name"))
    ]
    _strategy_set = set(strategy_symbols)

    # Stage 6 — Portfolio Pre-Check: decisions replayed from canonical events
    # only. Symbols the pre-check explicitly rejected stop here and NEVER
    # appear in Risk or later stages. Symbols with no recorded decision
    # (pre-check only evaluates actual BUY attempts) pass through.
    _pc = precheck_decisions or {}
    precheck_rejected_symbols = [
        s for s in strategy_symbols if (_pc.get(s) or {}).get("approved") is False
    ]
    _pc_rejected_set = set(precheck_rejected_symbols)
    precheck_symbols = [s for s in strategy_symbols if s not in _pc_rejected_set]
    _precheck_set = set(precheck_symbols)
    precheck_evaluated = [s for s in strategy_symbols if s in _pc]
    precheck_approved = [
        s for s in precheck_evaluated if (_pc.get(s) or {}).get("approved") is True
    ]

    # Stage 7 — Risk: pre-check output where all gates passed
    risk_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") in _precheck_set and r.get("all_gates_passed")
    ]
    _risk_set = set(risk_symbols)

    # Stage 7 — AI Decision: risk-approved symbols with a meaningful final action
    ai_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") in _risk_set and r.get("final_action") not in (None, "AVOID", "SELL")
    ]
    # AVOID tracked separately for stats (from risk-approved input only)
    avoid_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") in _risk_set and r.get("final_action") == "AVOID"
    ]
    buy_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") in _risk_set and _is_buy_action(r.get("final_action"))
    ]

    # Stage 8 — Execution: paper-eligible AND approved by Decision.
    # CONSERVATION RULE: Execution can NEVER output more records than it
    # receives from Decision.  A snapshot row can be marked paper_eligible
    # while its final_action is not BUY (stale eligibility, upstream record
    # mismatch).  Those rows are surfaced as anomalies — never counted as
    # execution output, never fabricated into the pipeline.
    _paper_eligible_all = [
        r["symbol"] for r in recs
        if r.get("symbol") and r.get("paper_eligible")
    ]
    _buy_set = set(buy_symbols)
    execution_symbols = [s for s in _paper_eligible_all if s in _buy_set]
    # Orphans: paper-eligible without an approved BUY decision — an integrity
    # violation of "every BUY originates from an approved Decision".
    execution_orphans = [s for s in _paper_eligible_all if s not in _buy_set]

    # ── Timing ─────────────────────────────────────────────────────────────
    def _ms(key: str) -> Optional[int]:
        v = timings.get(key)
        if v is None:
            return None
        try:
            return int(float(v) * 1000)
        except (TypeError, ValueError):
            return None

    # ── Assemble stages ────────────────────────────────────────────────────
    stages = [
        {
            "id": "supervisor",
            "label": "Supervisor",
            "order": 0,
            "stocks_in": universe_symbols_count,
            "stocks_out": universe_symbols_count,
            "rejected": 0,
            "rejected_symbols": [],
            "stocks": supervisor_symbols[:50],
            "duration_ms": _ms("supervisor") or 50,
            "description": f"Received {universe_symbols_count} symbols from watchlist",
            "status": "COMPLETE",
        },
        {
            "id": "market_data",
            "label": "Market Data",
            "order": 1,
            "stocks_in": universe_symbols_count,
            "stocks_out": len(market_data_symbols),
            "rejected": universe_symbols_count - len(market_data_symbols),
            "rejected_symbols": (snapshot.get("missing_symbols") or [])[:10],
            "stocks": market_data_symbols[:50],
            "anomalies": (["PROVIDER_COUNT_MISMATCH"] if provider_count_anomaly else []) + duplicate_symbols[:10],
            "anomaly_count": (1 if provider_count_anomaly else 0) + len(duplicate_symbols),
            "duration_ms": _ms("market_data") or 8500,
            "description": (
                f"Fetched live data for {market_data_received} symbols"
                + (f" · {len(duplicate_symbols)} duplicate record(s) removed" if duplicate_symbols else "")
                + (" · provider counts inconsistent (clamped)" if provider_count_anomaly else "")
            ),
            "status": "COMPLETE",
        },
        {
            "id": "research",
            "label": "Research",
            "order": 2,
            "stocks_in": len(market_data_symbols),
            "stocks_out": len(research_symbols),
            "rejected": 0,
            "rejected_symbols": [],
            "stocks": research_symbols[:50],
            "duration_ms": _ms("research") or 200,
            "description": "Global research context applied — earnings, macro, sector news",
            "status": "COMPLETE",
        },
        {
            "id": "market_intelligence",
            "label": "Market Intelligence",
            "order": 3,
            "stocks_in": len(research_symbols),
            "stocks_out": len(mi_symbols),
            "rejected": len(research_symbols) - len(mi_symbols),
            "rejected_symbols": [s for s in research_symbols if s not in set(mi_symbols)][:10],
            "stocks": mi_symbols[:50],
            "duration_ms": _ms("market_intelligence") or 1200,
            "description": f"{len(mi_symbols)} symbols passed data quality threshold",
            "status": "COMPLETE",
        },
        {
            "id": "monitoring",
            "label": "Monitoring",
            "order": 4,
            "stocks_in": len(mi_symbols),
            "stocks_out": len(monitoring_symbols),
            "rejected": 0,
            "rejected_symbols": [],
            "stocks": monitoring_symbols[:50],
            "duration_ms": _ms("monitoring") or 100,
            "description": "Regime and alert monitoring applied",
            "status": "COMPLETE",
        },
        {
            "id": "strategy",
            "label": "Strategy",
            "order": 5,
            "stocks_in": len(monitoring_symbols),
            "stocks_out": len(strategy_symbols),
            "rejected": len(monitoring_symbols) - len(strategy_symbols),
            "rejected_symbols": [s for s in monitoring_symbols if s not in set(strategy_symbols)][:10],
            "stocks": strategy_symbols[:50],
            "duration_ms": _ms("strategy") or 3000,
            "description": f"{len(strategy_symbols)} symbols matched a strategy",
            "status": "COMPLETE",
        },
        {
            "id": "portfolio_precheck",
            "label": "Portfolio Pre-Check",
            "order": 6,
            "stocks_in": len(strategy_symbols),
            "stocks_out": len(precheck_symbols),
            "rejected": len(precheck_rejected_symbols),
            "rejected_symbols": precheck_rejected_symbols[:10],
            "rejection_reasons": {
                s: (_pc.get(s) or {}).get("reasons") or []
                for s in precheck_rejected_symbols[:10]
            },
            "stocks": precheck_symbols[:50],
            "evaluated_count": len(precheck_evaluated),
            # Event-derived approvals only — symbols never evaluated (no BUY
            # attempt) are NOT counted as approved.
            "approved_count": len(precheck_approved),
            "not_evaluated": len(precheck_symbols) - len(precheck_approved),
            "duration_ms": _ms("portfolio_precheck") or 50,
            "description": (
                f"{len(precheck_evaluated)} BUY candidate(s) evaluated by the "
                f"Portfolio Engine · {len(precheck_rejected_symbols)} blocked"
                if precheck_evaluated
                else "No BUY candidates reached the portfolio pre-check"
            ),
            "status": "COMPLETE",
        },
        {
            "id": "risk",
            "label": "Risk",
            "order": 7,
            "stocks_in": len(precheck_symbols),
            "stocks_out": len(risk_symbols),
            "rejected": len(precheck_symbols) - len(risk_symbols),
            "rejected_symbols": [s for s in precheck_symbols if s not in set(risk_symbols)][:10],
            "stocks": risk_symbols[:50],
            "duration_ms": _ms("risk") or 500,
            "description": f"{len(risk_symbols)} approved · {len(precheck_symbols) - len(risk_symbols)} rejected by gates",
            "status": "COMPLETE",
        },
        {
            "id": "ai_decision",
            "label": "AI Decision",
            "order": 8,
            "stocks_in": len(risk_symbols),
            # stocks_out = BUY only; rejected = everything that didn't become BUY (clamped ≥ 0)
            "stocks_out": len(buy_symbols),
            "rejected": max(0, len(risk_symbols) - len(buy_symbols)),
            "rejected_symbols": avoid_symbols[:10],
            "stocks": buy_symbols[:50],
            "buy_count": len(buy_symbols),
            "avoid_count": len(avoid_symbols),
            "watch_count": max(0, len(ai_symbols) - len(buy_symbols)),
            "duration_ms": _ms("ai_decision") or 800,
            "description": f"BUY: {len(buy_symbols)} · AVOID/WATCH: {max(0, len(risk_symbols) - len(buy_symbols))}",
            "status": "COMPLETE",
        },
        {
            "id": "execution",
            "label": "Execution",
            "order": 9,
            "stocks_in": len(buy_symbols),
            "stocks_out": len(execution_symbols),
            # Conservation holds by construction: execution_symbols ⊆ buy_symbols
            "rejected": len(buy_symbols) - len(execution_symbols),
            "rejected_symbols": [s for s in buy_symbols if s not in set(execution_symbols)][:10],
            "stocks": execution_symbols[:50],
            "paper_orders": len(execution_symbols),
            "anomalies": execution_orphans[:10],
            "anomaly_count": len(execution_orphans),
            "duration_ms": _ms("execution") or 300,
            "description": (
                f"{len(execution_symbols)} paper orders placed"
                + (f" · {len(execution_orphans)} anomalous record(s) excluded (paper-eligible without BUY decision)" if execution_orphans else "")
            ),
            "status": "COMPLETE",
        },
    ]

    # Normalize the count contract on every stage:
    # Received = Passed + Rejected + Pending + Cancelled (pending/cancelled
    # default 0 in reconstructed replays; unaccounted symbols become pending).
    for s in stages:
        s.setdefault("anomalies", [])
        s.setdefault("anomaly_count", 0)
        unaccounted = s["stocks_in"] - s["stocks_out"] - max(0, s["rejected"])
        s["pending"] = max(0, unaccounted)
        s["cancelled"] = 0

    # ── Post-build integrity validation (warn to logs, never raise) ──────────
    import logging as _logging
    _log = _logging.getLogger(__name__)
    for s in stages:
        sid = s["id"]
        sin, sout, srej = s["stocks_in"], s["stocks_out"], s["rejected"]
        # Detect any remaining impossible values
        if srej < 0:
            _log.warning("REPLAY INTEGRITY: stage=%s rejected=%d < 0 — clamped but source data inconsistent", sid, srej)
        if sout < 0:
            _log.warning("REPLAY INTEGRITY: stage=%s stocks_out=%d < 0", sid, sout)
        if sout + max(0, srej) > sin:
            _log.warning(
                "REPLAY INTEGRITY: stage=%s input=%d < passed=%d + rejected=%d (stage creates records)",
                sid, sin, sout, srej,
            )

    return stages


# ---------------------------------------------------------------------------
# Execution trades helper — real paper trade records enriched with scan data
# ---------------------------------------------------------------------------

def _get_execution_trades(conn, scan_id: str, snapshot: Dict) -> List[Dict]:
    """
    Fetch paper trades from phase20_paper_trades scoped to the given scan_id.

    The phase20_paper_trades table stores one row per BUY/SELL event with a
    mandatory scan_id column, so this query is strictly session-scoped.
    Falls back to empty list gracefully — never cross-contaminates sessions.
    """
    if not conn:
        return []

    # Resolve 'latest' to the actual scan_id from the snapshot if needed
    effective_scan_id = snapshot.get("scan_id") or scan_id
    if not effective_scan_id or effective_scan_id == "latest":
        return []   # cannot scope without a concrete scan_id — return nothing

    try:
        trade_rows = _q(conn, """
            SELECT trade_id, scan_id, symbol, side, strategy_name,
                   fill_price, quantity, stop_loss, target, confidence,
                   fill_ts, exit_ts, exit_price, exit_rule, realized_pnl,
                   trade_quality_score, status
            FROM phase20_paper_trades
            WHERE scan_id = %s
            ORDER BY fill_ts ASC
            LIMIT 200
        """, (effective_scan_id,))
    except Exception:
        # Table may not exist (e.g. no DB / fresh environment)
        return []

    trades = []
    for row in trade_rows:
        sym = row.get("symbol")
        if not sym:
            continue
        entry_price = _pct(row.get("fill_price"))
        if not entry_price or entry_price <= 0:
            continue

        qty          = int(row.get("quantity") or 0) or max(1, int(10_000 // entry_price))
        capital_used = entry_price * qty
        stop_loss    = _pct(row.get("stop_loss"))
        target       = _pct(row.get("target"))
        confidence   = round(float(row.get("confidence") or 0))
        strategy     = row.get("strategy_name")
        risk_score   = round(float(row.get("trade_quality_score") or 0))
        entry_ts     = str(row.get("fill_ts") or "")
        exit_price   = _pct(row.get("exit_price"))
        exit_ts      = str(row.get("exit_ts") or "") or None
        exit_reason  = row.get("exit_rule")
        pnl          = _pct(row.get("realized_pnl"))

        # Compute pnl_pct from realized_pnl when possible
        pnl_pct: float | None = None
        if pnl is not None and capital_used > 0:
            pnl_pct = round((pnl / capital_used) * 100, 4)
        elif exit_price is not None:
            pnl = round((exit_price - entry_price) * qty, 2)
            pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 4)

        trades.append({
            "symbol":       sym,
            "action":       str(row.get("side") or "BUY"),
            "entry_price":  entry_price,
            "qty":          qty,
            "capital_used": round(capital_used, 2),
            "stop_loss":    stop_loss,
            "target":       target,
            "confidence":   confidence,
            "strategy":     strategy,
            "risk_score":   risk_score,
            "entry_ts":     entry_ts if entry_ts else None,
            "exit_price":   exit_price,
            "exit_ts":      exit_ts,
            "exit_reason":  exit_reason,
            "pnl":          pnl,
            "pnl_pct":      pnl_pct,
        })

    return trades


# ---------------------------------------------------------------------------
# Per-symbol journey reconstruction
# ---------------------------------------------------------------------------

def _build_symbol_journey(rec: Dict, snapshot: Dict,
                          precheck: Optional[Dict] = None,
                          execution_outcome: Optional[Dict] = None) -> List[Dict]:
    """
    Reconstruct the full per-symbol timeline across all 9 agent stages.
    Each entry has: stage, timestamp (relative), result, score, reason.
    """
    snap_ts = snapshot.get("snapshot_ts") or ""
    symbol = rec.get("symbol", "")
    dq = rec.get("data_quality")
    dq_score = _data_quality_score(dq)
    has_strategy = bool(rec.get("strategy_id") or rec.get("strategy_name"))
    all_gates = bool(rec.get("all_gates_passed"))
    final_action = rec.get("final_action") or "UNKNOWN"
    paper_eligible = bool(rec.get("paper_eligible"))
    error = rec.get("error") or ""

    # ── Execution outcome: derive label from actual pipeline event, not the
    # paper_eligible flag alone.  execution_outcome is injected by the caller
    # from pipeline_events (EXECUTION_SKIPPED_WITH_REASON / ORDER_REJECTED /
    # ORDER_SUBMITTED / ORDER_EXECUTED).  When absent the label is honest
    # ("outcome not recorded") rather than the misleading "Paper order placed".
    _eo = execution_outcome or {}
    _eo_type = _eo.get("event_type")
    _eo_gate_reasons: dict = _eo.get("failed_gate_reasons") or {}
    _eo_reason_str = (
        "; ".join(str(v) for v in _eo_gate_reasons.values())
        if _eo_gate_reasons
        else (_eo.get("note") or "")
    )
    if _eo_type in ("ORDER_SUBMITTED", "ORDER_EXECUTED"):
        _exec_result = "PAPER BUY"
        _exec_reason = "Paper order placed and recorded"
    elif _eo_type == "EXECUTION_SKIPPED_WITH_REASON":
        _exec_result = "SKIPPED"
        _exec_reason = (
            f"Execution skipped — {_eo_reason_str}"
            if _eo_reason_str else "Execution gate blocked this order"
        )
    elif _eo_type == "ORDER_REJECTED":
        _exec_result = "REJECTED"
        _exec_reason = (
            f"Order rejected — {_eo_reason_str}"
            if _eo_reason_str else "Order rejected by execution gate"
        )
    elif paper_eligible:
        # paper_eligible=True in snapshot but no execution event for this scan_id
        # "Paper eligible" (not "Paper order placed") — no actual order was placed
        _exec_result = "ELIGIBLE"
        _exec_reason = "Paper eligible"
    else:
        _exec_result = "SKIPPED" if not _is_buy_action(final_action) else "REJECTED"
        _exec_reason = (
            f"Action: {final_action}" if not _is_buy_action(final_action)
            else "Not paper-eligible"
        )

    journey = [
        {
            "stage": "supervisor",
            "label": "Supervisor",
            "result": "PASS",
            "score": None,
            "reason": "Symbol accepted into pipeline",
            "detail": None,
        },
        {
            "stage": "market_data",
            "label": "Market Data",
            "result": "PASS" if dq_score >= 35 else "FAIL",
            "score": round(dq_score),
            "reason": f"Data quality: {_str(dq)}",
            "detail": {
                "data_source": rec.get("data_source"),
                "data_age_days": rec.get("data_age_days"),
                "bars_available": rec.get("bars_available"),
                "latest_bar_date": rec.get("latest_bar_date"),
            },
        },
        {
            "stage": "research",
            "label": "Research",
            "result": "PASS",
            "score": None,
            "reason": "Global research context applied",
            "detail": {"sector": rec.get("sector"), "regime": rec.get("regime")},
        },
        {
            "stage": "market_intelligence",
            "label": "Market Intelligence",
            "result": "PASS" if dq_score >= 35 else "WARN",
            "score": round(dq_score),
            "reason": f"Intelligence score: {round(dq_score)}",
            "detail": {
                "data_quality": _str(dq),
                "regime": rec.get("regime"),
            },
        },
        {
            "stage": "monitoring",
            "label": "Monitoring",
            "result": "PASS",
            "score": None,
            "reason": "No active alerts",
            "detail": None,
        },
        {
            "stage": "strategy",
            "label": "Strategy",
            "result": "PASS" if has_strategy else "FAIL",
            "score": round(float(rec.get("technical_score") or 0)),
            "reason": rec.get("strategy_name") or ("No strategy matched" if not has_strategy else "Strategy assigned"),
            "detail": {
                "strategy": rec.get("strategy_name"),
                "score": rec.get("technical_score"),
                "confidence": rec.get("calibrated_confidence"),
                "adx": rec.get("adx"),
                "rsi": rec.get("rsi"),
                "volume_ratio": rec.get("volume_ratio"),
                "above_ema20": rec.get("above_ema20"),
                "above_ema50": rec.get("above_ema50"),
            },
        },
        {
            "stage": "portfolio_precheck",
            "label": "Portfolio Pre-Check",
            "result": (
                "NOT EVALUATED" if precheck is None
                else ("PASS" if precheck.get("approved") else "BLOCKED")
            ),
            "score": None,
            "reason": (
                "No BUY attempt reached the portfolio pre-check" if precheck is None
                else ("Allocation & limits approved" if precheck.get("approved")
                      else "; ".join(precheck.get("reasons") or ["Blocked by portfolio limits"]))
            ),
            "detail": precheck,
        },
        {
            "stage": "risk",
            "label": "Risk",
            "result": "PASS" if all_gates else "FAIL",
            "score": None,
            "reason": "All gates passed" if all_gates else _build_rejection_reason(rec),
            "detail": {
                "gate_price": rec.get("gate_price"),
                "gate_data_quality": rec.get("gate_data_quality"),
                "gate_rr": rec.get("gate_rr"),
                "gate_volume": rec.get("gate_volume"),
                "rr_ratio": rec.get("rr_ratio"),
                "entry_price": rec.get("entry_price"),
                "stop_loss": rec.get("stop_loss"),
                "target_price": rec.get("target_price"),
                "heat": rec.get("heat"),
            },
        },
        {
            "stage": "ai_decision",
            "label": "AI Decision",
            "result": final_action,
            "score": round(float(rec.get("opportunity_score") or rec.get("calibrated_confidence") or 0)),
            "reason": f"{final_action} — confidence {round(float(rec.get('calibrated_confidence') or 0))}%",
            "detail": {
                "final_action": final_action,
                "confidence": rec.get("calibrated_confidence"),
                "opportunity_score": rec.get("opportunity_score"),
                "technical_score": rec.get("technical_score"),
                "historical_adjustment": rec.get("historical_evidence_adjustment"),
                "low_evidence": rec.get("low_evidence"),
            },
        },
        {
            "stage": "execution",
            "label": "Execution",
            # result/reason derived from actual pipeline outcome; see variable
            # computation above (before journey = [...]).
            "result": _exec_result,
            "score": None,
            "reason": _exec_reason,
            "detail": {
                "paper_eligible": paper_eligible,
                "execution_event": _eo_type,
                "paper_order_id": rec.get("paper_order_id"),
                "paper_order_note": rec.get("paper_order_note"),
                "entry_price": rec.get("entry_price"),
            },
        },
    ]
    # Pre-check BLOCKED (event-derived): nothing downstream actually happened
    # for this symbol — mark Risk / AI Decision / Execution as skipped instead
    # of showing stale snapshot-derived PASS/BUY results.
    if precheck is not None and not precheck.get("approved"):
        _blocked_reason = "; ".join(precheck.get("reasons") or ["Blocked by portfolio limits"])
        for step in journey:
            if step["stage"] in ("risk", "ai_decision", "execution"):
                step["result"] = "SKIPPED"
                step["reason"] = f"Blocked at Portfolio Pre-Check: {_blocked_reason}"
    return journey


def _build_rejection_reason(rec: Dict) -> str:
    reasons = []
    if not rec.get("gate_price"):
        reasons.append("Price gate failed")
    if not rec.get("gate_data_quality"):
        reasons.append("Data quality gate failed")
    if not rec.get("gate_rr"):
        reasons.append(f"R:R too low ({round(float(rec.get('rr_ratio') or 0), 2)})")
    if not rec.get("gate_volume"):
        reasons.append("Volume gate failed")
    return "; ".join(reasons) if reasons else "Risk gate failed"


# ---------------------------------------------------------------------------
# Agent thinking
# ---------------------------------------------------------------------------

def _build_agent_thinking(rec: Dict) -> Dict:
    """Return per-agent WHY explanation for a given symbol recommendation."""
    conf = float(rec.get("calibrated_confidence") or 0)
    tech_score = float(rec.get("technical_score") or 0)
    final_action = rec.get("final_action") or "UNKNOWN"
    adx = _pct(rec.get("adx"))
    rsi = _pct(rec.get("rsi"))
    vol_ratio = _pct(rec.get("volume_ratio"))
    above_ema20 = rec.get("above_ema20")
    above_ema50 = rec.get("above_ema50")
    rr_ratio = _pct(rec.get("rr_ratio"))
    entry = _pct(rec.get("entry_price"))
    stop = _pct(rec.get("stop_loss"))
    target = _pct(rec.get("target_price"))

    # Strategy indicators
    indicators = []
    if adx is not None:
        indicators.append({"name": "ADX", "value": round(adx, 1), "status": "STRONG" if adx > 25 else "WEAK"})
    if rsi is not None:
        indicators.append({"name": "RSI", "value": round(rsi, 1), "status": "OVERSOLD" if rsi < 40 else "OVERBOUGHT" if rsi > 70 else "NEUTRAL"})
    if vol_ratio is not None:
        indicators.append({"name": "Volume Ratio", "value": f"{round(vol_ratio, 2)}x", "status": "HIGH" if vol_ratio > 1.5 else "NORMAL"})
    if above_ema20 is not None:
        indicators.append({"name": "Above EMA20", "value": "Yes" if above_ema20 else "No", "status": "PASS" if above_ema20 else "FAIL"})
    if above_ema50 is not None:
        indicators.append({"name": "Above EMA50", "value": "Yes" if above_ema50 else "No", "status": "PASS" if above_ema50 else "FAIL"})

    # Risk sizing (approximate)
    position_pct = None
    risk_pct = None
    if entry and stop and entry > 0:
        risk_per_share = abs(entry - stop)
        risk_pct = round((risk_per_share / entry) * 100, 2)
        # Approximate position at 1% portfolio risk (capital assumed ₹500,000)
        capital = 500_000
        if risk_per_share > 0:
            shares = int((capital * 0.01) / risk_per_share)
            position_pct = round((shares * entry / capital) * 100, 1)

    # AI explanation bullets
    ai_reasons = []
    if conf >= 80:
        ai_reasons.append("High confidence signal")
    if tech_score >= 75:
        ai_reasons.append("Strong technical setup")
    if vol_ratio and vol_ratio > 1.5:
        ai_reasons.append("Volume expansion")
    if above_ema20:
        ai_reasons.append("Trading above EMA20")
    if rr_ratio and rr_ratio >= 2:
        ai_reasons.append(f"Favourable R:R ({round(rr_ratio, 1)}:1)")
    if not ai_reasons:
        ai_reasons.append("Composite score threshold met")

    return {
        "strategy_agent": {
            "strategy": rec.get("strategy_name") or "Unknown",
            "score": round(tech_score),
            "confidence": round(conf),
            "decision": final_action,
            "indicators": indicators,
            "win_rate": _pct(rec.get("win_rate")),
            "profit_factor": _pct(rec.get("profit_factor")),
            "total_historical_trades": rec.get("total_trades"),
            "low_evidence": rec.get("low_evidence"),
        },
        "risk_agent": {
            "entry_price": entry,
            "stop_loss": stop,
            "target_price": target,
            "rr_ratio": rr_ratio,
            "position_size_pct": position_pct,
            "risk_pct": risk_pct,
            "heat": rec.get("heat"),
            "gates": {
                "price": bool(rec.get("gate_price")),
                "data_quality": bool(rec.get("gate_data_quality")),
                "rr": bool(rec.get("gate_rr")),
                "volume": bool(rec.get("gate_volume")),
            },
            "decision": "APPROVED" if rec.get("all_gates_passed") else "REJECTED",
            "rejection_reason": None if rec.get("all_gates_passed") else _build_rejection_reason(rec),
        },
        "ai_decision_agent": {
            "decision": final_action,
            "confidence": round(conf),
            "opportunity_score": round(float(rec.get("opportunity_score") or 0)),
            "reasons": ai_reasons,
            "holding_days": rec.get("expected_holding_days"),
            "paper_eligible": bool(rec.get("paper_eligible")),
        },
    }


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

def get_replay_sessions() -> Dict:
    """
    List available replay sessions.
    Primary: scan_state (latest scan, rich data).
    Secondary: signal_snapshots (historical scans, limited data).
    """
    conn = _get_conn()
    sessions = []

    if conn:
        try:
            # Latest scan from scan_state
            row = _q1(conn, """
                SELECT scan_id, status, started_at, completed_at, snapshot_ts,
                       symbols_requested, symbols_received, snapshot
                FROM scan_state WHERE id = 1
            """)
            if row:
                snap = row.get("snapshot") or {}
                if isinstance(snap, str):
                    snap = json.loads(snap)
                recs = snap.get("recommendations") or []
                buy_count = sum(1 for r in recs if _is_buy_action(r.get("final_action")))
                # Executed count comes from the ACTUAL ledger, not the
                # paper_eligible flag — eligibility does not guarantee a
                # persisted order (duplicate/circuit-breaker blocks etc.).
                paper_count = 0
                try:
                    led = _q1(conn, """
                        SELECT COUNT(*) AS n FROM phase20_paper_trades
                        WHERE scan_id = %s AND side = 'BUY'
                    """, (row.get("scan_id"),))
                    paper_count = int((led or {}).get("n") or 0)
                except Exception:
                    pass
                dur = snap.get("duration_s")
                _snap_ts_str = str(row.get("snapshot_ts") or row.get("completed_at") or "")
                sessions.append({
                    "scan_id": row["scan_id"] or "latest",
                    "snapshot_ts": _snap_ts_str,
                    "snapshot_date_ist": _snapshot_date_ist(_snap_ts_str),
                    "is_today_session": _is_today_session(_snap_ts_str),
                    "status": row.get("status") or "COMPLETED",
                    "universe_size": int(row.get("symbols_requested") or snap.get("universe_size") or 0),
                    "symbols_processed": int(row.get("symbols_received") or len(recs)),
                    "total_recommendations": len(recs),
                    "buy_signals": buy_count,
                    "paper_orders": paper_count,
                    "duration_s": round(float(dur), 1) if dur else None,
                    "source": "scan_state",
                    "is_latest": True,
                })

            # Historical scans from signal_snapshots
            hist_rows = _q(conn, """
                SELECT DISTINCT scan_id, snapshot_ts
                FROM signal_snapshots
                WHERE scan_id IS NOT NULL AND scan_id != ''
                ORDER BY snapshot_ts DESC
                LIMIT 20
            """)
            latest_sid = (row or {}).get("scan_id")
            for hr in hist_rows:
                sid = hr.get("scan_id")
                if sid == latest_sid:
                    continue
                _hr_snap_ts = str(hr.get("snapshot_ts") or "")
                sessions.append({
                    "scan_id": sid,
                    "snapshot_ts": _hr_snap_ts,
                    "snapshot_date_ist": _snapshot_date_ist(_hr_snap_ts),
                    "is_today_session": _is_today_session(_hr_snap_ts),
                    "status": "COMPLETED",
                    "universe_size": None,
                    "symbols_processed": None,
                    "total_recommendations": None,
                    "buy_signals": None,
                    "paper_orders": None,
                    "duration_s": None,
                    "source": "signal_snapshots",
                    "is_latest": False,
                })
        finally:
            conn.close()

    if not sessions:
        sessions.append({
            "scan_id": "demo",
            "snapshot_ts": datetime.now(timezone.utc).isoformat(),
            "status": "DEMO",
            "universe_size": 50,
            "symbols_processed": 48,
            "total_recommendations": 42,
            "buy_signals": 6,
            "paper_orders": 4,
            "duration_s": 45.0,
            "source": "demo",
            "is_latest": True,
        })

    return {"sessions": sessions, "count": len(sessions)}


def build_replay(scan_id: str) -> Dict:
    """
    Build the full pipeline replay for a given scan_id.
    Returns stages, per-symbol list (lightweight), and metadata.
    """
    conn = _get_conn()
    snapshot: Dict = {}

    if conn:
        try:
            # Try scan_state first (richest data)
            row = _q1(conn, "SELECT snapshot, scan_id FROM scan_state WHERE id = 1")
            if row:
                snap = row.get("snapshot") or {}
                if isinstance(snap, str):
                    snap = json.loads(snap)
                if scan_id in ("latest", row.get("scan_id"), ""):
                    snapshot = snap
                else:
                    # For historical scans use signal_snapshots signals array
                    sig_row = _q1(conn, """
                        SELECT signals, market_context, snapshot_ts
                        FROM signal_snapshots WHERE scan_id = %s LIMIT 1
                    """, (scan_id,))
                    if sig_row:
                        signals = sig_row.get("signals") or []
                        if isinstance(signals, str):
                            signals = json.loads(signals)
                        snapshot = {
                            "scan_id": scan_id,
                            "snapshot_ts": str(sig_row.get("snapshot_ts") or ""),
                            "recommendations": signals,
                            "universe_size": len(signals),
                            "provider_health": {"symbols_requested": len(signals), "symbols_received": len(signals)},
                            "timings": {},
                            "scan_audit": {},
                            "summary": {},
                        }
                    else:
                        # Requested scan is neither current nor archived —
                        # never silently replay a DIFFERENT scan (trade IDs
                        # and counts would belong to the wrong session).
                        conn.close()
                        return {"error": f"Scan {scan_id} not found (not current, not archived)",
                                "scan_id": scan_id, "not_found": True}
        finally:
            try:
                conn.close()
            except Exception:
                pass

    if not snapshot:
        return {"error": "No scan data found", "scan_id": scan_id}

    recs: List[Dict] = snapshot.get("recommendations") or []
    _pc_scan_id = str(snapshot.get("scan_id", scan_id) or scan_id or "")
    stages = _build_stages_from_snapshot(
        snapshot, precheck_decisions=_get_precheck_decisions(_pc_scan_id))

    # Lightweight symbol list (full details via /symbol/:symbol endpoint)
    symbols_list = []
    for r in recs:
        sym = r.get("symbol")
        if not sym:
            continue
        symbols_list.append({
            "symbol": sym,
            "sector": r.get("sector"),
            "final_action": r.get("final_action"),
            "confidence": round(float(r.get("calibrated_confidence") or 0)),
            "technical_score": round(float(r.get("technical_score") or 0)),
            "strategy": r.get("strategy_name"),
            "all_gates_passed": bool(r.get("all_gates_passed")),
            "paper_eligible": bool(r.get("paper_eligible")),
            "data_quality": r.get("data_quality"),
        })

    # Attach real execution trades from phase20_paper_trades scoped to this scan_id.
    # Use the concrete scan_id stored in the snapshot (which _get_execution_trades
    # will also read as its fallback), so that 'latest' is resolved before the query.
    conn2 = _get_conn()
    execution_trades: List[Dict] = []
    if conn2:
        try:
            execution_trades = _get_execution_trades(conn2, scan_id, snapshot)
        finally:
            conn2.close()

    resolved_scan_id = str(snapshot.get("scan_id", scan_id) or scan_id)
    snapshot_ts = str(snapshot.get("snapshot_ts", "") or "")
    starting_capital = _configured_capital()

    # ── Reconcile the Execution stage with the actual ledger ────────────────
    # The snapshot marks symbols "paper eligible", but an order only exists if
    # a phase20_paper_trades row was persisted for THIS scan (e.g. duplicates
    # against an already-open position are blocked and create no row).
    # Execution `out` must equal actual ledger orders; blocked eligibles are
    # reported as `cancelled` so conservation still holds exactly and every
    # page shows the same number.
    exec_stage = next((s for s in stages if s["id"] == "execution"), None)
    execution_blocks: List[Dict] = []
    if exec_stage is not None:
        ledger_symbols = [t.get("symbol") for t in execution_trades if t.get("symbol")]
        eligible_out = int(exec_stage.get("stocks_out", 0))
        actual_out = len(ledger_symbols)
        if actual_out != eligible_out:
            # Per-symbol block reasons from the phase22 evidence dataset —
            # recorded from the EXACT evaluation payload the executor used
            # (never re-evaluated here).
            try:
                conn2 = _get_conn()
                if conn2:
                    try:
                        ev_rows = _q(conn2, """
                            SELECT symbol, eligibility_result, blocking_reasons, trade_opened
                            FROM phase22_evidence
                            WHERE scan_id = %s AND decision = 'BUY'
                        """, (resolved_scan_id,))
                        ledger_set = set(ledger_symbols)
                        for er in ev_rows:
                            if er.get("symbol") in ledger_set:
                                continue
                            reasons = er.get("blocking_reasons") or []
                            if isinstance(reasons, str):
                                reasons = json.loads(reasons)
                            if not reasons and not er.get("trade_opened"):
                                reasons = ["automation_off_or_gate_blocked"]
                            execution_blocks.append({
                                "symbol": er.get("symbol"),
                                "eligibility_result": er.get("eligibility_result"),
                                "reasons": reasons,
                            })
                    finally:
                        conn2.close()
            except Exception:
                pass
            blocked = max(0, eligible_out - actual_out)
            exec_stage["stocks_out"] = actual_out
            exec_stage["cancelled"] = blocked
            exec_stage["stocks"] = ledger_symbols[:50]
            exec_stage["paper_orders"] = actual_out
            exec_stage["blocked_entries"] = execution_blocks[:20]
            exec_stage["description"] = (
                f"{actual_out} paper orders placed"
                + (f" · {blocked} eligible entr{'y' if blocked == 1 else 'ies'} blocked "
                   + (f"({'; '.join(f'{b['symbol']}: {', '.join(b['reasons'][:3])}' for b in execution_blocks[:4])})"
                      if execution_blocks else "(no ledger row — e.g. open position already exists)")
                   if blocked else "")
            )
            if actual_out > eligible_out:
                # Ledger overage (rows beyond snapshot eligibility): keep
                # conservation exact by raising stage input, and surface the
                # anomaly explicitly instead of producing an impossible count.
                overage = actual_out - eligible_out
                exec_stage["stocks_in"] = int(exec_stage.get("stocks_in", 0)) + overage
                exec_stage.setdefault("anomalies", []).append(
                    f"{overage} ledger order(s) without matching paper-eligible snapshot rows"
                )
                exec_stage["anomaly_count"] = len(exec_stage["anomalies"])

    # ── Unified Replay Snapshot (single source of truth) ─────────────────────
    # Every consumer (Replay page, Operations Centre, Portfolio, Timeline,
    # Integrity, AI Explanation) must read from THIS payload only.

    # Decisions — one record per evaluated symbol, from the canonical scan.
    decisions = [
        {
            "symbol": s["symbol"],
            "final_action": s.get("final_action"),
            "confidence": s.get("confidence"),
            "paper_eligible": bool(s.get("paper_eligible")),
            "all_gates_passed": bool(s.get("all_gates_passed")),
        }
        for s in symbols_list
    ]

    # Portfolio state — derived ONLY from the phase20_paper_trades ledger rows
    # (execution_trades) scoped to this scan. Never fabricated.
    open_trades = [t for t in execution_trades if t.get("exit_price") is None]
    closed_trades = [t for t in execution_trades if t.get("exit_price") is not None]
    deployed = sum(float(t.get("capital_used") or 0) for t in open_trades)
    realized_pnl = sum(float(t.get("pnl") or 0) for t in closed_trades)
    portfolio_state = {
        "source": "phase20_paper_trades",
        "starting_capital": starting_capital,
        "open_positions": len(open_trades),
        "closed_positions": len(closed_trades),
        "total_trades": len(execution_trades),
        "capital_deployed": round(deployed, 2),
        "realized_pnl": round(realized_pnl, 2),
        "cash": round(starting_capital - deployed + realized_pnl, 2),
        "equity": round(starting_capital + realized_pnl, 2),  # open positions at cost
    }

    # Pipeline counts — the ONLY count table any page may display.
    pipeline_counts = {
        s["id"]: {
            "label": s["label"],
            "in": s.get("stocks_in", 0),
            "out": s.get("stocks_out", 0),
            "rejected": max(0, s.get("rejected", 0)),
            "pending": max(0, s.get("pending", 0)),
            "cancelled": max(0, s.get("cancelled", 0)),
            # Pre-check extras (event-derived; absent for other stages)
            **({"approved": s.get("approved_count", 0),
                "evaluated": s.get("evaluated_count", 0),
                "not_evaluated": s.get("not_evaluated", 0)}
               if s["id"] == "portfolio_precheck" else {}),
        }
        for s in stages
    }
    pipeline_counts["portfolio"] = {
        "label": "Portfolio",
        "in": len(execution_trades),
        "out": len(open_trades),
        "rejected": 0,
        "pending": 0,
        "cancelled": len(closed_trades),  # exited positions
    }

    # Timeline events — server-built so the Timeline shows the same facts.
    timeline_events: List[Dict] = []
    for s in stages:
        timeline_events.append({
            "type": "stage",
            "stage_id": s["id"],
            "label": s["label"],
            "order": s.get("order", 0),
            "in": s.get("stocks_in", 0),
            "out": s.get("stocks_out", 0),
            "duration_ms": s.get("duration_ms"),
        })
    for t in execution_trades:
        timeline_events.append({
            "type": "trade_entry",
            "symbol": t.get("symbol"),
            "ts": t.get("entry_ts"),
            "price": t.get("entry_price"),
            "qty": t.get("qty"),
            "strategy": t.get("strategy"),
        })
        if t.get("exit_price") is not None:
            timeline_events.append({
                "type": "trade_exit",
                "symbol": t.get("symbol"),
                "ts": t.get("exit_ts"),
                "price": t.get("exit_price"),
                "pnl": t.get("pnl"),
            })

    payload = {
        "replay_id": f"RP-{resolved_scan_id}",
        "session_id": resolved_scan_id,
        "scan_id": resolved_scan_id,
        "snapshot_ts": snapshot_ts,
        "starting_capital": starting_capital,
        "stages": stages,
        "pipeline_counts": pipeline_counts,
        "symbols": symbols_list,
        "decisions": decisions,
        "total_symbols": len(symbols_list),
        "universe_size": int(snapshot.get("universe_size") or 0),
        "duration_s": snapshot.get("duration_s"),
        "regime": (snapshot.get("summary") or {}).get("regime"),
        "provider_health": snapshot.get("provider_health") or {},
        "execution_trades": execution_trades,
        # paper_trades is an alias of execution_trades: both come from the
        # phase20_paper_trades ledger scoped to this scan — one dataset.
        "paper_trades": execution_trades,
        "portfolio_state": portfolio_state,
        "timeline_events": timeline_events,
    }
    payload["integrity"] = _compute_integrity(payload, resolved_scan_id)
    return payload


_INTEGRITY_ERROR_DEFAULTS = {
    "overall": "ERROR",
    "snapshot_ts": "",
    "stages_count": 0,
    "trades_count": 0,
}


def get_replay_integrity(scan_id: str) -> Dict:
    """
    Run pipeline integrity checks and return a structured PASS/WARNING/ERROR report.
    Always returns all required fields regardless of error state so the frontend
    can render a consistent error banner without crashing.

    Note: build_replay() embeds this same report under `integrity` — this
    endpoint stays for direct access, but both derive from _compute_integrity()
    on the SAME replay payload so numbers can never diverge.
    """
    try:
        replay = build_replay(scan_id)
    except Exception as exc:
        return {
            "scan_id": scan_id,
            "checks": [{"check": "Build replay", "status": "ERROR", "detail": str(exc)}],
            **_INTEGRITY_ERROR_DEFAULTS,
        }

    if "error" in replay:
        return {
            "scan_id": scan_id,
            "checks": [{"check": "Build replay", "status": "ERROR", "detail": replay["error"]}],
            **_INTEGRITY_ERROR_DEFAULTS,
        }

    # build_replay already embeds the computed report.
    embedded = replay.get("integrity")
    if isinstance(embedded, dict) and embedded.get("checks"):
        return embedded
    return _compute_integrity(replay, scan_id)


def _compute_integrity(replay: Dict, scan_id: str = "") -> Dict:
    """Compute the integrity report from an already-built replay payload."""
    stages: List[Dict] = replay.get("stages") or []
    execution_trades: List[Dict] = replay.get("execution_trades") or []
    checks = []

    # 1. No negative rejected counts
    neg_stages = [s["label"] for s in stages if s.get("rejected", 0) < 0]
    checks.append({
        "check": "No negative rejected counts",
        "status": "PASS" if not neg_stages else "ERROR",
        "detail": f"Violations: {', '.join(neg_stages)}" if neg_stages else "All stages ≥ 0",
    })

    # 2. No stage creates records (output ≤ input)
    create_stages = [
        f"{s['label']} (in={s['stocks_in']} out={s['stocks_out']})"
        for s in stages
        if s.get("stocks_out", 0) > s.get("stocks_in", 0)
    ]
    checks.append({
        "check": "No stage creates symbols",
        "status": "PASS" if not create_stages else "ERROR",
        "detail": f"Creating records: {', '.join(create_stages)}" if create_stages else "Conservation law satisfied",
    })

    # 3. Exact conservation: in == out + rejected + pending + cancelled.
    #    Any deviation, in either direction, is an ERROR attributed to the
    #    exact stage that violates the rule — no slack, no tolerance.
    violation_stages = []
    for s in stages:
        si = s.get("stocks_in", 0)
        so = s.get("stocks_out", 0)
        sr = max(0, s.get("rejected", 0))
        sp = max(0, s.get("pending", 0))
        sc = max(0, s.get("cancelled", 0))
        accounted = so + sr + sp + sc
        if accounted != si:
            violation_stages.append(
                f"{s['label']}(in={si} out={so} rej={sr} pend={sp} canc={sc} → accounted={accounted})"
            )

    if violation_stages:
        status = "ERROR"
        detail = f"Conservation violated (in ≠ out+rejected+pending+cancelled): {', '.join(violation_stages)}"
    else:
        status = "PASS"
        detail = "Every stage satisfies in = out + rejected + pending + cancelled exactly"

    checks.append({"check": "Input = Passed + Rejected + Pending + Cancelled", "status": status, "detail": detail})

    # 4. No duplicate symbols within any stage's stock list
    dup_stages = []
    for s in stages:
        syms = s.get("stocks") or []
        if len(syms) != len(set(syms)):
            dup_stages.append(s["label"])
    checks.append({
        "check": "No duplicate symbols in any stage",
        "status": "PASS" if not dup_stages else "WARNING",
        "detail": f"Duplicates found: {', '.join(dup_stages)}" if dup_stages else "All symbol lists unique",
    })

    # 5. Execution count ≤ Decision output
    decision_stage = next((s for s in stages if s["id"] == "ai_decision"), None)
    execution_stage = next((s for s in stages if s["id"] == "execution"), None)
    if decision_stage and execution_stage:
        dec_out = decision_stage.get("stocks_out", 0)
        exec_in = execution_stage.get("stocks_in", 0)
        ok = exec_in <= dec_out
        checks.append({
            "check": "Execution input ≤ Decision output",
            "status": "PASS" if ok else "ERROR",
            "detail": f"Decision output={dec_out}, Execution input={exec_in}" + (" ✓" if ok else " — impossible"),
        })

    # 5b. Every executed order originates from an approved BUY decision
    exec_anomalies = (execution_stage or {}).get("anomalies") or []
    exec_anomaly_count = int((execution_stage or {}).get("anomaly_count") or 0)
    checks.append({
        "check": "Every order has an approved BUY decision",
        "status": "PASS" if exec_anomaly_count == 0 else "ERROR",
        "detail": (
            "All execution records trace back to a BUY decision"
            if exec_anomaly_count == 0
            else f"{exec_anomaly_count} paper-eligible record(s) without BUY decision (originating stage: AI Decision→Execution handoff): {', '.join(exec_anomalies)}"
        ),
    })

    # 6. Cash never negative (check portfolio trades)
    STARTING_CAPITAL = _configured_capital()
    running_cash = STARTING_CAPITAL
    cash_negative = False
    for t in sorted(execution_trades, key=lambda x: x.get("entry_ts") or ""):
        if t.get("action", "BUY") == "BUY":
            running_cash -= t.get("capital_used", 0)
        if t.get("exit_price") is not None and t.get("pnl") is not None:
            running_cash += t["capital_used"] + (t["pnl"] or 0)
        if running_cash < 0:
            cash_negative = True
            break
    checks.append({
        "check": "Cash never negative",
        "status": "PASS" if not cash_negative else "WARNING",
        "detail": "Cash balance stayed ≥ 0 throughout replay" if not cash_negative else f"Cash went negative (running balance ₹{running_cash:.0f})",
    })

    # 7. Position sizing valid (capital_used ≤ STARTING_CAPITAL)
    oversize = [t["symbol"] for t in execution_trades if t.get("capital_used", 0) > STARTING_CAPITAL]
    checks.append({
        "check": "Position sizing valid",
        "status": "PASS" if not oversize else "ERROR",
        "detail": f"Oversized positions: {', '.join(oversize)}" if oversize else "All positions within capital limits",
    })

    # 8. Portfolio positions consistent:
    #    The execution stage's stocks_out (orders placed) should match the number of
    #    phase20_paper_trades rows found for this scan.  A mismatch means the pipeline
    #    reported orders that were never persisted (or vice versa).
    open_trades   = [t for t in execution_trades if t.get("exit_price") is None]
    closed_trades = [t for t in execution_trades if t.get("exit_price") is not None]
    expected_orders = (execution_stage.get("stocks_out", 0) if execution_stage else 0)
    actual_orders   = len(execution_trades)
    portfolio_ok    = abs(expected_orders - actual_orders) <= max(1, expected_orders * 0.25)
    checks.append({
        "check": "Portfolio positions consistent",
        "status": "PASS" if portfolio_ok else "WARNING",
        "detail": (
            f"{open_trades.__len__()} open + {closed_trades.__len__()} closed = "
            f"{actual_orders} trades found; execution stage expected {expected_orders}"
            + (" ✓" if portfolio_ok else f" — mismatch of {abs(expected_orders - actual_orders)}")
        ),
    })

    overall = "PASS"
    if any(c["status"] == "ERROR" for c in checks):
        overall = "ERROR"
    elif any(c["status"] == "WARNING" for c in checks):
        overall = "WARNING"

    return {
        "scan_id": replay.get("scan_id") or scan_id,
        "snapshot_ts": replay.get("snapshot_ts", ""),
        "overall": overall,
        "checks": checks,
        "stages_count": len(stages),
        "trades_count": len(execution_trades),
    }


def get_symbol_journey(scan_id: str, symbol: str) -> Dict:
    """
    Full per-symbol timeline + agent thinking for Feature 12 & 13.
    """
    conn = _get_conn()
    snapshot: Dict = {}
    paper_trade = None
    exec_outcome = None  # populated inside try block; guard here for no-conn path

    if conn:
        try:
            # Resolve the snapshot for the REQUESTED scan — never silently
            # substitute the current scan_state for a historical scan_id.
            row = _q1(conn, "SELECT snapshot, scan_id FROM scan_state WHERE id = 1")
            current_sid = (row or {}).get("scan_id")
            if row and scan_id in ("latest", current_sid, ""):
                snap = row.get("snapshot") or {}
                if isinstance(snap, str):
                    snap = json.loads(snap)
                snapshot = snap
            else:
                sig_row = _q1(conn, """
                    SELECT signals, snapshot_ts
                    FROM signal_snapshots WHERE scan_id = %s LIMIT 1
                """, (scan_id,))
                if sig_row:
                    signals = sig_row.get("signals") or []
                    if isinstance(signals, str):
                        signals = json.loads(signals)
                    snapshot = {
                        "scan_id": scan_id,
                        "snapshot_ts": str(sig_row.get("snapshot_ts") or ""),
                        "recommendations": signals,
                    }

            # Paper trade for this symbol from the canonical phase20 ledger,
            # scoped to the resolved scan (same source as the Replay Snapshot).
            resolved_sid = snapshot.get("scan_id") or (current_sid if scan_id in ("latest", "") else scan_id)
            trade_row = _q1(conn, """
                SELECT symbol, side AS action, fill_price AS price,
                       (fill_price * quantity) AS total, fill_ts AS trade_ts,
                       trigger_source AS reason, status, exit_price, realized_pnl
                FROM phase20_paper_trades
                WHERE symbol = %s AND scan_id = %s
                ORDER BY entry_ts DESC LIMIT 1
            """, (symbol.upper(), resolved_sid))
            if trade_row:
                paper_trade = dict(trade_row)

            # Query the actual execution outcome from pipeline_events so the
            # journey can display the true terminal state rather than inferring
            # it from paper_eligible alone (which causes the misleading
            # "Paper order placed" label when execution was actually skipped).
            exec_outcome = None
            if resolved_sid:
                eo_row = _q1(conn, """
                    SELECT event_type, payload
                    FROM pipeline_events
                    WHERE scan_id = %s AND symbol = %s
                      AND event_type IN (
                          'EXECUTION_SKIPPED_WITH_REASON','ORDER_REJECTED',
                          'ORDER_SUBMITTED','ORDER_EXECUTED'
                      )
                    ORDER BY ts DESC LIMIT 1
                """, (resolved_sid, symbol.upper()))
                if eo_row:
                    payload = eo_row.get("payload") or {}
                    if isinstance(payload, str):
                        import json as _json
                        payload = _json.loads(payload)
                    exec_outcome = {"event_type": eo_row["event_type"], **payload}
        finally:
            conn.close()

    recs = snapshot.get("recommendations") or []
    rec = next((r for r in recs if (r.get("symbol") or "").upper() == symbol.upper()), None)

    if not rec:
        return {
            "symbol": symbol,
            "error": f"Symbol {symbol} not found in scan {scan_id}",
            "journey": [],
            "thinking": {},
        }

    _pc_map = _get_precheck_decisions(str(resolved_sid or scan_id or ""))
    journey = _build_symbol_journey(rec, snapshot,
                                    precheck=_pc_map.get(symbol.upper()),
                                    execution_outcome=exec_outcome)
    thinking = _build_agent_thinking(rec)

    return {
        "symbol": symbol,
        "sector": rec.get("sector"),
        "scan_id": snapshot.get("scan_id", scan_id),
        "snapshot_ts": snapshot.get("snapshot_ts", ""),
        "journey": journey,
        "thinking": thinking,
        "paper_trade": paper_trade,
        "recommendation": {
            "final_action": rec.get("final_action"),
            "confidence": round(float(rec.get("calibrated_confidence") or 0)),
            "opportunity_score": round(float(rec.get("opportunity_score") or 0)),
            "entry_price": rec.get("entry_price"),
            "stop_loss": rec.get("stop_loss"),
            "target_price": rec.get("target_price"),
            "rr_ratio": rec.get("rr_ratio"),
            "strategy": rec.get("strategy_name"),
        },
    }


def get_decision_comparison(scan_id: str) -> Dict:
    """
    Feature 14 — Compare AI decisions vs actual market outcomes.
    """
    conn = _get_conn()
    snapshot: Dict = {}
    trades = []
    price_history: Dict[str, float] = {}

    if conn:
        try:
            row = _q1(conn, "SELECT snapshot FROM scan_state WHERE id = 1")
            if row:
                snap = row.get("snapshot") or {}
                if isinstance(snap, str):
                    snap = json.loads(snap)
                snapshot = snap

            # Scan-scoped trades from the canonical phase20 ledger — the
            # legacy unscoped paper_trades table cross-contaminates sessions.
            _cmp_sid = snapshot.get("scan_id")
            if _cmp_sid:
                trade_rows = _q(conn, """
                    SELECT symbol, side AS action, fill_price AS price,
                           (fill_price * quantity) AS total, fill_ts AS trade_ts
                    FROM phase20_paper_trades
                    WHERE scan_id = %s
                    ORDER BY fill_ts DESC LIMIT 100
                """, (_cmp_sid,))
                trades = [dict(r) for r in trade_rows]

            price_rows = _q(conn, """
                SELECT symbol, price FROM phase11_price_snapshots
                WHERE scan_id = (SELECT scan_id FROM scan_state WHERE id = 1)
            """)
            for pr in price_rows:
                price_history[pr["symbol"]] = float(pr["price"] or 0)
        finally:
            conn.close()

    recs = snapshot.get("recommendations") or []
    trades_by_symbol = {t["symbol"]: t for t in trades if t.get("symbol")}

    comparisons = []
    for rec in recs:
        sym = rec.get("symbol")
        if not sym:
            continue
        ai_action = rec.get("final_action") or "UNKNOWN"
        entry_price = _pct(rec.get("entry_price"))
        current_price = price_history.get(sym)
        trade = trades_by_symbol.get(sym)

        # Determine outcome
        outcome_pct = None
        status = "PENDING"
        if trade and entry_price and entry_price > 0:
            actual_price = float(trade.get("price") or entry_price)
            outcome_pct = round(((actual_price - entry_price) / entry_price) * 100, 2)
            if ai_action == "BUY" and outcome_pct > 0:
                status = "CORRECT"
            elif ai_action == "BUY" and outcome_pct < -1:
                status = "LOSS"
            elif ai_action == "AVOID" and outcome_pct < -1:
                status = "CORRECT_AVOID"
            elif ai_action == "AVOID" and outcome_pct > 2:
                status = "MISSED_OPPORTUNITY"
            else:
                status = "NEUTRAL"
        elif ai_action == "AVOID" and current_price and entry_price and entry_price > 0:
            move = ((current_price - entry_price) / entry_price) * 100
            if move > 2:
                status = "MISSED_OPPORTUNITY"
                outcome_pct = round(move, 2)

        comparisons.append({
            "symbol": sym,
            "sector": rec.get("sector"),
            "ai_action": ai_action,
            "confidence": round(float(rec.get("calibrated_confidence") or 0)),
            "entry_price": entry_price,
            "current_price": current_price,
            "outcome_pct": outcome_pct,
            "status": status,
            "paper_order_id": rec.get("paper_order_id"),
            "strategy": rec.get("strategy_name"),
            # paper_traded flag: True when this symbol had an actual paper order placed
            "paper_traded": bool(trade) and ai_action == "BUY",
            "rejection_reason": None if ai_action == "BUY" else (
                "Avoid signal" if ai_action == "AVOID" else f"AI action: {ai_action}"
            ),
        })

    # Sort: CORRECT first, then MISSED_OPPORTUNITY, then others
    order = {"CORRECT": 0, "LOSS": 1, "MISSED_OPPORTUNITY": 2, "CORRECT_AVOID": 3, "NEUTRAL": 4, "PENDING": 5}
    comparisons.sort(key=lambda x: (order.get(x["status"], 99), -(x.get("confidence") or 0)))

    wins = sum(1 for c in comparisons if c["status"] == "CORRECT")
    losses = sum(1 for c in comparisons if c["status"] == "LOSS")
    missed = sum(1 for c in comparisons if c["status"] == "MISSED_OPPORTUNITY")
    pending = sum(1 for c in comparisons if c["status"] == "PENDING")
    stats_obj = {
        "total": len(comparisons),
        "wins": wins,
        "correct": wins,
        "losses": losses,
        "missed_opportunities": missed,
        "pending": pending,
    }
    return {
        "scan_id": snapshot.get("scan_id", scan_id),
        "snapshot_ts": snapshot.get("snapshot_ts", ""),
        "comparisons": comparisons,
        # Frontend expects `stats` (not `summary`); provide both for backwards compat
        "stats": stats_obj,
        "summary": stats_obj,
    }


def get_replay_summary(scan_id: str) -> Dict:
    """
    Feature 16 — Executive replay summary.
    """
    conn = _get_conn()
    snapshot: Dict = {}
    trades = []

    if conn:
        try:
            row = _q1(conn, "SELECT snapshot FROM scan_state WHERE id = 1")
            if row:
                snap = row.get("snapshot") or {}
                if isinstance(snap, str):
                    snap = json.loads(snap)
                snapshot = snap

            # Trades from the canonical phase20 ledger, scoped to THIS scan —
            # never the legacy unscoped paper_trades table.
            _sid = snapshot.get("scan_id") or (scan_id if scan_id not in ("latest", "") else None)
            if _sid:
                trades = [dict(r) for r in _q(conn, """
                    SELECT symbol, side AS action, fill_price AS price,
                           (fill_price * quantity) AS total, fill_ts AS trade_ts,
                           realized_pnl, status
                    FROM phase20_paper_trades
                    WHERE scan_id = %s
                    ORDER BY fill_ts DESC LIMIT 200
                """, (_sid,))]
        finally:
            conn.close()

    recs = snapshot.get("recommendations") or []
    provider = snapshot.get("provider_health") or {}
    timings = snapshot.get("timings") or {}

    universe = int(snapshot.get("universe_size") or provider.get("symbols_requested") or 0)
    passed_market_data = int(provider.get("symbols_received") or len(recs))
    passed_mi = sum(1 for r in recs if _data_quality_score(r.get("data_quality")) >= 35)
    passed_strategy = sum(1 for r in recs if r.get("strategy_id") or r.get("strategy_name"))
    passed_risk = sum(1 for r in recs if r.get("all_gates_passed"))
    buy_candidates = sum(1 for r in recs if _is_buy_action(r.get("final_action")))
    # Executed = actual ledger rows for this scan (trades list is already
    # scan-scoped above); paper_eligible is only an intent flag.
    paper_orders = sum(1 for t in trades if str(t.get("action") or "").upper() == "BUY")
    avoid_count = sum(1 for r in recs if r.get("final_action") == "AVOID")

    # Agent timing
    def _ms(k):
        v = timings.get(k)
        if v is None:
            return None
        try:
            return int(float(v) * 1000)
        except Exception:
            return None

    agent_times = {
        "Market Data": _ms("market_data"),
        "Strategy": _ms("strategy"),
        "AI Decision": _ms("ai_decision"),
        "Risk": _ms("risk"),
        "Execution": _ms("execution"),
    }
    times_known = {k: v for k, v in agent_times.items() if v is not None}
    slowest = max(times_known, key=times_known.__getitem__) if times_known else "Market Data"
    fastest = min(times_known, key=times_known.__getitem__) if times_known else "Execution"
    agent_most_rejections = "Risk" if (passed_strategy - passed_risk) > (passed_risk - buy_candidates) else "AI Decision"

    # Win rate estimate from paper trades
    profitable = sum(1 for t in trades if float(t.get("realized_pnl") or 0) > 0) if trades else 0
    win_rate = round((profitable / len(trades)) * 100, 1) if trades else None

    # Readiness verdict
    scan_duration = snapshot.get("duration_s")
    ready = (buy_candidates >= 3 and passed_risk >= buy_candidates and
             _data_quality_score(None) < 35 or passed_mi > universe * 0.7)
    verdict = "Ready for Production" if (passed_risk > 0 and buy_candidates > 0) else "Needs Investigation"

    return {
        "scan_id": snapshot.get("scan_id", scan_id),
        "snapshot_ts": snapshot.get("snapshot_ts", ""),
        "funnel": {
            "scanned": universe,
            "passed_market_data": passed_market_data,
            "passed_research": passed_market_data,
            "passed_market_intelligence": passed_mi,
            "passed_strategy": passed_strategy,
            "buy_candidates": buy_candidates,
            "risk_approved": passed_risk,
            "paper_trades": paper_orders,
        },
        "performance": {
            "win_rate": win_rate,
            "total_trades": len(trades),
            "profitable_trades": profitable,
        },
        "agents": {
            "most_rejections": agent_most_rejections,
            "slowest": slowest,
            "fastest": fastest,
            "slowest_ms": times_known.get(slowest),
            "fastest_ms": times_known.get(fastest),
        },
        "overall_ai_score": round(
            (passed_risk / max(universe, 1)) * 40 +
            (buy_candidates / max(passed_risk, 1)) * 30 +
            (paper_orders / max(buy_candidates, 1)) * 30
        ) if passed_risk > 0 else 0,
        "verdict": verdict,
        "scan_duration_s": scan_duration,
        "regime": (snapshot.get("summary") or {}).get("regime") or (snapshot.get("provider_health") or {}).get("regime"),
    }
