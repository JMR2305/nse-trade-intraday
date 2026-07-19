"""Tests for PersistenceAdapters.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.execution.recovery.persistence_adapter import (
    OrderStateMachinePersistenceAdapter,
    PositionEnginePersistenceAdapter,
)


class TestOrderStateMachinePersistenceAdapter:
    """OrderStateMachinePersistenceAdapter behavior."""

    def test_adapter_creation(self, state_machine):
        adapter = OrderStateMachinePersistenceAdapter(
            state_machine=state_machine,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
        )
        assert adapter._state_machine is state_machine

    @pytest.mark.asyncio
    async def test_submit_without_session(self, state_machine, sample_order):
        """Submit without session works (no persistence)."""
        adapter = OrderStateMachinePersistenceAdapter(
            state_machine=state_machine,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
        )
        result = await adapter.submit(sample_order)
        assert result.success
        assert result.new_state.value == "VALIDATED"

    @pytest.mark.asyncio
    async def test_validate_transition(self, state_machine, sample_order):
        # Register directly (CREATED) then validate — avoids submit's built-in validate
        state_machine.register(sample_order)
        adapter = OrderStateMachinePersistenceAdapter(
            state_machine=state_machine,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
        )
        result = await adapter.validate(sample_order.order_id)
        assert result.success
        assert result.new_state.value == "VALIDATED"

    @pytest.mark.asyncio
    async def test_accept_transition(self, state_machine, sample_order):
        # Build CREATED → VALIDATED manually, then accept
        state_machine.register(sample_order)
        adapter = OrderStateMachinePersistenceAdapter(
            state_machine=state_machine,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
        )
        await adapter.validate(sample_order.order_id)
        result = await adapter.accept(sample_order.order_id)
        assert result.success
        assert result.new_state.value == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_open_transition(self, state_machine, sample_order):
        state_machine.register(sample_order)
        adapter = OrderStateMachinePersistenceAdapter(
            state_machine=state_machine,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
        )
        await adapter.validate(sample_order.order_id)
        await adapter.accept(sample_order.order_id)
        result = await adapter.open_order(sample_order.order_id)
        assert result.success
        assert result.new_state.value == "OPEN"

    @pytest.mark.asyncio
    async def test_fill_transition(self, state_machine, sample_order):
        state_machine.register(sample_order)
        adapter = OrderStateMachinePersistenceAdapter(
            state_machine=state_machine,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
        )
        await adapter.validate(sample_order.order_id)
        await adapter.accept(sample_order.order_id)
        await adapter.open_order(sample_order.order_id)
        result = await adapter.fill(sample_order.order_id, quantity=100, price=Decimal("150.00"))
        assert result.success
        assert result.new_state.value == "FILLED"

    @pytest.mark.asyncio
    async def test_reject_transition(self, state_machine, sample_order):
        # submit → VALIDATED; reject is valid from VALIDATED
        adapter = OrderStateMachinePersistenceAdapter(
            state_machine=state_machine,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
        )
        await adapter.submit(sample_order)
        result = await adapter.reject(sample_order.order_id, reason="risk check failed")
        assert result.success
        assert result.new_state.value == "REJECTED"

    @pytest.mark.asyncio
    async def test_cancel_transition(self, state_machine, sample_order):
        state_machine.register(sample_order)
        adapter = OrderStateMachinePersistenceAdapter(
            state_machine=state_machine,
            order_repo=None,  # type: ignore[arg-type]
            audit_repo=None,  # type: ignore[arg-type]
        )
        await adapter.validate(sample_order.order_id)
        await adapter.accept(sample_order.order_id)
        await adapter.open_order(sample_order.order_id)
        await adapter.request_cancel(sample_order.order_id)
        result = await adapter.cancel(sample_order.order_id)
        assert result.success
        assert result.new_state.value == "CANCELLED"


class TestPositionEnginePersistenceAdapter:
    """PositionEnginePersistenceAdapter behavior."""

    def test_adapter_creation(self, position_engine):
        adapter = PositionEnginePersistenceAdapter(
            position_engine=position_engine,
            fill_repo=None,  # type: ignore[arg-type]
            trade_repo=None,  # type: ignore[arg-type]
            position_repo=None,  # type: ignore[arg-type]
        )
        assert adapter._position_engine is position_engine

    @pytest.mark.asyncio
    async def test_on_fill_without_session(self, position_engine, sample_fill_event):
        """Process fill without session works (no persistence)."""
        adapter = PositionEnginePersistenceAdapter(
            position_engine=position_engine,
            fill_repo=None,  # type: ignore[arg-type]
            trade_repo=None,  # type: ignore[arg-type]
            position_repo=None,  # type: ignore[arg-type]
        )
        result = await adapter.on_fill(sample_fill_event, session=None)
        assert result.trade_recorded
        assert result.position_impact == "OPEN"
