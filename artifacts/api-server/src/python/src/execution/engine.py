"""Paper matching engine.

Orchestrates market data consumption, order evaluation, fill generation,
and state-machine integration.  All state mutation flows through the
Batch 7A OrderStateMachine.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from src.execution.contracts import (
    ExecutionOrder,
    ExecutionOrderStatus,
)
from src.execution.exceptions import OverfillError
from src.execution.fills import FillEvent
from src.execution.matching import MarketSnapshot, OrderMatcher
from src.execution.policies import (
    LatencyPolicy,
    LiquidityPolicy,
    PriceSelectionPolicy,
    SlippagePolicy,
    ZeroLatencyPolicy,
)
from src.execution.state_machine import OrderStateMachine


# ------------------------------------------------------------------
# EngineResult
# ------------------------------------------------------------------

@dataclass(frozen=True)
class EngineResult:
    """Result of processing a market event through the engine."""
    market_event_id: str
    fills: list[FillEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ------------------------------------------------------------------
# MatchingEngine
# ------------------------------------------------------------------

class MatchingEngine:
    """Deterministic paper matching engine.

    Consumes market snapshots, evaluates registered orders, and applies
    fills through the Batch 7A state machine.

    Concurrency:
      - Multiple orders on the same instrument are evaluated concurrently.
      - Per-order state mutation is serialized by Batch 7A's locks.
      - The engine itself does not hold a global lock during evaluation.

    Idempotency:
      - Duplicate market events are detected per order via
        (order_id, market_event_id) deduplication.
      - Deterministic fill IDs prevent double-counting.
    """

    def __init__(
        self,
        state_machine: OrderStateMachine,
        price_policy: PriceSelectionPolicy | None = None,
        slippage_policy: SlippagePolicy | None = None,
        liquidity_policy: LiquidityPolicy | None = None,
        latency_policy: LatencyPolicy | None = None,
    ) -> None:
        self._state_machine = state_machine
        self._matcher = OrderMatcher(
            price_policy=price_policy,
            slippage_policy=slippage_policy,
            liquidity_policy=liquidity_policy,
        )
        self._latency_policy = latency_policy or ZeroLatencyPolicy()
        # Per-order dedup: set of (order_id, market_event_id) tuples
        self._processed_events: set[tuple[UUID, str]] = set()

    # ------------------------------------------------------------------
    # Order lifecycle
    # ------------------------------------------------------------------
    def register_order(self, order: ExecutionOrder) -> None:
        """Register an order with the state machine (CREATED state)."""
        self._state_machine.register(order)

    async def activate_order(self, order_id: UUID, actor: str = "matching_engine") -> None:
        """Transition order from ACCEPTED to OPEN.

        Expected pre-condition: order has already been validated and accepted.
        """
        state = self._state_machine.get_state(order_id)
        if state is None:
            raise RuntimeError(f"Order {order_id} not registered")
        if state.status == ExecutionOrderStatus.ACCEPTED:
            await self._state_machine.open_order(order_id, actor=actor)

    # ------------------------------------------------------------------
    # Market data processing
    # ------------------------------------------------------------------
    async def on_market_data(self, snapshot: MarketSnapshot) -> EngineResult:
        """Process a market snapshot against all executable orders.

        Evaluates every OPEN or PARTIALLY_FILLED order whose instrument
        matches the snapshot.  Applies fills through the state machine.
        """
        fills: list[FillEvent] = []
        errors: list[str] = []

        # Find all executable orders for this instrument
        executable_orders = self._executable_orders_for_instrument(
            snapshot.instrument_token
        )

        # Evaluate concurrently
        tasks = [
            self._evaluate_order(order_id, snapshot)
            for order_id in executable_orders
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
                continue
            if result is not None:
                fills.append(result)

        return EngineResult(
            market_event_id=snapshot.event_id or str(snapshot.timestamp),
            fills=fills,
            errors=errors,
        )

    async def _evaluate_order(
        self,
        order_id: UUID,
        snapshot: MarketSnapshot,
    ) -> FillEvent | None:
        """Evaluate a single order against a market snapshot.

        Returns the FillEvent if a fill occurred, None otherwise.
        """
        state = self._state_machine.get_state(order_id)
        if state is None:
            return None

        # Deduplication: skip if this (order, event) pair was already processed
        event_id = snapshot.event_id
        if not event_id:
            raise ValueError("MarketSnapshot.event_id must be a non-empty string")
        event_key = (order_id, event_id)
        if event_key in self._processed_events:
            return None
        self._processed_events.add(event_key)

        # Latency check
        if not self._latency_policy.is_eligible(
            state.order.created_at, snapshot.timestamp
        ):
            return None

        # Match
        match_result = self._matcher.match(
            order=state.order,
            status=state.status,
            filled_quantity=state.filled_quantity,
            remaining_quantity=state.remaining_quantity,
            snapshot=snapshot,
        )

        if not match_result.executable or match_result.fill_event is None:
            return None

        fill_event = match_result.fill_event

        # Apply fill through state machine
        try:
            if fill_event.remaining_quantity == 0:
                # Complete fill
                result = await self._state_machine.fill(
                    order_id=order_id,
                    quantity=fill_event.quantity,
                    price=fill_event.price,
                    actor="matching_engine",
                    metadata={"market_event_id": fill_event.market_event_id},
                )
            else:
                # Partial fill
                result = await self._state_machine.partially_fill(
                    order_id=order_id,
                    quantity=fill_event.quantity,
                    price=fill_event.price,
                    actor="matching_engine",
                    metadata={"market_event_id": fill_event.market_event_id},
                )

            if not result.success:
                # State machine rejected the transition
                return None

            return fill_event

        except OverfillError:
            # Should not happen due to matcher guards, but handle gracefully
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _executable_orders_for_instrument(
        self,
        instrument_token: int,
    ) -> list[UUID]:
        """Return order IDs for all OPEN or PARTIALLY_FILLED orders on the instrument."""
        return self._state_machine.get_executable_orders_for_instrument(instrument_token)

    def reset(self) -> None:
        """Reset engine state for deterministic replay."""
        self._processed_events.clear()
        self._matcher.reset()
