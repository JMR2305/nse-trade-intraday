"""
Risk Engine domain contracts.

All domain types are immutable Pydantic models with frozen=True.
Decimal is used for all monetary quantities.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum, auto
from typing import Optional, Dict, List, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator


class RiskSeverity(str, Enum):
    """Severity classification for risk violations."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"


class RiskAction(str, Enum):
    """Action recommended by the Risk Engine."""
    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"
    KILL_SWITCH = "KILL_SWITCH"


class RiskCheckType(str, Enum):
    """Types of risk checks performed."""
    ORDER_SIZE = "ORDER_SIZE"
    PRICE_TOLERANCE = "PRICE_TOLERANCE"
    POSITION_LIMIT = "POSITION_LIMIT"
    PORTFOLIO_EXPOSURE = "PORTFOLIO_EXPOSURE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MESSAGE_THROTTLE = "MESSAGE_THROTTLE"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    SELF_TRADE = "SELF_TRADE"
    PORTFOLIO_HEAT = "PORTFOLIO_HEAT"
    DRAWDOWN = "DRAWDOWN"
    TURNOVER_VELOCITY = "TURNOVER_VELOCITY"
    KILL_SWITCH = "KILL_SWITCH"


class RiskViolation(BaseModel, frozen=True):
    """Immutable record of a single risk rule violation."""

    check_type: RiskCheckType = Field(..., description="Type of risk check that failed")
    severity: RiskSeverity = Field(..., description="Severity of the violation")
    message: str = Field(..., description="Human-readable violation description")
    rule_id: str = Field(..., description="Identifier of the rule that was violated")
    limit_value: Optional[Decimal] = Field(None, description="The limit threshold that was breached")
    actual_value: Optional[Decimal] = Field(None, description="The actual value that breached the limit")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context")

    @validator("limit_value", "actual_value", pre=True, always=True)
    def _decimal_precision(cls, v):
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class RiskDecision(BaseModel, frozen=True):
    """Immutable decision produced by the Risk Engine for a single order or event."""

    action: RiskAction = Field(..., description="Final recommended action")
    violations: List[RiskViolation] = Field(default_factory=list, description="All violations found")
    check_timestamp: datetime = Field(..., description="Timestamp when the check was performed")
    order_id: Optional[str] = Field(None, description="Order identifier if applicable")
    account_id: str = Field(..., description="Account being evaluated")

    @property
    def is_allowed(self) -> bool:
        """True if the action is ALLOW (no violations or only INFO-level)."""
        return self.action == RiskAction.ALLOW

    @property
    def is_blocked(self) -> bool:
        """True if the action is BLOCK or KILL_SWITCH."""
        return self.action in (RiskAction.BLOCK, RiskAction.KILL_SWITCH)

    @property
    def has_critical(self) -> bool:
        """True if any CRITICAL or FATAL violation exists."""
        return any(
            v.severity in (RiskSeverity.CRITICAL, RiskSeverity.FATAL)
            for v in self.violations
        )


class RiskLimit(BaseModel, frozen=True):
    """Base model for all risk limit configurations."""

    rule_id: str = Field(..., description="Unique rule identifier")
    enabled: bool = Field(default=True, description="Whether this rule is active")
    severity: RiskSeverity = Field(default=RiskSeverity.CRITICAL, description="Severity when violated")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Rule-specific config")


class OrderSizeLimit(RiskLimit, frozen=True):
    """Maximum quantity allowed per single order."""

    max_quantity: Decimal = Field(..., gt=0, description="Maximum order quantity")
    instrument_token: Optional[str] = Field(None, description="Apply to specific instrument only")

    @validator("max_quantity", pre=True)
    def _to_decimal(cls, v):
        if not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class PriceToleranceLimit(RiskLimit, frozen=True):
    """Maximum price deviation from reference price (LTP)."""

    max_deviation_percent: Decimal = Field(..., gt=0, description="Max % deviation from LTP")
    instrument_token: Optional[str] = Field(None, description="Apply to specific instrument only")

    @validator("max_deviation_percent", pre=True)
    def _to_decimal(cls, v):
        if not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class PositionLimit(RiskLimit, frozen=True):
    """Maximum long or short position per instrument."""

    max_long_quantity: Decimal = Field(..., ge=0, description="Max long position")
    max_short_quantity: Decimal = Field(..., ge=0, description="Max short position")
    instrument_token: str = Field(..., description="Instrument identifier")

    @validator("max_long_quantity", "max_short_quantity", pre=True)
    def _to_decimal(cls, v):
        if not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class PortfolioExposureLimit(RiskLimit, frozen=True):
    """Maximum portfolio exposure as percentage of total equity."""

    max_exposure_percent: Decimal = Field(..., gt=0, le=100, description="Max % of equity")
    instrument_token: Optional[str] = Field(None, description="Specific instrument or None for total")

    @validator("max_exposure_percent", pre=True)
    def _to_decimal(cls, v):
        if not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class DailyLossLimit(RiskLimit, frozen=True):
    """Maximum realized loss allowed in a trading day."""

    max_daily_loss: Decimal = Field(..., gt=0, description="Max daily loss amount")
    warning_threshold_percent: Decimal = Field(
        default=Decimal("80.0"),
        description="Warning at % of max loss"
    )

    @validator("max_daily_loss", "warning_threshold_percent", pre=True)
    def _to_decimal(cls, v):
        if not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class MessageThrottleLimit(RiskLimit, frozen=True):
    """Maximum number of messages (orders) per time window."""

    max_messages: int = Field(..., gt=0, description="Max messages in window")
    window_seconds: int = Field(..., gt=0, description="Time window in seconds")
    scope: str = Field(default="account", description="Throttle scope: account, instrument, strategy")
    instrument_token: Optional[str] = Field(None, description="Instrument if scope=instrument")


class DuplicateOrderLimit(RiskLimit, frozen=True):
    """Prevent duplicate orders within a time window."""

    window_seconds: int = Field(default=5, gt=0, description="Deduplication window")
    compare_fields: List[str] = Field(
        default_factory=lambda: ["instrument_token", "side", "quantity", "price"],
        description="Fields to compare for duplication"
    )


class SelfTradeLimit(RiskLimit, frozen=True):
    """Prevent crossing with own open orders."""

    instrument_token: Optional[str] = Field(None, description="Specific instrument or all")


class PortfolioHeatLimit(RiskLimit, frozen=True):
    """Alert when portfolio concentration exceeds threshold."""

    max_concentration_percent: Decimal = Field(..., gt=0, le=100, description="Max % in single instrument")

    @validator("max_concentration_percent", pre=True)
    def _to_decimal(cls, v):
        if not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class DrawdownLimit(RiskLimit, frozen=True):
    """Maximum portfolio drawdown from peak equity."""

    max_drawdown_percent: Decimal = Field(..., gt=0, le=100, description="Max drawdown %")
    warning_threshold_percent: Decimal = Field(
        default=Decimal("70.0"),
        description="Warning at % of max drawdown"
    )

    @validator("max_drawdown_percent", "warning_threshold_percent", pre=True)
    def _to_decimal(cls, v):
        if not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class TurnoverVelocityLimit(RiskLimit, frozen=True):
    """Maximum turnover velocity (turnover / equity ratio)."""

    max_velocity: Decimal = Field(..., gt=0, description="Max turnover/equity ratio")
    window_hours: int = Field(default=1, gt=0, description="Measurement window in hours")

    @validator("max_velocity", pre=True)
    def _to_decimal(cls, v):
        if not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class RiskStateSnapshot(BaseModel, frozen=True):
    """Point-in-time snapshot of risk engine state for an account."""

    account_id: str = Field(..., description="Account identifier")
    snapshot_timestamp: datetime = Field(..., description="When this snapshot was taken")
    daily_realized_pnl: Decimal = Field(default=Decimal("0"), description="Cumulative realized P&L today")
    daily_turnover: Decimal = Field(default=Decimal("0"), description="Cumulative turnover today")
    peak_equity: Decimal = Field(default=Decimal("0"), description="Highest equity seen today")
    message_counts: Dict[str, int] = Field(default_factory=dict, description="Message counts by throttle key")
    kill_switch_active: bool = Field(default=False, description="Whether kill switch is engaged")
    kill_switch_reason: Optional[str] = Field(None, description="Reason for kill switch activation")

    @validator("daily_realized_pnl", "daily_turnover", "peak_equity", pre=True)
    def _to_decimal(cls, v):
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class RiskCheckContext(BaseModel, frozen=True):
    """Context passed to risk checks containing current market and portfolio state."""

    account_id: str = Field(..., description="Account being evaluated")
    order: Optional[Any] = Field(None, description="Order under evaluation (ExecutionOrder or dict)")
    portfolio_snapshot: Optional[Any] = Field(None, description="Current PortfolioSnapshot")
    position_snapshots: Dict[str, Any] = Field(default_factory=dict, description="PositionSnapshot by instrument")
    market_prices: Dict[str, Decimal] = Field(default_factory=dict, description="LTP by instrument_token")
    open_orders: List[Any] = Field(default_factory=list, description="List of open orders")
    check_timestamp: datetime = Field(..., description="Timestamp for this check")

    @validator("market_prices", pre=True, always=True)
    def _decimal_prices(cls, v):
        result = {}
        for k, val in v.items():
            if val is not None and not isinstance(val, Decimal):
                result[k] = Decimal(str(val))
            else:
                result[k] = val
        return result
