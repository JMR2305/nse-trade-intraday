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

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# ── KV keys ────────────────────────────────────────────────────────────────────

_SESSION_DATE_KEY  = "daily_session_date"           # "YYYY-MM-DD" of last init
_SESSION_TS_KEY    = "daily_session_initialized_at"  # ISO timestamp
_SESSION_STATE_KEY = "daily_session_state"          # INITIALISED | ERROR

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
    _kv_set(_SESSION_DATE_KEY,  today)
    _kv_set(_SESSION_TS_KEY,    now)
    _kv_set(_SESSION_STATE_KEY, "INITIALISED")
    result["completed_at"] = now

    # Determine overall success
    errors = [k for k, v in result["steps"].items()
              if isinstance(v, str) and v.startswith("ERROR")]
    result["success"] = len(errors) == 0
    result["errors"]  = errors

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


# ── Status endpoint helper ─────────────────────────────────────────────────────

def get_session_status() -> Dict[str, Any]:
    """
    Return a JSON-safe status dict for the /phase20/daily-session endpoint.
    """
    today      = _today_ist()
    init_date  = _kv_get(_SESSION_DATE_KEY)
    init_at    = _kv_get(_SESSION_TS_KEY)
    init_state = _kv_get(_SESSION_STATE_KEY, "UNKNOWN")

    initialized_today = init_date == today

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
