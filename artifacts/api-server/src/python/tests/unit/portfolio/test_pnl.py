"""Unit tests for P&L Engine (pnl.py).

Covers:
  - estimate_charges: brokerage, STT, GST computed
  - calculate_realised_pnl: profitable and losing trades
  - build_position_pnl: from PortfolioPosition
  - build_portfolio_pnl: drawdown calculation (peak > equity)
  - apply_confirmed_charges: fees_are_estimated=False
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.portfolio.contracts import (
    PortfolioPosition,
    PositionPnL,
    PositionSide,
    PositionStatus,
)
from src.portfolio.pnl import PnLEngine, PnLCalculator

_NOW = datetime.now(timezone.utc)
_TOKEN = 738561
_SYMBOL = "RELIANCE"

_ENGINE = PnLEngine()


def _make_long_position(
    qty: int = 10,
    entry: Decimal = Decimal("100"),
    realised: Decimal = Decimal("0"),
    unrealised: Decimal = Decimal("0"),
    fees: Decimal = Decimal("0"),
    market_price: Decimal | None = None,
) -> PortfolioPosition:
    """Helper to create a PortfolioPosition for testing."""
    return PortfolioPosition(
        instrument_token=_TOKEN,
        instrument_symbol=_SYMBOL,
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        open_quantity=qty,
        average_entry_price=entry,
        last_market_price=market_price,
        last_price_as_of=_NOW if market_price is not None else None,
        realised_pnl=realised,
        unrealised_pnl=unrealised,
        total_fees=fees,
        opened_at=_NOW,
    )


class TestEstimateCharges:
    def test_brokerage_flat_rate(self):
        """Brokerage is capped at ₹20 per leg."""
        charges = _ENGINE.estimate_charges(qty=100, price=Decimal("100"), side="BUY")
        assert charges["brokerage"] == Decimal("20")

    def test_stt_on_sell_delivery(self):
        """STT (0.1%) applied on sell-side CNC turnover."""
        # 100 qty * ₹100 = ₹10000 turnover → STT = 0.001 * 10000 = 10
        charges = _ENGINE.estimate_charges(qty=100, price=Decimal("100"), side="SELL", product="CNC")
        assert charges["stt"] == Decimal("10")

    def test_no_stt_on_buy_delivery(self):
        """No STT on buy side for CNC (delivery)."""
        charges = _ENGINE.estimate_charges(qty=100, price=Decimal("100"), side="BUY", product="CNC")
        assert charges["stt"] == Decimal("0")

    def test_gst_on_brokerage_and_exchange(self):
        """GST (18%) is applied on brokerage + exchange charge."""
        charges = _ENGINE.estimate_charges(qty=100, price=Decimal("100"), side="BUY")
        # brokerage=20; exchange_charge=100*100*0.0000345
        expected_gst_min = charges["brokerage"] * Decimal("0.18")
        assert charges["gst"] >= expected_gst_min

    def test_total_is_sum_of_components(self):
        """Total = brokerage + stt + exchange_charge + gst + sebi + stamp."""
        charges = _ENGINE.estimate_charges(qty=10, price=Decimal("50"), side="SELL")
        expected = (
            charges["brokerage"]
            + charges["stt"]
            + charges["exchange_charge"]
            + charges["gst"]
            + charges["sebi"]
            + charges["stamp"]
        )
        assert charges["total"] == expected

    def test_stamp_duty_on_buy(self):
        """Stamp duty is applied on buy side only."""
        buy_charges = _ENGINE.estimate_charges(qty=100, price=Decimal("100"), side="BUY")
        sell_charges = _ENGINE.estimate_charges(qty=100, price=Decimal("100"), side="SELL")
        assert buy_charges["stamp"] > Decimal("0")
        assert sell_charges["stamp"] == Decimal("0")

    def test_intraday_stt_on_buy(self):
        """Intraday (MIS) buy has STT."""
        charges = _ENGINE.estimate_charges(qty=100, price=Decimal("100"), side="BUY", product="MIS")
        assert charges["stt"] > Decimal("0")


class TestCalculateRealisedPnl:
    def test_long_profitable(self):
        """Long trade: sell > buy → positive net P&L."""
        pnl = _ENGINE.calculate_realised_pnl(
            buy_price=Decimal("100"),
            sell_price=Decimal("110"),
            qty=100,
            charges=Decimal("0"),
        )
        assert pnl == Decimal("1000")

    def test_long_losing(self):
        """Long trade: sell < buy → negative net P&L."""
        pnl = _ENGINE.calculate_realised_pnl(
            buy_price=Decimal("100"),
            sell_price=Decimal("90"),
            qty=100,
            charges=Decimal("0"),
        )
        assert pnl == Decimal("-1000")

    def test_charges_deducted(self):
        """Net P&L = gross - charges."""
        pnl = _ENGINE.calculate_realised_pnl(
            buy_price=Decimal("100"),
            sell_price=Decimal("110"),
            qty=100,
            charges=Decimal("50"),
        )
        assert pnl == Decimal("950")  # 1000 - 50

    def test_zero_pnl_at_breakeven(self):
        """Entry == exit → zero gross P&L (charges still deducted)."""
        pnl = _ENGINE.calculate_realised_pnl(
            buy_price=Decimal("100"),
            sell_price=Decimal("100"),
            qty=100,
            charges=Decimal("0"),
        )
        assert pnl == Decimal("0")

    def test_large_quantity(self):
        """Large quantity is handled correctly."""
        pnl = _ENGINE.calculate_realised_pnl(
            buy_price=Decimal("2500"),
            sell_price=Decimal("2550"),
            qty=1000,
            charges=Decimal("0"),
        )
        assert pnl == Decimal("50000")


class TestBuildPositionPnl:
    def test_build_from_position_cached_values(self):
        """build_position_pnl maps position fields when no market_price given."""
        pos = _make_long_position(
            realised=Decimal("500"),
            unrealised=Decimal("-100"),
            fees=Decimal("40"),
        )
        pnl = _ENGINE.build_position_pnl(pos)
        assert pnl.instrument_token == _TOKEN
        assert pnl.realised == Decimal("500")
        assert pnl.unrealised == Decimal("-100")
        assert pnl.total == Decimal("400")
        assert pnl.estimated_fees == Decimal("40")
        assert pnl.fees_are_estimated is True

    def test_build_with_market_price_recalculates(self):
        """build_position_pnl with market_price recalculates unrealised."""
        pos = _make_long_position(qty=10, entry=Decimal("100"), unrealised=Decimal("0"))
        pnl = _ENGINE.build_position_pnl(pos, market_price=Decimal("110"))
        # (110-100)*10 = 100
        assert pnl.unrealised == Decimal("100.00")

    def test_build_zero_position(self):
        """build_position_pnl with all zeros."""
        pos = _make_long_position()
        pnl = _ENGINE.build_position_pnl(pos)
        assert pnl.realised == Decimal("0")
        assert pnl.unrealised == Decimal("0")
        assert pnl.total == Decimal("0")


class TestBuildPortfolioPnl:
    def test_drawdown_calculation(self):
        """Drawdown = (peak - current) / peak."""
        pos = _make_long_position(unrealised=Decimal("0"))
        pnl = _ENGINE.build_portfolio_pnl(
            positions=[pos],
            realised_total=Decimal("0"),
            cash_balance=Decimal("90000"),
            initial_capital=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("200"),
            trading_date="2024-01-15",
        )
        # current_equity = cash + market_value_of_positions
        assert pnl.drawdown >= Decimal("0")
        assert pnl.drawdown <= Decimal("1")

    def test_no_drawdown_when_at_peak(self):
        """No drawdown when current == peak."""
        pnl = _ENGINE.build_portfolio_pnl(
            positions=[],
            realised_total=Decimal("0"),
            cash_balance=Decimal("100000"),
            initial_capital=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            trading_date="2024-01-15",
        )
        assert pnl.drawdown == Decimal("0")

    def test_drawdown_peak_larger(self):
        """Drawdown = (peak - current) / peak when peak > current."""
        pnl = _ENGINE.build_portfolio_pnl(
            positions=[],
            realised_total=Decimal("0"),
            cash_balance=Decimal("90000"),
            initial_capital=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            trading_date="2024-01-15",
        )
        assert pnl.drawdown == Decimal("0.1000")  # (100000-90000)/100000

    def test_aggregate_pnl_across_positions(self):
        """Total P&L is sum across positions."""
        pos1 = _make_long_position(realised=Decimal("200"), unrealised=Decimal("100"))
        pos2 = _make_long_position(realised=Decimal("300"), unrealised=Decimal("-50"))
        pnl = _ENGINE.build_portfolio_pnl(
            positions=[pos1, pos2],
            realised_total=Decimal("500"),
            cash_balance=Decimal("100000"),
            initial_capital=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            trading_date="2024-01-15",
        )
        assert pnl.realised == Decimal("500")
        assert pnl.unrealised == Decimal("50")


class TestApplyConfirmedCharges:
    def test_fees_are_estimated_becomes_false(self):
        """apply_confirmed_charges sets fees_are_estimated=False."""
        pos_pnl = PositionPnL(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            realised=Decimal("500"),
            unrealised=Decimal("0"),
            total=Decimal("500"),
            estimated_fees=Decimal("40"),
        )
        updated = _ENGINE.apply_confirmed_charges(
            position_pnl=pos_pnl,
            confirmed_brokerage=Decimal("20"),
            confirmed_taxes=Decimal("15"),
            confirmed_fees=Decimal("5"),
        )
        assert updated.fees_are_estimated is False
        assert updated.confirmed_fees == Decimal("40")
        # total = realised + unrealised - total_confirmed = 500 + 0 - 40 = 460
        assert updated.total == Decimal("460")

    def test_zero_confirmed_fees(self):
        """apply_confirmed_charges with zero fees."""
        pos_pnl = PositionPnL(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            realised=Decimal("100"),
            unrealised=Decimal("0"),
            total=Decimal("100"),
        )
        updated = _ENGINE.apply_confirmed_charges(
            pos_pnl, Decimal("0"), Decimal("0"), Decimal("0")
        )
        assert updated.fees_are_estimated is False
        assert updated.total == Decimal("100")


class TestPnLCalculatorAlias:
    def test_build_portfolio_pnl_alias(self):
        """PnLCalculator.build_portfolio_pnl alias works for backward compat."""
        pnl = PnLCalculator.build_portfolio_pnl(
            positions=[],
            daily_pnl=Decimal("0"),
            peak_equity=Decimal("100000"),
            current_equity=Decimal("100000"),
        )
        assert pnl.drawdown == Decimal("0")
        assert pnl.daily_pnl == Decimal("0")
