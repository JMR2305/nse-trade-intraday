from __future__ import annotations

from decimal import Decimal
from datetime import datetime

import pytest

from ai_forecast.features import FeatureGenerator
from ai_forecast.kronos_adapter import KronosAdapter, ForecastResult
from ai_forecast.confidence_gate import ForecastConfidenceGate
from ai_forecast.volatility import VolatilityForecaster
from ai_forecast.benchmark import ForecastBenchmark
from market_intelligence.multi_timeframe_context import (
    MarketRegime,
    MarketRegimeSnapshot,
    MultiTimeframeContext,
)


class TestAiForecastIntegration:
    def test_feature_to_gate_pipeline(self) -> None:
        """End-to-end: features -> forecast -> gate."""
        gen = FeatureGenerator()
        mtf = MultiTimeframeContext(
            instrument_token="INFY",
            snapshot_timestamp=datetime.utcnow(),
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
                detected_at=datetime.utcnow(),
            ),
        )
        features = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert features.feature_count == 42

        gate = ForecastConfidenceGate(min_confidence=Decimal("0.5"))
        forecast = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.65"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        gated = gate.apply(forecast)
        assert gated is not None
        assert gated.direction == "UP"

    def test_fail_open_with_gate(self) -> None:
        """When Kronos fails, adapter returns None (fail-open)."""
        gen = FeatureGenerator()  # defined locally — not from outer scope
        adapter = KronosAdapter(base_url="http://localhost:99999", timeout_ms=50, max_retries=0)
        mtf = MultiTimeframeContext(
            instrument_token="INFY",
            snapshot_timestamp=datetime.utcnow(),
            timeframes={},
        )
        features = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            adapter.forecast("INFY", features)
        )
        assert result is None

    def test_benchmark_tracks_accuracy(self) -> None:
        """Benchmark tracks forecast accuracy over multiple predictions."""
        bench = ForecastBenchmark()
        bench.record_forecast("INFY", "UP", Decimal("0.70"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "UP", datetime.utcnow().isoformat())
        bench.record_forecast("TCS", "DOWN", Decimal("0.60"), datetime.utcnow().isoformat())
        bench.evaluate("TCS", "UP", datetime.utcnow().isoformat())
        report = bench.generate_report()
        assert report.total_predictions == 2
        assert report.correct_predictions == 1
        assert report.accuracy == Decimal("0.5")
        assert "INFY" in report.by_instrument
        assert "TCS" in report.by_instrument

    def test_volatility_with_feature_context(self) -> None:
        """Volatility forecaster works with bar data from market context."""
        from market_data.contracts import CompletedBar
        import datetime as dt
        forecaster = VolatilityForecaster()
        bars = []
        base = datetime(2026, 7, 24, 9, 15)
        for i in range(30):
            bars.append(CompletedBar(
                instrument_token="INFY",
                timestamp=(base + dt.timedelta(minutes=i)).isoformat(),
                open=Decimal("100"),
                high=Decimal("102"),
                low=Decimal("98"),
                close=Decimal("100") + Decimal(str(i % 3 - 1)),
                volume=Decimal("1000"),
                interval="1m",
            ))
        result = forecaster.forecast("INFY", bars)
        assert result.expected_range > Decimal("0")
        assert result.confidence >= Decimal("0.5")

    def test_full_pipeline_no_crash(self) -> None:
        """Full pipeline: features -> kronos (fail-open) -> gate -> benchmark."""
        gen = FeatureGenerator()
        mtf = MultiTimeframeContext(
            instrument_token="INFY",
            snapshot_timestamp=datetime.utcnow(),
            timeframes={"1m": {"close": Decimal("100"), "rsi_14": Decimal("50")}},
        )
        features = gen.generate("INFY", mtf, datetime.utcnow().isoformat())

        adapter = KronosAdapter(base_url="http://localhost:99999", timeout_ms=50, max_retries=0)
        gate = ForecastConfidenceGate()
        bench = ForecastBenchmark()

        import asyncio
        forecast = asyncio.get_event_loop().run_until_complete(
            adapter.forecast("INFY", features)
        )

        if forecast is not None:
            gated = gate.apply(forecast)
            if gated is not None:
                bench.record_forecast(
                    gated.instrument_token,
                    gated.direction,
                    gated.confidence,
                    gated.computed_at,
                )

        report = bench.generate_report()
        assert report.total_predictions == 0  # No forecast received (Kronos unreachable)

    def test_context_builder_with_ai_forecast(self) -> None:
        """ContextBuilder accepts AI forecast dependencies without error."""
        from strategy.context_builder import ContextBuilder
        from strategy.contracts import StrategyConfig

        builder = ContextBuilder(
            ai_forecast_adapter=KronosAdapter(base_url="http://localhost:99999", timeout_ms=50, max_retries=0),
            confidence_gate=ForecastConfidenceGate(),
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
