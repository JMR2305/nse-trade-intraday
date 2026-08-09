"""
Risk Integration Layer — bridges the Risk Engine to the Execution Engine.

RiskIntegrationLayer is the single entry point for order submission.
It coordinates context collection, risk evaluation, execution, and
fill event publication in a serialized per-account flow.

ExecutionEnginePort is the interface the adapter must implement.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .contracts import (
    RiskConfiguration,
    RiskContext,
    RiskRequest,
    RiskResult,
)
from .engine import RiskEngine
from .exceptions import IntegrationLayerError
from .fill_event_bus import FillEvent, FillEventBus

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Port (interface) that the adapter must implement
# ────────────────────────────────────────────────────────────────────────────


class ExecutionEnginePort(ABC):
    """Interface the execution-engine adapter must implement.

    The Risk Integration Layer calls these methods to gather context
    and to forward risk-approved orders to the execution engine.
    """

    @abstractmethod
    async def get_portfolio_snapshot(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Return the current portfolio snapshot for the account.

        Keys: equity, cash, buying_power, available_margin, total_market_value.
        May return None if the portfolio cannot be fetched (treated as missing context).
        """

    @abstractmethod
    async def get_position_snapshots(self, account_id: str) -> Dict[str, Any]:
        """Return position snapshots keyed by instrument_token.

        Each value: {net_quantity, direction, market_value}.
        """

    @abstractmethod
    async def get_open_orders(self, account_id: str) -> List[Any]:
        """Return a list of currently open orders for the account."""

    @abstractmethod
    async def get_market_price(self, instrument_token: str) -> Optional[Decimal]:
        """Return the current last-traded price for the instrument.

        May return None if no market data is available (paper mode).
        """

    @abstractmethod
    async def submit_order(self, account_id: str, order: Any) -> Dict[str, Any]:
        """Execute a risk-approved order.

        Called only after all risk checks pass.
        Should raise an exception on execution failure.
        """


# ────────────────────────────────────────────────────────────────────────────
# Integration result
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class RiskIntegrationResult:
    """Result of a submit_order() call through the integration layer."""

    approved: bool
    risk_result: RiskResult
    execution_result: Optional[Dict[str, Any]] = None
    rejection_reason: Optional[str] = None
    error: Optional[str] = None
    # Original exception from the execution attempt (when error is set) so
    # callers can re-raise typed errors (idempotency, validation) instead of
    # collapsing everything into a generic Exception.
    exception: Optional[BaseException] = None

    @property
    def rejected(self) -> bool:
        return not self.approved

    @property
    def succeeded(self) -> bool:
        return self.approved and self.execution_result is not None and self.error is None


# ────────────────────────────────────────────────────────────────────────────
# Integration Layer
# ────────────────────────────────────────────────────────────────────────────


class RiskIntegrationLayer:
    """Orchestrates risk evaluation and execution for each order.

    Flow for submit_order():
      1. Acquire per-account serialization lock.
      2. Collect context from adapter (portfolio, positions, open orders, LTP).
      3. Build RiskRequest + RiskContext.
      4. Call RiskEngine.evaluate() with the configured limits.
      5. If approved → call adapter.submit_order() → get execution result.
      6. If filled → publish FillEvent via FillEventBus.
      7. Release lock; return RiskIntegrationResult.

    When enabled=False, orders bypass risk checks entirely (RC-7 compatibility).
    """

    def __init__(
        self,
        engine: RiskEngine,
        adapter: ExecutionEnginePort,
        limits: Optional[List[RiskConfiguration]] = None,
        fill_event_bus: Optional[FillEventBus] = None,
        enabled: bool = True,
    ) -> None:
        self._engine = engine
        self._adapter = adapter
        self._limits: List[RiskConfiguration] = limits or []
        self._fill_event_bus: FillEventBus = fill_event_bus or FillEventBus()
        self._enabled = enabled
        self._account_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_account_lock(self, account_id: str) -> asyncio.Lock:
        """Get (or create) the per-account serialization lock."""
        async with self._global_lock:
            if account_id not in self._account_locks:
                self._account_locks[account_id] = asyncio.Lock()
        return self._account_locks[account_id]

    def enable(self) -> None:
        """Enable risk gating (default state)."""
        self._enabled = True
        logger.info("RiskIntegrationLayer: risk gating ENABLED")

    def disable(self) -> None:
        """Disable risk gating (bypass mode for backward compatibility)."""
        self._enabled = False
        logger.warning(
            "RiskIntegrationLayer: risk gating DISABLED — orders pass through unchecked"
        )

    def add_limit(self, limit: RiskConfiguration) -> None:
        """Add a risk limit at runtime."""
        self._limits.append(limit)

    def set_limits(self, limits: List[RiskConfiguration]) -> None:
        """Replace all configured limits."""
        self._limits = list(limits)

    @property
    def limits(self) -> List[RiskConfiguration]:
        """Currently configured limits (read-only copy)."""
        return list(self._limits)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def fill_event_bus(self) -> FillEventBus:
        return self._fill_event_bus

    async def submit_order(
        self,
        account_id: str,
        order: Any,
        limits: Optional[List[RiskConfiguration]] = None,
    ) -> RiskIntegrationResult:
        """Submit an order through the risk gate and (if approved) to execution.

        Args:
            account_id: Account submitting the order.
            order: The order dict or object (forwarded to adapter.submit_order()).
            limits: Override limits for this call (uses self._limits if None).

        Returns:
            RiskIntegrationResult describing the outcome.
        """
        if not self._enabled:
            # Bypass mode: skip risk checks, execute directly.
            try:
                exec_result = await self._adapter.submit_order(account_id, order)
                # Create a trivial approved RiskResult for the bypass path
                from .contracts import RiskResult as _RR
                bypass_result = _RR(
                    approved=True,
                    violations=[],
                    check_timestamp=datetime.now(timezone.utc),
                    account_id=account_id,
                )
                return RiskIntegrationResult(
                    approved=True,
                    risk_result=bypass_result,
                    execution_result=exec_result,
                )
            except Exception as exc:
                logger.error(f"Execution error in bypass mode for {account_id}: {exc}")
                from .contracts import RiskResult as _RR
                bypass_result = _RR(
                    approved=True,
                    violations=[],
                    check_timestamp=datetime.now(timezone.utc),
                    account_id=account_id,
                )
                return RiskIntegrationResult(
                    approved=True,
                    risk_result=bypass_result,
                    error=str(exc),
                )

        account_lock = await self._get_account_lock(account_id)
        active_limits = limits if limits is not None else self._limits

        async with account_lock:
            check_timestamp = datetime.now(timezone.utc)

            # ── 1. Collect context ───────────────────────────────────────────
            try:
                portfolio = await self._adapter.get_portfolio_snapshot(account_id)
                positions = await self._adapter.get_position_snapshots(account_id)
                open_orders = await self._adapter.get_open_orders(account_id)

                # Fetch LTP for the order's instrument if available
                instrument_token = self._get_instrument_token(order)
                market_prices: Dict[str, Decimal] = {}
                if instrument_token:
                    ltp = await self._adapter.get_market_price(instrument_token)
                    if ltp is not None:
                        market_prices[instrument_token] = ltp

            except Exception as exc:
                logger.error(f"Context collection error for {account_id}: {exc}")
                raise IntegrationLayerError(
                    f"Failed to collect risk context for {account_id}: {exc}"
                ) from exc

            # ── 2. Build request + context ───────────────────────────────────
            request = RiskRequest(
                account_id=account_id,
                order=order,
                check_timestamp=check_timestamp,
            )
            context = RiskContext(
                account_id=account_id,
                portfolio_snapshot=portfolio,
                position_snapshots=positions,
                market_prices=market_prices,
                open_orders=open_orders,
                order=order,
            )

            # ── 3. Evaluate risk ─────────────────────────────────────────────
            risk_result = await self._engine.evaluate(request, context, active_limits)

            if not risk_result.approved:
                blocking = [
                    v.message for v in risk_result.violations
                    if v.severity.value in ("FATAL", "CRITICAL")
                ]
                rejection_reason = "; ".join(blocking) if blocking else "Risk check failed"
                logger.warning(
                    f"Order rejected for {account_id}: {rejection_reason}"
                )
                return RiskIntegrationResult(
                    approved=False,
                    risk_result=risk_result,
                    rejection_reason=rejection_reason,
                )

            # ── 4. Execute ───────────────────────────────────────────────────
            try:
                exec_result = await self._adapter.submit_order(account_id, order)
            except Exception as exc:
                logger.error(f"Execution error for {account_id}: {exc}", exc_info=True)
                return RiskIntegrationResult(
                    approved=True,   # Risk approved; execution failed
                    risk_result=risk_result,
                    error=str(exc),
                    exception=exc,
                )

            # ── 5. Publish fill event ────────────────────────────────────────
            if exec_result and exec_result.get("status") == "COMPLETE":
                await self._publish_fill(account_id, order, exec_result, check_timestamp)

            return RiskIntegrationResult(
                approved=True,
                risk_result=risk_result,
                execution_result=exec_result,
            )

    async def _publish_fill(
        self,
        account_id: str,
        order: Any,
        exec_result: Dict[str, Any],
        check_timestamp: datetime,
    ) -> None:
        """Build and publish a FillEvent to the bus after a successful fill."""
        try:
            fill_id = str(exec_result.get("broker_order_id") or exec_result.get("order_id", ""))
            instrument_token = self._get_instrument_token(order) or ""
            side = self._get_str(order, "side", "BUY")
            quantity = self._to_decimal(exec_result.get("filled_quantity", 0))
            fill_price = self._to_decimal(exec_result.get("average_price", 0))
            current_equity = self._to_decimal(0)  # Adapter can enrich if needed

            # Record fill in the engine for daily P&L tracking
            await self._engine.record_fill(
                account_id=account_id,
                fill_id=fill_id,
                realized_pnl=Decimal("0"),   # Entry fills have zero realized P&L
                turnover=abs(quantity * fill_price),
                current_equity=current_equity,
                fill_timestamp=check_timestamp,
            )

            # Build and publish to external subscribers
            event = FillEventBus.build_fill_event(
                fill_id=fill_id,
                account_id=account_id,
                instrument_token=instrument_token,
                side=side,
                quantity=quantity,
                fill_price=fill_price,
                current_equity=current_equity,
                fill_timestamp=check_timestamp,
                order_id=str(exec_result.get("order_id", "")),
                broker_fill_id=str(exec_result.get("broker_order_id", "")),
            )
            await self._fill_event_bus.publish_nowait(event)

        except Exception as exc:
            logger.warning(f"Fill event publication error for {account_id}: {exc}")

    @staticmethod
    def _get_instrument_token(order: Any) -> Optional[str]:
        if isinstance(order, dict):
            v = order.get("instrument_token")
        else:
            v = getattr(order, "instrument_token", None)
        return str(v) if v is not None else None

    @staticmethod
    def _get_str(order: Any, field: str, default: str = "") -> str:
        if isinstance(order, dict):
            return str(order.get(field, default))
        return str(getattr(order, field, default))

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")
