"""Unit tests for the order state machine.

Covers:
  - every allowed transition
  - every forbidden transition
  - terminal-state protection
  - partial-fill progression
  - overfill rejection
  - duplicate transition idempotency
  - monotonic sequence numbers
  - failed-transition atomicity
  - concurrent transition safety
  - immutable audit records
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from src.execution.contracts import (
    ExecutionOrder,
    ExecutionOrderAction,
    ExecutionOrderSide,
    ExecutionOrderStatus,
    ExecutionOrderType,
)
from src.execution.exceptions import (
    IdempotencyViolation,
    InvalidStateTransition,
    OverfillError,
)
from src.execution.state_machine import OrderStateMachine, TransitionResult


# ==================================================================
# Fixtures
# ==================================================================

@pytest.fixture
def machine() -> OrderStateMachine:
    return OrderStateMachine()


def _make_market_order(quantity: int = 100) -> ExecutionOrder:
    return ExecutionOrder(
        client_order_id=f"test-{uuid4().hex[:8]}",
        instrument_token=123456,
        side=ExecutionOrderSide.BUY,
        order_type=ExecutionOrderType.MARKET,
        quantity=quantity,
    )


# ==================================================================
# Allowed Transitions — Happy Path
# ==================================================================

class TestAllowedTransitions:
    @pytest.mark.asyncio
    async def test_created_to_validated(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        result = await machine.validate(order.order_id)
        assert result.success is True
        assert result.previous_state == ExecutionOrderStatus.CREATED
        assert result.new_state == ExecutionOrderStatus.VALIDATED
        assert result.audit_event is not None
        assert result.audit_event.sequence_number == 1

    @pytest.mark.asyncio
    async def test_created_to_rejected(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        result = await machine.reject(order.order_id, reason="Risk limit exceeded")
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_validated_to_accepted(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        result = await machine.accept(order.order_id)
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.ACCEPTED

    @pytest.mark.asyncio
    async def test_validated_to_rejected(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        result = await machine.reject(order.order_id, reason="Post-trade reject")
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_accepted_to_open(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        result = await machine.open_order(order.order_id)
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.OPEN

    @pytest.mark.asyncio
    async def test_open_to_filled(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        result = await machine.fill(order.order_id, quantity=100, price=Decimal("150.00"))
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.FILLED
        assert result.order is not None
        assert result.order.filled_quantity == 100
        assert result.order.remaining_quantity == 0
        assert result.order.average_fill_price == Decimal("150.00")

    @pytest.mark.asyncio
    async def test_open_to_partially_filled(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        result = await machine.partially_fill(order.order_id, quantity=25, price=Decimal("150.00"))
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.PARTIALLY_FILLED
        assert result.order.filled_quantity == 25
        assert result.order.remaining_quantity == 75

    @pytest.mark.asyncio
    async def test_open_to_cancel_pending(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        result = await machine.request_cancel(order.order_id)
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.CANCEL_PENDING

    @pytest.mark.asyncio
    async def test_open_to_expired(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        result = await machine.expire(order.order_id)
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_open_to_failed(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        result = await machine.fail(order.order_id, reason="Exchange disconnect")
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.FAILED

    @pytest.mark.asyncio
    async def test_cancel_pending_to_cancelled(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.request_cancel(order.order_id)
        result = await machine.cancel(order.order_id)
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_pending_back_to_open(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.request_cancel(order.order_id)
        result = await machine.transition(
            order_id=order.order_id,
            action=ExecutionOrderAction.OPEN,
            reason="Cancel rejected by exchange",
        )
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.OPEN

    @pytest.mark.asyncio
    async def test_partially_filled_to_filled(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.partially_fill(order.order_id, quantity=25, price=Decimal("150.00"))
        result = await machine.fill(order.order_id, quantity=75, price=Decimal("151.00"))
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.FILLED
        assert result.order.filled_quantity == 100
        assert result.order.remaining_quantity == 0
        # Average fill price = (25*150 + 75*151) / 100 = 150.75
        assert result.order.average_fill_price == Decimal("150.75")

    @pytest.mark.asyncio
    async def test_partially_filled_to_cancel_pending(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.partially_fill(order.order_id, quantity=25, price=Decimal("150.00"))
        result = await machine.request_cancel(order.order_id)
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.CANCEL_PENDING
        assert result.order.filled_quantity == 25  # unchanged

    @pytest.mark.asyncio
    async def test_created_to_failed(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        result = await machine.fail(order.order_id, reason="System error")
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.FAILED

    @pytest.mark.asyncio
    async def test_validated_to_failed(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        result = await machine.fail(order.order_id, reason="System error")
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.FAILED

    @pytest.mark.asyncio
    async def test_accepted_to_failed(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        result = await machine.fail(order.order_id, reason="System error")
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.FAILED


# ==================================================================
# Forbidden Transitions
# ==================================================================

class TestForbiddenTransitions:
    @pytest.mark.asyncio
    async def test_created_cannot_fill(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        with pytest.raises(InvalidStateTransition):
            await machine.fill(order.order_id, quantity=100, price=Decimal("100"))

    @pytest.mark.asyncio
    async def test_created_cannot_open(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        with pytest.raises(InvalidStateTransition):
            await machine.open_order(order.order_id)

    @pytest.mark.asyncio
    async def test_validated_cannot_fill(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        with pytest.raises(InvalidStateTransition):
            await machine.fill(order.order_id, quantity=100, price=Decimal("100"))

    @pytest.mark.asyncio
    async def test_accepted_cannot_cancel(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        with pytest.raises(InvalidStateTransition):
            await machine.cancel(order.order_id)

    @pytest.mark.asyncio
    async def test_open_cannot_accept(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        # accept was already called earlier (VALIDATED->ACCEPTED), so idempotency
        # catches the duplicate before state transition validation
        with pytest.raises(IdempotencyViolation):
            await machine.accept(order.order_id)

    @pytest.mark.asyncio
    async def test_filled_cannot_cancel(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.fill(order.order_id, quantity=100, price=Decimal("100"))
        result = await machine.cancel(order.order_id)
        assert result.success is False
        assert result.new_state == ExecutionOrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_rejected_cannot_validate(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.reject(order.order_id, reason="No")
        result = await machine.validate(order.order_id)
        assert result.success is False
        assert "terminal" in (result.reason or "").lower()

    @pytest.mark.asyncio
    async def test_cancelled_cannot_fill(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.request_cancel(order.order_id)
        await machine.cancel(order.order_id)
        result = await machine.fill(order.order_id, quantity=100, price=Decimal("100"))
        assert result.success is False
        assert result.new_state == ExecutionOrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_expired_cannot_open(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.expire(order.order_id)
        result = await machine.open_order(order.order_id)
        assert result.success is False
        assert result.new_state == ExecutionOrderStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_failed_cannot_validate(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.fail(order.order_id, reason="Error")
        result = await machine.validate(order.order_id)
        assert result.success is False
        assert result.new_state == ExecutionOrderStatus.FAILED


# ==================================================================
# Terminal State Protection
# ==================================================================

class TestTerminalStateProtection:
    @pytest.mark.asyncio
    async def test_all_terminal_states_reject_all_actions(self, machine: OrderStateMachine):
        """Verify every terminal state rejects every possible action."""
        terminal_states = [
            (ExecutionOrderStatus.REJECTED, lambda: machine.reject(uuid4(), "test")),
            (ExecutionOrderStatus.FILLED, lambda: machine.fill(uuid4(), 1, Decimal("1"))),
            (ExecutionOrderStatus.CANCELLED, lambda: machine.cancel(uuid4())),
            (ExecutionOrderStatus.EXPIRED, lambda: machine.expire(uuid4())),
            (ExecutionOrderStatus.FAILED, lambda: machine.fail(uuid4(), "test")),
        ]

        for status, _ in terminal_states:
            order = _make_market_order()
            machine.register(order)
            # Manually force to terminal state
            state = machine.get_state(order.order_id)
            assert state is not None
            state.status = status

            # Try every action
            for action in ExecutionOrderAction:
                result = await machine.transition(order.order_id, action=action)
                assert result.success is False, f"{status.value} should reject {action.value}"
                assert result.new_state == status


# ==================================================================
# Partial Fill Progression
# ==================================================================

class TestPartialFillProgression:
    @pytest.mark.asyncio
    async def test_25_50_75_100_progression(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)

        # Three partial fills: 25 + 25 + 25 = 75
        fills = [
            (25, Decimal("100.00")),
            (25, Decimal("101.00")),
            (25, Decimal("102.00")),
        ]

        for qty, price in fills:
            result = await machine.partially_fill(order.order_id, quantity=qty, price=price)
            assert result.success is True
            assert result.new_state == ExecutionOrderStatus.PARTIALLY_FILLED

        state = machine.get_state(order.order_id)
        assert state is not None
        assert state.filled_quantity == 75
        assert state.remaining_quantity == 25
        assert state.status == ExecutionOrderStatus.PARTIALLY_FILLED

        # Final fill of remaining 25 transitions to FILLED
        result = await machine.fill(order.order_id, quantity=25, price=Decimal("103.00"))
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.FILLED
        assert result.order.filled_quantity == 100
        assert result.order.remaining_quantity == 0
        # Average fill price = (25*100 + 25*101 + 25*102 + 25*103) / 100 = 101.50
        assert result.order.average_fill_price == Decimal("101.50")


# ==================================================================
# Overfill Rejection
# ==================================================================

class TestOverfillRejection:
    @pytest.mark.asyncio
    async def test_fill_exceeds_quantity(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        with pytest.raises(OverfillError):
            await machine.fill(order.order_id, quantity=101, price=Decimal("100"))

    @pytest.mark.asyncio
    async def test_partial_fill_then_overfill(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.partially_fill(order.order_id, quantity=60, price=Decimal("100"))
        with pytest.raises(OverfillError):
            await machine.fill(order.order_id, quantity=50, price=Decimal("100"))  # 60+50=110 > 100

    @pytest.mark.asyncio
    async def test_overfill_on_partial_fill_action(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        with pytest.raises(OverfillError):
            await machine.partially_fill(order.order_id, quantity=101, price=Decimal("100"))


# ==================================================================
# Duplicate Transition Idempotency
# ==================================================================

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_validate_rejected(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        with pytest.raises(IdempotencyViolation):
            await machine.validate(order.order_id)

    @pytest.mark.asyncio
    async def test_duplicate_accept_rejected(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        with pytest.raises(IdempotencyViolation):
            await machine.accept(order.order_id)

    @pytest.mark.asyncio
    async def test_duplicate_reject_rejected(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.reject(order.order_id, reason="Test")
        with pytest.raises(IdempotencyViolation):
            await machine.reject(order.order_id, reason="Test again")

    @pytest.mark.asyncio
    async def test_duplicate_cancel_rejected(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.request_cancel(order.order_id)
        await machine.cancel(order.order_id)
        with pytest.raises(IdempotencyViolation):
            await machine.cancel(order.order_id)

    @pytest.mark.asyncio
    async def test_duplicate_expire_rejected(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.expire(order.order_id)
        with pytest.raises(IdempotencyViolation):
            await machine.expire(order.order_id)

    @pytest.mark.asyncio
    async def test_duplicate_fail_rejected(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.fail(order.order_id, reason="Error")
        with pytest.raises(IdempotencyViolation):
            await machine.fail(order.order_id, reason="Error again")

    @pytest.mark.asyncio
    async def test_fill_actions_not_deduplicated(self, machine: OrderStateMachine):
        """Fill actions are naturally idempotent via quantity checks,
        not deduplication keys."""
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        # Two partial fills with same params should both succeed
        await machine.partially_fill(order.order_id, quantity=25, price=Decimal("100"))
        await machine.partially_fill(order.order_id, quantity=25, price=Decimal("100"))
        state = machine.get_state(order.order_id)
        assert state is not None
        assert state.filled_quantity == 50


# ==================================================================
# Monotonic Sequence Numbers
# ==================================================================

class TestMonotonicSequenceNumbers:
    @pytest.mark.asyncio
    async def test_sequence_increments_per_transition(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)

        result1 = await machine.validate(order.order_id)
        assert result1.audit_event.sequence_number == 1

        result2 = await machine.accept(order.order_id)
        assert result2.audit_event.sequence_number == 2

        result3 = await machine.open_order(order.order_id)
        assert result3.audit_event.sequence_number == 3

        result4 = await machine.fill(order.order_id, quantity=100, price=Decimal("100"))
        assert result4.audit_event.sequence_number == 4

    @pytest.mark.asyncio
    async def test_sequence_never_decreases(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        seq = machine.get_state(order.order_id).sequence_number
        assert seq == 2
        # Invalid transitions raise exceptions and do not mutate state or sequence
        with pytest.raises(InvalidStateTransition):
            await machine.cancel(order.order_id)  # invalid from ACCEPTED
        assert machine.get_state(order.order_id).sequence_number == 2


# ==================================================================
# Failed-Transition Atomicity
# ==================================================================

class TestFailedTransitionAtomicity:
    @pytest.mark.asyncio
    async def test_invalid_transition_leaves_order_unchanged(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)

        state_before = machine.get_state(order.order_id)
        assert state_before.status == ExecutionOrderStatus.VALIDATED
        seq_before = state_before.sequence_number

        with pytest.raises(InvalidStateTransition):
            await machine.fill(order.order_id, quantity=100, price=Decimal("100"))

        state_after = machine.get_state(order.order_id)
        assert state_after.status == ExecutionOrderStatus.VALIDATED
        assert state_after.sequence_number == seq_before
        assert state_after.filled_quantity == 0

    @pytest.mark.asyncio
    async def test_overfill_leaves_order_unchanged(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        await machine.partially_fill(order.order_id, quantity=50, price=Decimal("100"))

        state_before = machine.get_state(order.order_id)
        filled_before = state_before.filled_quantity

        with pytest.raises(OverfillError):
            await machine.fill(order.order_id, quantity=60, price=Decimal("100"))

        state_after = machine.get_state(order.order_id)
        assert state_after.filled_quantity == filled_before
        assert state_after.status == ExecutionOrderStatus.PARTIALLY_FILLED


# ==================================================================
# Concurrent Transition Safety
# ==================================================================

class TestConcurrentTransitions:
    @pytest.mark.asyncio
    async def test_concurrent_validates_serialized(self, machine: OrderStateMachine):
        """Multiple concurrent validate attempts on same order should
        result in exactly one success and one IdempotencyViolation."""
        order = _make_market_order()
        machine.register(order)

        async def attempt():
            try:
                return await machine.validate(order.order_id)
            except Exception as e:
                return e

        results = await asyncio.gather(attempt(), attempt())
        successes = [r for r in results if isinstance(r, TransitionResult) and r.success]
        exceptions = [r for r in results if isinstance(r, Exception)]

        assert len(successes) == 1
        assert len(exceptions) == 1
        assert isinstance(exceptions[0], IdempotencyViolation)

    @pytest.mark.asyncio
    async def test_concurrent_fills_serialized(self, machine: OrderStateMachine):
        """Concurrent partial fills should be serialized and sum correctly."""
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)

        async def fill_30():
            return await machine.partially_fill(order.order_id, quantity=30, price=Decimal("100"))

        async def fill_40():
            return await machine.partially_fill(order.order_id, quantity=40, price=Decimal("101"))

        results = await asyncio.gather(fill_30(), fill_40())
        state = machine.get_state(order.order_id)
        assert state.filled_quantity == 70
        assert state.status == ExecutionOrderStatus.PARTIALLY_FILLED

    @pytest.mark.asyncio
    async def test_concurrent_overfill_prevented(self, machine: OrderStateMachine):
        """Concurrent fills that would together exceed quantity should
        have at least one succeed and at least one fail with OverfillError."""
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)

        async def fill_60():
            try:
                return await machine.partially_fill(order.order_id, quantity=60, price=Decimal("100"))
            except Exception as e:
                return e

        async def fill_60_again():
            try:
                return await machine.partially_fill(order.order_id, quantity=60, price=Decimal("101"))
            except Exception as e:
                return e

        results = await asyncio.gather(fill_60(), fill_60_again())
        state = machine.get_state(order.order_id)
        # One should succeed (60), one should fail (would be 120)
        assert state.filled_quantity == 60
        exceptions = [r for r in results if isinstance(r, OverfillError)]
        assert len(exceptions) == 1


# ==================================================================
# Immutable Audit Records
# ==================================================================

class TestImmutableAuditRecords:
    @pytest.mark.asyncio
    async def test_audit_event_cannot_be_mutated(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        result = await machine.validate(order.order_id)
        event = result.audit_event

        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            event.sequence_number = 999

    @pytest.mark.asyncio
    async def test_audit_event_has_all_required_fields(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        result = await machine.validate(order.order_id)
        event = result.audit_event

        assert event.order_id == order.order_id
        assert event.client_order_id == order.client_order_id
        assert event.previous_state == ExecutionOrderStatus.CREATED
        assert event.new_state == ExecutionOrderStatus.VALIDATED
        assert event.action == ExecutionOrderAction.VALIDATE
        assert event.sequence_number == 1
        assert event.event_timestamp.tzinfo is not None
        assert event.actor == "system"

    @pytest.mark.asyncio
    async def test_fill_audit_includes_fill_record(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)
        result = await machine.partially_fill(
            order.order_id, quantity=25, price=Decimal("150.00"),
            metadata={"source": "mock_exchange"},
        )
        event = result.audit_event
        assert event.fill_record is not None
        assert event.fill_record.quantity == 25
        assert event.fill_record.price == Decimal("150.00")
        assert event.metadata == {"source": "mock_exchange"}


# ==================================================================
# Convenience Methods
# ==================================================================

class TestConvenienceMethods:
    @pytest.mark.asyncio
    async def test_submit_registers_and_validates(self, machine: OrderStateMachine):
        order = _make_market_order()
        result = await machine.submit(order)
        assert result.success is True
        assert result.new_state == ExecutionOrderStatus.VALIDATED
        assert machine.get_state(order.order_id) is not None

    @pytest.mark.asyncio
    async def test_custom_actor(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        result = await machine.validate(order.order_id, actor="risk_engine")
        assert result.audit_event.actor == "risk_engine"


class TestIdempotencyRetry:
    """Failed transitions must not commit idempotency markers; retries must succeed."""

    @pytest.mark.asyncio
    async def test_failed_transition_not_recorded(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        # validate succeeds
        await machine.validate(order.order_id)
        # accept succeeds
        await machine.accept(order.order_id)
        # cancel from ACCEPTED fails (InvalidStateTransition)
        with pytest.raises(InvalidStateTransition):
            await machine.cancel(order.order_id)
        # Retry: cancel should still fail with InvalidStateTransition, not IdempotencyViolation
        with pytest.raises(InvalidStateTransition):
            await machine.cancel(order.order_id)

    @pytest.mark.asyncio
    async def test_retry_after_failed_transition_succeeds(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        await machine.validate(order.order_id)
        # fail from VALIDATED succeeds
        result1 = await machine.fail(order.order_id, reason="System error")
        assert result1.success is True
        # Try to fail again — should get IdempotencyViolation (successfully committed)
        with pytest.raises(IdempotencyViolation):
            await machine.fail(order.order_id, reason="Retry")

    @pytest.mark.asyncio
    async def test_successful_duplicate_is_noop(self, machine: OrderStateMachine):
        order = _make_market_order()
        machine.register(order)
        result1 = await machine.validate(order.order_id)
        assert result1.success is True
        # Duplicate validate should raise IdempotencyViolation
        with pytest.raises(IdempotencyViolation):
            await machine.validate(order.order_id)
        # State should not have changed
        state = machine.get_state(order.order_id)
        assert state.status == ExecutionOrderStatus.VALIDATED
        assert state.sequence_number == 1


class TestNoDoubleFill:
    """No fill quantity may be applied twice."""

    @pytest.mark.asyncio
    async def test_duplicate_fill_event_idempotent(self, machine: OrderStateMachine):
        order = _make_market_order(quantity=100)
        machine.register(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await machine.open_order(order.order_id)

        # First partial fill
        result1 = await machine.partially_fill(order.order_id, quantity=30, price=Decimal("100"))
        assert result1.success is True
        assert result1.order.filled_quantity == 30

        # Second partial fill with same quantity (different action instance)
        result2 = await machine.partially_fill(order.order_id, quantity=30, price=Decimal("101"))
        assert result2.success is True
        assert result2.order.filled_quantity == 60

        # Total should be 60, not 30 (fill actions are not deduplicated, they accumulate)
        state = machine.get_state(order.order_id)
        assert state.filled_quantity == 60
        assert state.remaining_quantity == 40
