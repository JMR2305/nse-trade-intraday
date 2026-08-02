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

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_framework.base_agent import BaseAgent


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


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
        """Collect, normalise, and return the ResearchSnapshot payload."""
        start_ms = time.monotonic() * 1000

        events = _safe(self._load_events) or {}
        macro  = _safe(self._load_macro)  or {}
        lab    = _safe(self._load_research_lab) or {}

        payload = self._normalise(events, macro, lab)
        payload["collection_latency_ms"] = round(
            (time.monotonic() * 1000) - start_ms, 1
        )

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
