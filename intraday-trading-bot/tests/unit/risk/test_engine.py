"""
Unit tests for risk/engine.py.
"""

import pytest
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta

from src.risk.engine import RiskEngine
from src.risk.contracts import (
    RiskAction,
    RiskSeverity,
    OrderSizeLimit,
    PriceToleranceLimit,
    PositionLimit,
    PortfolioExposureLimit,
    DailyLossLimit,
    MessageThrottleLimit,
    DuplicateOrderLimit,
    SelfTradeLimit,
    PortfolioHeatLimit,
    DrawdownLimit,
    TurnoverVelocityLimit,
)


@pytest.fixture
def engine():
    return RiskEngine()


@pytest.fixture
def sample_limits():
    return [
        OrderSizeLimit(rule_id="os_001", max_quantity=Decimal("100")),
        PriceToleranceLimit(rule_id="pt_001", max_deviation_percent=Decimal("5")),
        PositionLimit(
            rule_id="pl_001",
            max_long_quantity=Decimal("1000"),
            max_short_quantity=Decimal("500"),
            instrument_token="INFY",
        ),
        PortfolioExposureLimit(rule_id="pe_001", max_exposure_percent=Decimal("90")),
        DailyLossLimit(rule_id="dl_001", max_daily_loss=Decimal("10000")),
        MessageThrottleLimit(rule_id="mt_001", max_messages=10, window_seconds=60),
        DuplicateOrderLimit(rule_id="dup_001", window_seconds=5),
        SelfTradeLimit(rule_id="st_001"),
        PortfolioHeatLimit(rule_id="ph_001", max_concentration_percent=Decimal("50")),
        DrawdownLimit(rule_id="dd_001", max_drawdown_percent=Decimal("10")),
        TurnoverVelocityLimit(rule_id="tv_001", max_velocity=Decimal("10")),
    ]


class TestRiskEngineRegistration:
    @pytest.mark.asyncio
    async def test_register_account(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        snapshot = await engine.get_state_snapshot("ACC001")
        assert snapshot.account_id == "ACC001"
        assert snapshot.peak_equity == Decimal("100000")

    @pytest.mark.asyncio
    async def test_register_with_limits(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"), limits=sample_limits)
        snapshot = await engine.get_state_snapshot("ACC001")
        assert snapshot is not None

    @pytest.mark.asyncio
    async def test_set_limits(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)
        # Verify limits are applied by running a check
        result = await engine.pre_trade_check(
            account_id="ACC001",
            order={"instrument_token": "INFY", "quantity": Decimal("50"), "side": "BUY", "price": Decimal("1500"), "order_type": "LIMIT"},
            market_prices={"INFY": Decimal("1500")},
        )
        assert result.action == RiskAction.ALLOW

    @pytest.mark.asyncio
    async def test_duplicate_registration_is_idempotent(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.register_account("ACC001", initial_equity=Decimal("200000"))
        snapshot = await engine.get_state_snapshot("ACC001")
        # Second registration should not overwrite
        assert snapshot.peak_equity == Decimal("100000")


class TestRiskEnginePreTrade:
    @pytest.mark.asyncio
    async def test_allow_valid_order(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order={
                "instrument_token": "INFY",
                "quantity": Decimal("10"),
                "side": "BUY",
                "price": Decimal("1500"),
                "order_type": "LIMIT",
            },
            market_prices={"INFY": Decimal("1500")},
        )
        assert result.action == RiskAction.ALLOW
        assert result.violations == []

    @pytest.mark.asyncio
    async def test_block_oversized_order(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order={
                "instrument_token": "INFY",
                "quantity": Decimal("200"),  # exceeds max 100
                "side": "BUY",
                "price": Decimal("1500"),
                "order_type": "LIMIT",
            },
            market_prices={"INFY": Decimal("1500")},
        )
        assert result.action == RiskAction.BLOCK
        assert any(v.check_type.value == "ORDER_SIZE" for v in result.violations)

    @pytest.mark.asyncio
    async def test_block_price_deviation(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order={
                "instrument_token": "INFY",
                "quantity": Decimal("10"),
                "side": "BUY",
                "price": Decimal("2000"),  # 33% deviation
                "order_type": "LIMIT",
            },
            market_prices={"INFY": Decimal("1500")},
        )
        assert result.action == RiskAction.BLOCK
        assert any(v.check_type.value == "PRICE_TOLERANCE" for v in result.violations)

    @pytest.mark.asyncio
    async def test_kill_switch_on_daily_loss(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", [
            DailyLossLimit(rule_id="dl_001", max_daily_loss=Decimal("1000")),
        ])

        # Record a loss that exceeds the limit
        await engine.record_fill(
            account_id="ACC001",
            realized_pnl=Decimal("-2000"),
            turnover=Decimal("50000"),
            current_equity=Decimal("98000"),
        )

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order={"instrument_token": "INFY", "quantity": Decimal("10"), "side": "BUY", "price": Decimal("1500"), "order_type": "LIMIT"},
            market_prices={"INFY": Decimal("1500")},
        )
        assert result.action == RiskAction.KILL_SWITCH
        assert engine.is_kill_switch_active("ACC001")

    @pytest.mark.asyncio
    async def test_throttle(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)

        order = {
            "instrument_token": "INFY",
            "quantity": Decimal("10"),
            "side": "BUY",
            "price": Decimal("1500"),
            "order_type": "LIMIT",
        }
        market_prices = {"INFY": Decimal("1500")}

        # Space calls 6s apart: just beyond the 5s duplicate-order dedup window
        # so duplicate detection never fires, while keeping all calls inside the
        # 60s throttle window (8 * 6s = 48s total span for the 9 passing calls).
        # The throttle rule fires at count >= max_messages (i.e. on the 10th call),
        # so we send 9 passing calls first, then assert the 10th is blocked.
        base_ts = datetime(2026, 1, 1, 9, 0, 0)
        for i in range(9):
            result = await engine.pre_trade_check(
                account_id="ACC001",
                order=order,
                market_prices=market_prices,
                check_timestamp=base_ts + timedelta(seconds=i * 6),
            )
            assert result.action in (RiskAction.ALLOW, RiskAction.WARN)

        # 10th call: message count reaches max_messages(10) → throttle fires.
        result = await engine.pre_trade_check(
            account_id="ACC001",
            order=order,
            market_prices=market_prices,
            check_timestamp=base_ts + timedelta(seconds=9 * 6),
        )
        assert result.action == RiskAction.BLOCK
        assert any(v.check_type.value == "MESSAGE_THROTTLE" for v in result.violations)

    @pytest.mark.asyncio
    async def test_duplicate_order(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)

        order = {
            "instrument_token": "INFY",
            "quantity": Decimal("10"),
            "side": "BUY",
            "price": Decimal("1500"),
            "order_type": "LIMIT",
        }
        market_prices = {"INFY": Decimal("1500")}

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order=order,
            market_prices=market_prices,
        )
        assert result.action == RiskAction.ALLOW

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order=order,
            market_prices=market_prices,
        )
        assert result.action == RiskAction.BLOCK
        assert any(v.check_type.value == "DUPLICATE_ORDER" for v in result.violations)

    @pytest.mark.asyncio
    async def test_no_limits_allows_all(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order={"instrument_token": "INFY", "quantity": Decimal("10000"), "side": "BUY", "price": Decimal("1500"), "order_type": "LIMIT"},
            market_prices={"INFY": Decimal("1500")},
        )
        assert result.action == RiskAction.ALLOW

    @pytest.mark.asyncio
    async def test_auto_register_unknown_account(self, engine):
        result = await engine.pre_trade_check(
            account_id="NEW001",
            order={"instrument_token": "INFY", "quantity": Decimal("10"), "side": "BUY"},
        )
        assert result.account_id == "NEW001"
        assert result.action == RiskAction.ALLOW

    @pytest.mark.asyncio
    async def test_self_trade_blocked(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)

        order = {"instrument_token": "INFY", "side": "BUY", "price": Decimal("1500"), "quantity": Decimal("10"), "order_type": "LIMIT"}
        open_orders = [{"instrument_token": "INFY", "side": "SELL", "price": Decimal("1490")}]

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order=order,
            open_orders=open_orders,
            market_prices={"INFY": Decimal("1500")},
        )
        assert result.action == RiskAction.BLOCK
        assert any(v.check_type.value == "SELF_TRADE" for v in result.violations)

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_orders(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)
        await engine.activate_kill_switch("ACC001", reason="Test", actor="test")

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order={"instrument_token": "INFY", "quantity": Decimal("10"), "side": "BUY", "price": Decimal("1500"), "order_type": "LIMIT"},
            market_prices={"INFY": Decimal("1500")},
        )
        assert result.action == RiskAction.KILL_SWITCH
        assert any(v.check_type.value == "KILL_SWITCH" for v in result.violations)

    @pytest.mark.asyncio
    async def test_kill_switch_deactivate(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)
        await engine.activate_kill_switch("ACC001", reason="Test")
        await engine.deactivate_kill_switch("ACC001", reason="Resolved")

        assert not engine.is_kill_switch_active("ACC001")

        result = await engine.pre_trade_check(
            account_id="ACC001",
            order={"instrument_token": "INFY", "quantity": Decimal("10"), "side": "BUY", "price": Decimal("1500"), "order_type": "LIMIT"},
            market_prices={"INFY": Decimal("1500")},
        )
        assert result.action == RiskAction.ALLOW


class TestRiskEnginePostTrade:
    @pytest.mark.asyncio
    async def test_post_trade_allow(self, engine, sample_limits):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", sample_limits)

        result = await engine.post_trade_check(
            account_id="ACC001",
            portfolio_snapshot={"equity": Decimal("100000"), "total_market_value": Decimal("30000")},
            position_snapshots={"INFY": {"market_value": Decimal("30000")}},
        )
        assert result.action == RiskAction.ALLOW

    @pytest.mark.asyncio
    async def test_post_trade_warn_on_concentration(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", [
            PortfolioHeatLimit(rule_id="ph_001", max_concentration_percent=Decimal("30"), severity=RiskSeverity.WARNING),
        ])

        result = await engine.post_trade_check(
            account_id="ACC001",
            portfolio_snapshot={"equity": Decimal("100000")},
            position_snapshots={"INFY": {"market_value": Decimal("40000")}},
        )
        assert result.action == RiskAction.WARN

    @pytest.mark.asyncio
    async def test_post_trade_never_blocks(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.set_limits("ACC001", [
            DrawdownLimit(rule_id="dd_001", max_drawdown_percent=Decimal("5")),
        ])

        await engine.record_fill(
            account_id="ACC001",
            realized_pnl=Decimal("0"),
            turnover=Decimal("0"),
            current_equity=Decimal("100000"),
        )

        result = await engine.post_trade_check(
            account_id="ACC001",
            portfolio_snapshot={"equity": Decimal("90000")},
            position_snapshots={},
        )
        assert result.action not in (RiskAction.BLOCK, RiskAction.KILL_SWITCH)


class TestRiskEngineRecordFill:
    @pytest.mark.asyncio
    async def test_record_fill_updates_state(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))

        await engine.record_fill(
            account_id="ACC001",
            realized_pnl=Decimal("500"),
            turnover=Decimal("10000"),
            current_equity=Decimal("100500"),
        )

        snapshot = await engine.get_state_snapshot("ACC001")
        assert snapshot.daily_realized_pnl == Decimal("500")
        assert snapshot.daily_turnover == Decimal("10000")
        assert snapshot.peak_equity == Decimal("100500")

    @pytest.mark.asyncio
    async def test_record_fill_auto_registers(self, engine):
        await engine.record_fill(
            account_id="NEW001",
            realized_pnl=Decimal("100"),
            turnover=Decimal("5000"),
            current_equity=Decimal("100100"),
        )
        snapshot = await engine.get_state_snapshot("NEW001")
        assert snapshot.daily_realized_pnl == Decimal("100")


class TestRiskEngineKillSwitch:
    @pytest.mark.asyncio
    async def test_manual_activate(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.activate_kill_switch("ACC001", reason="Circuit breaker", actor="operator")
        assert engine.is_kill_switch_active("ACC001")

        history = engine.get_kill_switch_history("ACC001")
        assert len(history) == 1
        assert history[0].action == "ACTIVATED"
        assert history[0].actor == "operator"

    @pytest.mark.asyncio
    async def test_manual_deactivate(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.activate_kill_switch("ACC001", reason="Test")
        await engine.deactivate_kill_switch("ACC001", reason="Cleared", actor="operator")

        assert not engine.is_kill_switch_active("ACC001")
        history = engine.get_kill_switch_history("ACC001")
        assert len(history) == 2
        assert history[1].action == "DEACTIVATED"

    @pytest.mark.asyncio
    async def test_kill_switch_unknown_account(self, engine):
        assert not engine.is_kill_switch_active("UNKNOWN")
        assert engine.get_kill_switch_history("UNKNOWN") == []


class TestRiskEngineReset:
    @pytest.mark.asyncio
    async def test_reset_account(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine.record_fill(
            account_id="ACC001",
            realized_pnl=Decimal("1000"),
            turnover=Decimal("50000"),
            current_equity=Decimal("101000"),
        )

        await engine.reset_account("ACC001", initial_equity=Decimal("101000"))
        snapshot = await engine.get_state_snapshot("ACC001")
        assert snapshot.daily_realized_pnl == Decimal("0")
        assert snapshot.daily_turnover == Decimal("0")

    @pytest.mark.asyncio
    async def test_engine_reset(self, engine):
        await engine.register_account("ACC001", initial_equity=Decimal("100000"))
        engine.reset()
        # After reset, account no longer registered
        assert "ACC001" not in engine._states

    @pytest.mark.asyncio
    async def test_per_engine_duplicate_rule_isolation(self):
        engine1 = RiskEngine()
        engine2 = RiskEngine()

        await engine1.register_account("ACC001", initial_equity=Decimal("100000"))
        await engine2.register_account("ACC001", initial_equity=Decimal("100000"))

        limits = [DuplicateOrderLimit(rule_id="dup_001", window_seconds=30)]
        await engine1.set_limits("ACC001", limits)
        await engine2.set_limits("ACC001", limits)

        order = {"instrument_token": "INFY", "quantity": Decimal("10"), "side": "BUY", "price": Decimal("1500")}

        # First call on engine1 records the order
        result1 = await engine1.pre_trade_check(account_id="ACC001", order=order)
        assert result1.action == RiskAction.ALLOW

        # Same order on engine2 should also allow (isolated state)
        result2 = await engine2.pre_trade_check(account_id="ACC001", order=order)
        assert result2.action == RiskAction.ALLOW
