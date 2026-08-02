"""
models.py — Phase 10A
Pydantic models, enums and helpers for the Agent Framework.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_display() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


# ── Agent State Machine ────────────────────────────────────────────────────────

class AgentState(str, Enum):
    """
    Agent lifecycle states. Every transition records a timestamp and reason.

    Valid transitions:
        INITIALIZING → STARTING → RUNNING ↔ BUSY ↔ IDLE
        Any active state → PAUSED → RUNNING/IDLE
        Any state → WARNING (auto-clears to last active state)
        Any state → ERROR → STOPPED
        Any active state → STOPPED
    """
    INITIALIZING = "INITIALIZING"
    STARTING     = "STARTING"
    RUNNING      = "RUNNING"
    BUSY         = "BUSY"
    IDLE         = "IDLE"
    PAUSED       = "PAUSED"
    WARNING      = "WARNING"
    ERROR        = "ERROR"
    STOPPED      = "STOPPED"

    @property
    def is_active(self) -> bool:
        return self in (
            AgentState.RUNNING, AgentState.BUSY,
            AgentState.IDLE, AgentState.WARNING,
        )

    @property
    def is_healthy(self) -> bool:
        return self in (AgentState.RUNNING, AgentState.BUSY, AgentState.IDLE)


class HealthStatus(str, Enum):
    HEALTHY  = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    UNKNOWN  = "UNKNOWN"
    OFFLINE  = "OFFLINE"


# ── Data classes (plain dicts — no Pydantic dependency needed) ─────────────────

class AgentRecord:
    """
    Registry entry for one agent. Mutable — fields updated in-place.
    All timestamps are ISO-8601 UTC strings.
    """
    __slots__ = (
        "agent_id", "name", "version", "owner",
        "state", "state_reason", "state_changed_at",
        "priority", "dependencies", "capabilities",
        "current_task",
        "last_heartbeat", "heartbeat_interval_s",
        "health_score",
        "queue_depth", "processing_time_ms",
        "snapshots_published", "snapshots_consumed",
        "registered_at", "started_at",
    )

    def __init__(
        self,
        agent_id: str,
        name: str,
        version: str = "1.0.0",
        owner: str = "ApexQuant AI",
        priority: int = 5,
        dependencies: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
        heartbeat_interval_s: float = 30.0,
    ) -> None:
        now = _now_iso()
        self.agent_id             = agent_id
        self.name                 = name
        self.version              = version
        self.owner                = owner
        self.state                = AgentState.INITIALIZING
        self.state_reason         = "Registered"
        self.state_changed_at     = now
        self.priority             = priority
        self.dependencies         = dependencies or []
        self.capabilities         = capabilities or []
        self.current_task: Optional[str] = None
        self.last_heartbeat: Optional[str] = None
        self.heartbeat_interval_s = heartbeat_interval_s
        self.health_score: float  = 0.0
        self.queue_depth: int     = 0
        self.processing_time_ms: float = 0.0
        self.snapshots_published: int  = 0
        self.snapshots_consumed: int   = 0
        self.registered_at        = now
        self.started_at: Optional[str] = None

    def transition(self, new_state: AgentState, reason: str = "") -> None:
        self.state           = new_state
        self.state_reason    = reason or new_state.value
        self.state_changed_at = _now_iso()
        if new_state == AgentState.STARTING:
            self.started_at = self.state_changed_at

    def beat(self) -> None:
        self.last_heartbeat = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id":             self.agent_id,
            "name":                 self.name,
            "version":              self.version,
            "owner":                self.owner,
            "state":                self.state.value,
            "state_reason":         self.state_reason,
            "state_changed_at":     self.state_changed_at,
            "priority":             self.priority,
            "dependencies":         self.dependencies,
            "capabilities":         self.capabilities,
            "current_task":         self.current_task,
            "last_heartbeat":       self.last_heartbeat,
            "heartbeat_interval_s": self.heartbeat_interval_s,
            "health_score":         round(self.health_score, 1),
            "queue_depth":          self.queue_depth,
            "processing_time_ms":   round(self.processing_time_ms, 1),
            "snapshots_published":  self.snapshots_published,
            "snapshots_consumed":   self.snapshots_consumed,
            "registered_at":        self.registered_at,
            "started_at":           self.started_at,
        }


class SnapshotEnvelope:
    """
    Wrapper around a snapshot payload published to the SnapshotBus.
    Contains metadata: publisher, topic, timestamp, sequence number.
    """
    __slots__ = ("topic", "publisher_id", "published_at", "sequence", "payload")

    def __init__(
        self,
        topic: str,
        publisher_id: str,
        payload: Dict[str, Any],
        sequence: int = 0,
    ) -> None:
        self.topic        = topic
        self.publisher_id = publisher_id
        self.published_at = _now_iso()
        self.sequence     = sequence
        self.payload      = payload

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic":        self.topic,
            "publisher_id": self.publisher_id,
            "published_at": self.published_at,
            "sequence":     self.sequence,
            "payload":      self.payload,
        }


# ── Severity constants ─────────────────────────────────────────────────────────

SEV_CRITICAL = "CRITICAL"
SEV_WARNING  = "WARNING"
SEV_INFO     = "INFO"
