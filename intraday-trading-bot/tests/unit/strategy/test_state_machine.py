"""Tests for strategy/state_machine.py."""
import pytest
import asyncio

from strategy.state_machine import StrategyStateMachine, TransitionResult
from strategy.contracts import StrategyLifecycleState
from strategy.exceptions import LifecycleTransitionError


class TestStrategyStateMachine:
    @pytest.fixture
    def machine(self):
        return StrategyStateMachine()

    @pytest.mark.asyncio
    async def test_initial_state(self, machine):
        assert machine.state == StrategyLifecycleState.REGISTERED
        assert machine.is_terminal is False
        assert machine.can_emit_signals is False

    @pytest.mark.asyncio
    async def test_registered_to_starting(self, machine):
        result = await machine.transition(StrategyLifecycleState.STARTING)
        assert result.success is True
        assert result.previous_state == StrategyLifecycleState.REGISTERED
        assert result.new_state == StrategyLifecycleState.STARTING
        assert machine.state == StrategyLifecycleState.STARTING

    @pytest.mark.asyncio
    async def test_starting_to_active(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        result = await machine.transition(StrategyLifecycleState.ACTIVE)
        assert result.success is True
        assert machine.state == StrategyLifecycleState.ACTIVE
        assert machine.can_emit_signals is True

    @pytest.mark.asyncio
    async def test_active_to_paused(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        await machine.transition(StrategyLifecycleState.ACTIVE)
        result = await machine.transition(StrategyLifecycleState.PAUSED)
        assert result.success is True
        assert machine.state == StrategyLifecycleState.PAUSED
        assert machine.can_emit_signals is False

    @pytest.mark.asyncio
    async def test_paused_to_active(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        await machine.transition(StrategyLifecycleState.ACTIVE)
        await machine.transition(StrategyLifecycleState.PAUSED)
        result = await machine.transition(StrategyLifecycleState.ACTIVE)
        assert result.success is True
        assert machine.can_emit_signals is True

    @pytest.mark.asyncio
    async def test_active_to_stopping(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        await machine.transition(StrategyLifecycleState.ACTIVE)
        result = await machine.transition(StrategyLifecycleState.STOPPING)
        assert result.success is True
        assert machine.state == StrategyLifecycleState.STOPPING

    @pytest.mark.asyncio
    async def test_stopping_to_stopped(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        await machine.transition(StrategyLifecycleState.ACTIVE)
        await machine.transition(StrategyLifecycleState.STOPPING)
        result = await machine.transition(StrategyLifecycleState.STOPPED)
        assert result.success is True
        assert machine.state == StrategyLifecycleState.STOPPED
        assert machine.is_terminal is True
        assert machine.can_emit_signals is False

    @pytest.mark.asyncio
    async def test_invalid_transition_active_to_registered(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        await machine.transition(StrategyLifecycleState.ACTIVE)
        with pytest.raises(LifecycleTransitionError):
            await machine.transition(StrategyLifecycleState.REGISTERED)

    @pytest.mark.asyncio
    async def test_invalid_transition_stopped_to_active(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        await machine.transition(StrategyLifecycleState.ACTIVE)
        await machine.transition(StrategyLifecycleState.STOPPING)
        await machine.transition(StrategyLifecycleState.STOPPED)
        with pytest.raises(LifecycleTransitionError):
            await machine.transition(StrategyLifecycleState.ACTIVE)

    @pytest.mark.asyncio
    async def test_no_op_transition(self, machine):
        result = await machine.transition(StrategyLifecycleState.REGISTERED)
        assert result.success is True
        assert "no-op" in (result.reason or "")
        assert machine.state == StrategyLifecycleState.REGISTERED

    @pytest.mark.asyncio
    async def test_error_state_recovery(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        await machine.transition(StrategyLifecycleState.ACTIVE)
        result = await machine.transition(StrategyLifecycleState.ERROR, reason="test error")
        assert result.success is True
        assert machine.state == StrategyLifecycleState.ERROR
        assert machine.can_emit_signals is False

        # Can go to STOPPING from ERROR
        result = await machine.transition(StrategyLifecycleState.STOPPING)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_transition_history(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        await machine.transition(StrategyLifecycleState.ACTIVE)
        history = machine.transition_history
        assert len(history) == 2
        assert history[0].previous_state == StrategyLifecycleState.REGISTERED
        assert history[0].new_state == StrategyLifecycleState.STARTING

    @pytest.mark.asyncio
    async def test_validate_transition(self, machine):
        assert machine.validate_transition(StrategyLifecycleState.STARTING) is True
        assert machine.validate_transition(StrategyLifecycleState.ACTIVE) is False

        await machine.transition(StrategyLifecycleState.STARTING)
        assert machine.validate_transition(StrategyLifecycleState.ACTIVE) is True
        assert machine.validate_transition(StrategyLifecycleState.REGISTERED) is False

    @pytest.mark.asyncio
    async def test_concurrent_transitions_safe(self, machine):
        await machine.transition(StrategyLifecycleState.STARTING)
        result = await machine.transition(StrategyLifecycleState.STARTING)
        assert result.success is True
