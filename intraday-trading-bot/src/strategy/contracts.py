"""Domain contracts for the Strategy Engine.

All types are Pydantic v2 models with frozen=True.
All monetary values use Decimal.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field

from execution.contracts import (
    ExecutionOrderSide,
    ExecutionOrderType,
    ExecutionOrder,
)
from execution.fills import FillEvent
from execution.portfolio import PortfolioSnapshot, PositionSnapshot
from market_data.contracts import CompletedBar, Tick
from risk.contracts import RiskStateSnapshot


class SignalAction(str, Enum):
    """Actions that a strategy signal can represent."""
    ENTER_LONG = "ENTER_LONG"
    EXIT_LONG = "EXIT_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT_SHORT = "EXIT_SHORT"
    HOLD = "HOLD"
    REBALANCE = "REBALANCE"


class StrategyLifecycleState(str, Enum):
    """Lifecycle states for a strategy instance."""
    REGISTERED = "REGISTERED"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class Signal(BaseModel, frozen=True):
    """Immutable trading signal emitted by a strategy.

    A signal represents a trading intent that the strategy runtime
    will validate, map to an order, and route through execution.
    """
    signal_id: UUID = Field(default_factory=uuid4)
    strategy_id: str
    instrument_token: str
    action: SignalAction
    side: ExecutionOrderSide
    quantity: Decimal = Field(..., gt=Decimal("0"))
    order_type: ExecutionOrderType = ExecutionOrderType.MARKET
    limit_price: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None
    reason: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def is_entry(self) -> bool:
        return self.action in (SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT)

    @property
    def is_exit(self) -> bool:
        return self.action in (SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT)


class StrategyConfig(BaseModel, frozen=True):
    """Immutable configuration for a strategy instance.

    This is the contract that users provide when registering a strategy.
    It is persisted and used to reconstruct the strategy on restart.
    """
    strategy_id: str
    strategy_type: str
    name: str
    description: Optional[str] = None
    instrument_tokens: List[str] = Field(default_factory=list)
    bar_timeframe: str = "1m"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    max_position_quantity: Decimal = Decimal("1000")
    max_orders_per_minute: int = 10
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyStateSnapshot(BaseModel, frozen=True):
    """Frozen point-in-time capture of mutable strategy runtime state.

    Used for persistence and for passing state into the StrategyContext.
    """
    strategy_id: str
    lifecycle_state: StrategyLifecycleState = StrategyLifecycleState.REGISTERED
    current_signals: List[Signal] = Field(default_factory=list)
    pending_orders: List[str] = Field(default_factory=list)
    filled_today: int = 0
    rejected_today: int = 0
    last_signal_timestamp: Optional[datetime] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)




class StrategyContext(BaseModel, frozen=True):
    """Per-strategy view of market + portfolio + risk state.

    This is a snapshot-in-time view constructed by the ContextBuilder
    and passed to strategy callbacks. It is immutable and safe to
    share across coroutines.

    RC-10B addition: forecast_snapshot
        Populated by StrategyRuntime before calling strategy.on_bar() when
        all three conditions are met:
          1. ai_forecast_gate is injected into the runtime.
          2. StrategyConfig.parameters["min_forecast_confidence"] is set.
          3. KronosAdapter returns a forecast whose confidence ≥ threshold.
        None in all other cases (fail-open): on_bar() behaves identically
        to the pre-RC-10B baseline.
    """
    strategy_id: str
    timestamp: datetime
    market_snapshots: Dict[str, Any] = Field(default_factory=dict)
    portfolio: PortfolioSnapshot = Field(default_factory=PortfolioSnapshot)
    strategy_positions: Dict[str, PositionSnapshot] = Field(default_factory=dict)
    risk_state: RiskStateSnapshot = Field(
        default_factory=lambda: RiskStateSnapshot(account_id="", snapshot_timestamp=datetime.utcnow())
    )
    strategy_state: StrategyStateSnapshot = Field(
        default_factory=lambda: StrategyStateSnapshot(strategy_id="", lifecycle_state=StrategyLifecycleState.REGISTERED)
    )
    # RC-10B: AI forecast advisory context — None when forecast is unavailable
    forecast_snapshot: Optional["ForecastSnapshot"] = None



class StrategyPerformanceSnapshot(BaseModel, frozen=True):
    """Frozen performance metrics for a strategy.

    Captured at a point in time for reporting and persistence.
    All monetary values are Decimal.
    """
    strategy_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal("0")
    avg_profit_per_trade: Decimal = Decimal("0")
    avg_loss_per_trade: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    max_drawdown_pct: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    sharpe_ratio: Optional[Decimal] = None
    return_pct: Optional[Decimal] = None


class SignalRoutingResult(BaseModel, frozen=True):
    """Result of routing a signal through the SignalRouter.

    Contains the outcome of validation, conflict detection, and order submission.
    """
    signal_id: UUID
    routed: bool
    client_order_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, ROUTED, REJECTED, ERROR
    rejection_reason: Optional[str] = None
    violations: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class StrategyRegistrationResult(BaseModel, frozen=True):
    """Result of registering a strategy with the StrategyCoordinator."""
    strategy_id: str
    success: bool
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConflictResolution(BaseModel, frozen=True):
    """Result of conflict detection between two or more signals."""
    has_conflict: bool
    conflict_reason: Optional[str] = None
    resolved_signal: Optional[Signal] = None
    rejected_signals: List[Signal] = Field(default_factory=list)


# RC-10B: AI Forecast Metadata
class AiForecastMetadata(BaseModel, frozen=True):
    """Frozen AI forecast result attached to a signal or context snapshot."""

    direction: str  # UP | DOWN | NEUTRAL
    confidence: Decimal
    model_version: str
    forecast_horizon: str = "15m"
    price_target: Optional[Decimal] = None


class ForecastSnapshot(BaseModel, frozen=True):
    """Immutable AI forecast injected into StrategyContext before on_bar().

    Populated when:
      - The strategy configures min_forecast_confidence, AND
      - KronosAdapter returns a forecast within the pre-on_bar window, AND
      - The forecast confidence meets or exceeds min_forecast_confidence.

    None (absent from context) when forecast is unavailable, timed out, or
    below threshold — these are all fail-open: on_bar() still runs normally.

    The strategy can read this snapshot to align its logic with the AI view,
    but it MUST NOT use it to directly place or modify orders — all orders
    must still flow through RC-8 (Risk Engine) and RC-7 (Execution Engine).

    Spec item 2 fields:
        direction           — UP | DOWN | NEUTRAL
        confidence          — raw model confidence ∈ [0.0, 1.0]
        forecast_horizon    — prediction horizon label (e.g. "15m")
        expected_volatility — ATR-derived volatility estimate (None until
                              VolatilityForecaster integration in RC-10C)
        model_version       — Kronos model identifier (e.g. "v2.0")
        forecast_timestamp  — ISO-8601 UTC timestamp from Kronos
    """

    direction: str                         # UP | DOWN | NEUTRAL
    confidence: Decimal                    # raw model confidence
    forecast_horizon: str                  # e.g. "15m"
    model_version: str                     # e.g. "v2.0"
    forecast_timestamp: str                # ISO-8601 UTC
    expected_volatility: Optional[Decimal] = None   # deferred RC-10C
