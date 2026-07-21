"""
Risk rule implementations.

Each rule implements a pure evaluate() method. Rules are stateless; all
mutable state is passed via RiskStateSnapshot and RiskContext. This makes
rules trivially testable and composable.

Rule registry maps RiskCheckType → RiskRule subclass.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, Dict, Type
import logging

from .contracts import (
    RiskCheckType,
    RiskConfiguration,
    RiskContext,
    RiskRequest,
    RiskResult,
    RiskSeverity,
    RiskStateSnapshot,
    RiskViolation,
    OrderQuantityLimit,
    OrderValueLimit,
    TickSizeLimit,
    PriceBandLimit,
    MaxPositionSizeLimit,
    InstrumentExposureLimit,
    NetExposureLimit,
    ConcentrationLimit,
    CashAvailabilityLimit,
    BuyingPowerLimit,
    PortfolioExposureLimit,
    MarginAvailabilityLimit,
    DailyLossLimit,
    DailyProfitTargetLock,
    MaxTradesPerDayLimit,
    MaxOrdersPerMinuteLimit,
    KillSwitchLimit,
    EmergencyHaltLimit,
    CircuitBreakerLimit,
    DuplicateOrderLimit,
    SelfTradeLimit,
    DrawdownLimit,
    TurnoverVelocityLimit,
)

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _violation(
    check_type: RiskCheckType,
    severity: RiskSeverity,
    message: str,
    rule_id: str,
    limit_value: Optional[Decimal] = None,
    actual_value: Optional[Decimal] = None,
) -> RiskViolation:
    """Build a RiskViolation concisely."""
    return RiskViolation(
        check_type=check_type,
        severity=severity,
        message=message,
        rule_id=rule_id,
        limit_value=limit_value,
        actual_value=actual_value,
    )


# ────────────────────────────────────────────────────────────────────────────
# Abstract base
# ────────────────────────────────────────────────────────────────────────────


class RiskRule(ABC):
    """Abstract base for all risk rules.

    Implementations must be stateless; all state is delivered via
    RiskStateSnapshot and RiskContext.
    """

    @property
    @abstractmethod
    def check_type(self) -> RiskCheckType:
        """The check type this rule implements."""

    @abstractmethod
    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: RiskConfiguration,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        """Evaluate the risk rule.

        Returns:
            RiskViolation if the rule is breached, None if it passes.
        """


# ────────────────────────────────────────────────────────────────────────────
# Safety rules (highest priority)
# ────────────────────────────────────────────────────────────────────────────


class KillSwitchRule(RiskRule):
    """Block all orders when the kill switch is active."""

    check_type = RiskCheckType.KILL_SWITCH

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: KillSwitchLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        if not state.kill_switch_active:
            return None
        reason = state.kill_switch_reason or "Kill switch engaged"
        return _violation(
            check_type=RiskCheckType.KILL_SWITCH,
            severity=RiskSeverity.FATAL,
            message=f"Kill switch is active: {reason}",
            rule_id=config.rule_id,
        )


class EmergencyHaltRule(RiskRule):
    """Block all orders when emergency halt is active."""

    check_type = RiskCheckType.EMERGENCY_HALT

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: EmergencyHaltLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        if not state.emergency_halt_active:
            return None
        return _violation(
            check_type=RiskCheckType.EMERGENCY_HALT,
            severity=RiskSeverity.FATAL,
            message="Emergency halt is active — all trading suspended",
            rule_id=config.rule_id,
        )


class CircuitBreakerRule(RiskRule):
    """Block all orders when the circuit breaker has triggered."""

    check_type = RiskCheckType.CIRCUIT_BREAKER

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: CircuitBreakerLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        if not state.circuit_breaker_triggered:
            return None
        return _violation(
            check_type=RiskCheckType.CIRCUIT_BREAKER,
            severity=RiskSeverity.FATAL,
            message="Circuit breaker has triggered — trading halted",
            rule_id=config.rule_id,
        )


# ────────────────────────────────────────────────────────────────────────────
# Pre-trade rules
# ────────────────────────────────────────────────────────────────────────────


class OrderQuantityRule(RiskRule):
    """Reject orders exceeding the maximum quantity."""

    check_type = RiskCheckType.ORDER_QUANTITY

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: OrderQuantityLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        order = context.order
        if order is None:
            return None

        quantity = self._get_quantity(order)
        if quantity is None:
            return None

        if config.instrument_token and self._get_token(order) != config.instrument_token:
            return None

        if quantity > config.max_quantity:
            return _violation(
                check_type=RiskCheckType.ORDER_QUANTITY,
                severity=config.severity,
                message=(
                    f"Order quantity {quantity} exceeds max {config.max_quantity}"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_quantity,
                actual_value=quantity,
            )
        return None

    @staticmethod
    def _get_quantity(order) -> Optional[Decimal]:
        if isinstance(order, dict):
            v = order.get("quantity")
        else:
            v = getattr(order, "quantity", None)
        if v is None:
            return None
        return Decimal(str(v))

    @staticmethod
    def _get_token(order) -> Optional[str]:
        if isinstance(order, dict):
            return str(order.get("instrument_token", ""))
        return str(getattr(order, "instrument_token", ""))


class OrderValueRule(RiskRule):
    """Reject orders whose notional value exceeds the limit."""

    check_type = RiskCheckType.ORDER_VALUE

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: OrderValueLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        order = context.order
        if order is None:
            return None

        quantity = self._get_decimal(order, "quantity")
        price = self._get_decimal(order, "price")

        if quantity is None:
            return None

        # Use market price if order price is None
        if price is None:
            token = str(self._get_raw(order, "instrument_token", ""))
            price = context.market_prices.get(token)

        if price is None:
            return None  # Cannot evaluate without a price

        notional = quantity * price
        if notional > config.max_value:
            return _violation(
                check_type=RiskCheckType.ORDER_VALUE,
                severity=config.severity,
                message=f"Order notional {notional} exceeds max {config.max_value}",
                rule_id=config.rule_id,
                limit_value=config.max_value,
                actual_value=notional,
            )
        return None

    @staticmethod
    def _get_decimal(order, field: str) -> Optional[Decimal]:
        v = order.get(field) if isinstance(order, dict) else getattr(order, field, None)
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            return None

    @staticmethod
    def _get_raw(order, field: str, default=None):
        if isinstance(order, dict):
            return order.get(field, default)
        return getattr(order, field, default)


class PriceBandRule(RiskRule):
    """Reject orders priced outside the allowed deviation from reference price."""

    check_type = RiskCheckType.PRICE_BAND

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: PriceBandLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        order = context.order
        if order is None:
            return None

        order_price = self._get_price(order)
        if order_price is None:
            return None  # Market orders, skip

        token = str(self._get_raw(order, "instrument_token", ""))
        if config.instrument_token and token != config.instrument_token:
            return None

        ltp = context.market_prices.get(token)
        if ltp is None:
            return None  # No reference price; PriceBandRule skips gracefully

        if ltp == _ZERO:
            return None

        deviation_pct = abs(order_price - ltp) / ltp * Decimal("100")
        if deviation_pct > config.max_deviation_percent:
            return _violation(
                check_type=RiskCheckType.PRICE_BAND,
                severity=config.severity,
                message=(
                    f"Order price {order_price} deviates {deviation_pct:.2f}% from LTP {ltp}; "
                    f"max allowed {config.max_deviation_percent}%"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_deviation_percent,
                actual_value=deviation_pct,
            )
        return None

    @staticmethod
    def _get_price(order) -> Optional[Decimal]:
        v = order.get("price") if isinstance(order, dict) else getattr(order, "price", None)
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            return None

    @staticmethod
    def _get_raw(order, field: str, default=None):
        if isinstance(order, dict):
            return order.get(field, default)
        return getattr(order, field, default)


class TickSizeRule(RiskRule):
    """Reject orders whose price is not a multiple of the tick size."""

    check_type = RiskCheckType.TICK_SIZE

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: TickSizeLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        order = context.order
        if order is None:
            return None

        price = order.get("price") if isinstance(order, dict) else getattr(order, "price", None)
        if price is None:
            return None

        price = Decimal(str(price))
        remainder = price % config.tick_size
        if remainder != _ZERO:
            return _violation(
                check_type=RiskCheckType.TICK_SIZE,
                severity=config.severity,
                message=(
                    f"Order price {price} is not a multiple of tick size {config.tick_size}"
                ),
                rule_id=config.rule_id,
                limit_value=config.tick_size,
                actual_value=remainder,
            )
        return None


# ────────────────────────────────────────────────────────────────────────────
# Position rules
# ────────────────────────────────────────────────────────────────────────────


class MaxPositionSizeRule(RiskRule):
    """Reject orders that would result in exceeding max position size."""

    check_type = RiskCheckType.MAX_POSITION_SIZE

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: MaxPositionSizeLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        order = context.order
        if order is None:
            return None

        order_qty = self._decimal(order, "quantity")
        if order_qty is None:
            return None

        side = self._str(order, "side", "").upper()
        token = str(self._raw(order, "instrument_token", ""))

        if config.instrument_token and token != config.instrument_token:
            return None

        position = context.position_snapshots.get(token, {})
        current_qty = position.get("net_quantity", _ZERO)
        if not isinstance(current_qty, Decimal):
            current_qty = Decimal(str(current_qty))

        if side == "BUY":
            new_qty = current_qty + order_qty
            if new_qty > config.max_long_quantity:
                return _violation(
                    check_type=RiskCheckType.MAX_POSITION_SIZE,
                    severity=config.severity,
                    message=(
                        f"Buy of {order_qty} would create long position {new_qty}; "
                        f"max long is {config.max_long_quantity}"
                    ),
                    rule_id=config.rule_id,
                    limit_value=config.max_long_quantity,
                    actual_value=new_qty,
                )
        elif side == "SELL":
            new_qty = current_qty - order_qty
            if new_qty < -config.max_short_quantity:
                return _violation(
                    check_type=RiskCheckType.MAX_POSITION_SIZE,
                    severity=config.severity,
                    message=(
                        f"Sell of {order_qty} would create short position {new_qty}; "
                        f"max short is {config.max_short_quantity}"
                    ),
                    rule_id=config.rule_id,
                    limit_value=config.max_short_quantity,
                    actual_value=abs(new_qty),
                )
        return None

    @staticmethod
    def _decimal(order, field: str) -> Optional[Decimal]:
        v = order.get(field) if isinstance(order, dict) else getattr(order, field, None)
        if v is None:
            return None
        return Decimal(str(v))

    @staticmethod
    def _str(order, field: str, default: str = "") -> str:
        v = order.get(field, default) if isinstance(order, dict) else getattr(order, field, default)
        return str(v)

    @staticmethod
    def _raw(order, field: str, default=None):
        if isinstance(order, dict):
            return order.get(field, default)
        return getattr(order, field, default)


class InstrumentExposureRule(RiskRule):
    """Reject orders that would exceed the notional exposure limit for an instrument."""

    check_type = RiskCheckType.INSTRUMENT_EXPOSURE

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: InstrumentExposureLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        order = context.order
        if order is None:
            return None

        token = str(
            order.get("instrument_token", "") if isinstance(order, dict)
            else getattr(order, "instrument_token", "")
        )
        if config.instrument_token and token != config.instrument_token:
            return None

        position = context.position_snapshots.get(token, {})
        current_mv = position.get("market_value", _ZERO)
        if not isinstance(current_mv, Decimal):
            current_mv = Decimal(str(current_mv))

        qty = self._decimal(order, "quantity")
        price = self._decimal(order, "price")
        if qty is None:
            return None
        if price is None:
            price = context.market_prices.get(token, _ZERO)

        order_mv = qty * price
        projected = abs(current_mv) + order_mv

        if projected > config.max_exposure:
            return _violation(
                check_type=RiskCheckType.INSTRUMENT_EXPOSURE,
                severity=config.severity,
                message=(
                    f"Projected exposure {projected} exceeds max {config.max_exposure}"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_exposure,
                actual_value=projected,
            )
        return None

    @staticmethod
    def _decimal(order, field: str) -> Optional[Decimal]:
        v = order.get(field) if isinstance(order, dict) else getattr(order, field, None)
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            return None


class NetExposureRule(RiskRule):
    """Enforce net long/short exposure limits across all instruments."""

    check_type = RiskCheckType.NET_EXPOSURE

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: NetExposureLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        long_exposure = _ZERO
        short_exposure = _ZERO

        for position in context.position_snapshots.values():
            qty = position.get("net_quantity", _ZERO)
            if not isinstance(qty, Decimal):
                qty = Decimal(str(qty))
            mv = position.get("market_value", _ZERO)
            if not isinstance(mv, Decimal):
                mv = Decimal(str(mv))

            if qty > _ZERO:
                long_exposure += mv
            elif qty < _ZERO:
                short_exposure += abs(mv)

        if long_exposure > config.max_net_long:
            return _violation(
                check_type=RiskCheckType.NET_EXPOSURE,
                severity=config.severity,
                message=(
                    f"Net long exposure {long_exposure} exceeds max {config.max_net_long}"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_net_long,
                actual_value=long_exposure,
            )
        if short_exposure > config.max_net_short:
            return _violation(
                check_type=RiskCheckType.NET_EXPOSURE,
                severity=config.severity,
                message=(
                    f"Net short exposure {short_exposure} exceeds max {config.max_net_short}"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_net_short,
                actual_value=short_exposure,
            )
        return None


class ConcentrationRule(RiskRule):
    """Prevent excessive portfolio concentration in a single instrument."""

    check_type = RiskCheckType.CONCENTRATION_LIMIT

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: ConcentrationLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        portfolio = context.portfolio_snapshot
        if portfolio is None:
            return None

        total_equity = portfolio.get("equity", _ZERO) if isinstance(portfolio, dict) else getattr(portfolio, "equity", _ZERO)
        if not isinstance(total_equity, Decimal):
            total_equity = Decimal(str(total_equity))

        if total_equity <= _ZERO:
            return None

        order = context.order
        if order is None:
            return None

        token = str(
            order.get("instrument_token", "") if isinstance(order, dict)
            else getattr(order, "instrument_token", "")
        )

        position = context.position_snapshots.get(token, {})
        current_mv = position.get("market_value", _ZERO)
        if not isinstance(current_mv, Decimal):
            current_mv = Decimal(str(current_mv))

        qty = self._decimal(order, "quantity")
        price = self._decimal(order, "price")
        if qty is None:
            return None
        if price is None:
            price = context.market_prices.get(token, _ZERO)

        projected_mv = abs(current_mv) + qty * price
        concentration_pct = projected_mv / total_equity * Decimal("100")

        if concentration_pct > config.max_concentration_percent:
            return _violation(
                check_type=RiskCheckType.CONCENTRATION_LIMIT,
                severity=config.severity,
                message=(
                    f"Projected concentration {concentration_pct:.2f}% in {token} "
                    f"exceeds max {config.max_concentration_percent}%"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_concentration_percent,
                actual_value=concentration_pct,
            )
        return None

    @staticmethod
    def _decimal(order, field: str) -> Optional[Decimal]:
        v = order.get(field) if isinstance(order, dict) else getattr(order, field, None)
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            return None


# ────────────────────────────────────────────────────────────────────────────
# Portfolio rules
# ────────────────────────────────────────────────────────────────────────────


class CashAvailabilityRule(RiskRule):
    """Reject buy orders when insufficient cash is available."""

    check_type = RiskCheckType.CASH_AVAILABILITY

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: CashAvailabilityLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        order = context.order
        if order is None:
            return None

        side = str(
            order.get("side", "") if isinstance(order, dict) else getattr(order, "side", "")
        ).upper()
        if side != "BUY":
            return None

        portfolio = context.portfolio_snapshot
        if portfolio is None:
            return None

        cash = portfolio.get("cash", _ZERO) if isinstance(portfolio, dict) else getattr(portfolio, "cash", _ZERO)
        if not isinstance(cash, Decimal):
            cash = Decimal(str(cash))

        qty = self._decimal(order, "quantity")
        price = self._decimal(order, "price")
        if qty is None:
            return None
        if price is None:
            token = str(
                order.get("instrument_token", "") if isinstance(order, dict)
                else getattr(order, "instrument_token", "")
            )
            price = context.market_prices.get(token, _ZERO)

        required = qty * price
        if required > cash:
            return _violation(
                check_type=RiskCheckType.CASH_AVAILABILITY,
                severity=config.severity,
                message=f"Insufficient cash: need {required}, available {cash}",
                rule_id=config.rule_id,
                limit_value=cash,
                actual_value=required,
            )
        return None

    @staticmethod
    def _decimal(order, field: str) -> Optional[Decimal]:
        v = order.get(field) if isinstance(order, dict) else getattr(order, field, None)
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            return None


class BuyingPowerRule(RiskRule):
    """Reject orders that would exceed available buying power."""

    check_type = RiskCheckType.BUYING_POWER

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: BuyingPowerLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        order = context.order
        if order is None:
            return None

        portfolio = context.portfolio_snapshot
        if portfolio is None:
            return None

        buying_power = portfolio.get("buying_power", _ZERO) if isinstance(portfolio, dict) else getattr(portfolio, "buying_power", _ZERO)
        if not isinstance(buying_power, Decimal):
            buying_power = Decimal(str(buying_power))

        qty = self._decimal(order, "quantity")
        price = self._decimal(order, "price")
        if qty is None:
            return None
        if price is None:
            token = str(
                order.get("instrument_token", "") if isinstance(order, dict)
                else getattr(order, "instrument_token", "")
            )
            price = context.market_prices.get(token, _ZERO)

        order_value = qty * price
        if order_value > buying_power:
            return _violation(
                check_type=RiskCheckType.BUYING_POWER,
                severity=config.severity,
                message=f"Order value {order_value} exceeds buying power {buying_power}",
                rule_id=config.rule_id,
                limit_value=buying_power,
                actual_value=order_value,
            )
        return None

    @staticmethod
    def _decimal(order, field: str) -> Optional[Decimal]:
        v = order.get(field) if isinstance(order, dict) else getattr(order, field, None)
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            return None


class PortfolioExposureRule(RiskRule):
    """Reject orders that would cause total exposure to exceed the limit."""

    check_type = RiskCheckType.PORTFOLIO_EXPOSURE

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: PortfolioExposureLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        portfolio = context.portfolio_snapshot
        if portfolio is None:
            return None

        equity = portfolio.get("equity", _ZERO) if isinstance(portfolio, dict) else getattr(portfolio, "equity", _ZERO)
        if not isinstance(equity, Decimal):
            equity = Decimal(str(equity))

        if equity <= _ZERO:
            return None

        order = context.order
        if order is None:
            return None

        qty = self._decimal(order, "quantity")
        price = self._decimal(order, "price")
        if qty is None:
            return None
        if price is None:
            token = str(
                order.get("instrument_token", "") if isinstance(order, dict)
                else getattr(order, "instrument_token", "")
            )
            price = context.market_prices.get(token, _ZERO)

        if price is None:
            return None

        # Calculate current total exposure
        total_mv = _ZERO
        for pos in context.position_snapshots.values():
            mv = pos.get("market_value", _ZERO)
            if not isinstance(mv, Decimal):
                mv = Decimal(str(mv))
            total_mv += abs(mv)

        order_value = qty * price
        projected_exposure_pct = (total_mv + order_value) / equity * Decimal("100")

        if projected_exposure_pct > config.max_exposure_percent:
            return _violation(
                check_type=RiskCheckType.PORTFOLIO_EXPOSURE,
                severity=config.severity,
                message=(
                    f"Projected portfolio exposure {projected_exposure_pct:.2f}% "
                    f"exceeds max {config.max_exposure_percent}%"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_exposure_percent,
                actual_value=projected_exposure_pct,
            )
        return None

    @staticmethod
    def _decimal(order, field: str) -> Optional[Decimal]:
        v = order.get(field) if isinstance(order, dict) else getattr(order, field, None)
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            return None


# ────────────────────────────────────────────────────────────────────────────
# Daily control rules
# ────────────────────────────────────────────────────────────────────────────


class DailyLossLimitRule(RiskRule):
    """Emit WARNING at warning threshold; FATAL when the daily loss limit is breached."""

    check_type = RiskCheckType.DAILY_LOSS_LIMIT

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: DailyLossLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        pnl = state.daily_realized_pnl
        loss = -pnl  # Positive value = loss

        if loss >= config.max_daily_loss:
            return _violation(
                check_type=RiskCheckType.DAILY_LOSS_LIMIT,
                severity=RiskSeverity.FATAL,
                message=(
                    f"Daily loss {loss} has reached limit {config.max_daily_loss}; "
                    f"trading halted"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_daily_loss,
                actual_value=loss,
            )

        warning_threshold = config.max_daily_loss * config.warning_threshold_percent / Decimal("100")
        if loss >= warning_threshold:
            return _violation(
                check_type=RiskCheckType.DAILY_LOSS_LIMIT,
                severity=RiskSeverity.WARNING,
                message=(
                    f"Daily loss {loss} approaching limit {config.max_daily_loss} "
                    f"({config.warning_threshold_percent}% threshold)"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_daily_loss,
                actual_value=loss,
            )

        return None


class DailyProfitTargetRule(RiskRule):
    """Lock trading once the daily profit target is reached."""

    check_type = RiskCheckType.DAILY_PROFIT_TARGET_LOCK

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: DailyProfitTargetLock,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        if state.daily_realized_pnl >= config.profit_target:
            return _violation(
                check_type=RiskCheckType.DAILY_PROFIT_TARGET_LOCK,
                severity=RiskSeverity.CRITICAL,
                message=(
                    f"Daily profit target {config.profit_target} reached; trading locked"
                ),
                rule_id=config.rule_id,
                limit_value=config.profit_target,
                actual_value=state.daily_realized_pnl,
            )
        return None


class MaxTradesPerDayRule(RiskRule):
    """Reject orders when the daily trade count has been exhausted."""

    check_type = RiskCheckType.MAX_TRADES_PER_DAY

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: MaxTradesPerDayLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        if state.trade_count >= config.max_trades:
            return _violation(
                check_type=RiskCheckType.MAX_TRADES_PER_DAY,
                severity=config.severity,
                message=(
                    f"Daily trade count {state.trade_count} has reached limit {config.max_trades}"
                ),
                rule_id=config.rule_id,
                limit_value=Decimal(str(config.max_trades)),
                actual_value=Decimal(str(state.trade_count)),
            )
        return None


class MaxOrdersPerMinuteRule(RiskRule):
    """Reject orders when the orders-per-minute throttle is exceeded."""

    check_type = RiskCheckType.MAX_ORDERS_PER_MINUTE

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: MaxOrdersPerMinuteLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        throttle_key = f"orders_per_minute:{request.account_id}"
        if config.scope == "instrument" and config.instrument_token:
            throttle_key += f":{config.instrument_token}"

        current_count = state.message_counts.get(throttle_key, 0)

        if current_count >= config.max_orders:
            return _violation(
                check_type=RiskCheckType.MAX_ORDERS_PER_MINUTE,
                severity=config.severity,
                message=(
                    f"Order rate {current_count} has reached limit {config.max_orders} "
                    f"within {config.window_seconds}s window"
                ),
                rule_id=config.rule_id,
                limit_value=Decimal(str(config.max_orders)),
                actual_value=Decimal(str(current_count)),
            )
        return None


# ────────────────────────────────────────────────────────────────────────────
# Monitoring rules (non-blocking unless threshold exceeded)
# ────────────────────────────────────────────────────────────────────────────


class DrawdownRule(RiskRule):
    """Monitor portfolio drawdown from peak equity."""

    check_type = RiskCheckType.DRAWDOWN

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: DrawdownLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        if state.peak_equity <= _ZERO:
            return None

        portfolio = context.portfolio_snapshot
        if portfolio is None:
            return None

        current_equity = portfolio.get("equity", _ZERO) if isinstance(portfolio, dict) else getattr(portfolio, "equity", _ZERO)
        if not isinstance(current_equity, Decimal):
            current_equity = Decimal(str(current_equity))

        drawdown_pct = (state.peak_equity - current_equity) / state.peak_equity * Decimal("100")

        if drawdown_pct > config.max_drawdown_percent:
            return _violation(
                check_type=RiskCheckType.DRAWDOWN,
                severity=config.severity,
                message=(
                    f"Portfolio drawdown {drawdown_pct:.2f}% exceeds max "
                    f"{config.max_drawdown_percent}%"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_drawdown_percent,
                actual_value=drawdown_pct,
            )
        return None


class TurnoverVelocityRule(RiskRule):
    """Monitor turnover velocity relative to equity."""

    check_type = RiskCheckType.TURNOVER_VELOCITY

    def evaluate(
        self,
        request: RiskRequest,
        context: RiskContext,
        config: TurnoverVelocityLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        portfolio = context.portfolio_snapshot
        if portfolio is None:
            return None

        equity = portfolio.get("equity", _ZERO) if isinstance(portfolio, dict) else getattr(portfolio, "equity", _ZERO)
        if not isinstance(equity, Decimal):
            equity = Decimal(str(equity))

        if equity <= _ZERO:
            return None

        velocity = state.daily_turnover / equity

        if velocity > config.max_velocity:
            return _violation(
                check_type=RiskCheckType.TURNOVER_VELOCITY,
                severity=config.severity,
                message=(
                    f"Turnover velocity {velocity:.2f}x equity exceeds max {config.max_velocity}x"
                ),
                rule_id=config.rule_id,
                limit_value=config.max_velocity,
                actual_value=velocity,
            )
        return None


# ────────────────────────────────────────────────────────────────────────────
# Rule registry
# ────────────────────────────────────────────────────────────────────────────

RULE_REGISTRY: Dict[RiskCheckType, Type[RiskRule]] = {
    # Safety
    RiskCheckType.KILL_SWITCH: KillSwitchRule,
    RiskCheckType.EMERGENCY_HALT: EmergencyHaltRule,
    RiskCheckType.CIRCUIT_BREAKER: CircuitBreakerRule,

    # Pre-trade
    RiskCheckType.ORDER_QUANTITY: OrderQuantityRule,
    RiskCheckType.ORDER_VALUE: OrderValueRule,
    RiskCheckType.PRICE_BAND: PriceBandRule,
    RiskCheckType.TICK_SIZE: TickSizeRule,

    # Position
    RiskCheckType.MAX_POSITION_SIZE: MaxPositionSizeRule,
    RiskCheckType.INSTRUMENT_EXPOSURE: InstrumentExposureRule,
    RiskCheckType.NET_EXPOSURE: NetExposureRule,
    RiskCheckType.CONCENTRATION_LIMIT: ConcentrationRule,

    # Portfolio
    RiskCheckType.CASH_AVAILABILITY: CashAvailabilityRule,
    RiskCheckType.BUYING_POWER: BuyingPowerRule,
    RiskCheckType.PORTFOLIO_EXPOSURE: PortfolioExposureRule,

    # Daily controls
    RiskCheckType.DAILY_LOSS_LIMIT: DailyLossLimitRule,
    RiskCheckType.DAILY_PROFIT_TARGET_LOCK: DailyProfitTargetRule,
    RiskCheckType.MAX_TRADES_PER_DAY: MaxTradesPerDayRule,
    RiskCheckType.MAX_ORDERS_PER_MINUTE: MaxOrdersPerMinuteRule,

    # Monitoring
    RiskCheckType.DRAWDOWN: DrawdownRule,
    RiskCheckType.TURNOVER_VELOCITY: TurnoverVelocityRule,
}


def get_rule(check_type: RiskCheckType) -> RiskRule:
    """Look up a rule by its check type.

    Raises:
        KeyError: If no rule is registered for the given check type.
    """
    rule_class = RULE_REGISTRY.get(check_type)
    if rule_class is None:
        raise KeyError(f"No risk rule registered for check_type={check_type!r}")
    return rule_class()
