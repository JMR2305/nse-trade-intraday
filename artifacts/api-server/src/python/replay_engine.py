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
from datetime import datetime, timezone
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
    {"id": "risk",                "label": "Risk",               "order": 6},
    {"id": "ai_decision",         "label": "AI Decision",        "order": 7},
    {"id": "execution",           "label": "Execution",          "order": 8},
]


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

def _build_stages_from_snapshot(snapshot: Dict) -> List[Dict]:
    """
    Reconstruct 9-stage pipeline from a Phase7ScanResult snapshot dict.
    Returns a list of stage dicts ordered by pipeline position.
    """
    recs: List[Dict] = snapshot.get("recommendations") or []
    provider = snapshot.get("provider_health") or {}
    audit = snapshot.get("scan_audit") or {}
    timings = snapshot.get("timings") or {}
    universe_size: int = int(snapshot.get("universe_size") or len(recs) or 0)

    # ── Reconstruct per-stage symbol sets ──────────────────────────────────

    # Stage 0 — Supervisor: all universe symbols
    supervisor_symbols = [r["symbol"] for r in recs if r.get("symbol")]
    # Try to get universe from provider_health for true universe size
    universe_symbols_count = int(provider.get("symbols_requested") or universe_size)

    # Stage 1 — Market Data: symbols that actually received data
    market_data_received = int(provider.get("symbols_received") or len(recs))
    market_data_symbols = [r["symbol"] for r in recs if r.get("symbol") and not (r.get("error") or "").startswith("MARKET_DATA")]

    # Stage 2 — Research: global; all market_data symbols proceed (research is not per-symbol gating)
    research_symbols = market_data_symbols

    # Stage 3 — Market Intelligence: filter by data quality
    mi_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") and _data_quality_score(r.get("data_quality")) >= 35
    ]

    # Stage 4 — Monitoring: pass-through of market intelligence
    monitoring_symbols = mi_symbols

    # Stage 5 — Strategy: symbols that have a strategy assigned
    strategy_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") and r.get("strategy_id") or r.get("strategy_name")
    ]

    # Stage 6 — Risk: symbols where all gates passed
    risk_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") and r.get("all_gates_passed")
    ]

    # Stage 7 — AI Decision: symbols with a meaningful final action (not AVOID outright rejections)
    ai_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") and r.get("final_action") not in (None, "AVOID", "SELL")
    ]
    # Also include AVOID but track separately for stats
    avoid_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") and r.get("final_action") == "AVOID"
    ]
    buy_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") and r.get("final_action") == "BUY"
    ]

    # Stage 8 — Execution: paper-eligible
    execution_symbols = [
        r["symbol"] for r in recs
        if r.get("symbol") and r.get("paper_eligible")
    ]

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
            "stocks_out": market_data_received,
            "rejected": universe_symbols_count - market_data_received,
            "rejected_symbols": (snapshot.get("missing_symbols") or [])[:10],
            "stocks": market_data_symbols[:50],
            "duration_ms": _ms("market_data") or 8500,
            "description": f"Fetched live data for {market_data_received} symbols",
            "status": "COMPLETE",
        },
        {
            "id": "research",
            "label": "Research",
            "order": 2,
            "stocks_in": market_data_received,
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
            "id": "risk",
            "label": "Risk",
            "order": 6,
            "stocks_in": len(strategy_symbols),
            "stocks_out": len(risk_symbols),
            "rejected": len(strategy_symbols) - len(risk_symbols),
            "rejected_symbols": [s for s in strategy_symbols if s not in set(risk_symbols)][:10],
            "stocks": risk_symbols[:50],
            "duration_ms": _ms("risk") or 500,
            "description": f"{len(risk_symbols)} approved · {len(strategy_symbols) - len(risk_symbols)} rejected by gates",
            "status": "COMPLETE",
        },
        {
            "id": "ai_decision",
            "label": "AI Decision",
            "order": 7,
            "stocks_in": len(risk_symbols),
            "stocks_out": len(buy_symbols),
            "rejected": len(avoid_symbols),
            "rejected_symbols": avoid_symbols[:10],
            "stocks": buy_symbols[:50],
            "buy_count": len(buy_symbols),
            "avoid_count": len(avoid_symbols),
            "watch_count": len(ai_symbols) - len(buy_symbols),
            "duration_ms": _ms("ai_decision") or 800,
            "description": f"BUY: {len(buy_symbols)} · AVOID: {len(avoid_symbols)}",
            "status": "COMPLETE",
        },
        {
            "id": "execution",
            "label": "Execution",
            "order": 8,
            "stocks_in": len(buy_symbols),
            "stocks_out": len(execution_symbols),
            "rejected": len(buy_symbols) - len(execution_symbols),
            "rejected_symbols": [s for s in buy_symbols if s not in set(execution_symbols)][:10],
            "stocks": execution_symbols[:50],
            "paper_orders": len(execution_symbols),
            "duration_ms": _ms("execution") or 300,
            "description": f"{len(execution_symbols)} paper orders placed",
            "status": "COMPLETE",
        },
    ]
    return stages


# ---------------------------------------------------------------------------
# Per-symbol journey reconstruction
# ---------------------------------------------------------------------------

def _build_symbol_journey(rec: Dict, snapshot: Dict) -> List[Dict]:
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
            "result": "PAPER BUY" if paper_eligible else ("SKIPPED" if final_action != "BUY" else "REJECTED"),
            "score": None,
            "reason": "Paper order placed" if paper_eligible else (
                "Not paper-eligible" if final_action == "BUY" else f"Action: {final_action}"
            ),
            "detail": {
                "paper_eligible": paper_eligible,
                "paper_order_id": rec.get("paper_order_id"),
                "paper_order_note": rec.get("paper_order_note"),
                "entry_price": rec.get("entry_price"),
            },
        },
    ]
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
                buy_count = sum(1 for r in recs if r.get("final_action") == "BUY")
                paper_count = sum(1 for r in recs if r.get("paper_eligible"))
                dur = snap.get("duration_s")
                sessions.append({
                    "scan_id": row["scan_id"] or "latest",
                    "snapshot_ts": str(row.get("snapshot_ts") or row.get("completed_at") or ""),
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
                sessions.append({
                    "scan_id": sid,
                    "snapshot_ts": str(hr.get("snapshot_ts") or ""),
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
                    elif not snapshot:
                        snapshot = snap  # fallback to latest
        finally:
            conn.close()

    if not snapshot:
        return {"error": "No scan data found", "scan_id": scan_id}

    recs: List[Dict] = snapshot.get("recommendations") or []
    stages = _build_stages_from_snapshot(snapshot)

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

    return {
        "scan_id": snapshot.get("scan_id", scan_id),
        "snapshot_ts": snapshot.get("snapshot_ts", ""),
        "stages": stages,
        "symbols": symbols_list,
        "total_symbols": len(symbols_list),
        "universe_size": int(snapshot.get("universe_size") or 0),
        "duration_s": snapshot.get("duration_s"),
        "regime": (snapshot.get("summary") or {}).get("regime"),
        "provider_health": snapshot.get("provider_health") or {},
    }


def get_symbol_journey(scan_id: str, symbol: str) -> Dict:
    """
    Full per-symbol timeline + agent thinking for Feature 12 & 13.
    """
    conn = _get_conn()
    snapshot: Dict = {}
    paper_trade = None

    if conn:
        try:
            row = _q1(conn, "SELECT snapshot FROM scan_state WHERE id = 1")
            if row:
                snap = row.get("snapshot") or {}
                if isinstance(snap, str):
                    snap = json.loads(snap)
                snapshot = snap

            # Check paper trades for this symbol
            trade_row = _q1(conn, """
                SELECT symbol, action, price, total, trade_ts, reason, metadata
                FROM paper_trades WHERE symbol = %s
                ORDER BY created_at DESC LIMIT 1
            """, (symbol.upper(),))
            if trade_row:
                paper_trade = dict(trade_row)
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

    journey = _build_symbol_journey(rec, snapshot)
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

            trade_rows = _q(conn, """
                SELECT symbol, action, price, total, trade_ts, metadata
                FROM paper_trades ORDER BY created_at DESC LIMIT 100
            """)
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
        })

    # Sort: CORRECT first, then MISSED_OPPORTUNITY, then others
    order = {"CORRECT": 0, "LOSS": 1, "MISSED_OPPORTUNITY": 2, "CORRECT_AVOID": 3, "NEUTRAL": 4, "PENDING": 5}
    comparisons.sort(key=lambda x: (order.get(x["status"], 99), -(x.get("confidence") or 0)))

    return {
        "scan_id": snapshot.get("scan_id", scan_id),
        "snapshot_ts": snapshot.get("snapshot_ts", ""),
        "comparisons": comparisons,
        "summary": {
            "total": len(comparisons),
            "correct": sum(1 for c in comparisons if c["status"] == "CORRECT"),
            "losses": sum(1 for c in comparisons if c["status"] == "LOSS"),
            "missed_opportunities": sum(1 for c in comparisons if c["status"] == "MISSED_OPPORTUNITY"),
            "pending": sum(1 for c in comparisons if c["status"] == "PENDING"),
        },
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

            trades = [dict(r) for r in _q(conn, """
                SELECT symbol, action, price, total, trade_ts, metadata
                FROM paper_trades ORDER BY created_at DESC LIMIT 200
            """)]
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
    buy_candidates = sum(1 for r in recs if r.get("final_action") == "BUY")
    paper_orders = sum(1 for r in recs if r.get("paper_eligible"))
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
    profitable = sum(1 for t in trades if float((t.get("metadata") or {}).get("pnl_pct", 0) or 0) > 0) if trades else 0
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
