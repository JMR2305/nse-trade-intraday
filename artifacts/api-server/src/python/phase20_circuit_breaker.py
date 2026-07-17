"""
phase20_circuit_breaker.py — Phase 20 paper-entry circuit breaker.

Automatically PAUSES new paper entries when any of these trip conditions is
met (evaluated from CLOSED Phase 20 ledger trades + today's realised P&L):

  1. CONSECUTIVE_LOSSES  — 3 consecutive losing closed trades
  2. DAILY_LOSS_LIMIT    — realised paper loss today reaches the configured
                           daily_loss_limit_pct of portfolio value
  3. NEGATIVE_EXPECTANCY — rolling 10-trade expectancy (mean realised P&L of
                           the last 10 closed trades) is negative

While tripped, ONLY new paper entries are blocked. Open-position monitoring,
auto paper exits, the scheduler, and evidence collection all stay active.
Live-order write paths remain disabled regardless (Phase 8 guarantee).

Resuming requires MANUAL REVIEW: the exact confirmation statement must be
supplied. Every trip and resume is recorded as a durable audit event
(notification + append-only kv audit log) with reason, timestamp, metrics,
and the affected strategies. The champion model and historical trade records
are never modified.

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import phase20_store as store

STATE_KEY = "entry_circuit_breaker"
AUDIT_KEY = "circuit_breaker_audit"

CONSECUTIVE_LOSS_LIMIT = 3
EXPECTANCY_WINDOW = 10

RESUME_CONFIRMATION_TEXT = (
    "I have manually reviewed the circuit breaker event and approve resuming "
    "automatic paper entries."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unreadable_state(detail: str) -> Dict[str, Any]:
    """Fail-safe state: unreadable/corrupted breaker state BLOCKS entries."""
    return {
        "tripped": True,
        "unreadable": True,
        "reasons": [{"code": "STATE_UNREADABLE",
                     "detail": f"Circuit-breaker state unreadable — entries "
                               f"blocked (fail-safe). {detail}",
                     "strategies": []}],
        "tripped_at": None,
        "affected_strategies": [],
        "metrics": {},
        "resume_confirmation_text": RESUME_CONFIRMATION_TEXT,
    }


def get_state() -> Dict[str, Any]:
    try:
        raw = store.kv_get(STATE_KEY)
    except Exception as exc:
        return _unreadable_state(str(exc)[:200])
    if raw is None:
        state: Dict[str, Any] = {}
    elif isinstance(raw, dict):
        state = raw
    else:
        # Corrupted state is UNREADABLE, never silently "not tripped".
        return _unreadable_state(
            f"Persisted state has invalid type {type(raw).__name__}.")
    state.setdefault("tripped", False)
    state.setdefault("reasons", [])
    state.setdefault("tripped_at", None)
    state.setdefault("affected_strategies", [])
    state.setdefault("metrics", {})
    state.setdefault("resume_confirmation_text", RESUME_CONFIRMATION_TEXT)
    return state


def _append_audit(event: Dict[str, Any]) -> None:
    """Append-only audit trail in durable kv (capped, never rewritten)."""
    try:
        log = store.kv_get(AUDIT_KEY) or []
        if not isinstance(log, list):
            log = []
        log.append(event)
        store.kv_set(AUDIT_KEY, log[-100:])
    except Exception:
        pass


def get_audit_log(limit: int = 50) -> List[Dict[str, Any]]:
    log = store.kv_get(AUDIT_KEY) or []
    if not isinstance(log, list):
        return []
    return list(reversed(log))[: int(limit)]


def _closed_trades() -> List[Dict[str, Any]]:
    """CLOSED Phase 20 ledger trades with realised P&L, oldest → newest.
    Read-only — historical records are never modified here."""
    from phase20_executor import get_ledger
    closed = [t for t in get_ledger(500)
              if t.get("status") == "CLOSED"
              and t.get("realized_pnl") is not None]
    closed.sort(key=lambda t: str(t.get("exit_ts") or ""))
    return closed


def compute_metrics(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the three trip metrics. Never raises."""
    closed = _closed_trades()

    # 1) Consecutive losses (most recent backwards).
    consecutive = 0
    consec_trades: List[Dict[str, Any]] = []
    for t in reversed(closed):
        if float(t.get("realized_pnl") or 0) < 0:
            consecutive += 1
            consec_trades.append(t)
        else:
            break

    # 2) Daily realised paper P&L vs configured limit — the same source the
    # entry gates use (paper_trader SELL trades today).
    daily_pnl = 0.0
    daily_loss_limit = 0.0
    try:
        from paper_trader import _load_state, get_portfolio
        today = datetime.now(timezone.utc).date().isoformat()
        state = _load_state()
        daily_pnl = sum(float(t.get("pnl") or 0)
                        for t in state.get("trades", [])
                        if t.get("action") == "SELL"
                        and str(t.get("timestamp", "")).startswith(today))
        total_value = float(get_portfolio()["total_value"]) or 1.0
        daily_loss_limit = (
            total_value * float(settings.get("daily_loss_limit_pct", 3.0)) / 100.0)
    except Exception:
        pass

    # 3) Rolling expectancy over the last N closed trades (needs a full window
    # — small samples must not trip the breaker).
    window = closed[-EXPECTANCY_WINDOW:]
    expectancy: Optional[float] = None
    if len(window) >= EXPECTANCY_WINDOW:
        expectancy = round(
            sum(float(t.get("realized_pnl") or 0) for t in window) / len(window), 2)

    def _strategies(trades: List[Dict[str, Any]]) -> List[str]:
        seen: List[str] = []
        for t in trades:
            s = str(t.get("strategy_name") or t.get("strategy_id") or "").strip()
            if s and s not in seen:
                seen.append(s)
        return seen

    reasons: List[Dict[str, Any]] = []
    if consecutive >= CONSECUTIVE_LOSS_LIMIT:
        reasons.append({
            "code": "CONSECUTIVE_LOSSES",
            "detail": f"{consecutive} consecutive losing paper trades "
                      f"(limit {CONSECUTIVE_LOSS_LIMIT})",
            "strategies": _strategies(consec_trades),
        })
    if daily_loss_limit > 0 and daily_pnl <= -daily_loss_limit:
        reasons.append({
            "code": "DAILY_LOSS_LIMIT",
            "detail": f"Realised paper P&L today ₹{daily_pnl:.2f} breaches the "
                      f"configured limit -₹{daily_loss_limit:.2f} "
                      f"({settings.get('daily_loss_limit_pct')}% of portfolio)",
            "strategies": [],
        })
    if expectancy is not None and expectancy < 0:
        reasons.append({
            "code": "NEGATIVE_EXPECTANCY",
            "detail": f"Rolling {EXPECTANCY_WINDOW}-trade expectancy "
                      f"₹{expectancy:.2f} per trade is negative",
            "strategies": _strategies(window),
        })

    return {
        "computed_at": _now_iso(),
        "closed_trades": len(closed),
        "consecutive_losses": consecutive,
        "consecutive_loss_limit": CONSECUTIVE_LOSS_LIMIT,
        "daily_realized_pnl": round(daily_pnl, 2),
        "daily_loss_limit": round(daily_loss_limit, 2),
        "rolling_expectancy": expectancy,
        "expectancy_window": EXPECTANCY_WINDOW,
        "trip_reasons": reasons,
    }


def evaluate_and_maybe_trip(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Evaluate the trip conditions and pause entries if any is met.
    Idempotent — an already-tripped breaker is never re-tripped (the original
    trip record is preserved; manual review is required to resume).
    Never resumes automatically. Never raises.
    """
    try:
        if settings is None:
            settings = store.get_settings()
        state = get_state()
        if state.get("unreadable"):
            # Never overwrite kv from an unreadable read — surface the
            # fail-safe block and leave the stored value for inspection.
            return state
        metrics = compute_metrics(settings)
        reasons = metrics.pop("trip_reasons")

        if state.get("tripped"):
            state["last_evaluation"] = metrics
            store.kv_set(STATE_KEY, state)
            return state
        if not reasons:
            state["last_evaluation"] = metrics
            store.kv_set(STATE_KEY, state)
            return state

        affected: List[str] = []
        for r in reasons:
            for s in r.get("strategies", []):
                if s not in affected:
                    affected.append(s)
        tripped_at = _now_iso()
        state = {
            "tripped": True,
            "reasons": reasons,
            "tripped_at": tripped_at,
            "affected_strategies": affected,
            "metrics": metrics,
            "last_evaluation": metrics,
            "resume_confirmation_text": RESUME_CONFIRMATION_TEXT,
        }
        store.kv_set(STATE_KEY, state)

        codes = ", ".join(r["code"] for r in reasons)
        detail = "; ".join(r["detail"] for r in reasons)
        _append_audit({
            "event": "CIRCUIT_BREAKER_TRIPPED",
            "at": tripped_at,
            "reasons": reasons,
            "affected_strategies": affected,
            "metrics": metrics,
        })
        store.add_notification(
            "CIRCUIT_BREAKER_TRIPPED",
            f"Paper entries PAUSED: {codes}",
            f"{detail}. New paper entries are paused until manual review. "
            f"Open-position monitoring, auto exits, the scheduler, and "
            f"evidence collection remain active. No live orders exist.",
            severity="CRITICAL",
            context={"reasons": reasons, "affected_strategies": affected,
                     "metrics": metrics})
        return state
    except Exception as exc:
        # Evaluation problems must never crash the scheduler tick — but they
        # also must never silently CLEAR an existing pause.
        try:
            state = get_state()
            state["last_evaluation_error"] = str(exc)[:200]
            return state
        except Exception:
            return _unreadable_state(str(exc)[:200])


def is_tripped() -> bool:
    try:
        return bool(get_state().get("tripped"))
    except Exception:
        return True  # fail-safe: unknown state blocks entries


def resume(confirmation_text: str, reviewed_by: str = "user") -> Dict[str, Any]:
    """
    Manual-review resume. Requires the EXACT confirmation statement.
    Records a durable audit event; preserves the previous trip in history.
    Raises ValueError when the confirmation is wrong or nothing is paused.
    """
    state = get_state()
    if not state.get("tripped"):
        raise ValueError("Circuit breaker is not tripped — nothing to resume.")
    if (confirmation_text or "").strip() != RESUME_CONFIRMATION_TEXT:
        raise ValueError(
            "Resuming paper entries requires the exact manual-review "
            "confirmation statement. Entries remain paused.")

    resumed_at = _now_iso()
    previous = {k: state.get(k) for k in
                ("reasons", "tripped_at", "affected_strategies", "metrics")}
    new_state = {
        "tripped": False,
        "reasons": [],
        "tripped_at": None,
        "affected_strategies": [],
        "metrics": {},
        "resumed_at": resumed_at,
        "resumed_by": reviewed_by,
        "last_trip": previous,
        "resume_confirmation_text": RESUME_CONFIRMATION_TEXT,
    }
    store.kv_set(STATE_KEY, new_state)
    _append_audit({
        "event": "CIRCUIT_BREAKER_RESUMED",
        "at": resumed_at,
        "reviewed_by": reviewed_by,
        "previous_trip": previous,
    })
    store.add_notification(
        "CIRCUIT_BREAKER_RESUMED",
        "Paper entries resumed after manual review",
        f"Circuit breaker cleared by {reviewed_by} at {resumed_at}. "
        f"Original trip: {', '.join(r.get('code', '?') for r in (previous.get('reasons') or []))} "
        f"at {previous.get('tripped_at')}.",
        severity="WARN",
        context={"reviewed_by": reviewed_by, "previous_trip": previous})
    return new_state
