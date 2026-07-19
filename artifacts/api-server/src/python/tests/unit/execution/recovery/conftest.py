"""Test fixtures for Batch 7D recovery tests.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

# Domain imports (from existing codebase)
from src.execution.contracts import (
    ExecutionOrder,
    ExecutionOrderSide,
    ExecutionOrderType,
    ExecutionOrderStatus,
    ExecutionOrderAction,
    ExecutionAuditEvent,
    FillRecord,
)
from src.execution.fills import FillEvent, FillEventBuilder
from src.execution.portfolio import PositionSnapshot, PortfolioSnapshot
from src.execution.position_engine import PositionEngine
from src.execution.state_machine import OrderStateMachine
from src.execution.trades import ExecutionTrade, TradeLedger
from src.execution.recovery.journal import ExecutionJournal, JournalEntry, JournalEntryType
from src.execution.recovery.snapshot import SnapshotManager, EngineSnapshot
from src.execution.recovery.replay_engine import ReplayEngine
from src.execution.recovery.recovery_manager import RecoveryManager
from src.execution.recovery.consistency_checker import ConsistencyChecker
from src.execution.recovery.persistence_adapter import (
    OrderStateMachinePersistenceAdapter,
    PositionEnginePersistenceAdapter,
)


# ------------------------------------------------------------------
# Basic fixtures
# ------------------------------------------------------------------

@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_order() -> ExecutionOrder:
    """A valid BUY LIMIT order."""
    return ExecutionOrder(
        order_id=uuid4(),
        client_order_id="test-order-001",
        instrument_token=12345,
        side=ExecutionOrderSide.BUY,
        order_type=ExecutionOrderType.LIMIT,
        quantity=100,
        limit_price=Decimal("150.00"),
        product="CNC",
        validity="DAY",
    )


@pytest.fixture
def sample_sell_order() -> ExecutionOrder:
    """A valid SELL LIMIT order."""
    return ExecutionOrder(
        order_id=uuid4(),
        client_order_id="test-order-002",
        instrument_token=12345,
        side=ExecutionOrderSide.SELL,
        order_type=ExecutionOrderType.LIMIT,
        quantity=50,
        limit_price=Decimal("155.00"),
        product="CNC",
        validity="DAY",
    )


@pytest.fixture
def state_machine() -> OrderStateMachine:
    """Fresh OrderStateMachine instance."""
    return OrderStateMachine()


@pytest.fixture
def position_engine() -> PositionEngine:
    """Fresh PositionEngine with default cash."""
    return PositionEngine(initial_cash=Decimal("1000000"))


@pytest.fixture
def trade_ledger() -> TradeLedger:
    """Fresh TradeLedger instance."""
    return TradeLedger()


@pytest.fixture
def journal() -> ExecutionJournal:
    """Fresh ExecutionJournal instance."""
    return ExecutionJournal()


@pytest.fixture
def fill_builder() -> FillEventBuilder:
    """Fresh FillEventBuilder instance."""
    return FillEventBuilder()


@pytest.fixture
def consistency_checker() -> ConsistencyChecker:
    """Fresh ConsistencyChecker instance."""
    return ConsistencyChecker()


# ------------------------------------------------------------------
# Pre-built domain objects
# ------------------------------------------------------------------

@pytest.fixture
def sample_fill_event(sample_order: ExecutionOrder) -> FillEvent:
    """A sample fill event for the sample order."""
    return FillEvent(
        fill_id="fill-001-sha256",
        order_id=sample_order.order_id,
        client_order_id=sample_order.client_order_id,
        instrument_token=sample_order.instrument_token,
        side=sample_order.side,
        quantity=50,
        price=Decimal("150.00"),
        gross_value=Decimal("7500.00"),
        market_event_id="market-001",
        market_timestamp=datetime.now(timezone.utc),
        cumulative_filled_quantity=50,
        remaining_quantity=50,
    )


@pytest.fixture
def sample_audit_event(sample_order: ExecutionOrder) -> ExecutionAuditEvent:
    """A sample audit event for state transition."""
    return ExecutionAuditEvent(
        event_id=uuid4(),
        order_id=sample_order.order_id,
        client_order_id=sample_order.client_order_id,
        sequence_number=1,
        previous_state=ExecutionOrderStatus.CREATED,
        new_state=ExecutionOrderStatus.VALIDATED,
        action=ExecutionOrderAction.validate,
        event_timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_position_snapshot() -> PositionSnapshot:
    """A sample LONG position."""
    return PositionSnapshot(
        instrument_token=12345,
        net_quantity=100,
        direction="LONG",
        average_buy_price=Decimal("150.00"),
        average_sell_price=Decimal("0"),
        total_buy_quantity=100,
        total_sell_quantity=0,
        total_buy_value=Decimal("15000.00"),
        total_sell_value=Decimal("0"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        market_price=Decimal("155.00"),
        market_timestamp=datetime.now(timezone.utc),
    )


# ------------------------------------------------------------------
# Async fixtures for engine state
# ------------------------------------------------------------------

@pytest_asyncio.fixture
async def filled_state_machine(
    state_machine: OrderStateMachine,
    sample_order: ExecutionOrder,
) -> OrderStateMachine:
    """State machine with one order progressed to OPEN state."""
    await state_machine.submit(sample_order)
    await state_machine.validate(sample_order.order_id)
    await state_machine.accept(sample_order.order_id)
    await state_machine.open_order(sample_order.order_id)
    return state_machine


@pytest_asyncio.fixture
async def partially_filled_position(
    position_engine: PositionEngine,
    sample_fill_event: FillEvent,
) -> PositionEngine:
    """Position engine with one partial fill applied."""
    await position_engine.on_fill(sample_fill_event)
    return position_engine
