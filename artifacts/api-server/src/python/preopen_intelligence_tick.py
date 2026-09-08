"""
preopen_intelligence_tick.py — Phase 5A IST checkpoint tick handler.

Called by the Node.js market-hours scheduler every minute via:
    python3 main.py preopen_intelligence_tick

This module owns all IST time-gating and per-phase deduplication so the
Node scheduler needs zero time-of-day awareness for Phase 5A.

Phase windows (IST):
  08:43–08:51  →  INIT             (once)   provider health, DB, prev-close, calendar
  08:53–09:00  →  READINESS        (once)   confirm provider is not UNAVAILABLE
   09:00–09:12  →  COLLECT          (every tick — one snapshot per minute)
  09:15–09:18  →  FREEZE           (once)   rank watchlist, generate signals
  09:18–09:23  →  RECONCILE        (once)   indicative vs actual price delta (09:20 prices)
  09:28–09:35  →  RECONCILE_0930   (once)   patch price_at_0930 on existing records

State is persisted per trading date in a JSON sidecar file so:
  - One-shot phases (init, readiness, freeze, reconcile) never repeat.
  - A hot-reload of the API server between 09:00–09:15 does not lose
    snapshots already collected.
  - The status endpoint can report phase, collect_count, and next run.

Provider failure at any phase marks the session DEGRADED/UNAVAILABLE.
It is always caught and returned as structured data — never re-raised.

PAPER TRADING / ADVISORY ONLY.
No order, execution, or trade-placement function exists here.
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

_IST        = timezone(timedelta(hours=5, minutes=30))
_ENABLED_VAR = "PREOPEN_INTELLIGENCE_ENABLED"
_STATE_FILE  = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".preopen_intelligence_tick_state.json",
)

# ── Phase gate definitions ─────────────────────────────────────────────────────
#
# Each tuple: (phase_name, window_start_hhmm, window_end_hhmm, once_only)
# once_only=True  → executed at most once per trading date (idempotent).
# once_only=False → executed on every tick inside the window (snapshot collect).
#
_PHASES = [
    ("init",            (8, 43), (8, 51),  True),
    ("readiness",       (8, 53), (9,  0),  True),
    # NSE order collection closes at a system-selected point between 09:07
    # and 09:08.  The 09:08–09:12 interval is the approved final-proof
    # window: accepted rows are fresh at ingestion, then frozen unchanged at
    # 09:15.  Do not collect during the matching/transition interval, where
    # a correctly static final auction timestamp can exceed the real-time
    # freshness limit and overwrite the last verified batch.
    ("collect",         (9,  0), (9, 12),  False),
    ("freeze",          (9, 15), (9, 18),  True),
    ("reconcile",       (9, 18), (9, 23),  True),
    ("reconcile_0930",  (9, 28), (9, 35),  True),   # post-open enrichment: patch price_at_0930
]

_PHASE_PREREQUISITES = {
    "reconcile": "freeze",
    "reconcile_0930": "reconcile",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_enabled() -> bool:
    return os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


def _now_ist() -> datetime:
    return datetime.now(_IST)


def _today_ist() -> str:
    return _now_ist().strftime("%Y-%m-%d")


def _is_trading_day() -> bool:
    try:
        from market_hours import is_trading_day
        return is_trading_day(_now_ist().date())
    except Exception:
        return _now_ist().weekday() < 5


def _active_phase(now: datetime) -> Optional[tuple]:
    """Return the phase tuple matching the current IST time, or None."""
    hm = now.hour * 60 + now.minute
    for p in _PHASES:
        name, (wh, wm), (eh, em), once = p
        # Windows are end-exclusive so a boundary minute belongs to the next
        # phase (09:00 is collection; 09:15 is freeze), never whichever tuple
        # happens to be listed first.
        if wh * 60 + wm <= hm < eh * 60 + em:
            return p
    return None


def _next_phase_label(now: datetime) -> Optional[str]:
    """Return a human label for the next upcoming phase, or None if all done."""
    hm = now.hour * 60 + now.minute
    for name, (wh, wm), (eh, em), _ in _PHASES:
        if hm < wh * 60 + wm:
            return f"{name} at {wh:02d}:{wm:02d} IST"
    return None


# ── Persistent tick state ──────────────────────────────────────────────────────

def _load_state(trading_date: str) -> dict:
    try:
        if not os.path.exists(_STATE_FILE):
            return {}
        with open(_STATE_FILE) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
        return data if data.get("trading_date") == trading_date else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(state, f, indent=2, default=str)
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, _STATE_FILE)
    except Exception:
        pass


# ── Phase implementations ──────────────────────────────────────────────────────

def _run_init(session_id: str, trading_date: str) -> dict:
    """
    08:43 — provider health check, DB readiness, prev-close refs, calendar.
    Returns a result dict; never raises.
    """
    steps: Dict[str, Any] = {}

    # 1. Calendar / session validation
    try:
        from market_hours import is_trading_day as itd, is_holiday, market_state
        steps["calendar_valid"]   = itd(_now_ist().date())
        steps["market_holiday"]   = is_holiday(_now_ist().date()) is not None
        steps["market_state"]     = market_state()
    except Exception as e:
        steps["calendar_error"]   = str(e)

    # 2. Provider health check
    provider_status = "UNKNOWN"
    try:
        import preopen_engine as eng
        health = eng.get_health()
        ph = health.get("provider_health", {})
        provider_status = ph.get("status", "UNKNOWN")
        steps["provider_status"]  = provider_status
        steps["provider_message"] = ph.get("message", "")
        steps["provider_name"]    = ph.get("provider", "unknown")
    except Exception as e:
        steps["provider_error"]   = str(e)
        provider_status           = "ERROR"

    # 3. DB readiness
    try:
        import preopen_db as pdb
        steps["db_ready"] = bool(pdb.upsert_session({
            "session_id":      session_id,
            "trading_date":    trading_date,
            "status":          "INITIALISING",
            "provider_status": provider_status,
        }))
    except Exception as e:
        steps["db_error"] = str(e)
        steps["db_ready"] = False

    # 4. Previous-close reference data
    try:
        import preopen_engine as eng
        snap = eng.get_snapshot()
        steps["prev_close_symbols"] = snap.get("symbol_count", 0)
    except Exception as e:
        steps["prev_close_error"] = str(e)

    session_status = (
        "DEGRADED"     if provider_status in ("DEGRADED",)
        else "UNAVAILABLE" if provider_status in ("UNAVAILABLE", "ERROR", "UNKNOWN")
        else "INITIALISED"
    )

    return {
        "success":          bool(steps.get("db_ready")),
        "provider_status":  provider_status,
        "session_status":   session_status,
        "steps":            steps,
    }


def _run_readiness(trading_date: str) -> dict:
    """08:55 — confirm provider is not UNAVAILABLE before collection begins."""
    try:
        import preopen_engine as eng
        status = eng.get_status()
        ps     = status.get("provider_status", "UNKNOWN")
        ready  = ps not in ("UNAVAILABLE", "ERROR")
        return {
            "ready":           ready,
            "provider_status": ps,
            "session_status":  status.get("session", {}).get("status") if status.get("session") else None,
        }
    except Exception as e:
        return {"ready": False, "provider_status": "ERROR", "error": str(e)}


def _run_collect(session_id: str) -> dict:
    """09:00–09:12 — one naturally scheduled snapshot pass."""
    try:
        import preopen_engine as eng
        result = eng.collect_snapshot(session_id=session_id, source="SCHEDULED")
        # The engine returns collection proof from the same transaction that
        # wrote snapshots. Never infer success from a later, aggregate session
        # row: an earlier batch could otherwise mask a failed current batch.
        collected = result.get(
            "provider_collected_count",
            result.get("symbol_count", result.get("symbols_captured", 0)),
        )
        persisted = result.get("persisted_count")
        expected = result.get("expected_count")
        persistence_status = str(result.get("persistence_status") or "UNCONFIRMED")
        success = bool(
            result.get("success", False)
            and persistence_status == "MATCH"
            and persisted is not None
            and expected is not None
            and int(persisted) == int(collected)
            and int(persisted) == int(expected)
            and int(result.get("failed_count") or 0) == 0
        )
        return {
            "success":          success,
            "symbol_count":     collected,
            "symbols_captured": collected,
            "persisted_symbol_count": persisted,
            "persistence_status": persistence_status,
            "provider_collected_count": collected,
            "persisted_count": persisted,
            "expected_count": expected,
            "failed_count": result.get("failed_count"),
            "error": result.get("error"),
            "stale_count":      result.get("stale_count", 0),
            "provider_status":  result.get("provider_status", "UNKNOWN"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _run_freeze(session_id: str, trading_date: str) -> dict:
    """09:15 — freeze ranked watchlist."""
    try:
        from preopen_scheduler import PreOpenScheduler
        sched = PreOpenScheduler(session_id=session_id)
        success = bool(sched._phase_09_15_freeze())
        return {
            "success": success,
            "phase":   sched.phase,
            "log":     sched._log[-5:],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _run_reconcile(session_id: str, trading_date: str) -> dict:
    """09:18 — reconcile indicative vs actual open prices."""
    try:
        from preopen_scheduler import PreOpenScheduler
        sched = PreOpenScheduler(session_id=session_id)
        sched._phase_09_20_reconcile()
        return {
            "success": sched.phase not in ("ERROR",),
            "phase":   sched.phase,
            "log":     sched._log[-5:],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _run_reconcile_0930(session_id: str, trading_date: str) -> dict:
    """
    09:28–09:35 — post-open enrichment: patch price_at_0930 on existing
    reconciliation records using live quotes fetched at 09:30 IST.

    This is a once-only, best-effort pass.  If live quotes are unavailable
    the function returns success=True with prices_patched=0 rather than
    failing the session — the 09:20 reconciliation data is still valid.
    """
    try:
        from preopen_scheduler import PreOpenScheduler
        sched = PreOpenScheduler(session_id=session_id)
        sched._phase_09_30_post_open_reconcile()
        return {
            "success":       sched.phase not in ("ERROR",),
            "phase":         sched.phase,
            "log":           sched._log[-5:],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Main tick ──────────────────────────────────────────────────────────────────

def run_tick() -> Dict[str, Any]:
    """
    Entry point — called by the Node scheduler every minute.
    Returns a structured dict; never raises.

    Return shape:
      {
        "ran":              bool,
        "phase":            str | None,
        "reason":           str,
        "trading_date":     str,
        "session_id":       str | None,
        "collect_count":    int,
        "phases_done":      [...],
        "next_phase":       str | None,
        "enabled":          bool,
        "auto_tick":        True,
        "provider_status":  str | None,
      }
    """
    now          = _now_ist()
    trading_date = now.strftime("%Y-%m-%d")

    base = {
        "ran":             False,
        "phase":           None,
        "trading_date":    trading_date,
        "session_id":      None,
        "collect_count":   0,
        "phases_done":     [],
        "next_phase":      _next_phase_label(now),
        "enabled":         _is_enabled(),
        "auto_tick":       True,
        "provider_status": None,
    }

    if not _is_enabled():
        return {**base, "reason": f"{_ENABLED_VAR} is false — tick is a no-op"}

    if not _is_trading_day():
        return {**base, "reason": f"{trading_date} is not a valid NSE trading day"}

    active = _active_phase(now)
    if active is None:
        return {**base, "reason": f"No phase window active at {now.strftime('%H:%M')} IST"}

    phase_name, _, _, once_only = active

    # Load or initialise today's state. The sidecar is merely a warm cache:
    # authoritative session identity and one-shot phase outcomes live in
    # Postgres so an Autoscale restart resumes the same session.
    state = _load_state(trading_date)
    durable = None
    try:
        import preopen_db as pdb
        durable = pdb.get_session_for_trading_date(trading_date)
    except Exception:
        durable = None
    if not state:
        state = {
            "trading_date":  trading_date,
            "session_id":    (durable or {}).get(
                "session_id", f"preopen-{trading_date}-{uuid.uuid4().hex[:6]}"),
            "phases_done":   {
                name: detail for name, detail
                in ((durable or {}).get("phase_state") or {}).items()
                if isinstance(detail, dict) and detail.get("completed") is True
            },
            "collect_count": 0,
        }
    elif durable:
        # The JSON sidecar is only a cache for counts/status display. A
        # completed one-shot phase is authoritative only after its database
        # record exists, so a crash between local writes can never unlock a
        # later phase.
        state["session_id"] = durable.get("session_id") or state["session_id"]
        state["phases_done"] = {
            name: detail for name, detail
            in (durable.get("phase_state") or {}).items()
            if isinstance(detail, dict) and detail.get("completed") is True
        }

    session_id = state["session_id"]
    base["session_id"]    = session_id
    base["collect_count"] = state.get("collect_count", 0)
    base["phases_done"]   = list(state.get("phases_done", {}).keys())

    # Idempotency for once-only phases
    if once_only and phase_name in state.get("phases_done", {}):
        return {
            **base,
            "reason": f"Phase '{phase_name}' already completed today",
        }

    # Execute the phase
    try:
        prerequisite = _PHASE_PREREQUISITES.get(phase_name)
        if prerequisite and prerequisite not in state.get("phases_done", {}):
            detail = {
                "success": False,
                "status": "BLOCKED_PREREQUISITE",
                "error": (
                    f"Phase '{phase_name}' requires durably completed "
                    f"phase '{prerequisite}'"
                ),
            }
        elif phase_name == "init":
            detail = _run_init(session_id, trading_date)
        elif phase_name == "readiness":
            detail = _run_readiness(trading_date)
        elif phase_name == "collect":
            detail = _run_collect(session_id)
            state["collect_attempt_count"] = state.get("collect_attempt_count", 0) + 1
            if detail.get("success"):
                state["collect_count"] = state.get("collect_count", 0) + 1
        elif phase_name == "freeze":
            detail = _run_freeze(session_id, trading_date)
        elif phase_name == "reconcile":
            detail = _run_reconcile(session_id, trading_date)
        elif phase_name == "reconcile_0930":
            detail = _run_reconcile_0930(session_id, trading_date)
        else:
            detail = {"error": f"Unknown phase: {phase_name}"}
    except Exception as e:
        return {**base, "reason": f"Phase '{phase_name}' raised unexpectedly: {e}"}

    phase_succeeded = bool(
        detail.get(
            "success",
            detail.get("ready") if phase_name == "readiness" else False,
        )
    )
    # Persist state for once-only phases only after a verified success. Failed
    # phases remain retryable in their time window and cannot unlock downstream
    # lifecycle work.
    if once_only and phase_succeeded:
        state.setdefault("phases_done", {})[phase_name] = {
            "ts": now.isoformat(), **detail,
        }
    durable_state_write_ok = True
    try:
        import preopen_db as pdb
        durable_state_write_ok = bool(pdb.update_phase_state(
            session_id, phase_name, {"ts": now.isoformat(), **detail},
            completed=phase_succeeded,
        ))
    except Exception:
        durable_state_write_ok = False

    if once_only and phase_succeeded and not durable_state_write_ok:
        state.get("phases_done", {}).pop(phase_name, None)
        phase_succeeded = False
        detail = {
            **detail,
            "success": False,
            "status": "PHASE_STATE_PERSISTENCE_FAILED",
            "error": f"Could not durably record phase '{phase_name}' completion",
        }

    _save_state(state)

    return {
        **base,
        "ran":             phase_succeeded,
        "phase":           phase_name,
        "reason":          (f"Phase '{phase_name}' executed"
                            if phase_succeeded
                            else f"Phase '{phase_name}' failed; retry remains available"),
        "collect_count":   state.get("collect_count", 0),
        "phases_done":     list(state.get("phases_done", {}).keys()),
        "next_phase":      _next_phase_label(now),
        "provider_status": detail.get("provider_status"),
        **{k: v for k, v in detail.items() if k not in ("provider_status", "phase")},
    }


# ── Status ─────────────────────────────────────────────────────────────────────

def get_tick_status() -> Dict[str, Any]:
    """
    Returns scheduler registration and progress for the /status endpoint.
    Called by preopen_engine.get_status().
    """
    now          = _now_ist()
    trading_date = now.strftime("%Y-%m-%d")
    state        = _load_state(trading_date)
    active       = _active_phase(now)

    return {
        "auto_tick":      True,
        "registered":     True,
        "enabled":        _is_enabled(),
        "trading_day":    _is_trading_day(),
        "ist_time":       now.strftime("%H:%M:%S"),
        "trading_date":   trading_date,
        "active_phase":   active[0] if active else None,
        "next_phase":     _next_phase_label(now),
        "session_id":     state.get("session_id"),
        "collect_count":  state.get("collect_count", 0),
        "phases_done":    list(state.get("phases_done", {}).keys()),
        "phases_detail":  state.get("phases_done", {}),
        "all_phases":     [p[0] for p in _PHASES],
        # active=True only when enabled + trading day + inside some phase window
        "active":         _is_enabled() and _is_trading_day() and (active is not None
                          or bool(state.get("phases_done"))),
    }
