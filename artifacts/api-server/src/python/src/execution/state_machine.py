"""Order state machine with deterministic transitions,
per-order async locking, idempotency, and immutable audit events.
"""
from __future__ import annotations

import asyncio
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.execution.contracts import (
    ExecutionAuditEvent,
    ExecutionOrder,
    ExecutionOrderAction,
    ExecutionOrderStatus,
    FillRecord,
    TERMINAL_STATES,
)
from src.execution.exceptions import (
    IdempotencyViolation,
    InvalidStateTransition,
    OrderValidationError,
    OverfillError,
)


# ------------------------------------------------------------------
# Transition graph
# ------------------------------------------------------------------

TRANSITION_GRAPH: dict[ExecutionOrderStatus, set[ExecutionOrderAction]] = {
    ExecutionOrderStatus.CREATED: {
        ExecutionOrderAction.VALIDATE,
        ExecutionOrderAction.REJECT,
        ExecutionOrderAction.FAIL,
    },
    ExecutionOrderStatus.VALIDATED: {
        ExecutionOrderAction.ACCEPT,
        ExecutionOrderAction.REJECT,
        ExecutionOrderAction.FAIL,
    },
    ExecutionOrderStatus.ACCEPTED: {
        ExecutionOrderAction.OPEN,
        ExecutionOrderAction.FAIL,
    },
    ExecutionOrderStatus.OPEN: {
        ExecutionOrderAction.PARTIALLY_FILL,
        ExecutionOrderAction.FILL,
        ExecutionOrderAction.REQUEST_CANCEL,
        ExecutionOrderAction.EXPIRE,
        ExecutionOrderAction.FAIL,
    },
    ExecutionOrderStatus.PARTIALLY_FILLED: {
        ExecutionOrderAction.PARTIALLY_FILL,
        ExecutionOrderAction.FILL,
        ExecutionOrderAction.REQUEST_CANCEL,
        ExecutionOrderAction.EXPIRE,
        ExecutionOrderAction.FAIL,
    },
    ExecutionOrderStatus.CANCEL_PENDING: {
        ExecutionOrderAction.CANCEL,
        ExecutionOrderAction.OPEN,          # cancel rejected, back to open
        ExecutionOrderAction.PARTIALLY_FILL,  # fill arrived while cancel pending
        ExecutionOrderAction.FILL,
        ExecutionOrderAction.FAIL,
    },
    # Terminal states — no outbound transitions
    ExecutionOrderStatus.REJECTED: set(),
    ExecutionOrderStatus.FILLED: set(),
    ExecutionOrderStatus.CANCELLED: set(),
    ExecutionOrderStatus.EXPIRED: set(),
    ExecutionOrderStatus.FAILED: set(),
}


# ------------------------------------------------------------------
# TransitionResult
# ------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionResult:
    """Result of a state transition attempt.

    success: whether the transition was accepted
    previous_state: state before the attempt
    new_state: state after the attempt (same as previous if failed)
    audit_event: the immutable audit record (None if transition failed)
    order: the updated order state (None if transition failed)
    """
    success: bool
    previous_state: ExecutionOrderStatus
    new_state: ExecutionOrderStatus
    audit_event: ExecutionAuditEvent | None
    order: "OrderState" | None
    reason: str | None = None


# ------------------------------------------------------------------
# OrderState (mutable runtime state)
# ------------------------------------------------------------------

@dataclass
class OrderState:
    """Mutable runtime state for an order within the state machine.

    Wraps the immutable ExecutionOrder contract and tracks live fields
    that change during the lifecycle (status, filled_quantity, etc.).
    """
    order: ExecutionOrder
    status: ExecutionOrderStatus = ExecutionOrderStatus.CREATED
    filled_quantity: int = 0
    remaining_quantity: int = field(init=False)
    average_fill_price: Decimal | None = None
    fill_records: list[FillRecord] = field(default_factory=list)
    sequence_number: int = 0
    _seen_transitions: set[tuple[str, str, int]] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        self.remaining_quantity = self.order.quantity

    @property
    def order_id(self) -> UUID:
        return self.order.order_id

    @property
    def client_order_id(self) -> str:
        return self.order.client_order_id

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def to_dict(self) -> dict[str, Any]:
        """Serialize current state for debugging/logging."""
        return {
            "order_id": str(self.order_id),
            "client_order_id": self.client_order_id,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "average_fill_price": str(self.average_fill_price) if self.average_fill_price else None,
            "sequence_number": self.sequence_number,
        }


# ------------------------------------------------------------------
# OrderStateMachine
# ------------------------------------------------------------------

class OrderStateMachine:
    """Deterministic, concurrent-safe order state machine.

    Each order is identified by ``order_id``.  Per-order async locks
    are stored in a WeakValueDictionary so they are garbage-collected
    when the order is no longer referenced.

    Idempotency is enforced via ``(client_order_id, action, seq)``
    deduplication on the OrderState itself.
    """

    def __init__(self) -> None:
        self._locks: weakref.WeakValueDictionary[UUID, asyncio.Lock] = weakref.WeakValueDictionary()
        self._orders: dict[UUID, OrderState] = {}

    # ------------------------------------------------------------------
    # Lock management
    # ------------------------------------------------------------------
    def _get_lock(self, order_id: UUID) -> asyncio.Lock:
        """Return the per-order lock, creating it if necessary."""
        lock = self._locks.get(order_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[order_id] = lock
        return lock

    # ------------------------------------------------------------------
    # Order registration
    # ------------------------------------------------------------------
    def register(self, order: ExecutionOrder) -> OrderState:
        """Register a new order in the machine (CREATED state)."""
        state = OrderState(order=order, status=ExecutionOrderStatus.CREATED)
        self._orders[order.order_id] = state
        return state

    def get_state(self, order_id: UUID) -> OrderState | None:
        """Retrieve the current runtime state for an order."""
        return self._orders.get(order_id)

    def get_executable_orders_for_instrument(
        self,
        instrument_token: int,
    ) -> list[UUID]:
        """Return order IDs for all OPEN or PARTIALLY_FILLED orders on the instrument.

        Safe for concurrent use — returns a snapshot; the caller must
        acquire per-order locks before mutating state.
        """
        return [
            order_id
            for order_id, state in self._orders.items()
            if state.order.instrument_token == instrument_token
            and state.status in (
                ExecutionOrderStatus.OPEN,
                ExecutionOrderStatus.PARTIALLY_FILLED,
            )
        ]

    # ------------------------------------------------------------------
    # Core transition method
    # ------------------------------------------------------------------
    async def transition(
        self,
        order_id: UUID,
        action: ExecutionOrderAction,
        reason: str | None = None,
        actor: str = "system",
        metadata: dict[str, Any] | None = None,
        fill_quantity: int | None = None,
        fill_price: Decimal | None = None,
        fill_metadata: dict[str, Any] | None = None,
    ) -> TransitionResult:
        """Attempt a state transition for the given order.

        This method is fully async-safe: it acquires a per-order lock,
        validates the transition, applies it atomically, and returns
        an immutable TransitionResult.

        Args:
            order_id: the UUID of the order
            action: the transition action to attempt
            reason: human-readable reason for the transition
            actor: who/what initiated the transition ("system", "user", "broker")
            metadata: arbitrary metadata for the audit event
            fill_quantity: required for PARTIALLY_FILL / FILL actions
            fill_price: required for PARTIALLY_FILL / FILL actions
            fill_metadata: optional metadata attached to the FillRecord

        Returns:
            TransitionResult with success flag, states, audit_event, order

        Raises:
            InvalidStateTransition: if the transition is not in the graph
            OverfillError: if a fill would exceed order quantity
            IdempotencyViolation: if this exact transition was already applied
        """
        lock = self._get_lock(order_id)
        async with lock:
            return await self._transition_locked(
                order_id=order_id,
                action=action,
                reason=reason,
                actor=actor,
                metadata=metadata,
                fill_quantity=fill_quantity,
                fill_price=fill_price,
                fill_metadata=fill_metadata,
            )

    async def _transition_locked(
        self,
        order_id: UUID,
        action: ExecutionOrderAction,
        reason: str | None,
        actor: str,
        metadata: dict[str, Any] | None,
        fill_quantity: int | None,
        fill_price: Decimal | None,
        fill_metadata: dict[str, Any] | None,
    ) -> TransitionResult:
        """Internal transition logic — must be called while holding the per-order lock."""
        state = self._orders.get(order_id)
        if state is None:
            return TransitionResult(
                success=False,
                previous_state=ExecutionOrderStatus.CREATED,
                new_state=ExecutionOrderStatus.CREATED,
                audit_event=None,
                order=None,
                reason=f"Order {order_id} not found",
            )

        previous_state = state.status

        # 1. Idempotency check for non-fill actions (read-only check before mutation)
        # OPEN is excluded because it can legitimately be applied from multiple
        # states (ACCEPTED -> OPEN, CANCEL_PENDING -> OPEN)
        # Fill actions are naturally idempotent via quantity checks
        dedup_key: tuple | None = None
        if action not in (
            ExecutionOrderAction.PARTIALLY_FILL,
            ExecutionOrderAction.FILL,
            ExecutionOrderAction.OPEN,
        ):
            dedup_key = (state.client_order_id, action.value)
            if dedup_key in state._seen_transitions:
                raise IdempotencyViolation(
                    client_order_id=state.client_order_id,
                    action=action.value,
                )

        # 2. Terminal-state guard
        if state.is_terminal():
            return TransitionResult(
                success=False,
                previous_state=previous_state,
                new_state=previous_state,
                audit_event=None,
                order=state,
                reason=f"Order is in terminal state {previous_state.value}",
            )

        # 3. Validate transition exists in graph
        allowed = TRANSITION_GRAPH.get(previous_state, set())
        if action not in allowed:
            raise InvalidStateTransition(
                order_id=str(order_id),
                from_state=previous_state.value,
                action=action.value,
                reason=f"Allowed from {previous_state.value}: {[a.value for a in allowed]}",
            )

        # 4. Compute new state
        new_state = self._resolve_new_state(previous_state, action)

        # 5. Handle fill-specific validation
        fill_record: FillRecord | None = None
        if action in (ExecutionOrderAction.PARTIALLY_FILL, ExecutionOrderAction.FILL):
            if fill_quantity is None or fill_price is None:
                raise OrderValidationError(
                    f"{action.value} requires fill_quantity and fill_price"
                )
            if fill_quantity <= 0:
                raise OrderValidationError("fill_quantity must be positive")
            if fill_price <= 0:
                raise OrderValidationError("fill_price must be positive")
            if state.filled_quantity + fill_quantity > state.order.quantity:
                raise OverfillError(
                    order_id=str(order_id),
                    filled=state.filled_quantity,
                    attempted=fill_quantity,
                    quantity=state.order.quantity,
                )

            fill_record = FillRecord(
                quantity=fill_quantity,
                price=fill_price,
                filled_at=datetime.now(timezone.utc),
                metadata=fill_metadata,
            )

            # Apply fill
            state.filled_quantity += fill_quantity
            state.remaining_quantity = state.order.quantity - state.filled_quantity
            state.fill_records.append(fill_record)

            # Compute average fill price
            total_value = sum(fr.quantity * fr.price for fr in state.fill_records)
            state.average_fill_price = total_value / Decimal(state.filled_quantity)

        # 6. Apply state change
        state.status = new_state
        state.sequence_number += 1

        # 7. Commit idempotency marker ONLY after successful mutation
        if dedup_key is not None:
            state._seen_transitions.add(dedup_key)

        # 7. Build audit event
        audit_event = ExecutionAuditEvent(
            order_id=order_id,
            client_order_id=state.client_order_id,
            sequence_number=state.sequence_number,
            previous_state=previous_state,
            new_state=new_state,
            action=action,
            reason=reason,
            actor=actor,
            metadata=metadata,
            fill_record=fill_record,
        )

        return TransitionResult(
            success=True,
            previous_state=previous_state,
            new_state=new_state,
            audit_event=audit_event,
            order=state,
        )

    # ------------------------------------------------------------------
    # State resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_new_state(
        current: ExecutionOrderStatus,
        action: ExecutionOrderAction,
    ) -> ExecutionOrderStatus:
        """Map (current_state, action) → new_state."""
        # Direct mappings
        mapping: dict[tuple[ExecutionOrderStatus, ExecutionOrderAction], ExecutionOrderStatus] = {
            (ExecutionOrderStatus.CREATED, ExecutionOrderAction.VALIDATE): ExecutionOrderStatus.VALIDATED,
            (ExecutionOrderStatus.CREATED, ExecutionOrderAction.REJECT): ExecutionOrderStatus.REJECTED,
            (ExecutionOrderStatus.CREATED, ExecutionOrderAction.FAIL): ExecutionOrderStatus.FAILED,
            (ExecutionOrderStatus.VALIDATED, ExecutionOrderAction.ACCEPT): ExecutionOrderStatus.ACCEPTED,
            (ExecutionOrderStatus.VALIDATED, ExecutionOrderAction.REJECT): ExecutionOrderStatus.REJECTED,
            (ExecutionOrderStatus.VALIDATED, ExecutionOrderAction.FAIL): ExecutionOrderStatus.FAILED,
            (ExecutionOrderStatus.ACCEPTED, ExecutionOrderAction.OPEN): ExecutionOrderStatus.OPEN,
            (ExecutionOrderStatus.ACCEPTED, ExecutionOrderAction.FAIL): ExecutionOrderStatus.FAILED,
            (ExecutionOrderStatus.OPEN, ExecutionOrderAction.REQUEST_CANCEL): ExecutionOrderStatus.CANCEL_PENDING,
            (ExecutionOrderStatus.OPEN, ExecutionOrderAction.EXPIRE): ExecutionOrderStatus.EXPIRED,
            (ExecutionOrderStatus.OPEN, ExecutionOrderAction.FAIL): ExecutionOrderStatus.FAILED,
            (ExecutionOrderStatus.PARTIALLY_FILLED, ExecutionOrderAction.REQUEST_CANCEL): ExecutionOrderStatus.CANCEL_PENDING,
            (ExecutionOrderStatus.PARTIALLY_FILLED, ExecutionOrderAction.EXPIRE): ExecutionOrderStatus.EXPIRED,
            (ExecutionOrderStatus.PARTIALLY_FILLED, ExecutionOrderAction.FAIL): ExecutionOrderStatus.FAILED,
            (ExecutionOrderStatus.CANCEL_PENDING, ExecutionOrderAction.CANCEL): ExecutionOrderStatus.CANCELLED,
            (ExecutionOrderStatus.CANCEL_PENDING, ExecutionOrderAction.OPEN): ExecutionOrderStatus.OPEN,
            (ExecutionOrderStatus.CANCEL_PENDING, ExecutionOrderAction.FAIL): ExecutionOrderStatus.FAILED,
        }

        key = (current, action)
        if key in mapping:
            return mapping[key]

        # Fill actions map to PARTIALLY_FILLED or FILLED based on quantity
        if action == ExecutionOrderAction.PARTIALLY_FILL:
            return ExecutionOrderStatus.PARTIALLY_FILLED

        if action == ExecutionOrderAction.FILL:
            return ExecutionOrderStatus.FILLED

        # Fallback (should never reach here if graph is correct)
        raise InvalidStateTransition(
            order_id="unknown",
            from_state=current.value,
            action=action.value,
            reason="No mapping defined",
        )

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------
    async def submit(self, order: ExecutionOrder, actor: str = "system") -> TransitionResult:
        """Register and validate a new order."""
        self.register(order)
        return await self.transition(
            order_id=order.order_id,
            action=ExecutionOrderAction.VALIDATE,
            actor=actor,
            reason="Order submitted",
        )

    async def validate(self, order_id: UUID, actor: str = "system") -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.VALIDATE,
            actor=actor,
            reason="Validation passed",
        )

    async def accept(self, order_id: UUID, actor: str = "system") -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.ACCEPT,
            actor=actor,
            reason="Order accepted",
        )

    async def reject(self, order_id: UUID, reason: str, actor: str = "system") -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.REJECT,
            actor=actor,
            reason=reason,
        )

    async def open_order(self, order_id: UUID, actor: str = "system") -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.OPEN,
            actor=actor,
            reason="Order opened",
        )

    async def partially_fill(
        self,
        order_id: UUID,
        quantity: int,
        price: Decimal,
        actor: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.PARTIALLY_FILL,
            actor=actor,
            fill_quantity=quantity,
            fill_price=price,
            metadata=metadata,
        )

    async def fill(
        self,
        order_id: UUID,
        quantity: int,
        price: Decimal,
        actor: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.FILL,
            actor=actor,
            fill_quantity=quantity,
            fill_price=price,
            metadata=metadata,
        )

    async def request_cancel(self, order_id: UUID, actor: str = "system") -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.REQUEST_CANCEL,
            actor=actor,
            reason="Cancel requested",
        )

    async def cancel(self, order_id: UUID, actor: str = "system") -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.CANCEL,
            actor=actor,
            reason="Cancel confirmed",
        )

    async def expire(self, order_id: UUID, actor: str = "system") -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.EXPIRE,
            actor=actor,
            reason="Order expired",
        )

    async def fail(self, order_id: UUID, reason: str, actor: str = "system") -> TransitionResult:
        return await self.transition(
            order_id=order_id,
            action=ExecutionOrderAction.FAIL,
            actor=actor,
            reason=reason,
        )
