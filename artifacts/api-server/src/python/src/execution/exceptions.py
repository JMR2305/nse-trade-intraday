"""Execution domain exceptions.

All exceptions inherit from ExecutionException for typed catching.
"""
from __future__ import annotations


class ExecutionException(Exception):
    """Base exception for the execution domain."""
    pass


class InvalidStateTransition(ExecutionException):
    """Raised when an order state transition is not allowed by the graph."""

    def __init__(self, order_id: str, from_state: str, action: str, reason: str | None = None) -> None:
        self.order_id = order_id
        self.from_state = from_state
        self.action = action
        msg = f"Transition '{action}' from '{from_state}' not allowed for order {order_id}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class OrderValidationError(ExecutionException):
    """Raised when order construction or field validation fails."""
    pass


class IdempotencyViolation(ExecutionException):
    """Raised when a duplicate transition is detected for the same client_order_id."""

    def __init__(self, client_order_id: str, action: str) -> None:
        self.client_order_id = client_order_id
        self.action = action
        super().__init__(f"Duplicate action '{action}' for client_order_id '{client_order_id}'")


class OverfillError(ExecutionException):
    """Raised when a fill would exceed the order quantity."""

    def __init__(self, order_id: str, filled: int, attempted: int, quantity: int) -> None:
        self.order_id = order_id
        self.filled = filled
        self.attempted = attempted
        self.quantity = quantity
        super().__init__(
            f"Overfill on order {order_id}: filled={filled}, attempted={attempted}, quantity={quantity}"
        )


class ConcurrentTransitionError(ExecutionException):
    """Raised when a transition conflicts with an in-flight transition."""
    pass
