"""
shared_services.py — Phase 10B
Read-only snapshot functions for the Risk Agent.

get_risk_snapshot() provides a three-level data strategy:
  1. SnapshotBus cache  (instant, from a running agent)
  2. execute_task()     (computes fresh from portfolio + market data)
  3. Phase-20 gates     (derived from the last entry evaluation — always available)

This guarantees available=True whenever the Phase-20 pipeline has been
evaluated at least once, so the AI Operations Centre card never shows WAITING.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_framework.config import disabled_response

RISK_AGENT_ENABLED = "RISK_AGENT_ENABLED"


def _is_enabled() -> bool:
    import os
    return os.environ.get(RISK_AGENT_ENABLED, "true").lower() in ("1", "true", "yes")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


# ── Agent singleton (lazy, no auto-restart) ───────────────────────────────────

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from risk_agent.agent import RiskAgent
        _agent = RiskAgent()
        _agent.start()
        _agent.beat()
    return _agent


# ── Level-3 fallback: build snapshot from Phase-20 evaluation data ────────────

def _snapshot_from_phase20() -> Optional[Dict[str, Any]]:
    """
    Construct a risk snapshot from the last Phase-20 entry evaluation.

    This data is durable (Postgres KV) and is always up-to-date after any
    scan run.  It provides:
      - candidates_evaluated / approved / rejected
      - rejection_reasons (from failed gate names)
      - capital used / available (from paper portfolio)
      - risk_score (derived from approval rate)
      - reward_risk (average R:R from candidates)

    Returns None only when no evaluation has been run yet.
    """
    try:
        import phase20_store as _store
        ev = _store.kv_get("last_entry_evaluation") or {}
    except Exception:
        return None

    if not ev:
        return None

    candidates: List[Dict[str, Any]] = ev.get("candidates") or []
    eligible   = int(ev.get("eligible_count", 0))
    blocked    = int(ev.get("blocked_count", 0))
    total      = len(candidates)

    # Collect rejection reasons from blocked candidates
    reasons: set = set()
    rr_values: list = []
    for c in candidates:
        if not c.get("eligible"):
            for fg in (c.get("failed_gates") or [])[:4]:
                reasons.add(fg.replace("_", " ").title())
        sizing = c.get("sizing") or {}
        rr = sizing.get("rr_ratio") or c.get("rr_ratio") or 0
        if rr:
            try:
                rr_values.append(float(rr))
            except (TypeError, ValueError):
                pass

    avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0.0
    approval_rate = (eligible / total * 100) if total > 0 else 100.0
    risk_score = round(max(0.0, min(100.0, approval_rate)), 1)

    # Portfolio capital data
    capital_used  = 0.0
    capital_avail = 0.0
    open_positions = 0
    try:
        from paper_trader import get_portfolio
        pf = get_portfolio()
        open_positions = len(pf.get("positions") or [])
        capital_avail  = float(pf.get("cash", 0))
        invested       = float(pf.get("invested_value", 0))
        capital_used   = invested
        total_value    = float(pf.get("total_value", capital_avail + invested)) or 1.0
        capital_used_pct = round(invested / total_value * 100, 1)
    except Exception:
        capital_used_pct = 0.0
        total_value      = 0.0

    # Risk level from approval rate
    if risk_score >= 80:
        risk_level = "LOW"
    elif risk_score >= 60:
        risk_level = "MODERATE"
    elif risk_score >= 40:
        risk_level = "HIGH"
    else:
        risk_level = "CRITICAL"

    global_gates = ev.get("global_gates") or []
    global_pass  = bool(ev.get("global_pass", False))

    return {
        "available":             True,
        "advisory_only":         True,
        "read_only":             True,
        "source":                "phase20_evaluation",
        "generated_at":          ev.get("evaluated_at") or _now_iso(),
        "scan_id":               ev.get("scan_id"),
        "snapshot_ts":           ev.get("snapshot_ts"),

        # Candidate pipeline counts
        "candidates_evaluated":  total,
        "approved":              eligible,
        "rejected":              blocked,
        "eligible_count":        eligible,
        "blocked_count":         blocked,
        "rejection_reasons":     sorted(reasons)[:6],

        # Capital / position data
        "capital_used":          round(capital_used, 2),
        "capital_used_pct":      capital_used_pct,
        "capital_available":     round(capital_avail, 2),
        "open_positions":        open_positions,

        # Scores
        "risk_score":            risk_score,
        "risk_level":            risk_level,
        "reward_risk":           avg_rr,
        "approval_rate_pct":     round(approval_rate, 1),

        # Gate summary
        "global_pass":           global_pass,
        "global_gates":          global_gates,
        "market_state":          ev.get("market_state", "UNKNOWN"),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def get_risk_snapshot() -> Dict[str, Any]:
    """
    Returns a rich risk snapshot.  Always available=True once the Phase-20
    pipeline has run at least once.

    Data priority:
      1. SnapshotBus cache (from a running RiskAgent — fastest)
      2. Fresh execute_task() computation
      3. Phase-20 entry-evaluation data (always up-to-date, guaranteed)
    """
    if not _is_enabled():
        return disabled_response(RISK_AGENT_ENABLED)

    # ── Level 1: SnapshotBus cache ────────────────────────────────────────────
    def _from_bus():
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        env = bus.latest("risk")
        if env and env.payload:
            p = dict(env.payload)
            p["from_cache"] = True
            p["available"]  = True
            return p
        return None

    bus_result = _safe(_from_bus)
    if bus_result and bus_result.get("available"):
        # Supplement with phase20 counts if missing
        if "candidates_evaluated" not in bus_result:
            p20 = _safe(_snapshot_from_phase20)
            if p20:
                bus_result.setdefault("candidates_evaluated", p20.get("candidates_evaluated", 0))
                bus_result.setdefault("approved",             p20.get("approved", 0))
                bus_result.setdefault("rejected",             p20.get("rejected", 0))
                bus_result.setdefault("rejection_reasons",    p20.get("rejection_reasons", []))
                bus_result.setdefault("global_pass",          p20.get("global_pass"))
                bus_result.setdefault("global_gates",         p20.get("global_gates", []))
        return bus_result

    # ── Level 2: Fresh agent computation ─────────────────────────────────────
    def _from_agent():
        agent = _get_agent()
        agent.beat()
        payload = agent.execute_task()
        if payload:
            _safe(lambda: agent.publish(payload, "risk"))
            payload["available"] = True
            # Supplement with phase20 counts
            p20 = _safe(_snapshot_from_phase20)
            if p20:
                payload.setdefault("candidates_evaluated", p20.get("candidates_evaluated", 0))
                payload.setdefault("approved",             p20.get("approved", 0))
                payload.setdefault("rejected",             p20.get("rejected", 0))
                payload.setdefault("rejection_reasons",    p20.get("rejection_reasons", []))
                payload.setdefault("global_pass",          p20.get("global_pass"))
                payload.setdefault("global_gates",         p20.get("global_gates", []))
        return payload

    agent_result = _safe(_from_agent)
    if agent_result and agent_result.get("available"):
        return agent_result

    # ── Level 3: Phase-20 evaluation data (always available post-scan) ────────
    p20_result = _safe(_snapshot_from_phase20)
    if p20_result:
        return p20_result

    # Nothing available yet (no scan has run)
    return {
        "available":    False,
        "advisory_only": True,
        "error":        "Risk snapshot unavailable — no scan has run yet",
    }


def get_risk_detail() -> Dict[str, Any]:
    """Same as get_risk_snapshot — full breakdown for the detail view."""
    if not _is_enabled():
        return disabled_response(RISK_AGENT_ENABLED)
    return get_risk_snapshot()
