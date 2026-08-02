"""
agent_registry.py — Phase 10A
Central registry of all registered agents.

Thread-safe. READ-ONLY · ADVISORY-ONLY — never restarts agents.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from .models import AgentRecord, AgentState


class AgentRegistry:
    """
    Singleton registry. Agents call register() on startup and
    deregister() on shutdown. The registry never modifies agent state —
    it only stores and queries records.
    """

    _instance: Optional["AgentRegistry"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._agents: Dict[str, AgentRecord] = {}
        self._mu = threading.Lock()

    @classmethod
    def instance(cls) -> "AgentRegistry":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton — for testing only."""
        with cls._class_lock:
            cls._instance = None

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def register(self, record: AgentRecord) -> AgentRecord:
        """Register an agent. Overwrites any existing record with the same ID."""
        with self._mu:
            self._agents[record.agent_id] = record
        return record

    def deregister(self, agent_id: str) -> bool:
        """Remove an agent from the registry. Returns True if it existed."""
        with self._mu:
            return self._agents.pop(agent_id, None) is not None

    def get(self, agent_id: str) -> Optional[AgentRecord]:
        return self._agents.get(agent_id)

    def all(self) -> List[AgentRecord]:
        with self._mu:
            return list(self._agents.values())

    def count(self) -> int:
        return len(self._agents)

    # ── Queries ───────────────────────────────────────────────────────────────

    def by_state(self, state: AgentState) -> List[AgentRecord]:
        with self._mu:
            return [a for a in self._agents.values() if a.state == state]

    def healthy(self) -> List[AgentRecord]:
        return [a for a in self.all() if a.state.is_healthy]

    def active(self) -> List[AgentRecord]:
        return [a for a in self.all() if a.state.is_active]

    def with_errors(self) -> List[AgentRecord]:
        with self._mu:
            return [
                a for a in self._agents.values()
                if a.state in (AgentState.ERROR, AgentState.WARNING)
            ]

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        agents = self.all()
        from .models import AgentState as S  # avoid circular at module level
        return {
            "total":       len(agents),
            "running":     sum(1 for a in agents if a.state == S.RUNNING),
            "busy":        sum(1 for a in agents if a.state == S.BUSY),
            "idle":        sum(1 for a in agents if a.state == S.IDLE),
            "paused":      sum(1 for a in agents if a.state == S.PAUSED),
            "warning":     sum(1 for a in agents if a.state == S.WARNING),
            "error":       sum(1 for a in agents if a.state == S.ERROR),
            "stopped":     sum(1 for a in agents if a.state == S.STOPPED),
            "initializing":sum(1 for a in agents if a.state in (S.INITIALIZING, S.STARTING)),
        }
