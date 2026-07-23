"""Integration tests: ContextBuilder backward-compat without intelligence injection."""
from __future__ import annotations

from decimal import Decimal

from strategy.contracts import StrategyConfig
from strategy.context_builder import ContextBuilder


class TestContextBuilderNoIntelligence:
    def test_same_result_as_pre_10a(self) -> None:
        builder = ContextBuilder()
        config = StrategyConfig(
            strategy_id="test",
            strategy_type="trend",
            name="Test",
            instrument_tokens=["INFY", "TCS"],
        )
        ctx = builder.build(config, {})
        assert ctx.strategy_id == "test"
        assert ctx.market_snapshots == {}

    def test_positional_constructor_still_valid(self) -> None:
        builder = ContextBuilder()
        assert builder._indicator_engine is None
        assert builder._regime_detector is None
        assert builder._announcement_service is None
        assert builder._watchlist_ranker is None

    def test_build_returns_strategy_context(self) -> None:
        builder = ContextBuilder()
        config = StrategyConfig(
            strategy_id="s1",
            strategy_type="trend",
            name="S1",
            instrument_tokens=["A"],
        )
        ctx = builder.build(config, {})
        # market_snapshots empty when no intelligence injected
        assert ctx.market_snapshots == {}

    def test_build_strategy_id_matches_config(self) -> None:
        builder = ContextBuilder()
        config = StrategyConfig(
            strategy_id="unique_id_xyz",
            strategy_type="trend",
            name="T",
            instrument_tokens=[],
        )
        ctx = builder.build(config, {})
        assert ctx.strategy_id == "unique_id_xyz"
