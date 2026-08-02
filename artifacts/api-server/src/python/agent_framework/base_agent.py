"""
base_agent.py — Phase 10A
Abstract BaseAgent — the root class for all ApexQuant AI agents.

Every agent MUST inherit from BaseAgent.
Every agent operates in READ-ONLY and ADVISORY-ONLY mode.
No agent may place orders, modify portfolio, strategy, AI, or execution state.

Lifecycle:
    __init__() → register() → start() → [run loop] → stop()
"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from .models import AgentRecord, AgentState, SnapshotEnvelope
from .agent_registry import AgentRegistry
from .lifecycle_manager import LifecycleManager
from .snapshot_bus import SnapshotBus
from .heartbeat_service import HeartbeatService
from .health_monitor import HealthMonitor


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BaseAgent(ABC):
    """
    Root class for all ApexQuant AI agents.

    Subclasses must implement:
        execute_task()  — the agent's primary work unit (one invocation per tick)

    Subclasses should call:
        publish(topic, payload)  — to share results via SnapshotBus
        beat()                   — to record heartbeat
    """

    # Heartbeat sent every N seconds
    HEARTBEAT_INTERVAL_S: float = 30.0

    def __init__(
        self,
        agent_id: str,
        name: str,
        version: str = "1.0.0",
        owner: str = "ApexQuant AI",
        priority: int = 5,
        dependencies: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
    ) -> None:
        self._id      = agent_id
        self._name    = name
        self._started = time.monotonic()
        self._lock    = threading.Lock()

        # Infrastructure
        self._registry  = AgentRegistry.instance()
        self._lifecycle = LifecycleManager()
        self._bus       = SnapshotBus.instance()
        self._hb_svc    = HeartbeatService()
        self._monitor   = HealthMonitor()

        # Register
        self._record = AgentRecord(
            agent_id             = agent_id,
            name                 = name,
            version              = version,
            owner                = owner,
            priority             = priority,
            dependencies         = dependencies,
            capabilities         = capabilities,
            heartbeat_interval_s = self.HEARTBEAT_INTERVAL_S,
        )
        self._registry.register(self._record)

        # Task queue (simple FIFO advisory task descriptions)
        self._queue: Deque[str] = deque(maxlen=100)

        # Last heartbeat time (monotonic)
        self._last_hb_time: float = 0.0

    # ── Abstract interface ─────────────────────────────────────────────────────

    @abstractmethod
    def execute_task(self) -> Optional[Dict[str, Any]]:
        """
        The agent's primary work unit.
        Called once per tick. Should be fast (< 5s).
        Return a payload dict to publish to the default topic, or None.
        READ-ONLY. ADVISORY-ONLY.
        """
        ...

    @property
    def default_topic(self) -> str:
        """Override to set the agent's default SnapshotBus topic."""
        return self._id

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> bool:
        ok, msg = self._lifecycle.start(self._record, "Agent starting")
        return ok

    def stop(self, reason: str = "Operator stop") -> bool:
        ok, msg = self._lifecycle.stop(self._record, reason)
        return ok

    def pause(self, reason: str = "Operator pause") -> bool:
        ok, _ = self._lifecycle.pause(self._record, reason)
        return ok

    def resume(self, reason: str = "Operator resume") -> bool:
        ok, _ = self._lifecycle.resume(self._record, reason)
        return ok

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def beat(self) -> None:
        """Record a heartbeat on this agent's registry record."""
        self._record.beat()
        self._last_hb_time = time.monotonic()
        self._monitor.update_record(self._record)

    def maybe_beat(self) -> bool:
        """Send heartbeat if interval has elapsed. Returns True if sent."""
        now = time.monotonic()
        if (now - self._last_hb_time) >= self.HEARTBEAT_INTERVAL_S:
            self.beat()
            return True
        return False

    # ── Snapshot publishing ───────────────────────────────────────────────────

    def publish(
        self,
        payload: Dict[str, Any],
        topic: Optional[str] = None,
    ) -> SnapshotEnvelope:
        """Publish a snapshot to the bus. Returns the envelope."""
        t = topic or self.default_topic
        start = time.monotonic()
        envelope = self._bus.publish(t, self._id, payload)
        self._record.snapshots_published += 1
        self._record.processing_time_ms = (time.monotonic() - start) * 1000
        self._monitor.update_record(self._record)
        return envelope

    # ── Task queue (advisory) ─────────────────────────────────────────────────

    def enqueue(self, task_description: str) -> None:
        self._queue.append(task_description)
        self._record.queue_depth = len(self._queue)

    def dequeue(self) -> Optional[str]:
        if self._queue:
            task = self._queue.popleft()
            self._record.queue_depth = len(self._queue)
            return task
        return None

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def state(self) -> AgentState:
        return self._record.state

    @property
    def record(self) -> AgentRecord:
        return self._record

    @property
    def agent_id(self) -> str:
        return self._id

    def uptime_s(self) -> float:
        return time.monotonic() - self._started

    def to_dict(self) -> Dict[str, Any]:
        d = self._record.to_dict()
        d["uptime_s"] = round(self.uptime_s(), 1)
        return d
