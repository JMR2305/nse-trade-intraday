"""Unit tests for execution policies."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.execution.contracts import ExecutionOrderSide
from src.execution.policies import (
    BasisPointsSlippagePolicy,
    DefaultLiquidityPolicy,
    DefaultPriceSelectionPolicy,
    FixedLatencyPolicy,
    FixedTicksSlippagePolicy,
    ZeroLatencyPolicy,
)


# ==================================================================
# Price Selection
# ==================================================================

class TestPriceSelection:
    def test_buy_prefers_ask(self):
        policy = DefaultPriceSelectionPolicy()
        price = policy.select_price(
            side=ExecutionOrderSide.BUY,
            last_traded_price=Decimal("100"),
            bid_price=Decimal("99"),
            ask_price=Decimal("101"),
        )
        assert price == Decimal("101")

    def test_buy_fallback_to_ltp(self):
        policy = DefaultPriceSelectionPolicy()
        price = policy.select_price(
            side=ExecutionOrderSide.BUY,
            last_traded_price=Decimal("100"),
            bid_price=Decimal("99"),
            ask_price=None,
        )
        assert price == Decimal("100")

    def test_sell_prefers_bid(self):
        policy = DefaultPriceSelectionPolicy()
        price = policy.select_price(
            side=ExecutionOrderSide.SELL,
            last_traded_price=Decimal("100"),
            bid_price=Decimal("99"),
            ask_price=Decimal("101"),
        )
        assert price == Decimal("99")

    def test_sell_fallback_to_ltp(self):
        policy = DefaultPriceSelectionPolicy()
        price = policy.select_price(
            side=ExecutionOrderSide.SELL,
            last_traded_price=Decimal("100"),
            bid_price=None,
            ask_price=Decimal("101"),
        )
        assert price == Decimal("100")


# ==================================================================
# Slippage
# ==================================================================

class TestBasisPointsSlippage:
    def test_buy_slippage_worsens_upward(self):
        policy = BasisPointsSlippagePolicy(basis_points=Decimal("10"))
        price = policy.apply_slippage(
            side=ExecutionOrderSide.BUY,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        assert price > Decimal("100")
        # 10 bps = 0.1%, so 100 * 1.001 = 100.10
        assert price == Decimal("100.10")

    def test_sell_slippage_worsens_downward(self):
        policy = BasisPointsSlippagePolicy(basis_points=Decimal("10"))
        price = policy.apply_slippage(
            side=ExecutionOrderSide.SELL,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        assert price < Decimal("100")
        # 100 / 1.001 ≈ 99.90
        assert price == Decimal("99.90")

    def test_zero_slippage_no_change(self):
        policy = BasisPointsSlippagePolicy(basis_points=Decimal("0"))
        price = policy.apply_slippage(
            side=ExecutionOrderSide.BUY,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        assert price == Decimal("100")

    def test_tick_size_rounding(self):
        policy = BasisPointsSlippagePolicy(basis_points=Decimal("5"))
        price = policy.apply_slippage(
            side=ExecutionOrderSide.BUY,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        # 100 * 1.0005 = 100.05, rounded to 0.05 tick = 100.05
        assert price == Decimal("100.05")


class TestFixedTicksSlippage:
    def test_buy_worsens_upward(self):
        policy = FixedTicksSlippagePolicy(ticks=2)
        price = policy.apply_slippage(
            side=ExecutionOrderSide.BUY,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        assert price == Decimal("100.10")

    def test_sell_worsens_downward(self):
        policy = FixedTicksSlippagePolicy(ticks=2)
        price = policy.apply_slippage(
            side=ExecutionOrderSide.SELL,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        assert price == Decimal("99.90")

    def test_zero_ticks_no_change(self):
        policy = FixedTicksSlippagePolicy(ticks=0)
        price = policy.apply_slippage(
            side=ExecutionOrderSide.BUY,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        assert price == Decimal("100")


# ==================================================================
# Liquidity
# ==================================================================

class TestLiquidity:
    def test_full_fill_when_no_liquidity_info(self):
        policy = DefaultLiquidityPolicy()
        qty = policy.compute_fill_quantity(
            order_quantity=100,
            remaining_quantity=100,
            available_liquidity=None,
        )
        assert qty == 100

    def test_capped_by_liquidity(self):
        policy = DefaultLiquidityPolicy()
        qty = policy.compute_fill_quantity(
            order_quantity=100,
            remaining_quantity=100,
            available_liquidity=50,
        )
        assert qty == 50

    def test_capped_by_remaining(self):
        policy = DefaultLiquidityPolicy()
        qty = policy.compute_fill_quantity(
            order_quantity=100,
            remaining_quantity=30,
            available_liquidity=100,
        )
        assert qty == 30

    def test_zero_remaining(self):
        policy = DefaultLiquidityPolicy()
        qty = policy.compute_fill_quantity(
            order_quantity=100,
            remaining_quantity=0,
            available_liquidity=100,
        )
        assert qty == 0

    def test_zero_liquidity(self):
        policy = DefaultLiquidityPolicy()
        qty = policy.compute_fill_quantity(
            order_quantity=100,
            remaining_quantity=100,
            available_liquidity=0,
        )
        assert qty == 0


# ==================================================================
# Latency
# ==================================================================

class TestLatency:
    def test_zero_latency_always_eligible(self):
        policy = ZeroLatencyPolicy()
        from datetime import datetime, timezone
        assert policy.is_eligible(
            datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )

    def test_fixed_latency_eligible_after_delay(self):
        policy = FixedLatencyPolicy(delay_seconds=Decimal("5"))
        from datetime import datetime, timezone
        order_ts = datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc)
        event_ts = datetime(2026, 7, 20, 9, 15, 6, tzinfo=timezone.utc)
        assert policy.is_eligible(order_ts, event_ts)

    def test_fixed_latency_not_eligible_before_delay(self):
        policy = FixedLatencyPolicy(delay_seconds=Decimal("5"))
        from datetime import datetime, timezone
        order_ts = datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc)
        event_ts = datetime(2026, 7, 20, 9, 15, 3, tzinfo=timezone.utc)
        assert not policy.is_eligible(order_ts, event_ts)


class TestTickSizeRoundingConsistency:
    """Both slippage policies must apply consistent tick-size rounding."""

    def test_basis_points_rounds_to_tick(self):
        policy = BasisPointsSlippagePolicy(basis_points=Decimal("7"))
        price = policy.apply_slippage(
            side=ExecutionOrderSide.BUY,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        # 100 * 1.0007 = 100.07, rounded to nearest 0.05 = 100.05
        assert price == Decimal("100.05")

    def test_fixed_ticks_rounds_to_tick(self):
        policy = FixedTicksSlippagePolicy(ticks=1)
        price = policy.apply_slippage(
            side=ExecutionOrderSide.BUY,
            price=Decimal("100.02"),  # not tick-aligned
            tick_size=Decimal("0.05"),
        )
        # 100.02 + 0.05 = 100.07, rounded to nearest 0.05 = 100.05
        assert price == Decimal("100.05")
