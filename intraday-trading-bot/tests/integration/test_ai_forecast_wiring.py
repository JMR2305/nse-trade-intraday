"""Integration tests: RC-10B AI forecast pipeline wired into StrategyRuntime.

Covers:
  - Gate is actually invoked (not bypassed) when strategy opts in
  - Signal metadata["forecast"] is attached when gate approves
  - Original frozen Signal object is unchanged (enriched copy emitted)
  - Signal is suppressed when confidence < min_forecast_confidence
  - Fail-open: gate error → original signal emitted
  - Gate not invoked when min_forecast_confidence not in strategy params
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
from market_data.contracts import CompletedBar
from market_intelligence.multi_timeframe_context import MultiTimeframeContext
from strategy.contracts import Signal, SignalAction, StrategyConfig, StrategyContext
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


def make_strategy_config(
    with_min_confidence: bool = True,
    threshold: str = "0.65",
) -> StrategyConfig:
    params: Dict[str, Any] = {}
    if with_min_confidence:
        params["min_forecast_confidence"] = float(threshold)
    return StrategyConfig(
        strategy_id="test-strategy",
        strategy_type="momentum",
        name="Test Strategy",
        instrument_tokens=["INFY"],
        parameters=params,
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


def make_mtf_context(token: str = "INFY") -> MultiTimeframeContext:
    return MultiTimeframeContext(
        instrument_token=token,
        snapshot_timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
        timeframes={"1m": {"close": Decimal("1500"), "rsi_14": Decimal("55")}},
        regime=None,
        active_announcements=[],
        watchlist_rank=None,
        composite_score=None,
    )


async def build_runtime(
    config: StrategyConfig,
    signal_to_emit: Optional[Signal],
    gate_forecast: Optional[ForecastResult] = None,
    gate_raises: bool = False,
    no_gate: bool = False,
) -> tuple[StrategyRuntime, List[Signal]]:
    """Create a fully-mocked StrategyRuntime in ACTIVE state.

    Returns (runtime, emitted_signals).  Transitions state machine to ACTIVE
    so _process_bar() actually processes bars (can_emit_signals == True).
    """
    from strategy.contracts import StrategyLifecycleState, StrategyLifecycleState as LCS

    emitted: List[Signal] = []

    # Strategy mock
    strategy = MagicMock()
    strategy.on_bar.return_value = signal_to_emit

    # Context builder mock
    mtf_ctx = make_mtf_context("INFY")
    ctx = MagicMock(spec=StrategyContext)
    ctx.market_snapshots = {"INFY": mtf_ctx}

    context_builder = AsyncMock()
    context_builder.build_context.return_value = ctx

    # Market data service mock
    market_data = AsyncMock()

    # Fill event bus mock
    fill_bus = MagicMock()

    # Gate mock
    ai_forecast_gate = None
    feature_generator = None

    if not no_gate:
        adapter = AsyncMock()
        if gate_raises:
            adapter.forecast.side_effect = RuntimeError("Kronos error")
        else:
            adapter.forecast.return_value = gate_forecast

        feature_generator = MagicMock(spec=FeatureGenerator)
        feature_generator.generate.return_value = MagicMock(
            features=tuple(Decimal("0.1") for _ in range(25)),
            schema_version="1.0",
        )

        ai_forecast_gate = ForecastConfidenceGate(adapter=adapter, generator=feature_generator)

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

    # Transition REGISTERED → STARTING → ACTIVE so _process_bar() processes bars
    await runtime._state_machine.transition(StrategyLifecycleState.STARTING)
    await runtime._state_machine.transition(StrategyLifecycleState.ACTIVE)

    return runtime, emitted


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRuntimeForecastWiring:
    @pytest.mark.asyncio
    async def test_gate_invoked_when_strategy_opts_in(self) -> None:
        """Gate should_route must be called when min_forecast_confidence is set."""
        config = make_strategy_config(with_min_confidence=True, threshold="0.65")
        signal = make_signal()
        forecast = make_forecast("0.80")
        runtime, emitted = await build_runtime(config, signal, gate_forecast=forecast)

        with patch.object(
            runtime._ai_forecast_gate,
            "should_route",
            wraps=runtime._ai_forecast_gate.should_route,
        ) as spy:
            await runtime._process_bar(make_completed_bar())
            spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_metadata_forecast_attached_when_approved(self) -> None:
        """Signal emitted after gate approval must have metadata['forecast']."""
        config = make_strategy_config(with_min_confidence=True, threshold="0.65")
        signal = make_signal()
        forecast = make_forecast("0.80")
        runtime, emitted = await build_runtime(config, signal, gate_forecast=forecast)

        await runtime._process_bar(make_completed_bar())

        assert len(emitted) == 1
        emitted_signal = emitted[0]
        assert "forecast" in emitted_signal.metadata
        fm = emitted_signal.metadata["forecast"]
        assert fm["direction"] == "UP"
        assert fm["confidence"] == str(Decimal("0.80"))
        assert fm["model_version"] == "v2.0"
        assert fm["forecast_horizon"] == "15m"
        assert fm["feature_schema_version"] == FEATURE_SCHEMA_VERSION

    @pytest.mark.asyncio
    async def test_original_signal_is_unchanged(self) -> None:
        """The original frozen Signal object must not be mutated — only a copy is emitted."""
        config = make_strategy_config(with_min_confidence=True, threshold="0.65")
        original_signal = make_signal()
        original_metadata_id = id(original_signal.metadata)
        forecast = make_forecast("0.80")
        runtime, emitted = await build_runtime(config, original_signal, gate_forecast=forecast)

        await runtime._process_bar(make_completed_bar())

        assert len(emitted) == 1
        emitted_signal = emitted[0]
        # Original signal must be the same frozen object — metadata unmodified
        assert original_signal.metadata == {}
        # Emitted signal is a different object with enriched metadata
        assert emitted_signal is not original_signal
        assert "forecast" in emitted_signal.metadata

    @pytest.mark.asyncio
    async def test_signal_suppressed_when_below_threshold(self) -> None:
        """Gate below threshold → no signal emitted."""
        config = make_strategy_config(with_min_confidence=True, threshold="0.75")
        signal = make_signal()
        forecast = make_forecast("0.60")  # below 0.75 threshold
        runtime, emitted = await build_runtime(config, signal, gate_forecast=forecast)

        await runtime._process_bar(make_completed_bar())

        assert emitted == []

    @pytest.mark.asyncio
    async def test_gate_not_invoked_without_strategy_opt_in(self) -> None:
        """No min_forecast_confidence in parameters → gate must NOT be invoked."""
        config = make_strategy_config(with_min_confidence=False)
        signal = make_signal()
        runtime, emitted = await build_runtime(config, signal, gate_forecast=make_forecast("0.80"))

        with patch.object(
            runtime._ai_forecast_gate,
            "should_route",
            wraps=runtime._ai_forecast_gate.should_route,
        ) as spy:
            await runtime._process_bar(make_completed_bar())
            spy.assert_not_called()

        # Signal emitted without forecast metadata
        assert len(emitted) == 1
        assert "forecast" not in emitted[0].metadata

    @pytest.mark.asyncio
    async def test_gate_error_fail_open(self) -> None:
        """Gate raising exception → original signal emitted (fail-open)."""
        config = make_strategy_config(with_min_confidence=True, threshold="0.65")
        signal = make_signal()
        runtime, emitted = await build_runtime(config, signal, gate_raises=True)

        await runtime._process_bar(make_completed_bar())

        # Fail-open: signal is emitted despite gate error
        assert len(emitted) == 1

    @pytest.mark.asyncio
    async def test_runtime_works_without_gate(self) -> None:
        """No ai_forecast_gate injected → runtime behaves as RC-9 baseline."""
        config = make_strategy_config(with_min_confidence=True, threshold="0.65")
        signal = make_signal()
        runtime, emitted = await build_runtime(config, signal, no_gate=True)

        await runtime._process_bar(make_completed_bar())

        assert len(emitted) == 1
        assert "forecast" not in emitted[0].metadata

    @pytest.mark.asyncio
    async def test_no_signal_from_strategy_no_emission(self) -> None:
        """Strategy returning None → nothing emitted."""
        config = make_strategy_config(with_min_confidence=True)
        runtime, emitted = await build_runtime(config, signal_to_emit=None, gate_forecast=make_forecast())

        await runtime._process_bar(make_completed_bar())

        assert emitted == []

    @pytest.mark.asyncio
    async def test_feature_generator_update_called_per_bar(self) -> None:
        """FeatureGenerator.update_bar() must be called for each bar processed."""
        config = make_strategy_config(with_min_confidence=True)
        signal = make_signal()
        runtime, _ = await build_runtime(config, signal, gate_forecast=make_forecast())

        update_calls = []
        original_update = runtime._feature_generator.update_bar

        def tracking_update(token, close, volume):
            update_calls.append((token, close, volume))

        runtime._feature_generator.update_bar = tracking_update

        bar = make_completed_bar()
        await runtime._process_bar(bar)

        assert len(update_calls) == 1
        assert update_calls[0][0] == "INFY"
        assert update_calls[0][1] == bar.close
