"""
supervisor.py — Phase 10A
Supervisor Agent implementation.

Responsibilities:
  - Monitor all registered agents via AgentRegistry
  - Track heartbeats via HeartbeatService
  - Compute health scores via HealthMonitor
  - Generate advisory alerts (NEVER auto-restart)
  - Expose get_supervisor_snapshot() for downstream consumers

READ-ONLY · ADVISORY-ONLY
The Supervisor MUST NEVER restart agents automatically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_framework.agent_registry import AgentRegistry
from agent_framework.health_monitor import HealthMonitor
from agent_framework.heartbeat_service import HeartbeatService
from agent_framework.metrics import FrameworkMetrics, ScalabilityEstimator
from agent_framework.models import AgentState, HealthStatus
from agent_framework.snapshot_bus import SnapshotBus


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SupervisorAgent:
    """
    Read-only supervisor that observes the AgentRegistry and reports.
    Does not extend BaseAgent (it is the overseer, not a peer agent).

    NEVER issues auto-restart recommendations as actions —
    all output is advisory text for human operators.
    """

    def __init__(self) -> None:
        self._registry = AgentRegistry.instance()
        self._monitor  = HealthMonitor()
        self._hb_svc   = HeartbeatService()
        self._bus      = SnapshotBus.instance()

    # ── Core snapshot ─────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """
        Build the full supervisor snapshot.
        Reads AgentRegistry + SnapshotBus — zero trading state mutations.
        """
        records = self._registry.all()

        # Update health scores on all records (read-only operation)
        for r in records:
            self._monitor.update_record(r)

        overall   = self._monitor.overall_health(records)
        alerts    = self._monitor.advisory_alerts(records)
        hb_summary = self._hb_svc.summary(records)
        fw_metrics = FrameworkMetrics.aggregate(records)
        reg_summary = self._registry.summary()

        # Bus statistics
        bus_stats = self._bus.stats()

        # Determine system capacity
        current_symbols = 0
        md_env = self._bus.latest("market_data")
        if md_env:
            current_symbols = md_env.payload.get("symbols_count", 0)
        scalability = ScalabilityEstimator.estimate(
            records,
            current_symbols=current_symbols,
        )

        return {
            "available":        True,
            "advisory_only":    True,
            "read_only":        True,
            "overall_health":   overall,
            "agent_summary":    reg_summary,
            "framework_metrics": fw_metrics,
            "heartbeat_summary": hb_summary,
            "alerts":           alerts,
            "alert_count":      len(alerts),
            "critical_count":   sum(1 for a in alerts if a["severity"] == "CRITICAL"),
            "warning_count":    sum(1 for a in alerts if a["severity"] == "WARNING"),
            "snapshot_bus":     bus_stats,
            "scalability":      scalability,
            "generated_at":     _now_iso(),
        }

    # ── Agent list ────────────────────────────────────────────────────────────

    def agent_list(self) -> List[Dict[str, Any]]:
        records = self._registry.all()
        result  = []
        for r in records:
            self._monitor.update_record(r)
            hb_status, elapsed = self._hb_svc.check(
                r.agent_id, r.last_heartbeat, r.heartbeat_interval_s
            )
            d = r.to_dict()
            d["heartbeat_status"] = hb_status
            d["heartbeat_elapsed_s"] = round(elapsed, 1) if elapsed >= 0 else None
            d["health_status"] = self._monitor.health_status(r.health_score).value
            result.append(d)
        return result

    # ── Agent detail ──────────────────────────────────────────────────────────

    def agent_detail(self, agent_id: str) -> Optional[Dict[str, Any]]:
        r = self._registry.get(agent_id)
        if not r:
            return None
        self._monitor.update_record(r)
        hb_status, elapsed = self._hb_svc.check(
            r.agent_id, r.last_heartbeat, r.heartbeat_interval_s
        )
        d = r.to_dict()
        d["heartbeat_status"]    = hb_status
        d["heartbeat_elapsed_s"] = round(elapsed, 1) if elapsed >= 0 else None
        d["health_status"]       = self._monitor.health_status(r.health_score).value
        d["allowed_transitions"] = [
            s.value for s in {
                AgentState.RUNNING, AgentState.BUSY, AgentState.IDLE,
                AgentState.PAUSED, AgentState.WARNING, AgentState.ERROR, AgentState.STOPPED
            } if s != r.state
        ]

        # Latest snapshot from bus for this agent
        env = self._bus.latest(agent_id)
        d["latest_snapshot_ts"] = env.published_at if env else None
        d["latest_snapshot_seq"] = env.sequence if env else None

        return d

    # ── Alerts ────────────────────────────────────────────────────────────────

    def alerts(self) -> Dict[str, Any]:
        records = self._registry.all()
        alert_list = self._monitor.advisory_alerts(records)
        return {
            "available":      True,
            "advisory_only":  True,
            "alert_count":    len(alert_list),
            "critical_count": sum(1 for a in alert_list if a["severity"] == "CRITICAL"),
            "warning_count":  sum(1 for a in alert_list if a["severity"] == "WARNING"),
            "alerts":         alert_list,
            "generated_at":   _now_iso(),
        }


# Module-level singleton
_supervisor: Optional[SupervisorAgent] = None


def get_supervisor() -> SupervisorAgent:
    global _supervisor
    if _supervisor is None:
        _supervisor = SupervisorAgent()
    return _supervisor
