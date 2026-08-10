"""
daily_session_manager.py — Phase 11/20 Daily Paper-Trading Session Manager

Runs once per calendar trading day (idempotent via KV guard).
Responsibilities:
  1. Archive previous day's paper portfolio (trades stamped archived_at).
  2. Reset paper portfolio to ₹50,000 fresh capital.
  3. Automatically enable auto_paper_entries with the required confirmation.
  4. Verify / warm-start all Phase 10 agents.
  5. Log the session initialisation to the notification store.

Called every minute from phase20_scheduler.run_tick() during the pre-market
window (08:43–09:20 IST) so the session is always ready before OPEN.

Also called at the START of OPEN if the server missed the pre-market window
(e.g. server cold-started after 09:15).

PAPER TRADING ONLY — NO LIVE ORDERS.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# ── KV keys ────────────────────────────────────────────────────────────────────

_SESSION_DATE_KEY  = "daily_session_date"           # "YYYY-MM-DD" of last init
_SESSION_TS_KEY    = "daily_session_initialized_at"  # ISO timestamp
_SESSION_STATE_KEY = "daily_session_state"          # INITIALISED | ERROR
_SESSION_ERROR_KEY = "daily_session_last_error"     # {at, source, detail} of last failure
_SESSION_RECOVERED_KEY = "daily_session_recovered"  # {date, at} of today's recovery (if any)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_ist() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:
        # Fallback: UTC+5:30
        from datetime import timedelta
        return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def _hour_min_ist() -> int:
    """Return hours*60+minutes in IST."""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.now(ZoneInfo("Asia/Kolkata"))
        return dt.hour * 60 + dt.minute
    except Exception:
        from datetime import timedelta
        dt = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        return dt.hour * 60 + dt.minute


def _kv_get(key: str, default: Any = None) -> Any:
    try:
        from phase20_store import kv_get
        return kv_get(key, default)
    except Exception:
        return default


def _kv_set(key: str, value: Any) -> None:
    try:
        from phase20_store import kv_set
        kv_set(key, value)
    except Exception:
        pass


def _notify(kind: str, title: str, body: str = "", severity: str = "INFO") -> None:
    try:
        from phase20_store import add_notification
        add_notification(kind, title, body, severity=severity)
    except Exception:
        pass


# ── Agent warm-start ───────────────────────────────────────────────────────────

def verify_agents() -> Dict[str, Any]:
    """
    Warm-start / health-check all Phase 10 agents via lazy initialisation.
    Each agent module already lazy-creates its agent on first call; we simply
    trigger the init path and record the outcome.

    Returns a dict:  { "agents": {name: "OK"|"ERROR"}, "healthy": int, "total": int }
    """
    agents: Dict[str, str] = {}

    agent_imports = [
        ("supervisor",           "supervisor_agent.supervisor",         "get_supervisor"),
        ("market_data",          "market_data_agent.agent",             "get_agent"),
        ("research",             "research_agent.agent",                "get_agent"),
        ("market_intelligence",  "market_intelligence_agent.agent",     "get_agent"),
        ("stock_monitoring",     "stock_monitoring_agent.agent",        "get_agent"),
        ("strategy",             "strategy_agent.agent",                "get_agent"),
        ("risk",                 "risk_agent.agent",                    "get_agent"),
        ("ai_decision",          "ai_decision_agent.agent",             "get_agent"),
        ("execution",            "execution_agent.agent",               "get_agent"),
        ("learning",             "learning_agent.agent",                "get_agent"),
        ("knowledge",            "knowledge_agent.agent",               "get_agent"),
    ]

    for name, module_path, fn_name in agent_imports:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            fn  = getattr(mod, fn_name, None)
            if fn is not None:
                fn()   # lazy-creates / warms up the agent singleton
            agents[name] = "OK"
        except Exception as exc:
            agents[name] = f"ERROR: {str(exc)[:80]}"

    healthy = sum(1 for v in agents.values() if v == "OK")
    return {"agents": agents, "healthy": healthy, "total": len(agents)}


# ── Core session initialisation ────────────────────────────────────────────────

def initialize_daily_session(force: bool = False) -> Dict[str, Any]:
    """
    Perform today's one-time session initialisation:
      1. Archive previous paper portfolio (trades preserved in history).
      2. Reset portfolio to ₹50,000 fresh capital.
      3. Enable auto_paper_entries with the required confirmation text.
      4. Warm-start all agents.
      5. Apply Mode B top-up if Continuous Research Mode is active.
      6. Record KV guards so this is idempotent today.

    Returns a result dict with full details.
    """
    today = _today_ist()

    # Idempotency guard — skip if already done today (unless forced)
    if not force:
        last = _kv_get(_SESSION_DATE_KEY)
        if last == today:
            return {
                "skipped":    True,
                "reason":     "Already initialised today",
                "date":       today,
                "init_at":    _kv_get(_SESSION_TS_KEY),
            }

    result: Dict[str, Any] = {
        "date":      today,
        "started_at": _iso_now(),
        "steps":     {},
    }

    # ── 1. Archive + reset portfolio ──────────────────────────────────────────
    try:
        import paper_trader as _pt
        _pt.reset_portfolio()      # archives old trades, resets to INITIAL_CAPITAL (₹50K)
        result["steps"]["portfolio_reset"] = "OK"
    except Exception as exc:
        result["steps"]["portfolio_reset"] = f"ERROR: {str(exc)[:200]}"

    # ── 2. Enable auto_paper_entries ──────────────────────────────────────────
    try:
        from phase20_store import update_settings, CONFIRMATION_TEXT
        update_settings(
            {
                "auto_paper_entries": True,
                "auto_paper_exits":   True,
                "auto_scan_enabled":  True,
            },
            confirmation_text=CONFIRMATION_TEXT,
        )
        result["steps"]["auto_entries_enabled"] = "OK"
    except Exception as exc:
        result["steps"]["auto_entries_enabled"] = f"ERROR: {str(exc)[:200]}"

    # ── 3. Warm-start agents ──────────────────────────────────────────────────
    try:
        agent_result = verify_agents()
        result["steps"]["agents"] = agent_result
    except Exception as exc:
        result["steps"]["agents"] = {"error": str(exc)[:200]}

    # ── 4. Apply Mode B top-up if active ─────────────────────────────────────
    try:
        from phase11_autonomous import check_and_apply_topup
        topup = check_and_apply_topup()
        result["steps"]["topup"] = topup or {"applied": False, "reason": "Mode A or threshold not met"}
    except Exception as exc:
        result["steps"]["topup"] = {"applied": False, "error": str(exc)[:100]}

    # ── 5. Record KV guards ───────────────────────────────────────────────────
    now = _iso_now()

    # Determine overall success — a step failed when:
    #   * its value is a string starting with "ERROR", OR
    #   * it is a dict carrying an "error" key (e.g. topup failure), OR
    #   * it is the agents dict and any agent reported an ERROR status.
    def _step_error_detail(name: str, v: Any) -> Optional[Any]:
        if isinstance(v, str) and v.startswith("ERROR"):
            return v
        if isinstance(v, dict):
            if v.get("error"):
                return {"error": v["error"]}
            if name == "agents":
                bad = {a: s for a, s in (v.get("agents") or {}).items()
                       if isinstance(s, str) and s.startswith("ERROR")}
                if bad:
                    return {"failed_agents": bad,
                            "healthy": v.get("healthy"), "total": v.get("total")}
        return None

    error_details = {k: d for k, v in result["steps"].items()
                     if (d := _step_error_detail(k, v)) is not None}
    errors = list(error_details.keys())
    result["success"] = len(errors) == 0
    result["errors"]  = errors

    _kv_set(_SESSION_DATE_KEY,  today)
    _kv_set(_SESSION_TS_KEY,    now)
    _kv_set(_SESSION_STATE_KEY, "INITIALISED" if not errors else "ERROR")
    if errors:
        _kv_set(_SESSION_ERROR_KEY, {
            "at":     now,
            "source": "session_init_steps",
            "detail": error_details,
        })
    else:
        _kv_set(_SESSION_ERROR_KEY, None)
    result["completed_at"] = now

    # ── 6. Notification ───────────────────────────────────────────────────────
    agents_ok = result["steps"].get("agents", {})
    healthy   = agents_ok.get("healthy", "?") if isinstance(agents_ok, dict) else "?"
    total     = agents_ok.get("total",   "?") if isinstance(agents_ok, dict) else "?"

    body = (
        f"Paper trading session started for {today}. "
        f"Capital reset to ₹50,000. "
        f"Auto entries enabled. "
        f"Agents: {healthy}/{total} healthy."
    )
    if errors:
        body += f" Errors: {', '.join(errors)}"

    _notify(
        "SESSION_INIT",
        f"Daily paper trading session ready — {today}",
        body,
        severity="INFO" if not errors else "WARNING",
    )

    # ── 7. Recovery notice ────────────────────────────────────────────────────
    # If today's market-open CRITICAL alert already fired (its kv_claim_once
    # key exists — read-only check, we must NOT claim it here or we'd
    # suppress a legitimate future alert) and this init succeeded, close the
    # loop with a one-time INFO "recovered" notification (own claim key).
    if not errors:
        try:
            alert_key = f"session_init_open_alert:{today}"
            if _kv_get(alert_key) is not None:
                from phase20_store import kv_claim_once, add_notification
                if kv_claim_once(f"session_init_recovered:{today}"):
                    add_notification(
                        "SESSION_INIT_RECOVERED",
                        f"Session initialised (recovered) — {today}",
                        ("Today's paper trading session is now INITIALISED "
                         "after the earlier market-open failure alert. "
                         "Auto paper entries can run normally."),
                        severity="INFO",
                        context={"date": today, "recovered_at": now},
                    )
                    # Durable stamp so the dashboard session card can show
                    # "recovered at HH:MM" for the rest of the day.
                    _kv_set(_SESSION_RECOVERED_KEY, {"date": today, "at": now})
                    result["recovery_notice"] = {"emitted": True}
                else:
                    result["recovery_notice"] = {
                        "emitted": False, "reason": "already emitted today"}
        except Exception as exc:   # never break init on notification issues
            result["recovery_notice"] = {"emitted": False,
                                         "error": str(exc)[:200]}

    return result


# ── Scheduler hook ─────────────────────────────────────────────────────────────

def check_and_maybe_initialize(mstate: str) -> Optional[Dict[str, Any]]:
    """
    Called every minute by phase20_scheduler.run_tick().

    Triggers session initialisation when:
      - Market state is PRE_OPEN (08:43–09:15 IST) or OPEN (catches late starts), AND
      - It is not a weekend/holiday (scheduler gate handles this but we double-check), AND
      - Today's session has not yet been initialised.

    Returns init result dict, or None if no action was taken.
    """
    relevant = mstate in ("PRE_OPEN", "OPEN")
    if not relevant:
        return None

    today = _today_ist()
    last  = _kv_get(_SESSION_DATE_KEY)
    if last == today:
        return None   # already done

    # For PRE_OPEN, only run in the 08:43–09:20 window.
    # For OPEN, always run (server missed pre-market).
    if mstate == "PRE_OPEN":
        hm = _hour_min_ist()
        if hm < 8 * 60 + 43 or hm > 9 * 60 + 20:
            return None

    return initialize_daily_session()


# ── Market-open failure alert ──────────────────────────────────────────────────

def check_open_alert(mstate: str) -> Optional[Dict[str, Any]]:
    """
    Called every minute by phase20_scheduler.run_tick() after
    check_and_maybe_initialize().

    When the market has reached OPEN and today's session is still NOT
    INITIALISED (never ran, or ran with errors → state=ERROR), emit exactly
    one CRITICAL notification per IST trading day (atomic kv_claim_once, so
    concurrent Autoscale ticks can't double-alert). The notification includes
    the persisted daily_session_last_error detail when present, and the
    SESSION_INIT_FAILED kind is on the email-alert critical list.

    Never raises. Returns a small status dict, or None when idle.
    """
    if mstate != "OPEN":
        return None
    try:
        today = _today_ist()
        init_date = _kv_get(_SESSION_DATE_KEY)
        state = _kv_get(_SESSION_STATE_KEY, "UNKNOWN")
        initialized_ok = (init_date == today and state == "INITIALISED")
        if initialized_ok:
            return None

        session_state = state if init_date == today else "NOT_INITIALIZED"

        from phase20_store import kv_claim_once, add_notification
        claim_key = f"session_init_open_alert:{today}"
        if not kv_claim_once(claim_key):
            return {"alerted": False, "state": session_state,
                    "reason": "already alerted today"}

        last_error = _kv_get(_SESSION_ERROR_KEY)
        body = (
            f"Market is OPEN but today's paper trading session is "
            f"{session_state} (expected INITIALISED). Auto paper entries "
            f"will NOT run until the session is initialised. "
            f"Retry from the AI Paper Trader page."
        )
        if isinstance(last_error, dict) and last_error:
            try:
                detail = json.dumps(last_error.get("detail"),
                                    default=str)[:600]
            except Exception:
                detail = str(last_error.get("detail"))[:600]
            body += (f" Last error (at {last_error.get('at')}, "
                     f"source {last_error.get('source')}): {detail}")

        add_notification(
            "SESSION_INIT_FAILED",
            f"Daily session NOT initialised at market open — {today}",
            body,
            severity="CRITICAL",
            context={
                "date": today,
                "session_state": session_state,
                "last_init_date": init_date,
                "last_error": last_error,
            },
        )
        return {"alerted": True, "state": session_state,
                "claim_key": claim_key}
    except Exception as exc:   # never break the scheduler tick
        return {"alerted": False, "error": str(exc)[:200]}


# ── Status endpoint helper ─────────────────────────────────────────────────────

def record_session_error(payload_json: str = "{}") -> Dict[str, Any]:
    """
    Persist a crash-level session-init error (e.g. the Python process exited
    non-zero before initialize_daily_session() could record anything itself).

    Called by the API server when `daily_session_init` fails at the process
    level.  Stores timestamp, command, exit code, stderr/traceback, and a
    recovery hint so the dashboard can show the exact failure beside NOT INIT.
    """
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except Exception:
        payload = {"raw": str(payload_json)[:500]}
    entry = {
        "at":     _iso_now(),
        "source": "python_crash",
        "detail": {
            "command":   str(payload.get("command", "daily_session_init"))[:200],
            "exit_code": payload.get("exit_code"),
            "error":     str(payload.get("error", ""))[:1500],
            "hint":      "Retry from the AI Paper Trader page; if it recurs, "
                         "check api-server logs for the full traceback.",
        },
    }
    _kv_set(_SESSION_ERROR_KEY, entry)
    _kv_set(_SESSION_STATE_KEY, "ERROR")
    return {"ok": True, "recorded": entry}


def get_session_status() -> Dict[str, Any]:
    """
    Return a JSON-safe status dict for the /phase20/daily-session endpoint.
    """
    today      = _today_ist()
    init_date  = _kv_get(_SESSION_DATE_KEY)
    init_at    = _kv_get(_SESSION_TS_KEY)
    init_state = _kv_get(_SESSION_STATE_KEY, "UNKNOWN")
    last_error = _kv_get(_SESSION_ERROR_KEY)

    initialized_today = init_date == today

    # Today's recovery stamp (set when a failed init later succeeded and the
    # SESSION_INIT_RECOVERED notice was emitted). Only surfaced while the
    # session is INITIALISED today — never for other days or states.
    recovered_at = None
    rec = _kv_get(_SESSION_RECOVERED_KEY)
    if (isinstance(rec, dict) and rec.get("date") == today
            and initialized_today and init_state == "INITIALISED"):
        recovered_at = rec.get("at")

    # Market state so the UI can distinguish "not initialised because the
    # market is closed" (expected) from a real initialisation failure.
    mstate = "UNKNOWN"
    try:
        from market_hours import market_state
        mstate = market_state()
    except Exception:
        pass

    # Phase 20 settings
    settings: Dict[str, Any] = {}
    try:
        from phase20_store import get_settings
        settings = get_settings()
    except Exception:
        pass

    # Phase 11 capital config
    capital_cfg: Dict[str, Any] = {}
    try:
        from phase11_autonomous import get_capital_config
        capital_cfg = get_capital_config()
    except Exception:
        pass

    return {
        "today":               today,
        "initialized_today":   initialized_today,
        "last_init_date":      init_date,
        "last_init_at":        init_at,
        "session_state":       init_state if initialized_today else "NOT_INITIALIZED",
        "market_state":        mstate,
        "last_error":          last_error if (initialized_today and init_state == "ERROR") or not initialized_today else None,
        "recovered_at":        recovered_at,
        "auto_scan_enabled":   settings.get("auto_scan_enabled",  True),
        "auto_paper_entries":  settings.get("auto_paper_entries", False),
        "auto_paper_exits":    settings.get("auto_paper_exits",   True),
        "capital_mode":        capital_cfg.get("capital_mode",        "A"),
        "capital_mode_label":  capital_cfg.get("mode_label",          "Evaluation (fixed capital)"),
        "starting_capital":    capital_cfg.get("starting_capital",    50_000.0),
        "topup_threshold":     capital_cfg.get("topup_threshold",     10_000.0),
        "paper_only":          True,
        "advisory_only":       True,
        "no_live_orders":      True,
    }
