"""Integration tests: RC-10B StrategyContext ForecastSnapshot injection.

Verifies that the AI forecast is injected into StrategyContext BEFORE
strategy.on_bar() is called, so the strategy can read forecast direction /
confidence / horizon during its own bar processing logic.

Spec reference: RC-10B section 2 (StrategyContext Enrichment) and the
execution flow diagram:
  ContextBuilder → FeatureGenerator → KronosAdapter → ForecastConfidenceGate
  → StrategyContext → strategy.on_bar() → SignalRouter → RC-8 → RC-7

Key invariants:
  - forecast_snapshot is a ForecastSnapshot when confidence ≥ threshold.
  - forecast_snapshot is None when confidence < threshold (signal suppressed).
  - forecast_snapshot is None when Kronos is unavailable (fail-open).
  - forecast_snapshot is None when gate is not injected (disabled mode).
  - strategy.on_bar() is always called — even when forecast is unavailable.
  - ForecastSnapshot fields match the 6 spec-required fields.
  - The original base StrategyContext is never mutated.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_forecast.confidence_gate import ForecastConfidenceGate
from ai_forecast.features import FEATURE_SCHEMA_VERSION, FeatureGenerator
from ai_forecast.kronos_adapter import ForecastResult
from execution.contracts import ExecutionOrderSide, ExecutionOrderType
from execution.portfolio import PortfolioSnapshot
from market_data.contracts import CompletedBar
from market_intelligence.multi_timeframe_context import MultiTimeframeContext
from risk.contracts import RiskStateSnapshot
from strategy.contracts import (
    ForecastSnapshot,
    Signal,
    SignalAction,
    StrategyConfig,
    StrategyContext,
    StrategyLifecycleState,
    StrategyStateSnapshot,
)
from strategy.runtime import StrategyRuntime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_completed_bar(token: str = "INFY", close: str = "1500") -> CompletedBar:
    return CompletedBar(
        instrument_token=token,
        timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc).isoformat(),
        open=Decimal(close),
        high=Decimal(close) + Decimal("5"),
        low=Decimal(close) - Decimal("5"),
        close=Decimal(close),
        volume=Decimal("10000"),
        interval="1m",
    )


def make_signal(token: str = "INFY") -> Signal:
    return Signal(
        strategy_id="test-strategy",
        instrument_token=token,
        action=SignalAction.ENTER_LONG,
        side=ExecutionOrderSide.BUY,
        quantity=Decimal("10"),
        timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
        metadata={},
    )


def make_strategy_config(threshold: str = "0.65") -> StrategyConfig:
    return StrategyConfig(
        strategy_id="test-strategy",
        strategy_type="momentum",
        name="Test Strategy",
        instrument_tokens=["INFY"],
        parameters={"min_forecast_confidence": float(threshold)},
    )


def make_forecast(confidence: str = "0.80", direction: str = "UP") -> ForecastResult:
    return ForecastResult(
        instrument_token="INFY",
        forecast_horizon="15m",
        direction=direction,
        confidence=Decimal(confidence),
        model_version="v2.0",
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


def make_real_strategy_context(token: str = "INFY") -> StrategyContext:
    """Build a real (non-mock) StrategyContext with a MultiTimeframeContext."""
    mtf = MultiTimeframeContext(
        instrument_token=token,
        snapshot_timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
        timeframes={"1m": {"close": Decimal("1500"), "rsi_14": Decimal("55")}},
        regime=None,
        active_announcements=[],
        watchlist_rank=None,
        composite_score=None,
    )
    return StrategyContext(
        strategy_id="test-strategy",
        timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
        market_snapshots={token: mtf},
        portfolio=PortfolioSnapshot(),
        strategy_positions={},
        risk_state=RiskStateSnapshot(
            account_id="acct1",
            snapshot_timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
        ),
        strategy_state=StrategyStateSnapshot(
            strategy_id="test-strategy",
            lifecycle_state=StrategyLifecycleState.ACTIVE,
        ),
    )


async def build_runtime_real_context(
    config: StrategyConfig,
    signal_to_emit: Optional[Signal],
    gate_forecast: Optional[ForecastResult] = None,
    gate_raises: bool = False,
    no_gate: bool = False,
    adapter_delay_ms: float = 0.0,
) -> tuple[StrategyRuntime, List[Signal], List[StrategyContext]]:
    """Build a runtime with a real StrategyContext and capture on_bar() context args.

    Returns (runtime, emitted_signals, captured_contexts).
    captured_contexts[i] is the StrategyContext passed to strategy.on_bar() on bar i.
    """
    emitted: List[Signal] = []
    captured_contexts: List[StrategyContext] = []

    real_ctx = make_real_strategy_context()

    # Strategy that captures the context argument
    def on_bar_side_effect(bar: CompletedBar, ctx: Any) -> Optional[Signal]:
        captured_contexts.append(ctx)
        return signal_to_emit

    strategy = MagicMock()
    strategy.on_bar.side_effect = on_bar_side_effect

    context_builder = AsyncMock()
    context_builder.build_context.return_value = real_ctx

    market_data = AsyncMock()
    fill_bus = MagicMock()

    ai_forecast_gate = None
    feature_generator = None

    if not no_gate:
        adapter = AsyncMock()
        if gate_raises:
            adapter.forecast.side_effect = RuntimeError("Kronos unavailable")
        elif adapter_delay_ms > 0:
            async def slow_forecast(*args, **kwargs):
                await asyncio.sleep(adapter_delay_ms / 1000.0)
                return gate_forecast
            adapter.forecast.side_effect = slow_forecast
        else:
            adapter.forecast.return_value = gate_forecast

        feature_generator = MagicMock(spec=FeatureGenerator)
        feature_generator.generate.return_value = MagicMock(
            features=tuple(Decimal("0.1") for _ in range(25)),
            schema_version="1.0",
        )
        feature_generator.update_bar = MagicMock()

        ai_forecast_gate = ForecastConfidenceGate(
            adapter=adapter, generator=feature_generator
        )

    runtime = StrategyRuntime(
        config=config,
        strategy=strategy,
        context_builder=context_builder,
        market_data_service=market_data,
        fill_event_bus=fill_bus,
        signal_callback=lambda s: emitted.append(s),
        ai_forecast_gate=ai_forecast_gate,
        feature_generator=feature_generator,
    )

    await runtime._state_machine.transition(StrategyLifecycleState.STARTING)
    await runtime._state_machine.transition(StrategyLifecycleState.ACTIVE)

    return runtime, emitted, captured_contexts


# ---------------------------------------------------------------------------
# StrategyContext ForecastSnapshot injection tests
# ---------------------------------------------------------------------------

class TestStrategyContextForecastInjection:
    """Verify ForecastSnapshot is injected into StrategyContext before on_bar()."""

    @pytest.mark.asyncio
    async def test_forecast_snapshot_injected_when_approved(self) -> None:
        """When confidence ≥ threshold, on_bar() receives ctx.forecast_snapshot."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()
        forecast = make_forecast("0.80", "UP")

        runtime, _emitted, captured = await build_runtime_real_context(
            config, signal, gate_forecast=forecast
        )
        await runtime._process_bar(make_completed_bar())

        assert len(captured) == 1
        ctx = captured[0]
        assert isinstance(ctx, StrategyContext)
        assert ctx.forecast_snapshot is not None
        fs = ctx.forecast_snapshot
        assert isinstance(fs, ForecastSnapshot)

    @pytest.mark.asyncio
    async def test_forecast_snapshot_has_all_spec_fields(self) -> None:
        """ForecastSnapshot must carry all 6 spec-required fields."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()
        forecast = make_forecast("0.80", "UP")

        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, gate_forecast=forecast
        )
        await runtime._process_bar(make_completed_bar())

        assert len(captured) == 1
        fs = captured[0].forecast_snapshot
        assert fs is not None

        # Spec section 2: all 6 required fields
        assert fs.direction == "UP"                           # Forecast Direction
        assert fs.confidence == Decimal("0.80")               # Confidence Score
        assert fs.forecast_horizon == "15m"                   # Prediction Horizon
        assert fs.expected_volatility is None                  # Expected Volatility (deferred RC-10C)
        assert fs.model_version == "v2.0"                     # Model Version
        assert isinstance(fs.forecast_timestamp, str)         # Forecast Timestamp
        assert len(fs.forecast_timestamp) > 0

    @pytest.mark.asyncio
    async def test_forecast_snapshot_none_when_below_threshold(self) -> None:
        """Below threshold → signal suppressed AND context had no forecast_snapshot.

        The pre-on_bar injection should NOT inject when confidence < threshold.
        """
        config = make_strategy_config(threshold="0.75")
        signal = make_signal()
        forecast = make_forecast("0.55")  # below 0.75

        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, gate_forecast=forecast
        )
        await runtime._process_bar(make_completed_bar())

        # Signal was suppressed
        assert emitted == []
        # on_bar WAS called (strategy always runs regardless of gate decision)
        assert len(captured) == 1
        # Context must NOT carry forecast since confidence was below threshold
        assert captured[0].forecast_snapshot is None

    @pytest.mark.asyncio
    async def test_forecast_snapshot_none_when_kronos_unavailable(self) -> None:
        """Kronos error → fail-open, context.forecast_snapshot stays None."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()

        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, gate_raises=True
        )
        await runtime._process_bar(make_completed_bar())

        # Fail-open: signal is still emitted
        assert len(emitted) == 1
        # on_bar was called
        assert len(captured) == 1
        # Context has no forecast (Kronos was unavailable)
        assert captured[0].forecast_snapshot is None

    @pytest.mark.asyncio
    async def test_forecast_snapshot_none_when_gate_disabled(self) -> None:
        """No gate injected → RC-9 baseline — forecast_snapshot always None."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()

        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, no_gate=True
        )
        await runtime._process_bar(make_completed_bar())

        assert len(emitted) == 1
        assert len(captured) == 1
        ctx = captured[0]
        # In disabled mode the context is the real StrategyContext with no forecast
        assert ctx.forecast_snapshot is None

    @pytest.mark.asyncio
    async def test_base_context_not_mutated(self) -> None:
        """The original StrategyContext must never be mutated — only a copy enriched."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()
        forecast = make_forecast("0.80")

        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, gate_forecast=forecast
        )

        # Grab the base context before processing
        base_ctx = runtime._context_builder.build_context.return_value
        original_snapshot = base_ctx.forecast_snapshot  # should be None

        await runtime._process_bar(make_completed_bar())

        # Base context must remain unchanged
        assert base_ctx.forecast_snapshot is original_snapshot  # still None
        # Captured (enriched) context is a different object
        assert captured[0] is not base_ctx
        assert captured[0].forecast_snapshot is not None

    @pytest.mark.asyncio
    async def test_forecast_snapshot_injected_exact_threshold(self) -> None:
        """confidence == threshold is approved → snapshot injected."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()
        forecast = make_forecast("0.65")  # exactly at threshold

        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, gate_forecast=forecast
        )
        await runtime._process_bar(make_completed_bar())

        assert len(emitted) == 1
        assert captured[0].forecast_snapshot is not None
        assert captured[0].forecast_snapshot.confidence == Decimal("0.65")

    @pytest.mark.asyncio
    async def test_signal_metadata_also_enriched(self) -> None:
        """Signal metadata["forecast"] must still be populated (backward compat)."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()
        forecast = make_forecast("0.80")

        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, gate_forecast=forecast
        )
        await runtime._process_bar(make_completed_bar())

        assert len(emitted) == 1
        fm = emitted[0].metadata.get("forecast")
        assert fm is not None
        assert fm["direction"] == "UP"
        assert fm["raw_confidence"] == str(Decimal("0.80"))
        assert fm["confidence"] == str(Decimal("0.80"))  # backward-compat alias

    @pytest.mark.asyncio
    async def test_down_direction_snapshot(self) -> None:
        """ForecastSnapshot carries DOWN direction correctly."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()
        forecast = make_forecast("0.80", "DOWN")

        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, gate_forecast=forecast
        )
        await runtime._process_bar(make_completed_bar())

        fs = captured[0].forecast_snapshot
        assert fs is not None
        assert fs.direction == "DOWN"

    @pytest.mark.asyncio
    async def test_forecast_snapshot_immutable(self) -> None:
        """ForecastSnapshot must be a frozen Pydantic model."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()
        forecast = make_forecast("0.80")

        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, gate_forecast=forecast
        )
        await runtime._process_bar(make_completed_bar())

        fs = captured[0].forecast_snapshot
        assert fs is not None
        with pytest.raises(Exception):  # frozen Pydantic
            fs.direction = "NEUTRAL"  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_strategy_always_called_even_without_forecast(self) -> None:
        """strategy.on_bar() must be invoked regardless of forecast availability."""
        config = make_strategy_config(threshold="0.65")
        signal = make_signal()

        # Kronos is unavailable — no forecast in context
        runtime, emitted, captured = await build_runtime_real_context(
            config, signal, gate_raises=True
        )
        await runtime._process_bar(make_completed_bar())

        # on_bar was called exactly once
        assert len(captured) == 1
        # Signal was emitted (fail-open)
        assert len(emitted) == 1


# ---------------------------------------------------------------------------
# ForecastSnapshot contract tests
# ---------------------------------------------------------------------------

class TestForecastSnapshotContract:
    def test_frozen(self) -> None:
        fs = ForecastSnapshot(
            direction="UP",
            confidence=Decimal("0.75"),
            forecast_horizon="15m",
            model_version="v1",
            forecast_timestamp="2026-07-24T09:30:00+00:00",
        )
        with pytest.raises(Exception):
            fs.direction = "DOWN"  # type: ignore[misc]

    def test_expected_volatility_optional(self) -> None:
        fs = ForecastSnapshot(
            direction="UP",
            confidence=Decimal("0.75"),
            forecast_horizon="15m",
            model_version="v1",
            forecast_timestamp="2026-07-24T09:30:00+00:00",
        )
        assert fs.expected_volatility is None

    def test_strategy_context_default_is_none(self) -> None:
        """StrategyContext.forecast_snapshot defaults to None (backward compat)."""
        ctx = StrategyContext(
            strategy_id="x",
            timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
        )
        assert ctx.forecast_snapshot is None

    def test_strategy_context_with_forecast_snapshot(self) -> None:
        """StrategyContext accepts a ForecastSnapshot."""
        fs = ForecastSnapshot(
            direction="UP",
            confidence=Decimal("0.80"),
            forecast_horizon="15m",
            model_version="v2.0",
            forecast_timestamp="2026-07-24T09:30:00+00:00",
        )
        ctx = StrategyContext(
            strategy_id="x",
            timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
            forecast_snapshot=fs,
        )
        assert ctx.forecast_snapshot is fs
        assert ctx.forecast_snapshot.direction == "UP"

    def test_strategy_context_model_copy_with_forecast(self) -> None:
        """model_copy can add forecast_snapshot to an existing context."""
        ctx = StrategyContext(
            strategy_id="x",
            timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
        )
        fs = ForecastSnapshot(
            direction="DOWN",
            confidence=Decimal("0.72"),
            forecast_horizon="15m",
            model_version="v2.0",
            forecast_timestamp="2026-07-24T09:30:00+00:00",
        )
        enriched = ctx.model_copy(update={"forecast_snapshot": fs})
        assert enriched.forecast_snapshot is fs
        # Original must be unchanged
        assert ctx.forecast_snapshot is None
        # enriched is a different object
        assert enriched is not ctx


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _run_one_bar(
    runtime: StrategyRuntime,
    captured: List[StrategyContext],
) -> None:
    """Run one bar through the runtime if captured is still empty."""
    if not captured:
        await runtime._process_bar(make_completed_bar())
