"""
Risk Engine domain contracts — Pydantic v2 compatible.

All domain types are immutable Pydantic models with frozen=True.
Decimal is used for all monetary quantities.

This module defines the canonical contracts for the Batch 8 Risk Engine:
- RiskRequest: the input to a risk check
- RiskResult: the output of a risk check (approved + violations)
- RiskContext: the evaluation context (market data, portfolio state)
- RiskConfiguration: limit and rule configurations
- RiskViolation: a single breached limit
- RiskAudit: immutable audit record of every risk decision
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, List, Any, Literal
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator


class RiskSeverity(str, Enum):
    """Severity classification for risk violations."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"


class RiskCheckType(str, Enum):
    """Types of risk checks performed by the Risk Engine."""
    # Pre-trade Risk
    ORDER_QUANTITY = "ORDER_QUANTITY"
    ORDER_VALUE = "ORDER_VALUE"
    TICK_SIZE = "TICK_SIZE"
    PRICE_BAND = "PRICE_BAND"

    # Position Risk
    MAX_POSITION_SIZE = "MAX_POSITION_SIZE"
    INSTRUMENT_EXPOSURE = "INSTRUMENT_EXPOSURE"
    NET_EXPOSURE = "NET_EXPOSURE"
    CONCENTRATION_LIMIT = "CONCENTRATION_LIMIT"

    # Portfolio Risk
    CASH_AVAILABILITY = "CASH_AVAILABILITY"
    BUYING_POWER = "BUYING_POWER"
    PORTFOLIO_EXPOSURE = "PORTFOLIO_EXPOSURE"
    MARGIN_AVAILABILITY = "MARGIN_AVAILABILITY"

    # Daily Controls
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    DAILY_PROFIT_TARGET_LOCK = "DAILY_PROFIT_TARGET_LOCK"
    MAX_TRADES_PER_DAY = "MAX_TRADES_PER_DAY"
    MAX_ORDERS_PER_MINUTE = "MAX_ORDERS_PER_MINUTE"

    # Safety
    KILL_SWITCH = "KILL_SWITCH"
    EMERGENCY_HALT = "EMERGENCY_HALT"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"

    # Additional checks
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    SELF_TRADE = "SELF_TRADE"
    DRAWDOWN = "DRAWDOWN"
    TURNOVER_VELOCITY = "TURNOVER_VELOCITY"


class RiskViolation(BaseModel, frozen=True):
    """Immutable record of a single risk rule violation."""

    check_type: RiskCheckType = Field(..., description="Type of risk check that failed")
    severity: RiskSeverity = Field(..., description="Severity of the violation")
    message: str = Field(..., description="Human-readable violation description")
    rule_id: str = Field(..., description="Identifier of the rule that was violated")
    limit_value: Optional[Decimal] = Field(None, description="The limit threshold that was breached")
    actual_value: Optional[Decimal] = Field(None, description="The actual value that breached the limit")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context")

    @field_validator("limit_value", "actual_value", mode="before")
    @classmethod
    def _decimal_precision(cls, v):
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class RiskResult(BaseModel, frozen=True):
    """Immutable result of a risk check.

    The Risk Engine returns this for every order evaluation.
    approved=True means the order may proceed to the Execution Engine.
    approved=False means the order is rejected; violations explain why.
    """

    approved: bool = Field(..., description="True if the order passes all risk checks")
    violations: List[RiskViolation] = Field(default_factory=list, description="All violations found")
    check_timestamp: datetime = Field(..., description="Timestamp when the check was performed")
    order_id: Optional[str] = Field(None, description="Order identifier if applicable")
    account_id: str = Field(..., description="Account being evaluated")

    @property
    def is_allowed(self) -> bool:
        return self.approved

    @property
    def is_blocked(self) -> bool:
        return not self.approved

    @property
    def has_critical(self) -> bool:
        return any(
            v.severity in (RiskSeverity.CRITICAL, RiskSeverity.FATAL)
            for v in self.violations
        )

    @property
    def action(self) -> str:
        if not self.violations:
            return "ALLOW"
        if any(v.severity == RiskSeverity.FATAL for v in self.violations):
            return "KILL_SWITCH"
        if any(v.severity == RiskSeverity.CRITICAL for v in self.violations):
            return "BLOCK"
        return "WARN"


class RiskRequest(BaseModel, frozen=True):
    """A request to evaluate an order for risk."""

    account_id: str = Field(..., description="Account submitting the order")
    order: Any = Field(..., description="The order to evaluate (ExecutionOrder or dict)")
    check_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp for this check"
    )

    @field_validator("check_timestamp", mode="before")
    @classmethod
    def _ensure_datetime(cls, v):
        if v is None:
            return datetime.now(timezone.utc)
        return v


class RiskContext(BaseModel, frozen=True):
    """Contextual market and portfolio state for risk evaluation."""

    account_id: str = Field(..., description="Account being evaluated")
    portfolio_snapshot: Optional[Any] = Field(None, description="Current PortfolioSnapshot")
    position_snapshots: Dict[str, Any] = Field(default_factory=dict)
    market_prices: Dict[str, Decimal] = Field(default_factory=dict)
    open_orders: List[Any] = Field(default_factory=list)
    order: Optional[Any] = Field(None, description="The order being evaluated")

    @field_validator("market_prices", mode="before")
    @classmethod
    def _decimal_prices(cls, v):
        result = {}
        for k, val in v.items():
            if val is not None and not isinstance(val, Decimal):
                result[k] = Decimal(str(val))
            else:
                result[k] = val
        return result


class RiskConfiguration(BaseModel, frozen=True):
    """Base configuration for a single risk rule."""

    rule_id: str = Field(..., description="Unique rule identifier")
    enabled: bool = Field(default=True, description="Whether this rule is active")
    severity: RiskSeverity = Field(default=RiskSeverity.CRITICAL, description="Severity when violated")
    check_type: RiskCheckType = Field(..., description="The type of check this rule performs")
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Pre-trade Risk Configurations ──

class OrderQuantityLimit(RiskConfiguration, frozen=True):
    """Maximum quantity allowed per single order."""

    max_quantity: Decimal = Field(..., gt=0, description="Maximum order quantity")
    instrument_token: Optional[str] = Field(None)
    check_type: Literal[RiskCheckType.ORDER_QUANTITY] = RiskCheckType.ORDER_QUANTITY

    @field_validator("max_quantity", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class OrderValueLimit(RiskConfiguration, frozen=True):
    """Maximum notional value allowed per single order."""

    max_value: Decimal = Field(..., gt=0, description="Maximum order notional value")
    instrument_token: Optional[str] = Field(None)
    check_type: Literal[RiskCheckType.ORDER_VALUE] = RiskCheckType.ORDER_VALUE

    @field_validator("max_value", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class TickSizeLimit(RiskConfiguration, frozen=True):
    """Order price must be a multiple of the instrument's tick size."""

    tick_size: Decimal = Field(..., gt=0)
    instrument_token: Optional[str] = Field(None)
    check_type: Literal[RiskCheckType.TICK_SIZE] = RiskCheckType.TICK_SIZE

    @field_validator("tick_size", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class PriceBandLimit(RiskConfiguration, frozen=True):
    """Order price must be within a percentage band of the reference price."""

    max_deviation_percent: Decimal = Field(..., gt=0)
    instrument_token: Optional[str] = Field(None)
    check_type: Literal[RiskCheckType.PRICE_BAND] = RiskCheckType.PRICE_BAND

    @field_validator("max_deviation_percent", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


# ── Position Risk Configurations ──

class MaxPositionSizeLimit(RiskConfiguration, frozen=True):
    """Maximum absolute position size per instrument."""

    max_long_quantity: Decimal = Field(..., ge=0)
    max_short_quantity: Decimal = Field(..., ge=0)
    instrument_token: str = Field(..., description="Instrument identifier")
    check_type: Literal[RiskCheckType.MAX_POSITION_SIZE] = RiskCheckType.MAX_POSITION_SIZE

    @field_validator("max_long_quantity", "max_short_quantity", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class InstrumentExposureLimit(RiskConfiguration, frozen=True):
    """Maximum notional exposure per instrument."""

    max_exposure: Decimal = Field(..., gt=0)
    instrument_token: str = Field(...)
    check_type: Literal[RiskCheckType.INSTRUMENT_EXPOSURE] = RiskCheckType.INSTRUMENT_EXPOSURE

    @field_validator("max_exposure", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class NetExposureLimit(RiskConfiguration, frozen=True):
    """Maximum net long/short exposure across all instruments."""

    max_net_long: Decimal = Field(..., ge=0)
    max_net_short: Decimal = Field(..., ge=0)
    check_type: Literal[RiskCheckType.NET_EXPOSURE] = RiskCheckType.NET_EXPOSURE

    @field_validator("max_net_long", "max_net_short", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class ConcentrationLimit(RiskConfiguration, frozen=True):
    """Maximum portfolio concentration in a single instrument."""

    max_concentration_percent: Decimal = Field(..., gt=0, le=100)
    check_type: Literal[RiskCheckType.CONCENTRATION_LIMIT] = RiskCheckType.CONCENTRATION_LIMIT

    @field_validator("max_concentration_percent", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


# ── Portfolio Risk Configurations ──

class CashAvailabilityLimit(RiskConfiguration, frozen=True):
    check_type: Literal[RiskCheckType.CASH_AVAILABILITY] = RiskCheckType.CASH_AVAILABILITY


class BuyingPowerLimit(RiskConfiguration, frozen=True):
    check_type: Literal[RiskCheckType.BUYING_POWER] = RiskCheckType.BUYING_POWER


class PortfolioExposureLimit(RiskConfiguration, frozen=True):
    """Maximum total portfolio exposure as percentage of equity."""

    max_exposure_percent: Decimal = Field(..., gt=0, le=100)
    check_type: Literal[RiskCheckType.PORTFOLIO_EXPOSURE] = RiskCheckType.PORTFOLIO_EXPOSURE

    @field_validator("max_exposure_percent", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class MarginAvailabilityLimit(RiskConfiguration, frozen=True):
    check_type: Literal[RiskCheckType.MARGIN_AVAILABILITY] = RiskCheckType.MARGIN_AVAILABILITY


# ── Daily Control Configurations ──

class DailyLossLimit(RiskConfiguration, frozen=True):
    """Maximum realized loss allowed in a trading day."""

    max_daily_loss: Decimal = Field(..., gt=0)
    warning_threshold_percent: Decimal = Field(default=Decimal("80.0"))
    check_type: Literal[RiskCheckType.DAILY_LOSS_LIMIT] = RiskCheckType.DAILY_LOSS_LIMIT

    @field_validator("max_daily_loss", "warning_threshold_percent", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class DailyProfitTargetLock(RiskConfiguration, frozen=True):
    """Lock trading after reaching daily profit target."""

    profit_target: Decimal = Field(..., gt=0)
    check_type: Literal[RiskCheckType.DAILY_PROFIT_TARGET_LOCK] = RiskCheckType.DAILY_PROFIT_TARGET_LOCK

    @field_validator("profit_target", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class MaxTradesPerDayLimit(RiskConfiguration, frozen=True):
    """Maximum number of trades per day."""

    max_trades: int = Field(..., gt=0)
    check_type: Literal[RiskCheckType.MAX_TRADES_PER_DAY] = RiskCheckType.MAX_TRADES_PER_DAY


class MaxOrdersPerMinuteLimit(RiskConfiguration, frozen=True):
    """Maximum number of orders per minute."""

    max_orders: int = Field(..., gt=0)
    window_seconds: int = Field(default=60, gt=0)
    scope: str = Field(default="account")
    instrument_token: Optional[str] = Field(None)
    check_type: Literal[RiskCheckType.MAX_ORDERS_PER_MINUTE] = RiskCheckType.MAX_ORDERS_PER_MINUTE


# ── Safety Configurations ──

class KillSwitchLimit(RiskConfiguration, frozen=True):
    """Emergency kill switch — when active, blocks all new orders."""

    allow_risk_reducing: bool = Field(default=False)
    check_type: Literal[RiskCheckType.KILL_SWITCH] = RiskCheckType.KILL_SWITCH


class EmergencyHaltLimit(RiskConfiguration, frozen=True):
    check_type: Literal[RiskCheckType.EMERGENCY_HALT] = RiskCheckType.EMERGENCY_HALT


class CircuitBreakerLimit(RiskConfiguration, frozen=True):
    """Circuit breaker — halt trading after rapid portfolio decline."""

    max_decline_percent: Decimal = Field(..., gt=0, le=100)
    lookback_seconds: int = Field(default=300, gt=0)
    check_type: Literal[RiskCheckType.CIRCUIT_BREAKER] = RiskCheckType.CIRCUIT_BREAKER

    @field_validator("max_decline_percent", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


# ── Additional Configurations ──

class DuplicateOrderLimit(RiskConfiguration, frozen=True):
    window_seconds: int = Field(default=5, gt=0)
    check_type: Literal[RiskCheckType.DUPLICATE_ORDER] = RiskCheckType.DUPLICATE_ORDER


class SelfTradeLimit(RiskConfiguration, frozen=True):
    check_type: Literal[RiskCheckType.SELF_TRADE] = RiskCheckType.SELF_TRADE


class DrawdownLimit(RiskConfiguration, frozen=True):
    """Monitor portfolio drawdown from peak equity."""

    max_drawdown_percent: Decimal = Field(..., gt=0, le=100)
    check_type: Literal[RiskCheckType.DRAWDOWN] = RiskCheckType.DRAWDOWN

    @field_validator("max_drawdown_percent", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class TurnoverVelocityLimit(RiskConfiguration, frozen=True):
    """Monitor turnover velocity relative to equity."""

    max_velocity: Decimal = Field(..., gt=0)
    check_type: Literal[RiskCheckType.TURNOVER_VELOCITY] = RiskCheckType.TURNOVER_VELOCITY

    @field_validator("max_velocity", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


# ── Audit ──

class RiskAudit(BaseModel, frozen=True):
    """Immutable audit record of a risk engine decision."""

    audit_id: str = Field(...)
    account_id: str = Field(...)
    order_id: Optional[str] = Field(None)
    approved: bool = Field(...)
    violations: List[RiskViolation] = Field(default_factory=list)
    check_timestamp: datetime = Field(...)
    context_snapshot: Dict[str, Any] = Field(default_factory=dict)


# ── State Snapshot ──

class RiskStateSnapshot(BaseModel, frozen=True):
    """Point-in-time snapshot of risk engine state for an account."""

    account_id: str = Field(...)
    snapshot_timestamp: datetime = Field(...)
    daily_realized_pnl: Decimal = Field(default=Decimal("0"))
    daily_turnover: Decimal = Field(default=Decimal("0"))
    trade_count: int = Field(default=0)
    order_count: int = Field(default=0)
    peak_equity: Decimal = Field(default=Decimal("0"))
    message_counts: Dict[str, int] = Field(default_factory=dict)
    kill_switch_active: bool = Field(default=False)
    kill_switch_reason: Optional[str] = Field(None)
    emergency_halt_active: bool = Field(default=False)
    circuit_breaker_triggered: bool = Field(default=False)

    @field_validator("daily_realized_pnl", "daily_turnover", "peak_equity", mode="before")
    @classmethod
    def _to_decimal(cls, v):
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v
