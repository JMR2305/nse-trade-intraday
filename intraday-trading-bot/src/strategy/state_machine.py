"""Strategy lifecycle state machine.

Enforces valid transitions between StrategyLifecycleState values.
Thread-safe via per-state-machine locking.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Set, Dict

from strategy.contracts import StrategyLifecycleState
from strategy.exceptions import LifecycleTransitionError


# Valid transitions: source state -> set of allowed destination states
_VALID_TRANSITIONS: Dict[StrategyLifecycleState, Set[StrategyLifecycleState]] = {
    StrategyLifecycleState.REGISTERED: {
        StrategyLifecycleState.STARTING,
        StrategyLifecycleState.STOPPED,
    },
    StrategyLifecycleState.STARTING: {
        StrategyLifecycleState.ACTIVE,
        StrategyLifecycleState.ERROR,
        StrategyLifecycleState.STOPPING,
    },
    StrategyLifecycleState.ACTIVE: {
        StrategyLifecycleState.PAUSED,
        StrategyLifecycleState.STOPPING,
        StrategyLifecycleState.ERROR,
    },
    StrategyLifecycleState.PAUSED: {
        StrategyLifecycleState.ACTIVE,
        StrategyLifecycleState.STOPPING,
        StrategyLifecycleState.ERROR,
    },
    StrategyLifecycleState.STOPPING: {
        StrategyLifecycleState.STOPPED,
        StrategyLifecycleState.ERROR,
    },
    StrategyLifecycleState.STOPPED: set(),  # Terminal state
    StrategyLifecycleState.ERROR: {
        StrategyLifecycleState.STOPPING,
        StrategyLifecycleState.STOPPED,
    },
}

_TERMINAL_STATES: Set[StrategyLifecycleState] = {
    StrategyLifecycleState.STOPPED,
}


@dataclass
class TransitionResult:
    """Result of a lifecycle state transition attempt."""
    success: bool
    previous_state: StrategyLifecycleState
    new_state: StrategyLifecycleState
    timestamp: datetime = field(default_factory=datetime.utcnow)
    reason: Optional[str] = None


class StrategyStateMachine:
    """Concurrency-safe state machine for strategy lifecycle.

    Each StrategyRuntime owns one instance. Transitions are
    protected by an asyncio.Lock.
    """

    def __init__(self, initial_state: StrategyLifecycleState = StrategyLifecycleState.REGISTERED):
        self._state = initial_state
        self._lock = asyncio.Lock()
        self._transition_history: list = []

    @property
    def state(self) -> StrategyLifecycleState:
        """Current lifecycle state."""
        return self._state

    @property
    def is_terminal(self) -> bool:
        """True if the current state is terminal (STOPPED)."""
        return self._state in _TERMINAL_STATES

    @property
    def can_emit_signals(self) -> bool:
        """True if the strategy is allowed to emit signals in this state."""
        return self._state == StrategyLifecycleState.ACTIVE

    @property
    def transition_history(self) -> list:
        """Copy of transition history."""
        return list(self._transition_history)

    async def transition(
        self,
        target: StrategyLifecycleState,
        reason: Optional[str] = None,
    ) -> TransitionResult:
        """Attempt a state transition.

        Args:
            target: The desired new state.
            reason: Optional human-readable reason for the transition.

        Returns:
            TransitionResult indicating success or failure.

        Raises:
            LifecycleTransitionError: If the transition is invalid.
        """
        async with self._lock:
            previous = self._state

            if previous == target:
                return TransitionResult(
                    success=True,
                    previous_state=previous,
                    new_state=target,
                    reason=reason or "no-op: already in target state",
                )

            if previous in _TERMINAL_STATES:
                raise LifecycleTransitionError(
                    f"Cannot transition from terminal state {previous.value} to {target.value}"
                )

            allowed = _VALID_TRANSITIONS.get(previous, set())
            if target not in allowed:
                raise LifecycleTransitionError(
                    f"Invalid transition: {previous.value} -> {target.value}. "
                    f"Allowed: {[s.value for s in allowed]}"
                )

            self._state = target
            result = TransitionResult(
                success=True,
                previous_state=previous,
                new_state=target,
                reason=reason,
            )
            self._transition_history.append(result)
            return result

    def validate_transition(self, target: StrategyLifecycleState) -> bool:
        """Check if a transition is valid without executing it.

        This is a synchronous, lock-free check for use in pre-validation.
        """
        previous = self._state
        if previous == target:
            return True
        if previous in _TERMINAL_STATES:
            return False
        allowed = _VALID_TRANSITIONS.get(previous, set())
        return target in allowed
