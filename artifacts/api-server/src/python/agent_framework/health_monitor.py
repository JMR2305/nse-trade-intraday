"""
health_monitor.py — Phase 10A
Computes health scores, detects stalled agents, and generates
advisory alerts for the Supervisor.

SAFETY:
- Read-only inspection of AgentRecord state.
- Advisory alerts ONLY — NEVER auto-restarts agents.
- Never modifies trading state, orders, portfolio, or strategy.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import AgentRecord, AgentState, HealthStatus, SEV_CRITICAL, SEV_WARNING, SEV_INFO
from .heartbeat_service import HeartbeatService


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class HealthMonitor:
    """
    Computes a 0–100 health score for each agent and detects problems.

    Scoring weights:
        State          40 pts  (RUNNING/IDLE=40, BUSY=35, PAUSED=25, WARNING=10, ERROR/STOPPED=0)
        Heartbeat      30 pts  (OK=30, LATE=20, MISSED=5, STALLED/NEVER=0)
        Error rate     20 pts  (derived from queue_depth and processing_time)
        Activity       10 pts  (has published at least one snapshot)
    """

    def __init__(self) -> None:
        self._hb = HeartbeatService()

    # ── Score ─────────────────────────────────────────────────────────────────

    def score(self, record: AgentRecord) -> float:
        state_pts  = self._state_score(record.state)
        hb_status, _ = self._hb.check(
            record.agent_id, record.last_heartbeat, record.heartbeat_interval_s
        )
        hb_pts     = self._hb_score(hb_status)
        error_pts  = self._error_score(record)
        activity_pts = 10 if record.snapshots_published > 0 else 0

        return min(100.0, max(0.0, state_pts + hb_pts + error_pts + activity_pts))

    @staticmethod
    def _state_score(state: AgentState) -> float:
        return {
            AgentState.RUNNING:      40.0,
            AgentState.IDLE:         40.0,
            AgentState.BUSY:         35.0,
            AgentState.PAUSED:       25.0,
            AgentState.WARNING:      10.0,
            AgentState.ERROR:         0.0,
            AgentState.STOPPED:       0.0,
            AgentState.INITIALIZING: 20.0,
            AgentState.STARTING:     20.0,
        }.get(state, 0.0)

    @staticmethod
    def _hb_score(status: str) -> float:
        return {"OK": 30.0, "LATE": 20.0, "MISSED": 5.0, "STALLED": 0.0, "NEVER": 0.0}.get(status, 0.0)

    @staticmethod
    def _error_score(record: AgentRecord) -> float:
        # 20 pts when queue is empty and processing time is reasonable
        if record.processing_time_ms < 5_000 and record.queue_depth == 0:
            return 20.0
        if record.processing_time_ms < 10_000:
            return 10.0
        return 0.0

    # ── Health status ─────────────────────────────────────────────────────────

    def health_status(self, score: float) -> HealthStatus:
        if score >= 70:
            return HealthStatus.HEALTHY
        if score >= 40:
            return HealthStatus.DEGRADED
        if score > 0:
            return HealthStatus.CRITICAL
        return HealthStatus.OFFLINE

    # ── Update record ─────────────────────────────────────────────────────────

    def update_record(self, record: AgentRecord) -> float:
        """Recompute and store health_score on the record. Returns new score."""
        s = self.score(record)
        record.health_score = s
        return s

    # ── Advisory alerts ───────────────────────────────────────────────────────
    # NEVER auto-restarts. Recommendations only.

    def advisory_alerts(self, records: List[AgentRecord]) -> List[Dict[str, Any]]:
        alerts = []
        for r in records:
            self.update_record(r)
            hb_status, elapsed = self._hb.check(
                r.agent_id, r.last_heartbeat, r.heartbeat_interval_s
            )

            # Stalled agent
            if hb_status == "STALLED":
                alerts.append({
                    "agent_id":   r.agent_id,
                    "name":       r.name,
                    "severity":   SEV_CRITICAL,
                    "code":       "AGENT_STALLED",
                    "title":      f"Agent stalled: {r.name}",
                    "body":       (
                        f"No heartbeat for {elapsed:.0f}s "
                        f"(interval: {r.heartbeat_interval_s}s). "
                        "Operator action required. DO NOT auto-restart."
                    ),
                    "recommendation": "Investigate and restart manually if needed.",
                    "generated_at":   _now_iso(),
                    "auto_action":    None,   # NEVER auto-restart
                })

            # Missed heartbeat
            elif hb_status == "MISSED":
                alerts.append({
                    "agent_id":   r.agent_id,
                    "name":       r.name,
                    "severity":   SEV_WARNING,
                    "code":       "HEARTBEAT_MISSED",
                    "title":      f"Missed heartbeat: {r.name}",
                    "body":       f"No heartbeat for {elapsed:.0f}s.",
                    "recommendation": "Monitor closely. Restart manually if condition persists.",
                    "generated_at":   _now_iso(),
                    "auto_action":    None,
                })

            # Error state
            if r.state == AgentState.ERROR:
                alerts.append({
                    "agent_id":   r.agent_id,
                    "name":       r.name,
                    "severity":   SEV_CRITICAL,
                    "code":       "AGENT_ERROR",
                    "title":      f"Agent in ERROR state: {r.name}",
                    "body":       r.state_reason,
                    "recommendation": "Review logs and restart manually.",
                    "generated_at":   _now_iso(),
                    "auto_action":    None,
                })

            # Warning state
            elif r.state == AgentState.WARNING:
                alerts.append({
                    "agent_id":   r.agent_id,
                    "name":       r.name,
                    "severity":   SEV_WARNING,
                    "code":       "AGENT_WARNING",
                    "title":      f"Agent warning: {r.name}",
                    "body":       r.state_reason,
                    "recommendation": "Investigate warning condition.",
                    "generated_at":   _now_iso(),
                    "auto_action":    None,
                })

            # Low health score
            if r.health_score < 40 and r.state not in (AgentState.ERROR, AgentState.STOPPED):
                alerts.append({
                    "agent_id":   r.agent_id,
                    "name":       r.name,
                    "severity":   SEV_WARNING,
                    "code":       "LOW_HEALTH_SCORE",
                    "title":      f"Low health score: {r.name} ({r.health_score:.0f}/100)",
                    "body":       "Agent health is below acceptable threshold.",
                    "recommendation": "Investigate agent logs and metrics.",
                    "generated_at":   _now_iso(),
                    "auto_action":    None,
                })

        return alerts

    # ── Overall system health ─────────────────────────────────────────────────

    def overall_health(self, records: List[AgentRecord]) -> Dict[str, Any]:
        if not records:
            return {
                "status": HealthStatus.UNKNOWN.value,
                "score":  0.0,
                "available": False,
            }

        scores = [self.score(r) for r in records]
        avg    = sum(scores) / len(scores)
        status = self.health_status(avg)

        critical = sum(1 for r in records if r.state == AgentState.ERROR)
        warning  = sum(1 for r in records if r.state == AgentState.WARNING)

        return {
            "status":          status.value,
            "score":           round(avg, 1),
            "critical_agents": critical,
            "warning_agents":  warning,
            "available":       True,
        }
