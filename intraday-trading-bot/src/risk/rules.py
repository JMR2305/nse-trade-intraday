"""
Risk rule protocols and concrete implementations.

All risk rules implement the RiskRule Protocol. Rules are stateless evaluators
that receive a RiskCheckContext and a RiskLimit, and return a RiskViolation
if the limit is breached, or None if the check passes.

Rules are deterministic and idempotent — same inputs always produce same outputs.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, Optional, Dict, Any, List
from datetime import datetime, timedelta
import hashlib
import json

from .contracts import (
    RiskViolation,
    RiskCheckContext,
    RiskCheckType,
    RiskSeverity,
    RiskLimit,
    OrderSizeLimit,
    PriceToleranceLimit,
    PositionLimit,
    PortfolioExposureLimit,
    DailyLossLimit,
    MessageThrottleLimit,
    DuplicateOrderLimit,
    SelfTradeLimit,
    PortfolioHeatLimit,
    DrawdownLimit,
    TurnoverVelocityLimit,
    RiskStateSnapshot,
)


class RiskRule(Protocol):
    """Protocol for all risk check rules."""

    def evaluate(
        self,
        context: RiskCheckContext,
        limit: RiskLimit,
        state: RiskStateSnapshot,
    ) -> Optional[RiskViolation]:
        ...


class OrderSizeRule:
    """Pre-trade: validates order quantity does not exceed max limit."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, OrderSizeLimit) or not limit.enabled:
            return None
        if context.order is None:
            return None

        order = context.order
        quantity = self._get_quantity(order)
        instrument = self._get_instrument(order)

        if quantity is None:
            return None
        if limit.instrument_token is not None and limit.instrument_token != instrument:
            return None
        if quantity > limit.max_quantity:
            return RiskViolation(
                check_type=RiskCheckType.ORDER_SIZE,
                severity=limit.severity,
                message=f"Order quantity {quantity} exceeds max {limit.max_quantity}",
                rule_id=limit.rule_id,
                limit_value=limit.max_quantity,
                actual_value=quantity,
                metadata={"instrument_token": instrument},
            )
        return None

    @staticmethod
    def _get_quantity(order: Any) -> Optional[Decimal]:
        qty = order.get("quantity") if isinstance(order, dict) else getattr(order, "quantity", None)
        if qty is not None and not isinstance(qty, Decimal):
            return Decimal(str(qty))
        return qty

    @staticmethod
    def _get_instrument(order: Any) -> Optional[str]:
        if isinstance(order, dict):
            return order.get("instrument_token")
        return getattr(order, "instrument_token", None)


class PriceToleranceRule:
    """Pre-trade: validates limit price is within tolerance of LTP."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, PriceToleranceLimit) or not limit.enabled:
            return None
        if context.order is None:
            return None

        order = context.order
        instrument = self._get_instrument(order)
        price = self._get_price(order)
        order_type = self._get_order_type(order)

        if price is None or order_type not in ("LIMIT", "SL", "SL_M"):
            return None
        if limit.instrument_token is not None and limit.instrument_token != instrument:
            return None

        ltp = context.market_prices.get(instrument)
        if ltp is None or ltp == 0:
            return None

        deviation_percent = (abs(price - ltp) / ltp) * Decimal("100")
        if deviation_percent > limit.max_deviation_percent:
            return RiskViolation(
                check_type=RiskCheckType.PRICE_TOLERANCE,
                severity=limit.severity,
                message=(
                    f"Price {price} deviates {deviation_percent:.2f}% from LTP {ltp}, "
                    f"max allowed {limit.max_deviation_percent}%"
                ),
                rule_id=limit.rule_id,
                limit_value=limit.max_deviation_percent,
                actual_value=deviation_percent,
                metadata={"instrument_token": instrument, "ltp": ltp, "price": price},
            )
        return None

    @staticmethod
    def _get_instrument(order: Any) -> Optional[str]:
        if isinstance(order, dict):
            return order.get("instrument_token")
        return getattr(order, "instrument_token", None)

    @staticmethod
    def _get_price(order: Any) -> Optional[Decimal]:
        p = order.get("price") if isinstance(order, dict) else getattr(order, "price", None)
        if p is not None and not isinstance(p, Decimal):
            return Decimal(str(p))
        return p

    @staticmethod
    def _get_order_type(order: Any) -> Optional[str]:
        if isinstance(order, dict):
            return order.get("order_type")
        ot = getattr(order, "order_type", None)
        return str(ot) if ot is not None else None


class PositionLimitRule:
    """Pre-trade: validates new order won't exceed position limits."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, PositionLimit) or not limit.enabled:
            return None
        if context.order is None:
            return None

        order = context.order
        instrument = self._get_instrument(order)
        quantity = self._get_quantity(order)
        side = self._get_side(order)

        if instrument is None or quantity is None or side is None:
            return None
        if limit.instrument_token != instrument:
            return None

        current_pos = context.position_snapshots.get(instrument)
        current_qty = Decimal("0")
        if current_pos is not None:
            raw = current_pos.get("net_quantity", Decimal("0")) if isinstance(current_pos, dict) else getattr(current_pos, "net_quantity", Decimal("0"))
            current_qty = Decimal(str(raw)) if not isinstance(raw, Decimal) else raw

        side_multiplier = Decimal("1") if side.upper() == "BUY" else Decimal("-1")
        projected_qty = current_qty + (quantity * side_multiplier)

        if projected_qty > limit.max_long_quantity:
            return RiskViolation(
                check_type=RiskCheckType.POSITION_LIMIT,
                severity=limit.severity,
                message=f"Projected long position {projected_qty} exceeds limit {limit.max_long_quantity} for {instrument}",
                rule_id=limit.rule_id,
                limit_value=limit.max_long_quantity,
                actual_value=projected_qty,
                metadata={"instrument_token": instrument, "current_quantity": current_qty, "projected_quantity": projected_qty},
            )
        if projected_qty < -limit.max_short_quantity:
            return RiskViolation(
                check_type=RiskCheckType.POSITION_LIMIT,
                severity=limit.severity,
                message=f"Projected short position {abs(projected_qty)} exceeds limit {limit.max_short_quantity} for {instrument}",
                rule_id=limit.rule_id,
                limit_value=limit.max_short_quantity,
                actual_value=abs(projected_qty),
                metadata={"instrument_token": instrument, "current_quantity": current_qty, "projected_quantity": projected_qty},
            )
        return None

    @staticmethod
    def _get_instrument(order: Any) -> Optional[str]:
        if isinstance(order, dict):
            return order.get("instrument_token")
        return getattr(order, "instrument_token", None)

    @staticmethod
    def _get_quantity(order: Any) -> Optional[Decimal]:
        qty = order.get("quantity") if isinstance(order, dict) else getattr(order, "quantity", None)
        if qty is not None and not isinstance(qty, Decimal):
            return Decimal(str(qty))
        return qty

    @staticmethod
    def _get_side(order: Any) -> Optional[str]:
        if isinstance(order, dict):
            return order.get("side")
        side = getattr(order, "side", None)
        return str(side).upper() if side is not None else None


class PortfolioExposureRule:
    """Pre-trade: validates total portfolio exposure doesn't exceed equity %."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, PortfolioExposureLimit) or not limit.enabled:
            return None
        if context.portfolio_snapshot is None:
            return None

        portfolio = context.portfolio_snapshot
        equity = portfolio.get("equity", Decimal("0")) if isinstance(portfolio, dict) else getattr(portfolio, "equity", Decimal("0"))
        total_market_value = portfolio.get("total_market_value", Decimal("0")) if isinstance(portfolio, dict) else getattr(portfolio, "total_market_value", Decimal("0"))
        if not isinstance(equity, Decimal):
            equity = Decimal(str(equity))
        if not isinstance(total_market_value, Decimal):
            total_market_value = Decimal(str(total_market_value))

        if equity <= 0:
            return None

        exposure_percent = (total_market_value / equity) * Decimal("100")
        if exposure_percent > limit.max_exposure_percent:
            return RiskViolation(
                check_type=RiskCheckType.PORTFOLIO_EXPOSURE,
                severity=limit.severity,
                message=f"Portfolio exposure {exposure_percent:.2f}% exceeds limit {limit.max_exposure_percent}%",
                rule_id=limit.rule_id,
                limit_value=limit.max_exposure_percent,
                actual_value=exposure_percent,
                metadata={"equity": equity, "market_value": total_market_value},
            )
        return None


class DailyLossLimitRule:
    """Pre-trade: blocks new orders if daily loss limit is breached."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, DailyLossLimit) or not limit.enabled:
            return None

        daily_pnl = state.daily_realized_pnl
        if daily_pnl >= 0:
            return None

        loss_amount = abs(daily_pnl)
        if loss_amount >= limit.max_daily_loss:
            return RiskViolation(
                check_type=RiskCheckType.DAILY_LOSS_LIMIT,
                severity=RiskSeverity.FATAL,
                message=f"Daily loss {loss_amount} has reached limit {limit.max_daily_loss}. Trading halted.",
                rule_id=limit.rule_id,
                limit_value=limit.max_daily_loss,
                actual_value=loss_amount,
                metadata={"daily_pnl": daily_pnl},
            )

        warning_threshold = limit.max_daily_loss * (limit.warning_threshold_percent / Decimal("100"))
        if loss_amount >= warning_threshold:
            return RiskViolation(
                check_type=RiskCheckType.DAILY_LOSS_LIMIT,
                severity=RiskSeverity.WARNING,
                message=f"Daily loss {loss_amount} at {limit.warning_threshold_percent}% of limit {limit.max_daily_loss}",
                rule_id=limit.rule_id,
                limit_value=warning_threshold,
                actual_value=loss_amount,
                metadata={"daily_pnl": daily_pnl, "threshold": warning_threshold},
            )
        return None


class MessageThrottleRule:
    """Pre-trade: throttles message rate per scope."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, MessageThrottleLimit) or not limit.enabled:
            return None

        key = self._build_throttle_key(context, limit)
        if key is None:
            return None

        count = state.message_counts.get(key, 0)
        if count >= limit.max_messages:
            return RiskViolation(
                check_type=RiskCheckType.MESSAGE_THROTTLE,
                severity=limit.severity,
                message=f"Message rate {count} exceeds limit {limit.max_messages} in {limit.window_seconds}s window for {limit.scope}",
                rule_id=limit.rule_id,
                limit_value=Decimal(limit.max_messages),
                actual_value=Decimal(count),
                metadata={"throttle_key": key, "window_seconds": limit.window_seconds},
            )
        return None

    def _build_throttle_key(self, context, limit: MessageThrottleLimit) -> Optional[str]:
        if limit.scope == "account":
            return f"account:{context.account_id}"
        elif limit.scope == "instrument":
            instrument = self._get_instrument(context.order)
            if instrument is None:
                return None
            if limit.instrument_token and limit.instrument_token != instrument:
                return None
            return f"instrument:{instrument}"
        elif limit.scope == "strategy":
            strategy_id = "default"
            if context.order is not None:
                strategy_id = context.order.get("strategy_id", "default") if isinstance(context.order, dict) else getattr(context.order, "strategy_id", "default")
            return f"strategy:{strategy_id}"
        return None

    @staticmethod
    def _get_instrument(order: Any) -> Optional[str]:
        if order is None:
            return None
        if isinstance(order, dict):
            return order.get("instrument_token")
        return getattr(order, "instrument_token", None)


class DuplicateOrderRule:
    """Pre-trade: prevents duplicate orders within a time window."""

    def __init__(self):
        # Instance-level dedup store: {account_id: [(hash, timestamp), ...]}
        self._seen_orders: Dict[str, List[tuple]] = {}

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, DuplicateOrderLimit) or not limit.enabled:
            return None
        if context.order is None:
            return None

        order_hash = self._hash_order(context.order, limit.compare_fields)
        account_id = context.account_id
        now = context.check_timestamp
        window = timedelta(seconds=limit.window_seconds)

        # Clean old entries
        account_seen = self._seen_orders.get(account_id, [])
        self._seen_orders[account_id] = [
            (h, ts) for h, ts in account_seen
            if now - ts <= window
        ]

        # Check for duplicate
        for h, _ in self._seen_orders[account_id]:
            if h == order_hash:
                return RiskViolation(
                    check_type=RiskCheckType.DUPLICATE_ORDER,
                    severity=limit.severity,
                    message=f"Duplicate order detected within {limit.window_seconds}s window",
                    rule_id=limit.rule_id,
                    metadata={"window_seconds": limit.window_seconds},
                )

        # Record this order
        self._seen_orders[account_id].append((order_hash, now))
        return None

    def _hash_order(self, order: Any, fields: List[str]) -> str:
        if isinstance(order, dict):
            values = {f: str(order.get(f, "")) for f in fields}
        else:
            values = {f: str(getattr(order, f, "")) for f in fields}
        canonical = json.dumps(values, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def reset(self) -> None:
        """Clear all dedup state — used for deterministic replay."""
        self._seen_orders.clear()


class SelfTradeRule:
    """Pre-trade: prevents crossing with own open orders."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, SelfTradeLimit) or not limit.enabled:
            return None
        if context.order is None or not context.open_orders:
            return None

        order = context.order
        instrument = self._get_instrument(order)
        side = self._get_side(order)
        price = self._get_price(order)

        if instrument is None or side is None or price is None:
            return None
        if limit.instrument_token and limit.instrument_token != instrument:
            return None

        opposite_side = "SELL" if side.upper() == "BUY" else "BUY"
        for open_order in context.open_orders:
            open_instrument = self._get_instrument(open_order)
            open_side = self._get_side(open_order)
            open_price = self._get_price(open_order)

            if open_instrument != instrument or open_side != opposite_side:
                continue
            if self._would_cross(side, price, open_side, open_price):
                return RiskViolation(
                    check_type=RiskCheckType.SELF_TRADE,
                    severity=limit.severity,
                    message=f"Self-trade detected: {side} {price} crosses {open_side} {open_price}",
                    rule_id=limit.rule_id,
                    metadata={"instrument_token": instrument, "new_order_side": side, "new_order_price": price, "open_order_price": open_price},
                )
        return None

    @staticmethod
    def _would_cross(side1: str, price1: Decimal, side2: str, price2: Decimal) -> bool:
        if side1.upper() == "BUY" and side2.upper() == "SELL":
            return price1 >= price2
        elif side1.upper() == "SELL" and side2.upper() == "BUY":
            return price1 <= price2
        return False

    @staticmethod
    def _get_instrument(order: Any) -> Optional[str]:
        if isinstance(order, dict):
            return order.get("instrument_token")
        return getattr(order, "instrument_token", None)

    @staticmethod
    def _get_side(order: Any) -> Optional[str]:
        if isinstance(order, dict):
            return order.get("side")
        side = getattr(order, "side", None)
        return str(side).upper() if side is not None else None

    @staticmethod
    def _get_price(order: Any) -> Optional[Decimal]:
        p = order.get("price") if isinstance(order, dict) else getattr(order, "price", None)
        if p is not None and not isinstance(p, Decimal):
            return Decimal(str(p))
        return p


class PortfolioHeatRule:
    """Post-trade: monitors portfolio concentration."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, PortfolioHeatLimit) or not limit.enabled:
            return None
        if context.portfolio_snapshot is None:
            return None

        portfolio = context.portfolio_snapshot
        equity = portfolio.get("equity", Decimal("0")) if isinstance(portfolio, dict) else getattr(portfolio, "equity", Decimal("0"))
        if not isinstance(equity, Decimal):
            equity = Decimal(str(equity))
        if equity <= 0:
            return None

        for instrument, position in context.position_snapshots.items():
            market_value = position.get("market_value", Decimal("0")) if isinstance(position, dict) else getattr(position, "market_value", Decimal("0"))
            if not isinstance(market_value, Decimal):
                market_value = Decimal(str(market_value))
            concentration = (market_value / equity) * Decimal("100")
            if concentration > limit.max_concentration_percent:
                return RiskViolation(
                    check_type=RiskCheckType.PORTFOLIO_HEAT,
                    severity=limit.severity,
                    message=f"Concentration in {instrument} {concentration:.2f}% exceeds limit {limit.max_concentration_percent}%",
                    rule_id=limit.rule_id,
                    limit_value=limit.max_concentration_percent,
                    actual_value=concentration,
                    metadata={"instrument_token": instrument, "equity": equity},
                )
        return None


class DrawdownRule:
    """Post-trade: monitors portfolio drawdown from peak equity."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, DrawdownLimit) or not limit.enabled:
            return None
        if context.portfolio_snapshot is None:
            return None

        portfolio = context.portfolio_snapshot
        equity = portfolio.get("equity", Decimal("0")) if isinstance(portfolio, dict) else getattr(portfolio, "equity", Decimal("0"))
        if not isinstance(equity, Decimal):
            equity = Decimal(str(equity))

        peak = state.peak_equity
        if peak <= 0:
            return None

        drawdown = ((peak - equity) / peak) * Decimal("100")
        if drawdown >= limit.max_drawdown_percent:
            return RiskViolation(
                check_type=RiskCheckType.DRAWDOWN,
                severity=RiskSeverity.FATAL,
                message=f"Drawdown {drawdown:.2f}% has reached max {limit.max_drawdown_percent}%. Trading halted.",
                rule_id=limit.rule_id,
                limit_value=limit.max_drawdown_percent,
                actual_value=drawdown,
                metadata={"peak_equity": peak, "current_equity": equity},
            )

        warning_threshold = limit.max_drawdown_percent * (limit.warning_threshold_percent / Decimal("100"))
        if drawdown >= warning_threshold:
            return RiskViolation(
                check_type=RiskCheckType.DRAWDOWN,
                severity=RiskSeverity.WARNING,
                message=f"Drawdown {drawdown:.2f}% at {limit.warning_threshold_percent}% of limit {limit.max_drawdown_percent}%",
                rule_id=limit.rule_id,
                limit_value=warning_threshold,
                actual_value=drawdown,
                metadata={"peak_equity": peak, "current_equity": equity},
            )
        return None


class TurnoverVelocityRule:
    """Post-trade: monitors turnover velocity relative to equity."""

    def evaluate(self, context, limit, state) -> Optional[RiskViolation]:
        if not isinstance(limit, TurnoverVelocityLimit) or not limit.enabled:
            return None
        if context.portfolio_snapshot is None:
            return None

        portfolio = context.portfolio_snapshot
        equity = portfolio.get("equity", Decimal("0")) if isinstance(portfolio, dict) else getattr(portfolio, "equity", Decimal("0"))
        if not isinstance(equity, Decimal):
            equity = Decimal(str(equity))
        if equity <= 0:
            return None

        velocity = state.daily_turnover / equity
        if velocity > limit.max_velocity:
            return RiskViolation(
                check_type=RiskCheckType.TURNOVER_VELOCITY,
                severity=limit.severity,
                message=f"Turnover velocity {velocity:.2f} exceeds limit {limit.max_velocity} (turnover {state.daily_turnover} / equity {equity})",
                rule_id=limit.rule_id,
                limit_value=limit.max_velocity,
                actual_value=velocity,
                metadata={"daily_turnover": state.daily_turnover, "equity": equity},
            )
        return None


# Registry mapping check types to rule implementations
RULE_REGISTRY: Dict[RiskCheckType, Any] = {
    RiskCheckType.ORDER_SIZE: OrderSizeRule(),
    RiskCheckType.PRICE_TOLERANCE: PriceToleranceRule(),
    RiskCheckType.POSITION_LIMIT: PositionLimitRule(),
    RiskCheckType.PORTFOLIO_EXPOSURE: PortfolioExposureRule(),
    RiskCheckType.DAILY_LOSS_LIMIT: DailyLossLimitRule(),
    RiskCheckType.MESSAGE_THROTTLE: MessageThrottleRule(),
    RiskCheckType.DUPLICATE_ORDER: DuplicateOrderRule(),
    RiskCheckType.SELF_TRADE: SelfTradeRule(),
    RiskCheckType.PORTFOLIO_HEAT: PortfolioHeatRule(),
    RiskCheckType.DRAWDOWN: DrawdownRule(),
    RiskCheckType.TURNOVER_VELOCITY: TurnoverVelocityRule(),
}
