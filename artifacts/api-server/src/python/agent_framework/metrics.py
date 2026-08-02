"""
metrics.py — Phase 10A
Performance metrics for individual agents and the framework overall.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class AgentMetrics:
    """
    Per-agent performance metrics collected during a session.
    All times are in milliseconds unless suffixed otherwise.
    """
    agent_id:                   str
    startup_time_ms:            float = 0.0
    heartbeat_latency_ms:       float = 0.0   # avg time to send heartbeat
    snapshot_publish_latency_ms: float = 0.0  # avg time to publish snapshot
    snapshot_consume_latency_ms: float = 0.0  # avg time subscriber is notified
    memory_mb:                  float = 0.0
    cpu_pct:                    float = 0.0
    queue_depth:                int   = 0
    monitored_symbols:          int   = 0
    avg_scan_interval_s:        float = 0.0
    total_tasks_processed:      int   = 0
    total_errors:               int   = 0
    uptime_s:                   float = 0.0
    last_updated:               str   = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Round floats for clean JSON
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = round(v, 2)
        return d


class FrameworkMetrics:
    """
    Aggregated metrics across all registered agents.
    Derived purely from AgentRecord fields — no new computation.
    """

    @staticmethod
    def aggregate(agent_records: List[Any]) -> Dict[str, Any]:
        """
        Build framework-level metrics from a list of AgentRecord objects.
        """
        if not agent_records:
            return {
                "agent_count":           0,
                "active_agents":         0,
                "healthy_agents":        0,
                "warning_agents":        0,
                "error_agents":          0,
                "stopped_agents":        0,
                "total_snapshots_published": 0,
                "total_snapshots_consumed":  0,
                "avg_health_score":      0.0,
                "total_queue_depth":     0,
                "avg_processing_time_ms": 0.0,
                "generated_at":          _now_iso(),
            }

        from .models import AgentState  # local import avoids circular
        active   = [a for a in agent_records if a.state.is_active]
        healthy  = [a for a in agent_records if a.state.is_healthy]
        warning  = [a for a in agent_records if a.state == AgentState.WARNING]
        errors   = [a for a in agent_records if a.state == AgentState.ERROR]
        stopped  = [a for a in agent_records if a.state == AgentState.STOPPED]

        scores = [a.health_score for a in agent_records if a.health_score > 0]

        return {
            "agent_count":               len(agent_records),
            "active_agents":             len(active),
            "healthy_agents":            len(healthy),
            "warning_agents":            len(warning),
            "error_agents":              len(errors),
            "stopped_agents":            len(stopped),
            "total_snapshots_published": sum(a.snapshots_published for a in agent_records),
            "total_snapshots_consumed":  sum(a.snapshots_consumed  for a in agent_records),
            "avg_health_score":          round(sum(scores) / len(scores), 1) if scores else 0.0,
            "total_queue_depth":         sum(a.queue_depth for a in agent_records),
            "avg_processing_time_ms":    round(
                sum(a.processing_time_ms for a in agent_records) / len(agent_records), 1
            ),
            "generated_at":              _now_iso(),
        }


class ScalabilityEstimator:
    """
    Advisory-only capacity estimates based on current agent configuration.
    NEVER modifies any system state.
    """

    # Empirical baselines (conservative)
    _SYMBOLS_PER_AGENT_SAFE     = 100
    _SYMBOLS_PER_AGENT_MAX      = 200
    _SCAN_INTERVAL_BASE_S       = 90.0
    _SCAN_INTERVAL_PER_SYMBOL   = 0.05   # additional seconds per symbol

    @classmethod
    def estimate(
        cls,
        agent_records: List[Any],
        current_symbols: int = 0,
        current_scan_interval_s: float = 90.0,
    ) -> Dict[str, Any]:
        agent_count = max(1, len(agent_records))
        safe_capacity  = cls._SYMBOLS_PER_AGENT_SAFE  * agent_count
        max_capacity   = cls._SYMBOLS_PER_AGENT_MAX   * agent_count

        # Recommended scan interval grows with symbol count
        rec_interval = cls._SCAN_INTERVAL_BASE_S + (current_symbols * cls._SCAN_INTERVAL_PER_SYMBOL)

        future_agents_supported = max(0, 10 - agent_count)  # platform cap 10 agents

        return {
            "current_monitored_symbols":   current_symbols,
            "safe_capacity_symbols":       safe_capacity,
            "estimated_max_capacity":      max_capacity,
            "current_scan_interval_s":     round(current_scan_interval_s, 1),
            "recommended_scan_interval_s": round(rec_interval, 1),
            "current_agent_count":         agent_count,
            "future_agents_supported":     future_agents_supported,
            "utilisation_pct":             round((current_symbols / safe_capacity) * 100, 1) if safe_capacity > 0 else 0.0,
            "advisory_only":               True,
        }
