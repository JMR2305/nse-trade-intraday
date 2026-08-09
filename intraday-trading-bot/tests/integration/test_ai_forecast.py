"""Integration tests for the AI-forecast pipeline (RC-10B API)."""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from ai_forecast.features import FeatureGenerator, LegacyFeatureGenerator
from ai_forecast.kronos_adapter import KronosAdapter, ForecastResult
from ai_forecast.confidence_gate import ForecastConfidenceGate
from ai_forecast.volatility import VolatilityForecaster
from ai_forecast.benchmark import InMemoryForecastBenchmark
from market_intelligence.multi_timeframe_context import (
    MarketRegime,
    MarketRegimeSnapshot,
    MultiTimeframeContext,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestAiForecastIntegration:
    def test_feature_to_gate_pipeline(self) -> None:
        """End-to-end: features -> forecast -> gate (RC-10B 25-feature schema)."""
        gen = FeatureGenerator()
        mtf = MultiTimeframeContext(
            instrument_token="INFY",
            snapshot_timestamp=_utcnow(),
            timeframes={
                "1m": {
                    "sma_10": Decimal("105"),
                    "sma_20": Decimal("104"),
                    "rsi_14": Decimal("55"),
                    "atr_14": Decimal("2.5"),
                    "adx_14": Decimal("25"),
                    "close": Decimal("105"),
                }
            },
            regime=MarketRegimeSnapshot(
                instrument_token="INFY",
                regime=MarketRegime.UPTREND,
                confidence=Decimal("0.75"),
                detected_at=_utcnow(),
            ),
        )
        features = gen.generate("INFY", mtf, _utcnow().isoformat())
        # RC-10B canonical schema: 25 features
        assert features.feature_count == 25

        # Static apply() is still available on ForecastConfidenceGate
        forecast = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.65"),
            model_version="v1",
            computed_at=_utcnow().isoformat(),
        )
        gated = ForecastConfidenceGate.apply(forecast, min_confidence=Decimal("0.5"))
        assert gated is not None
        assert gated.direction == "UP"

    def test_legacy_feature_generator_still_produces_42(self) -> None:
        """LegacyFeatureGenerator retained under schema version 'legacy-42-v1'."""
        gen = LegacyFeatureGenerator()
        mtf = MultiTimeframeContext(
            instrument_token="INFY",
            snapshot_timestamp=_utcnow(),
            timeframes={},
        )
        features = gen.generate("INFY", mtf, _utcnow().isoformat())
        assert features.feature_count == 42
        assert features.schema_version == "legacy-42-v1"

    def test_fail_open_with_gate(self) -> None:
        """When Kronos fails, adapter returns None (fail-open)."""
        gen = FeatureGenerator()
        adapter = KronosAdapter(base_url="http://localhost:99999", timeout_ms=50, max_retries=0)
        mtf = MultiTimeframeContext(
            instrument_token="INFY",
            snapshot_timestamp=_utcnow(),
            timeframes={},
        )
        features = gen.generate("INFY", mtf, _utcnow().isoformat())
        import asyncio
        result = asyncio.run(adapter.forecast("INFY", features))
        assert result is None

    def test_benchmark_tracks_accuracy(self) -> None:
        """InMemoryForecastBenchmark tracks forecast accuracy over multiple predictions."""
        ts1 = _utcnow().isoformat()
        ts2 = _utcnow().isoformat()
        bench = InMemoryForecastBenchmark()
        bench.record_forecast("INFY", "UP", Decimal("0.70"), ts1)
        bench.evaluate("INFY", "UP", ts1)    # correct
        bench.record_forecast("TCS", "DOWN", Decimal("0.60"), ts2)
        bench.evaluate("TCS", "UP", ts2)     # wrong
        report = bench.generate_report()
        assert report.sample_count == 2
        # 1/2 correct → directional_accuracy = 0.5
        assert report.directional_accuracy == Decimal("0.5000")

    def test_volatility_with_bar_data(self) -> None:
        """VolatilityForecaster.update() then forecast() works with CompletedBar stream."""
        from market_data.contracts import CompletedBar
        import datetime as dt
        forecaster = VolatilityForecaster()
        base = datetime(2026, 7, 24, 9, 15, tzinfo=timezone.utc)
        for i in range(30):
            bar = CompletedBar(
                instrument_token="INFY",
                timestamp=(base + dt.timedelta(minutes=i)).isoformat(),
                open=Decimal("100"),
                high=Decimal("102"),
                low=Decimal("98"),
                close=Decimal("100") + Decimal(str(i % 3 - 1)),
                volume=Decimal("1000"),
                interval="1m",
            )
            forecaster.update(bar)
        result = forecaster.forecast("INFY")
        assert result.predicted_atr >= Decimal("0")
        assert result.confidence >= Decimal("0.3")

    def test_full_pipeline_no_crash(self) -> None:
        """Full pipeline: features -> kronos (fail-open) -> gate -> benchmark."""
        gen = FeatureGenerator()
        mtf = MultiTimeframeContext(
            instrument_token="INFY",
            snapshot_timestamp=_utcnow(),
            timeframes={"1m": {"close": Decimal("100"), "rsi_14": Decimal("50")}},
        )
        features = gen.generate("INFY", mtf, _utcnow().isoformat())

        adapter = KronosAdapter(base_url="http://localhost:99999", timeout_ms=50, max_retries=0)
        bench = InMemoryForecastBenchmark()

        import asyncio
        forecast = asyncio.run(adapter.forecast("INFY", features))

        if forecast is not None:
            gated = ForecastConfidenceGate.apply(forecast, min_confidence=Decimal("0.0"))
            if gated is not None:
                bench.record_forecast(
                    gated.instrument_token,
                    gated.direction,
                    gated.confidence,
                    gated.computed_at,
                )

        report = bench.generate_report()
        assert report.sample_count == 0  # No forecast received (Kronos unreachable)

    def test_context_builder_with_ai_forecast(self) -> None:
        """ContextBuilder accepts AI forecast dependencies without error."""
        from strategy.context_builder import ContextBuilder
        from strategy.contracts import StrategyConfig

        builder = ContextBuilder(
            ai_forecast_adapter=KronosAdapter(
                base_url="http://localhost:99999", timeout_ms=50, max_retries=0
            ),
            confidence_gate=ForecastConfidenceGate.__new__(ForecastConfidenceGate),
        )
        config = StrategyConfig(
            strategy_id="test",
            strategy_type="trend",
            name="Test",
            instrument_tokens=["INFY"],
        )
        ctx = builder.build(config, {})
        assert ctx.strategy_id == "test"
        # With no indicator engine, market_snapshots should be empty
        assert ctx.market_snapshots == {}
