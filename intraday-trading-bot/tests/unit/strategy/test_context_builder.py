"""Tests for strategy/context_builder.py."""
import pytest
from decimal import Decimal
from datetime import datetime

from strategy.context_builder import ContextBuilder
from strategy.contracts import StrategyConfig, StrategyStateSnapshot, StrategyLifecycleState
from market_data.service import MarketDataService
from execution.portfolio import PortfolioSnapshot, PositionSnapshot


@pytest.fixture
def market_data_service():
    mds = MarketDataService()
    mds.set_snapshot("RELIANCE", {
        "ltp": Decimal("2500"),
        "bid": Decimal("2499"),
        "ask": Decimal("2501"),
    })
    return mds

@pytest.fixture
def base_config():
    return StrategyConfig(
        strategy_id="test_strat",
        strategy_type="mock",
        name="Test",
        instrument_tokens=["RELIANCE", "TCS"],
    )

@pytest.fixture
def strategy_state():
    return StrategyStateSnapshot(
        strategy_id="test_strat",
        lifecycle_state=StrategyLifecycleState.ACTIVE,
    )


class TestContextBuilder:
    @pytest.mark.asyncio
    async def test_build_context_basic(self, market_data_service, base_config, strategy_state):
        builder = ContextBuilder(market_data_service)
        ctx = await builder.build_context(base_config, strategy_state)

        assert ctx.strategy_id == "test_strat"
        assert ctx.timestamp is not None
        assert "RELIANCE" in ctx.market_snapshots
        assert ctx.portfolio.cash == Decimal("0")
        assert ctx.portfolio.equity == Decimal("0")
        assert ctx.strategy_positions == {}

    @pytest.mark.asyncio
    async def test_build_context_with_positions(self, market_data_service, base_config, strategy_state):
        builder = ContextBuilder(market_data_service)
        positions = {
            "RELIANCE": PositionSnapshot(
                instrument_token="RELIANCE",
                net_quantity=Decimal("100"),
                direction="LONG",
            )
        }
        ctx = await builder.build_context(base_config, strategy_state, strategy_positions=positions)

        assert ctx.strategy_positions["RELIANCE"].net_quantity == Decimal("100")
        assert ctx.strategy_positions["RELIANCE"].direction == "LONG"

    @pytest.mark.asyncio
    async def test_build_context_with_portfolio(self, market_data_service, base_config, strategy_state):
        builder = ContextBuilder(market_data_service)
        portfolio = PortfolioSnapshot(
            cash=Decimal("100000"),
            equity=Decimal("150000"),
        )
        ctx = await builder.build_context(base_config, strategy_state, portfolio=portfolio)

        assert ctx.portfolio.cash == Decimal("100000")
        assert ctx.portfolio.equity == Decimal("150000")

    @pytest.mark.asyncio
    async def test_build_context_missing_snapshot(self, base_config, strategy_state):
        mds = MarketDataService()
        builder = ContextBuilder(mds)
        ctx = await builder.build_context(base_config, strategy_state)

        assert ctx.market_snapshots == {}

    @pytest.mark.asyncio
    async def test_build_context_risk_state_default(self, market_data_service, base_config, strategy_state):
        builder = ContextBuilder(market_data_service)
        ctx = await builder.build_context(base_config, strategy_state)

        assert ctx.risk_state is not None
        assert ctx.risk_state.account_id == "test_strat"
