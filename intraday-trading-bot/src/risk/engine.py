"""
Risk Engine — main orchestrator for pre-trade and post-trade risk checks.

The RiskEngine sits between the Strategy Layer and the Execution Engine.
It evaluates orders before they reach execution (pre-trade) and monitors
portfolio state after fills (post-trade).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio

from .contracts import (
    RiskDecision,
    RiskAction,
    RiskViolation,
    RiskCheckContext,
    RiskCheckType,
    RiskLimit,
    RiskStateSnapshot,
)
from .rules import RULE_REGISTRY, DuplicateOrderRule
from .state import RiskState
from .kill_switch import KillSwitch


class RiskEngine:
    """Central risk evaluation engine."""

    PRE_TRADE_CHECKS = {
        RiskCheckType.ORDER_SIZE,
        RiskCheckType.PRICE_TOLERANCE,
        RiskCheckType.POSITION_LIMIT,
        RiskCheckType.PORTFOLIO_EXPOSURE,
        RiskCheckType.DAILY_LOSS_LIMIT,
        RiskCheckType.MESSAGE_THROTTLE,
        RiskCheckType.DUPLICATE_ORDER,
        RiskCheckType.SELF_TRADE,
    }

    POST_TRADE_CHECKS = {
        RiskCheckType.PORTFOLIO_HEAT,
        RiskCheckType.DRAWDOWN,
        RiskCheckType.TURNOVER_VELOCITY,
    }

    def __init__(
        self,
        limits: Optional[Dict[str, List[RiskLimit]]] = None,
        allow_risk_reducing_on_kill: bool = False,
    ):
        self._states: Dict[str, RiskState] = {}
        self._kill_switches: Dict[str, KillSwitch] = {}
        self._limits: Dict[str, List[RiskLimit]] = limits or {}
        self._allow_risk_reducing_on_kill: bool = allow_risk_reducing_on_kill
        self._lock: asyncio.Lock = asyncio.Lock()
        # Per-engine rule instances — DuplicateOrderRule is stateful, must not be shared
        self._rule_instances: Dict[RiskCheckType, Any] = dict(RULE_REGISTRY)
        self._rule_instances[RiskCheckType.DUPLICATE_ORDER] = DuplicateOrderRule()

    async def register_account(
        self,
        account_id: str,
        initial_equity: Decimal = Decimal("0"),
        limits: Optional[List[RiskLimit]] = None,
    ) -> None:
        async with self._lock:
            if account_id not in self._states:
                self._states[account_id] = RiskState(account_id, initial_equity)
                self._kill_switches[account_id] = KillSwitch(
                    account_id,
                    allow_risk_reducing=self._allow_risk_reducing_on_kill,
                )
            if limits is not None:
                self._limits[account_id] = limits

    async def set_limits(self, account_id: str, limits: List[RiskLimit]) -> None:
        async with self._lock:
            self._limits[account_id] = limits

    async def pre_trade_check(
        self,
        account_id: str,
        order: Any,
        portfolio_snapshot: Optional[Any] = None,
        position_snapshots: Optional[Dict[str, Any]] = None,
        market_prices: Optional[Dict[str, Decimal]] = None,
        open_orders: Optional[List[Any]] = None,
        check_timestamp: Optional[datetime] = None,
    ) -> RiskDecision:
        if check_timestamp is None:
            check_timestamp = datetime.utcnow()

        if account_id not in self._states:
            await self.register_account(account_id)

        state = self._states[account_id]
        kill_switch = self._kill_switches[account_id]
        limits = self._limits.get(account_id, [])

        context = RiskCheckContext(
            account_id=account_id,
            order=order,
            portfolio_snapshot=portfolio_snapshot,
            position_snapshots=position_snapshots or {},
            market_prices=market_prices or {},
            open_orders=open_orders or [],
            check_timestamp=check_timestamp,
        )

        state_snapshot = await state.to_snapshot_locked(check_timestamp)
        violations: List[RiskViolation] = []

        # 1. Check kill switch first
        order_side = self._get_order_side(order)
        current_direction = self._get_current_direction(order, position_snapshots)
        ks_violation = kill_switch.evaluate_order(order_side, current_direction)
        if ks_violation is not None:
            violations.append(ks_violation)

        # 2. Record message for throttling (before checking throttle rules)
        await self._record_message_throttle(state, context, limits, check_timestamp)

        # 3. Evaluate all pre-trade rules
        for limit in limits:
            check_type = self._limit_to_check_type(limit)
            if check_type is None or check_type not in self.PRE_TRADE_CHECKS:
                continue

            rule = self._rule_instances.get(check_type)
            if rule is None:
                continue

            # Re-fetch state snapshot after throttle recording
            state_snapshot = state.to_snapshot(check_timestamp)
            violation = rule.evaluate(context, limit, state_snapshot)
            if violation is not None:
                violations.append(violation)

        # 4. Determine action
        action = self._determine_action(violations)

        # 5. Auto-activate kill switch on FATAL violations
        if action == RiskAction.KILL_SWITCH and not kill_switch.is_active:
            fatal_reasons = [v.message for v in violations if v.severity.value == "FATAL"]
            reason = "; ".join(fatal_reasons) if fatal_reasons else "Risk limit breached"
            kill_switch.activate(reason, actor="risk_engine", timestamp=check_timestamp)
            await state.activate_kill_switch(reason)

        return RiskDecision(
            action=action,
            violations=violations,
            check_timestamp=check_timestamp,
            order_id=self._get_order_id(order),
            account_id=account_id,
        )

    async def post_trade_check(
        self,
        account_id: str,
        portfolio_snapshot: Any,
        position_snapshots: Dict[str, Any],
        check_timestamp: Optional[datetime] = None,
    ) -> RiskDecision:
        if check_timestamp is None:
            check_timestamp = datetime.utcnow()

        if account_id not in self._states:
            await self.register_account(account_id)

        state = self._states[account_id]
        limits = self._limits.get(account_id, [])

        context = RiskCheckContext(
            account_id=account_id,
            order=None,
            portfolio_snapshot=portfolio_snapshot,
            position_snapshots=position_snapshots,
            market_prices={},
            open_orders=[],
            check_timestamp=check_timestamp,
        )

        state_snapshot = await state.to_snapshot_locked(check_timestamp)
        violations: List[RiskViolation] = []

        for limit in limits:
            check_type = self._limit_to_check_type(limit)
            if check_type is None or check_type not in self.POST_TRADE_CHECKS:
                continue
            rule = self._rule_instances.get(check_type)
            if rule is None:
                continue
            violation = rule.evaluate(context, limit, state_snapshot)
            if violation is not None:
                violations.append(violation)

        action = self._determine_action(violations, post_trade=True)

        # Post-trade checks never block — the fill already happened.
        if action in (RiskAction.BLOCK, RiskAction.KILL_SWITCH):
            action = RiskAction.WARN

        return RiskDecision(
            action=action,
            violations=violations,
            check_timestamp=check_timestamp,
            order_id=None,
            account_id=account_id,
        )

    async def record_fill(
        self,
        account_id: str,
        realized_pnl: Decimal,
        turnover: Decimal,
        current_equity: Decimal,
        fill_timestamp: Optional[datetime] = None,
    ) -> None:
        if fill_timestamp is None:
            fill_timestamp = datetime.utcnow()
        if account_id not in self._states:
            await self.register_account(account_id)
        await self._states[account_id].record_fill(realized_pnl, turnover, current_equity, fill_timestamp)

    async def activate_kill_switch(
        self,
        account_id: str,
        reason: str,
        actor: str = "manual",
        timestamp: Optional[datetime] = None,
    ) -> None:
        if timestamp is None:
            timestamp = datetime.utcnow()
        if account_id not in self._kill_switches:
            await self.register_account(account_id)
        self._kill_switches[account_id].activate(reason, actor=actor, timestamp=timestamp)
        await self._states[account_id].activate_kill_switch(reason)

    async def deactivate_kill_switch(
        self,
        account_id: str,
        reason: str,
        actor: str = "manual",
        timestamp: Optional[datetime] = None,
    ) -> None:
        if timestamp is None:
            timestamp = datetime.utcnow()
        if account_id not in self._kill_switches:
            return
        self._kill_switches[account_id].deactivate(reason, actor=actor, timestamp=timestamp)
        await self._states[account_id].deactivate_kill_switch()

    async def get_state_snapshot(self, account_id: str) -> RiskStateSnapshot:
        if account_id not in self._states:
            await self.register_account(account_id)
        return await self._states[account_id].to_snapshot_locked(datetime.utcnow())

    async def reset_account(self, account_id: str, initial_equity: Decimal = Decimal("0")) -> None:
        if account_id in self._states:
            await self._states[account_id].reset_daily(initial_equity)

    def get_kill_switch_history(self, account_id: str) -> List[Any]:
        if account_id not in self._kill_switches:
            return []
        return self._kill_switches[account_id].get_history()

    def is_kill_switch_active(self, account_id: str) -> bool:
        if account_id not in self._kill_switches:
            return False
        return self._kill_switches[account_id].is_active

    def reset(self) -> None:
        """Reset all engine state — used for deterministic replay testing."""
        self._states.clear()
        self._kill_switches.clear()
        dup_rule = self._rule_instances.get(RiskCheckType.DUPLICATE_ORDER)
        if dup_rule is not None:
            dup_rule.reset()

    # --- Private helpers ---

    async def _record_message_throttle(self, state, context, limits, now) -> None:
        from .rules import MessageThrottleRule
        from .contracts import MessageThrottleLimit

        for limit in limits:
            if isinstance(limit, MessageThrottleLimit) and limit.enabled:
                rule = MessageThrottleRule()
                key = rule._build_throttle_key(context, limit)
                if key is not None:
                    await state.record_message(key, limit.window_seconds, now)

    def _determine_action(self, violations: List[RiskViolation], post_trade: bool = False) -> RiskAction:
        if not violations:
            return RiskAction.ALLOW
        if not post_trade and any(v.severity.value == "FATAL" for v in violations):
            return RiskAction.KILL_SWITCH
        if not post_trade and any(v.severity.value == "CRITICAL" for v in violations):
            return RiskAction.BLOCK
        if any(v.severity.value in ("WARNING", "INFO", "CRITICAL", "FATAL") for v in violations):
            return RiskAction.WARN
        return RiskAction.ALLOW

    def _limit_to_check_type(self, limit: RiskLimit) -> Optional[RiskCheckType]:
        from .contracts import (
            OrderSizeLimit, PriceToleranceLimit, PositionLimit,
            PortfolioExposureLimit, DailyLossLimit, MessageThrottleLimit,
            DuplicateOrderLimit, SelfTradeLimit, PortfolioHeatLimit,
            DrawdownLimit, TurnoverVelocityLimit,
        )
        mapping = {
            OrderSizeLimit: RiskCheckType.ORDER_SIZE,
            PriceToleranceLimit: RiskCheckType.PRICE_TOLERANCE,
            PositionLimit: RiskCheckType.POSITION_LIMIT,
            PortfolioExposureLimit: RiskCheckType.PORTFOLIO_EXPOSURE,
            DailyLossLimit: RiskCheckType.DAILY_LOSS_LIMIT,
            MessageThrottleLimit: RiskCheckType.MESSAGE_THROTTLE,
            DuplicateOrderLimit: RiskCheckType.DUPLICATE_ORDER,
            SelfTradeLimit: RiskCheckType.SELF_TRADE,
            PortfolioHeatLimit: RiskCheckType.PORTFOLIO_HEAT,
            DrawdownLimit: RiskCheckType.DRAWDOWN,
            TurnoverVelocityLimit: RiskCheckType.TURNOVER_VELOCITY,
        }
        return mapping.get(type(limit))

    @staticmethod
    def _get_order_side(order: Any) -> str:
        if isinstance(order, dict):
            return (order.get("side") or "BUY").upper()
        return str(getattr(order, "side", "BUY")).upper()

    @staticmethod
    def _get_order_id(order: Any) -> Optional[str]:
        if isinstance(order, dict):
            return order.get("order_id") or order.get("client_order_id")
        return getattr(order, "order_id", None) or getattr(order, "client_order_id", None)

    @staticmethod
    def _get_current_direction(order: Any, positions: Optional[Dict[str, Any]]) -> str:
        if positions is None:
            return "FLAT"
        instrument = order.get("instrument_token") if isinstance(order, dict) else getattr(order, "instrument_token", None)
        if instrument is None:
            return "FLAT"
        pos = positions.get(instrument)
        if pos is None:
            return "FLAT"
        return (pos.get("direction") or "FLAT").upper() if isinstance(pos, dict) else str(getattr(pos, "direction", "FLAT")).upper()
