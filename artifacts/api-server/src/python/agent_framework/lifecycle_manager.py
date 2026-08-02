"""
lifecycle_manager.py — Phase 10A
Manages agent state transitions with reason/timestamp tracking.

SAFETY: The lifecycle manager records advisory state changes only.
It NEVER issues orders, modifies portfolio, strategy, or AI state.
The Supervisor NEVER restarts agents — recommendations only.
"""
from __future__ import annotations

from typing import Optional, Tuple

from .models import AgentState, AgentRecord


# ── Valid transition table ─────────────────────────────────────────────────────

_TRANSITIONS: dict = {
    AgentState.INITIALIZING: {AgentState.STARTING, AgentState.STOPPED, AgentState.ERROR},
    AgentState.STARTING:     {AgentState.RUNNING, AgentState.IDLE, AgentState.ERROR, AgentState.STOPPED},
    AgentState.RUNNING:      {AgentState.BUSY, AgentState.IDLE, AgentState.PAUSED, AgentState.WARNING, AgentState.ERROR, AgentState.STOPPED},
    AgentState.BUSY:         {AgentState.RUNNING, AgentState.IDLE, AgentState.PAUSED, AgentState.WARNING, AgentState.ERROR, AgentState.STOPPED},
    AgentState.IDLE:         {AgentState.RUNNING, AgentState.BUSY, AgentState.PAUSED, AgentState.WARNING, AgentState.ERROR, AgentState.STOPPED},
    AgentState.PAUSED:       {AgentState.RUNNING, AgentState.IDLE, AgentState.ERROR, AgentState.STOPPED},
    AgentState.WARNING:      {AgentState.RUNNING, AgentState.BUSY, AgentState.IDLE, AgentState.PAUSED, AgentState.ERROR, AgentState.STOPPED},
    AgentState.ERROR:        {AgentState.STOPPED},
    AgentState.STOPPED:      set(),  # terminal — manual re-registration required
}


class LifecycleManager:
    """
    Validates and applies agent state transitions.

    The caller is responsible for acquiring any necessary locks on the
    AgentRecord before calling transition().
    """

    def transition(
        self,
        record: AgentRecord,
        new_state: AgentState,
        reason: str = "",
    ) -> Tuple[bool, str]:
        """
        Attempt to transition record to new_state.
        Returns (success, message).
        """
        current = record.state
        allowed = _TRANSITIONS.get(current, set())

        if new_state not in allowed:
            msg = (
                f"Invalid transition {current.value} → {new_state.value} "
                f"for agent '{record.agent_id}'. "
                f"Allowed: {[s.value for s in allowed] or 'none (terminal)'}"
            )
            return False, msg

        record.transition(new_state, reason or f"Operator: {new_state.value}")
        return True, f"Transitioned {current.value} → {new_state.value}"

    # ── Convenience methods ────────────────────────────────────────────────────

    def start(self, record: AgentRecord, reason: str = "Starting") -> Tuple[bool, str]:
        ok, msg = self.transition(record, AgentState.STARTING, reason)
        if ok:
            ok, msg = self.transition(record, AgentState.RUNNING, "Started successfully")
        return ok, msg

    def stop(self, record: AgentRecord, reason: str = "Operator stop") -> Tuple[bool, str]:
        # Any non-terminal state can go to STOPPED
        record.transition(AgentState.STOPPED, reason)
        return True, f"Stopped agent '{record.agent_id}'"

    def pause(self, record: AgentRecord, reason: str = "Operator pause") -> Tuple[bool, str]:
        return self.transition(record, AgentState.PAUSED, reason)

    def resume(self, record: AgentRecord, reason: str = "Operator resume") -> Tuple[bool, str]:
        return self.transition(record, AgentState.RUNNING, reason)

    def mark_error(self, record: AgentRecord, reason: str = "Error") -> Tuple[bool, str]:
        record.transition(AgentState.ERROR, reason)
        return True, f"Marked error for '{record.agent_id}': {reason}"

    def mark_warning(self, record: AgentRecord, reason: str = "Warning") -> Tuple[bool, str]:
        return self.transition(record, AgentState.WARNING, reason)

    def mark_busy(self, record: AgentRecord, task: str = "") -> Tuple[bool, str]:
        ok, msg = self.transition(record, AgentState.BUSY, f"Processing: {task}" if task else "Busy")
        if ok and task:
            record.current_task = task
        return ok, msg

    def mark_idle(self, record: AgentRecord) -> Tuple[bool, str]:
        ok, msg = self.transition(record, AgentState.IDLE, "Task complete")
        if ok:
            record.current_task = None
        return ok, msg

    # ── Introspection ─────────────────────────────────────────────────────────

    def allowed_transitions(self, record: AgentRecord) -> list:
        return [s.value for s in _TRANSITIONS.get(record.state, set())]
