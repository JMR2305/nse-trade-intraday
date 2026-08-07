"""
agent.py — Phase 10A
Research Agent.

Responsibilities:
  - Collect corporate announcements, earnings, economic calendar,
    macro events, sector news, company actions from existing research feeds
  - Normalise into a unified ResearchSnapshot
  - Publish to SnapshotBus topic "research"
  - NO recommendations. NO order placement.

Data sources (all read-only from existing infrastructure):
  - event_intelligence.shared_services
  - macro_intelligence.shared_services
  - research_lab.shared_services (if available)
  - explainable_ai (if available)

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agent_framework.base_agent import BaseAgent


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Module-level telemetry tracking (per-cycle, reset each execute_task) ──────
_last_failure_at:   Optional[str] = None
_last_success_at:   Optional[str] = None
_last_failure_reason: str = ""
_last_recovery_action: str = ""

# V4.3 per-cycle counters — reset at the top of execute_task().
_timeout_count:     int = 0  # loaders that exceeded the cycle deadline
_retry_count:       int = 0  # unused in concurrent mode; kept for KV compat
_loaders_failed:    int = 0  # loaders that raised or timed out
_loaders_succeeded: int = 0  # loaders that returned a non-None result

# Total wall-clock budget for ONE collection cycle (all loaders combined).
# Running loaders concurrently means the worst-case cycle duration equals this
# value, not N × this value (which was the bug in the sequential approach).
_CYCLE_DEADLINE_S: int = 30

# ── Per-source in-flight guards ───────────────────────────────────────────────
# Track the live thread for each loader slot so that if a previous cycle's
# thread is still running (hung I/O) we do NOT start a new thread for that
# source.  This bounds outstanding threads to at most one per source regardless
# of how many cycles elapse while I/O is stuck.
#
# Index: 0 = event_intelligence, 1 = macro_intelligence, 2 = research_lab.
# Protected by _GUARDS_LOCK to allow safe reads from the scheduler thread.
_GUARD_COUNT = 3  # must equal len(loader_specs) in execute_task
_active_loader_threads: List[Optional[threading.Thread]] = [None] * _GUARD_COUNT
_GUARDS_LOCK = threading.Lock()


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _run_loaders_concurrent(
    loaders: List[Tuple[Any, str]],
    cycle_deadline_s: int = _CYCLE_DEADLINE_S,
) -> List[Dict[str, Any]]:
    """
    Run all loaders simultaneously in separate daemon threads, sharing a
    single monotonic deadline for the entire collection cycle.

    Design — deadline:
      • The cycle deadline is monotonic: every ``thread.join(timeout=…)`` call
        uses ``max(0, deadline - time.monotonic())`` so the total wait across
        all loaders is bounded by ``cycle_deadline_s`` regardless of how many
        loaders there are.  Three loaders sharing a 30-second deadline take at
        most 30 seconds, not 90 seconds.

    Design — thread lifecycle:
      • Each loader runs in a ``threading.Thread`` with ``daemon=True``.
        Daemon threads do not prevent the Python process from exiting.
        CPython has no mechanism to interrupt blocking I/O, so a loader whose
        network call is still in progress when the deadline fires is left
        running in the background.  It will eventually finish (or be abandoned
        at process exit) and then become garbage-collected.

    Design — bounded outstanding threads (in-flight guards):
      • The module-level ``_active_loader_threads`` list tracks the most
        recently started thread for each loader slot.  Before starting a new
        thread the guard is checked: if the previous thread for that slot is
        still alive, NO new thread is started and the slot is treated as timed
        out for this cycle.  This caps outstanding threads at ONE per source
        regardless of how many cycles elapse while I/O is stuck.
      • The guard is updated under ``_GUARDS_LOCK`` so that reads from the
        scheduler thread are safe.

    Returns a list of results in the same order as *loaders*.
    Failed or timed-out slots return ``{}`` (safe empty-dict default).
    Updates module-level counters for the caller to assess cycle health.
    """
    global _last_failure_at, _last_success_at, _last_failure_reason
    global _last_recovery_action, _timeout_count, _loaders_failed, _loaders_succeeded
    global _active_loader_threads

    n = len(loaders)
    results:    List[Optional[Dict[str, Any]]] = [None] * n
    exceptions: List[Optional[Exception]]      = [None] * n
    done_flags: List[bool]                     = [False] * n

    def runner(idx: int, fn) -> None:
        try:
            results[idx] = fn()
        except Exception as exc:
            exceptions[idx] = exc
        finally:
            done_flags[idx] = True

    deadline = time.monotonic() + cycle_deadline_s

    # ── Start eligible loaders (in-flight guard check) ────────────────────────
    started: List[Optional[threading.Thread]] = [None] * n  # None = skipped
    with _GUARDS_LOCK:
        for i, (fn, label) in enumerate(loaders):
            slot = i if i < _GUARD_COUNT else None
            prev = _active_loader_threads[slot] if slot is not None else None
            if prev is not None and prev.is_alive():
                # Previous cycle's thread is still running — skip this slot.
                # Counted as a timeout below; no new thread started.
                pass
            else:
                t = threading.Thread(
                    target=runner,
                    args=(i, fn),
                    name=f"research-loader-{label}",
                    daemon=True,
                )
                if slot is not None:
                    _active_loader_threads[slot] = t
                started[i] = t
                t.start()

    # ── Distribute the shared deadline across all join() calls ────────────────
    for i, (_, label) in enumerate(loaders):
        t = started[i]
        if t is None:
            # This slot was skipped because the previous thread is still alive.
            _timeout_count += 1
            _loaders_failed += 1
            _last_failure_at = _now_iso()
            _last_failure_reason = (
                f"{label}: previous cycle thread still running — "
                f"skipped to prevent thread accumulation"
            )
            _last_recovery_action = (
                "Research failure mode determines downstream behaviour."
            )
            continue

        remaining = max(0.0, deadline - time.monotonic())
        t.join(timeout=remaining)

        if not done_flags[i]:
            # Thread is still alive after the deadline.
            _timeout_count += 1
            _loaders_failed += 1
            _last_failure_at = _now_iso()
            _last_failure_reason = f"{label}: exceeded {cycle_deadline_s}s cycle deadline"
            _last_recovery_action = (
                "Loader did not complete within the cycle deadline.  "
                "The daemon thread continues until its I/O resolves or the "
                "process exits.  Research failure mode governs downstream behaviour."
            )
        elif exceptions[i] is not None:
            _loaders_failed += 1
            _last_failure_at = _now_iso()
            _last_failure_reason = (
                f"{label}: {type(exceptions[i]).__name__}: {exceptions[i]}"
            )
            _last_recovery_action = (
                "Loader raised an exception.  "
                "Research failure mode governs downstream behaviour."
            )
        elif results[i] is None:
            # Loader returned None — no data available (source unavailable or
            # returned an explicit None).  Treated as a failure for mode-tracking
            # purposes so that all-None cycles correctly trigger MARKET_ONLY /
            # PIPELINE_HALTED, not NORMAL.
            _loaders_failed += 1
            _last_failure_at = _now_iso()
            _last_failure_reason = f"{label}: returned None (no data available)"
            _last_recovery_action = (
                "Loader returned None — source unavailable or no data for this cycle.  "
                "Research failure mode governs downstream behaviour."
            )
        else:
            _loaders_succeeded += 1
            _last_success_at = _now_iso()

    # Write failure summary to KV if any loader failed this cycle.
    if _loaders_failed > 0:
        try:
            from phase20_store import kv_set
            kv_set("research_agent_failure", {
                "last_failure_at":   _last_failure_at,
                "failure_reason":    _last_failure_reason,
                "recovery_action":   _last_recovery_action,
                "last_success_at":   _last_success_at,
                "timeout_count":     _timeout_count,
                "loaders_failed":    _loaders_failed,
                "loaders_succeeded": _loaders_succeeded,
            })
        except Exception:
            pass

    return [r if r is not None else {} for r in results]


class ResearchAgent(BaseAgent):
    """
    Collects research data from existing feeds, normalises it, and
    publishes a unified ResearchSnapshot.

    READ-ONLY: reads from event/macro intelligence modules only.
    ADVISORY-ONLY: publishes snapshots, never places recommendations.
    """

    HEARTBEAT_INTERVAL_S: float = 60.0

    def __init__(self) -> None:
        super().__init__(
            agent_id     = "research-agent",
            name         = "Research Agent",
            version      = "1.0.0",
            owner        = "ApexQuant AI",
            priority     = 2,
            dependencies = [],
            capabilities = [
                "corporate_announcements", "earnings_calendar",
                "economic_calendar", "macro_events",
                "sector_news", "company_actions",
            ],
        )
        self._last_snapshot: Optional[Dict[str, Any]] = None

    @property
    def default_topic(self) -> str:
        return "research"

    def execute_task(self) -> Optional[Dict[str, Any]]:
        """
        Collect, normalise, and return the ResearchSnapshot payload.

        V4.3 — concurrent loader design:
          All three data sources are fetched simultaneously in daemon threads
          sharing a single 30-second wall-clock deadline (_CYCLE_DEADLINE_S).
          This bounds the worst-case cycle to 30 seconds regardless of how many
          sources hang, rather than N × 30 seconds in the former sequential
          approach.  See _run_loaders_concurrent() for the full design notes.
        """
        global _timeout_count, _retry_count, _loaders_failed, _loaders_succeeded
        # Reset all per-cycle counters at the start of each execution so that
        # counts reflect only this cycle's activity, not process-lifetime totals.
        _timeout_count     = 0
        _retry_count       = 0
        _loaders_failed    = 0
        _loaders_succeeded = 0

        _TOTAL_SOURCES = 3
        start_ms = time.monotonic() * 1000

        # Run all three loaders concurrently with a shared cycle deadline.
        loader_specs: List[Tuple[Any, str]] = [
            (self._load_events,       "event_intelligence"),
            (self._load_macro,        "macro_intelligence"),
            (self._load_research_lab, "research_lab"),
        ]
        events, macro, lab = _run_loaders_concurrent(
            loader_specs, cycle_deadline_s=_CYCLE_DEADLINE_S
        )

        payload = self._normalise(events, macro, lab)
        payload["collection_latency_ms"] = round(
            (time.monotonic() * 1000) - start_ms, 1
        )

        # Include failure diagnostics + V4.3 telemetry counters
        payload["last_failure_at"]     = _last_failure_at
        payload["last_failure_reason"] = _last_failure_reason
        payload["last_success_at"]     = _last_success_at or _now_iso()
        payload["recovery_action"]     = _last_recovery_action or "None required"
        payload["timeout_count"]       = _timeout_count
        payload["retry_count"]         = _retry_count
        payload["loaders_succeeded"]   = _loaders_succeeded
        payload["loaders_failed"]      = _loaders_failed

        # V4.3 Research mode computation
        # ─────────────────────────────────────────────────────────────────────
        # NORMAL         — all loaders succeeded (or at least one did).
        # MARKET_ONLY    — some loaders failed; fail_open mode: pipeline
        #                  continues using whatever data was collected.
        # PIPELINE_HALTED — ALL loaders failed and the operator has chosen
        #                  fail_closed: new paper entries are paused until
        #                  research recovers.
        #
        # Rule: only escalate to MARKET_ONLY / PIPELINE_HALTED when every
        # loader exhausted its attempts without returning a result.  A single
        # slow or flaky source is insufficient — that would cause spurious
        # alerts on any transient network hiccup.
        all_loaders_failed = (_loaders_failed >= _TOTAL_SOURCES
                              and _loaders_succeeded == 0)

        research_mode = "NORMAL"
        if all_loaders_failed:
            try:
                from phase20_store import get_settings as _gs
                failure_mode = str((_gs() or {}).get("research_failure_mode", "fail_open"))
            except Exception:
                failure_mode = "fail_open"
            research_mode = (
                "PIPELINE_HALTED" if failure_mode == "fail_closed"
                else "MARKET_ONLY"
            )

        payload["research_mode"] = research_mode

        # Persist research_mode and telemetry to KV so ops_centre and the
        # entry gate can read the current cycle's health without re-running
        # the full agent.
        try:
            from phase20_store import kv_set as _kv_set
            _kv_set("research_agent_mode", {
                "mode":              research_mode,
                "all_loaders_failed": all_loaders_failed,
                "loaders_succeeded": _loaders_succeeded,
                "loaders_failed":    _loaders_failed,
                "timeout_count":     _timeout_count,
                "retry_count":       _retry_count,
                "updated_at":        _now_iso(),
            })
        except Exception:
            pass

        self._last_snapshot = payload
        return payload

    # ── Data collection (all read-only) ───────────────────────────────────────

    @staticmethod
    def _load_events() -> Dict[str, Any]:
        from event_intelligence.shared_services import get_event_intelligence_snapshot
        return get_event_intelligence_snapshot()

    @staticmethod
    def _load_macro() -> Dict[str, Any]:
        from macro_intelligence.shared_services import get_macro_intelligence_snapshot
        return get_macro_intelligence_snapshot()

    @staticmethod
    def _load_research_lab() -> Dict[str, Any]:
        from research_lab.shared_services import get_research_lab_snapshot
        return get_research_lab_snapshot()

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalise(
        self,
        events: Dict[str, Any],
        macro: Dict[str, Any],
        lab: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Corporate announcements
        announcements    = events.get("announcements") or []
        earnings         = events.get("earnings")      or []
        economic_cal     = events.get("economic_calendar") or macro.get("economic_calendar") or []
        macro_events     = macro.get("macro_events")   or []
        sector_news      = events.get("sector_news")   or lab.get("sector_news") or []
        company_actions  = events.get("company_actions") or []

        # Macro context
        rbi_stance       = macro.get("rbi_policy_stance")    or "UNKNOWN"
        macro_regime     = macro.get("macro_regime")          or "UNKNOWN"
        macro_outlook    = macro.get("macro_outlook")         or ""
        global_risk      = macro.get("global_risk_score")     or 0.0

        # Research lab
        active_experiments = lab.get("active_experiments")    or 0
        insights_count     = lab.get("total_insights")        or 0

        return {
            # Metadata
            "agent_id":        "research-agent",
            "agent_name":      "Research Agent",
            "advisory_only":   True,
            "read_only":       True,

            # Corporate announcements
            "announcements":       announcements[:20],
            "announcement_count":  len(announcements),

            # Earnings
            "earnings_events":     earnings[:10],
            "earnings_count":      len(earnings),

            # Economic calendar
            "economic_calendar":   economic_cal[:10],
            "economic_event_count":len(economic_cal),

            # Macro
            "macro_events":        macro_events[:10],
            "macro_event_count":   len(macro_events),
            "rbi_policy_stance":   rbi_stance,
            "macro_regime":        macro_regime,
            "macro_outlook":       macro_outlook[:500] if macro_outlook else "",
            "global_risk_score":   float(global_risk) if global_risk else 0.0,

            # Sector news
            "sector_news":         sector_news[:10],
            "sector_news_count":   len(sector_news),

            # Company actions
            "company_actions":     company_actions[:10],
            "company_action_count":len(company_actions),

            # Research lab
            "active_experiments":  active_experiments,
            "insights_count":      insights_count,

            # Totals
            "total_research_items": (
                len(announcements) + len(earnings) + len(economic_cal) +
                len(macro_events) + len(sector_news) + len(company_actions)
            ),

            # Generated
            "generated_at":        _now_iso(),
        }

    def last_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._last_snapshot
