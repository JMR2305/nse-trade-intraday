"""
Risk Engine package — public API surface.

Import order:
  1. contracts (no internal deps)
  2. exceptions (imports contracts)
  3. state (imports contracts)
  4. rules (imports contracts)
  5. kill_switch (imports contracts)
  6. engine (imports all of the above)
  7. persistence (imports engine, contracts) — optional
  8. fill_event_bus (standalone)
  9. integration_layer (imports engine, fill_event_bus)
"""

from .contracts import (
    # Severity / type enums
    RiskSeverity,
    RiskCheckType,

    # Core domain types
    RiskViolation,
    RiskResult,
    RiskRequest,
    RiskContext,
    RiskAudit,
    RiskStateSnapshot,

    # Pre-trade limit configurations
    OrderQuantityLimit,
    OrderValueLimit,
    TickSizeLimit,
    PriceBandLimit,

    # Position limit configurations
    MaxPositionSizeLimit,
    InstrumentExposureLimit,
    NetExposureLimit,
    ConcentrationLimit,

    # Portfolio limit configurations
    CashAvailabilityLimit,
    BuyingPowerLimit,
    PortfolioExposureLimit,
    MarginAvailabilityLimit,

    # Daily control configurations
    DailyLossLimit,
    DailyProfitTargetLock,
    MaxTradesPerDayLimit,
    MaxOrdersPerMinuteLimit,

    # Safety configurations
    KillSwitchLimit,
    EmergencyHaltLimit,
    CircuitBreakerLimit,

    # Additional configurations
    DuplicateOrderLimit,
    SelfTradeLimit,
    DrawdownLimit,
    TurnoverVelocityLimit,

    # Base
    RiskConfiguration,
)

from .exceptions import (
    RiskEngineError,
    RiskCheckFailed,
    KillSwitchActive,
    EmergencyHaltActive,
    CircuitBreakerTriggered,
    DailyLossLimitBreached,
    ThrottleLimitBreached,
    RiskStateError,
    RiskStateCorrupted,
    RiskStateNotFound,
    RiskConfigurationError,
    FillDeliveryError,
    IntegrationLayerError,
)

from .state import RiskState

from .kill_switch import KillSwitch, KillSwitchEvent

from .rules import RiskRule, RULE_REGISTRY, get_rule

from .engine import RiskEngine

from .fill_event_bus import FillEvent, FillEventBus

from .integration_layer import (
    ExecutionEnginePort,
    RiskIntegrationLayer,
    RiskIntegrationResult,
)

try:
    from .persistence import RiskEnginePersistenceAdapter
except ImportError:
    RiskEnginePersistenceAdapter = None  # type: ignore[assignment,misc]

__all__ = [
    # Severity / type enums
    "RiskSeverity",
    "RiskCheckType",

    # Core domain types
    "RiskViolation",
    "RiskResult",
    "RiskRequest",
    "RiskContext",
    "RiskAudit",
    "RiskStateSnapshot",

    # Base configuration
    "RiskConfiguration",

    # Pre-trade limits
    "OrderQuantityLimit",
    "OrderValueLimit",
    "TickSizeLimit",
    "PriceBandLimit",

    # Position limits
    "MaxPositionSizeLimit",
    "InstrumentExposureLimit",
    "NetExposureLimit",
    "ConcentrationLimit",

    # Portfolio limits
    "CashAvailabilityLimit",
    "BuyingPowerLimit",
    "PortfolioExposureLimit",
    "MarginAvailabilityLimit",

    # Daily controls
    "DailyLossLimit",
    "DailyProfitTargetLock",
    "MaxTradesPerDayLimit",
    "MaxOrdersPerMinuteLimit",

    # Safety
    "KillSwitchLimit",
    "EmergencyHaltLimit",
    "CircuitBreakerLimit",

    # Additional
    "DuplicateOrderLimit",
    "SelfTradeLimit",
    "DrawdownLimit",
    "TurnoverVelocityLimit",

    # Exceptions
    "RiskEngineError",
    "RiskCheckFailed",
    "KillSwitchActive",
    "EmergencyHaltActive",
    "CircuitBreakerTriggered",
    "DailyLossLimitBreached",
    "ThrottleLimitBreached",
    "RiskStateError",
    "RiskStateCorrupted",
    "RiskStateNotFound",
    "RiskConfigurationError",
    "FillDeliveryError",
    "IntegrationLayerError",

    # Core classes
    "RiskState",
    "KillSwitch",
    "KillSwitchEvent",
    "RiskRule",
    "RULE_REGISTRY",
    "get_rule",
    "RiskEngine",

    # Fill event bus
    "FillEvent",
    "FillEventBus",

    # Integration layer
    "ExecutionEnginePort",
    "RiskIntegrationLayer",
    "RiskIntegrationResult",

    # Persistence (optional)
    "RiskEnginePersistenceAdapter",
]
