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
        try:
            md_env = self._bus.latest("market_data")
            if md_env:
                current_symbols = md_env.payload.get("symbols_count", 0)
        except Exception:
            pass  # bus read failure handled in pipeline_health loop below
        scalability = ScalabilityEstimator.estimate(
            records,
            current_symbols=current_symbols,
        )

        # ── V4.3 Pipeline health — topic age and dependency violations ──────────
        pipeline_topics = [
            "market_data", "research", "market_intelligence",
            "monitoring", "strategy", "risk", "ai_decision",
            "execution",
        ]
        pipeline_health: Dict[str, Any] = {}
        for topic in pipeline_topics:
            # Distinguish three states per topic:
            #
            # 1. latest() returns an envelope  → available=True, never_published=False
            # 2. latest() returns None          → available=False, never_published=True
            #    (topic has never published in this process instance)
            # 3. latest() raises an exception   → available=False, never_published=False,
            #    error=True (bus-read failure; unknown state — NOT the same as
            #    never_published; must not contribute to cold-start suppression)
            env = None
            try:
                env = self._bus.latest(topic)
            except Exception as _exc:
                # Bus read failure: classify as error, not as never_published.
                # This prevents a transient bus fault from silently setting
                # pipeline_cold_start=True and suppressing violation banners.
                pipeline_health[topic] = {
                    "available":      False,
                    "age_seconds":    None,
                    "stale":          False,
                    "never_published": False,  # unknown — do not treat as cold-start
                    "error":          True,
                }
                continue

            if env is not None:
                # Topic has published at least once in this process instance.
                try:
                    from datetime import timezone as _tz
                    age_s = round(
                        (datetime.now(_tz.utc) - env.received_at).total_seconds()
                    )
                except Exception:
                    age_s = None
                pipeline_health[topic] = {
                    "available":      True,
                    "age_seconds":    age_s,
                    "stale":          age_s is not None and age_s > 600,
                    "never_published": False,
                    "error":          False,
                }
            else:
                # latest() returned None: topic has genuinely never published
                # in this bus singleton instance.  Expected during cold start;
                # NOT the same as stale data.
                pipeline_health[topic] = {
                    "available":      False,
                    "age_seconds":    None,
                    "stale":          False,   # not stale — just not yet published
                    "never_published": True,
                    "error":          False,
                }

        # Cold-start flag: True only when EVERY topic has never_published=True
        # (no errors, no data at all).  A single error or published topic prevents
        # cold-start mode so operators are not left without pipeline health signals.
        pipeline_cold_start: bool = all(
            h.get("never_published", False) and not h.get("error", False)
            for h in pipeline_health.values()
        )

        # Dependency violation check.
        #
        # The current SnapshotBus holds envelopes for the process lifetime and
        # provides no eviction path.  Therefore in normal operation a topic can
        # only be in one of two states reachable via bus.latest():
        #   • available=True  (envelope present)
        #   • available=False, never_published=True  (envelope absent)
        #
        # The third state (available=False, never_published=False) arises only
        # from bus-read exceptions (error=True above).
        #
        # Violation type 1: child has data but upstream is unavailable.
        #   This is always a real violation — something produced downstream
        #   results without valid upstream input.
        #
        # Violation type 2 (error path): child is in error state (available=False,
        #   never_published=False, error=True) while parent is healthy.
        #   Surface this so operators know a bus-read failure is blocking a
        #   downstream topic.
        #
        # No violation for never_published children: during initialization the
        #   downstream agents simply haven't run yet — this is expected and must
        #   not alarm operators every time the server restarts.
        _deps = {
            "market_intelligence": "market_data",
            "monitoring":          "market_intelligence",
            "strategy":            "monitoring",
            "risk":                "strategy",
            "ai_decision":         "risk",
            "execution":           "ai_decision",
        }
        dependency_violations: List[str] = []
        for child, parent in _deps.items():
            child_h  = pipeline_health.get(child, {})
            parent_h = pipeline_health.get(parent, {})
            if child_h.get("available") and not parent_h.get("available"):
                # Type 1: child has data but upstream is unavailable
                dependency_violations.append(
                    f"{child} has data but upstream {parent} is unavailable"
                )
            elif (not child_h.get("available")
                  and child_h.get("error")           # bus-read failure for child
                  and parent_h.get("available")
                  and not parent_h.get("stale")):
                # Type 2 (error path): child bus-read failed; parent is healthy
                dependency_violations.append(
                    f"{child} is unavailable (bus read error) despite {parent} being healthy"
                )

        # Stale topics — exclude never-published topics so cold-start does not
        # flood the recommendations with meaningless "stale" warnings.
        stale_topics = [
            t for t, h in pipeline_health.items()
            if h.get("stale") and not h.get("never_published")
        ]

        # Structured operator recommendations from framework health
        recommendations: List[Dict[str, Any]] = []
        error_agents = int(reg_summary.get("error", 0))
        if error_agents > 0:
            recommendations.append({
                "priority": "HIGH",
                "category": "AGENT_HEALTH",
                "message":  f"{error_agents} agent(s) are in ERROR state. Review agent logs.",
                "action":   "Check agent error details in the Operations Centre agent cards.",
            })
        if dependency_violations:
            recommendations.append({
                "priority": "MEDIUM",
                "category": "DEPENDENCY_VIOLATION",
                "message":  f"{len(dependency_violations)} pipeline dependency violation(s) detected.",
                "action":   "; ".join(dependency_violations),
            })
        if stale_topics:
            recommendations.append({
                "priority": "MEDIUM",
                "category": "STALE_DATA",
                "message":  f"Stale pipeline data for: {', '.join(stale_topics)}.",
                "action":   "Trigger a fresh scan or verify the data provider connection.",
            })
        alert_count = len(alerts)
        critical_count = sum(1 for a in alerts if a.get("severity") == "CRITICAL")
        if critical_count > 0:
            recommendations.append({
                "priority": "HIGH",
                "category": "ALERTS",
                "message":  f"{critical_count} CRITICAL alert(s) require immediate attention.",
                "action":   "Review the Supervisor alerts list and resolve each CRITICAL item.",
            })

        return {
            "available":        True,
            "advisory_only":    True,
            "read_only":        True,
            "overall_health":   overall,
            "agent_summary":    reg_summary,
            "framework_metrics": fw_metrics,
            "heartbeat_summary": hb_summary,
            "alerts":           alerts,
            "alert_count":      alert_count,
            "critical_count":   critical_count,
            "warning_count":    sum(1 for a in alerts if a["severity"] == "WARNING"),
            "snapshot_bus":     bus_stats,
            "scalability":      scalability,
            # V4.3 additions
            "pipeline_health":          pipeline_health,
            "pipeline_cold_start":      pipeline_cold_start,
            "dependency_violations":    dependency_violations,
            "stale_topics":             stale_topics,
            "recommendations":          recommendations,
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
