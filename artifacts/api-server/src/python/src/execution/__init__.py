"""Execution engine package.

Part 7A: Contracts and Order State Machine
Part 7B: Paper Matching and Fill Engine

This package provides:
  - ExecutionOrder: immutable order contract with validation
  - ExecutionOrderStatus / ExecutionOrderType / ExecutionOrderSide: lifecycle enums
  - ExecutionAuditEvent: immutable transition audit record
  - OrderStateMachine: deterministic, concurrent-safe state machine
  - ExecutionException hierarchy: typed domain exceptions
  - MatchingEngine: paper-only matching and fill engine
  - OrderMatcher: eligibility logic per order type
  - FillEvent: rich immutable fill output
  - MarketSnapshot: normalized market data for execution
  - Policies: price selection, slippage, liquidity, latency

Integration note:
  Existing project order/trade/position models are NOT imported here.
  Future batches will provide adapter layers to bridge these contracts
  with the existing ORM models and PaperBroker interfaces.
"""
from __future__ import annotations

# Conditional imports matching the pattern used in src.brokers and src.database.repositories
try:
    # 7A exports
    from src.execution.contracts import (
        ExecutionAuditEvent,
        ExecutionOrder,
        ExecutionOrderAction,
        ExecutionOrderSide,
        ExecutionOrderStatus,
        ExecutionOrderType,
        FillRecord,
        TERMINAL_STATES,
    )
    from src.execution.exceptions import (
        ConcurrentTransitionError,
        ExecutionException,
        IdempotencyViolation,
        InvalidStateTransition,
        OrderValidationError,
        OverfillError,
    )
    from src.execution.state_machine import (
        OrderState,
        OrderStateMachine,
        TransitionResult,
    )
    # 7B exports
    from src.execution.fills import FillEvent, FillEventBuilder
    from src.execution.matching import MarketSnapshot, MatchResult, OrderMatcher, TriggerStateTracker
    from src.execution.engine import EngineResult, MatchingEngine
    from src.execution.policies import (
        BasisPointsSlippagePolicy,
        DefaultLiquidityPolicy,
        DefaultPriceSelectionPolicy,
        FixedLatencyPolicy,
        FixedTicksSlippagePolicy,
        LatencyPolicy,
        LiquidityPolicy,
        PriceSelectionPolicy,
        SlippagePolicy,
        ZeroLatencyPolicy,
    )

    __all__ = [
        # 7A Contracts
        "ExecutionAuditEvent",
        "ExecutionOrder",
        "ExecutionOrderAction",
        "ExecutionOrderSide",
        "ExecutionOrderStatus",
        "ExecutionOrderType",
        "FillRecord",
        "TERMINAL_STATES",
        # 7A Exceptions
        "ConcurrentTransitionError",
        "ExecutionException",
        "IdempotencyViolation",
        "InvalidStateTransition",
        "OrderValidationError",
        "OverfillError",
        # 7A State machine
        "OrderState",
        "OrderStateMachine",
        "TransitionResult",
        # 7B Fills
        "FillEvent",
        "FillEventBuilder",
        # 7B Matching
        "MarketSnapshot",
        "MatchResult",
        "OrderMatcher",
        "TriggerStateTracker",
        # 7B Engine
        "EngineResult",
        "MatchingEngine",
        # 7B Policies
        "BasisPointsSlippagePolicy",
        "DefaultLiquidityPolicy",
        "DefaultPriceSelectionPolicy",
        "FixedLatencyPolicy",
        "FixedTicksSlippagePolicy",
        "LatencyPolicy",
        "LiquidityPolicy",
        "PriceSelectionPolicy",
        "SlippagePolicy",
        "ZeroLatencyPolicy",
    ]
except ImportError:
    __all__ = []
