"""Integration tests: ContextBuilder with market intelligence injected."""
from __future__ import annotations

import datetime as dt
from datetime import datetime
from decimal import Decimal

from market_data.contracts import CompletedBar
from market_intelligence.indicator_engine import IndicatorEngine
from market_intelligence.regime import MarketRegimeDetector
from market_intelligence.announcements import AnnouncementIntelligenceService
from strategy.contracts import StrategyConfig
from strategy.context_builder import ContextBuilder


def make_bars(count: int, token: str = "INFY") -> list:
    bars = []
    base = datetime(2026, 7, 23, 9, 15)
    for i in range(count):
        bars.append(CompletedBar(
            instrument_token=token,
            timestamp=(base + dt.timedelta(minutes=i)).isoformat(),
            open=Decimal("100") + Decimal(str(i)),
            high=Decimal("101") + Decimal(str(i)),
            low=Decimal("99") + Decimal(str(i)),
            close=Decimal("100") + Decimal(str(i)),
            volume=Decimal("1000"),
            interval="1m",
        ))
    return bars


class TestContextBuilderWithIntelligence:
    def test_populates_market_snapshots(self) -> None:
        engine = IndicatorEngine(max_bars=50)
        for b in make_bars(30):
            engine.update(b, "1m")

        builder = ContextBuilder(
            indicator_engine=engine,
            regime_detector=MarketRegimeDetector(),
            announcement_service=AnnouncementIntelligenceService(),
        )
        config = StrategyConfig(
            strategy_id="test", strategy_type="trend", name="Test", instrument_tokens=["INFY"]
        )
        ctx = builder.build(config, {})
        assert "INFY" in ctx.market_snapshots
        assert "timeframes" in ctx.market_snapshots["INFY"]
        assert "regime" in ctx.market_snapshots["INFY"]

    def test_skips_unknown_instruments(self) -> None:
        engine = IndicatorEngine()
        builder = ContextBuilder(
            indicator_engine=engine,
            regime_detector=MarketRegimeDetector(),
        )
        config = StrategyConfig(
            strategy_id="test", strategy_type="trend", name="Test", instrument_tokens=["UNKNOWN"]
        )
        ctx = builder.build(config, {})
        assert "UNKNOWN" not in ctx.market_snapshots

    def test_no_intelligence_injection_preserves_behavior(self) -> None:
        builder = ContextBuilder()
        config = StrategyConfig(
            strategy_id="test", strategy_type="trend", name="Test", instrument_tokens=["INFY"]
        )
        ctx = builder.build(config, {})
        assert ctx.market_snapshots == {}
        assert ctx.strategy_id == "test"

    def test_multiple_instruments(self) -> None:
        engine = IndicatorEngine(max_bars=50)
        for token in ["INFY", "TCS"]:
            for b in make_bars(30, token):
                engine.update(b, "1m")

        builder = ContextBuilder(
            indicator_engine=engine,
            regime_detector=MarketRegimeDetector(),
        )
        config = StrategyConfig(
            strategy_id="test", strategy_type="trend", name="Test",
            instrument_tokens=["INFY", "TCS"],
        )
        ctx = builder.build(config, {})
        assert "INFY" in ctx.market_snapshots
        assert "TCS" in ctx.market_snapshots

    def test_regime_confidence_in_range(self) -> None:
        engine = IndicatorEngine(max_bars=50)
        for b in make_bars(30):
            engine.update(b, "1m")

        builder = ContextBuilder(
            indicator_engine=engine,
            regime_detector=MarketRegimeDetector(),
        )
        config = StrategyConfig(
            strategy_id="test", strategy_type="trend", name="Test", instrument_tokens=["INFY"]
        )
        ctx = builder.build(config, {})
        regime = ctx.market_snapshots["INFY"]["regime"]
        assert Decimal("0") <= regime.confidence <= Decimal("1")
