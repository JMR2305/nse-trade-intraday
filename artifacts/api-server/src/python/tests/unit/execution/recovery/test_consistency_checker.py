"""Tests for ConsistencyChecker.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.execution.recovery.consistency_checker import ConsistencyChecker, ConsistencyReport, ConsistencyViolation
from src.execution.portfolio import PositionSnapshot, PortfolioSnapshot
from src.execution.trades import TradeLedger, ExecutionTrade
from src.execution.contracts import ExecutionOrderSide


class TestConsistencyReport:
    """ConsistencyReport behavior."""

    def test_empty_report_is_valid(self):
        report = ConsistencyReport(is_valid=True)
        assert report.is_valid
        assert len(report.violations) == 0

    def test_add_violation_makes_invalid(self):
        report = ConsistencyReport(is_valid=True)
        report.add_violation("test", "message", "expected", "actual")
        assert not report.is_valid
        assert len(report.violations) == 1
        assert report.violations[0].category == "test"


class TestPortfolioChecks:
    """Portfolio-level consistency checks."""

    def test_valid_portfolio_passes(self, consistency_checker):
        portfolio = PortfolioSnapshot(
            cash=Decimal("100000"),
            equity=Decimal("105000"),
            positions=(),
            market_value=Decimal("5000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            total_pnl=Decimal("0"),
            buying_power=Decimal("100000"),
            margin_used=Decimal("0"),
            trade_count=0,
            turnover=Decimal("0"),
            timestamp=datetime.now(timezone.utc),
        )
        report = consistency_checker.validate(
            portfolio=portfolio,
            positions={},
            cash=Decimal("100000"),
            trade_ledger=None,
        )
        assert report.is_valid

    def test_equity_mismatch_detected(self, consistency_checker):
        portfolio = PortfolioSnapshot(
            cash=Decimal("100000"),
            equity=Decimal("110000"),  # Wrong: should be 105000
            positions=(),
            market_value=Decimal("5000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            total_pnl=Decimal("0"),
            buying_power=Decimal("100000"),
            margin_used=Decimal("0"),
            trade_count=0,
            turnover=Decimal("0"),
            timestamp=datetime.now(timezone.utc),
        )
        report = consistency_checker.validate(
            portfolio=portfolio,
            positions={},
            cash=Decimal("100000"),
            trade_ledger=None,
        )
        assert not report.is_valid
        assert any(v.category == "portfolio" and "equity" in v.message for v in report.violations)

    def test_cash_mismatch_detected(self, consistency_checker):
        portfolio = PortfolioSnapshot(
            cash=Decimal("100000"),
            equity=Decimal("105000"),
            positions=(),
            market_value=Decimal("5000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            total_pnl=Decimal("0"),
            buying_power=Decimal("100000"),
            margin_used=Decimal("0"),
            trade_count=0,
            turnover=Decimal("0"),
            timestamp=datetime.now(timezone.utc),
        )
        report = consistency_checker.validate(
            portfolio=portfolio,
            positions={},
            cash=Decimal("90000"),  # Mismatch
            trade_ledger=None,
        )
        assert not report.is_valid
        assert any(v.category == "portfolio" and "cash" in v.message for v in report.violations)

    def test_pnl_mismatch_detected(self, consistency_checker):
        portfolio = PortfolioSnapshot(
            cash=Decimal("100000"),
            equity=Decimal("105000"),
            positions=(),
            market_value=Decimal("5000"),
            realized_pnl=Decimal("1000"),
            unrealized_pnl=Decimal("500"),
            total_pnl=Decimal("2000"),  # Wrong: should be 1500
            buying_power=Decimal("100000"),
            margin_used=Decimal("0"),
            trade_count=0,
            turnover=Decimal("0"),
            timestamp=datetime.now(timezone.utc),
        )
        report = consistency_checker.validate(
            portfolio=portfolio,
            positions={},
            cash=Decimal("100000"),
            trade_ledger=None,
        )
        assert not report.is_valid
        assert any(v.category == "portfolio" and "P&L" in v.message for v in report.violations)


class TestPositionChecks:
    """Position-level consistency checks."""

    def test_valid_position_passes(self, consistency_checker):
        pos = PositionSnapshot(
            instrument_token=12345,
            net_quantity=100,
            direction="LONG",
            average_buy_price=Decimal("150.00"),
            average_sell_price=Decimal("0"),
            total_buy_quantity=100,
            total_sell_quantity=0,
            total_buy_value=Decimal("15000.00"),
            total_sell_value=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("500"),
            market_price=Decimal("155.00"),
            market_timestamp=datetime.now(timezone.utc),
        )
        report = consistency_checker.validate(
            portfolio=None,
            positions={12345: pos},
            cash=Decimal("0"),
            trade_ledger=None,
        )
        assert report.is_valid

    def test_direction_mismatch_detected(self, consistency_checker):
        # PositionSnapshot.__post_init__ validates direction at construction time,
        # so we must construct a valid object first, then simulate DB-level
        # corruption (e.g. a stale snapshot row) by overwriting the field directly.
        pos = PositionSnapshot(
            instrument_token=12345,
            net_quantity=-50,  # SHORT
            direction="SHORT",
            average_buy_price=Decimal("0"),
            average_sell_price=Decimal("150.00"),
            total_buy_quantity=0,
            total_sell_quantity=50,
            total_buy_value=Decimal("0"),
            total_sell_value=Decimal("7500.00"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=datetime.now(timezone.utc),
        )
        # Simulate storage-layer corruption: direction field disagrees with net_quantity
        object.__setattr__(pos, "direction", "LONG")
        report = consistency_checker.validate(
            portfolio=None,
            positions={12345: pos},
            cash=Decimal("0"),
            trade_ledger=None,
        )
        assert not report.is_valid
        assert any(v.category == "position" and "direction" in v.message for v in report.violations)

    def test_net_quantity_mismatch_detected(self, consistency_checker):
        pos = PositionSnapshot(
            instrument_token=12345,
            net_quantity=100,  # Says 100
            direction="LONG",
            average_buy_price=Decimal("150.00"),
            average_sell_price=Decimal("0"),
            total_buy_quantity=80,  # But only 80 bought
            total_sell_quantity=0,
            total_buy_value=Decimal("12000.00"),
            total_sell_value=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=datetime.now(timezone.utc),
        )
        report = consistency_checker.validate(
            portfolio=None,
            positions={12345: pos},
            cash=Decimal("0"),
            trade_ledger=None,
        )
        assert not report.is_valid
        assert any(v.category == "position" and "Net quantity" in v.message for v in report.violations)

    def test_unrealized_pnl_mismatch_detected(self, consistency_checker):
        pos = PositionSnapshot(
            instrument_token=12345,
            net_quantity=100,
            direction="LONG",
            average_buy_price=Decimal("150.00"),
            average_sell_price=Decimal("0"),
            total_buy_quantity=100,
            total_sell_quantity=0,
            total_buy_value=Decimal("15000.00"),
            total_sell_value=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("1000"),  # Wrong: should be 100 * (155 - 150) = 500
            market_price=Decimal("155.00"),
            market_timestamp=datetime.now(timezone.utc),
        )
        report = consistency_checker.validate(
            portfolio=None,
            positions={12345: pos},
            cash=Decimal("0"),
            trade_ledger=None,
        )
        assert not report.is_valid
        assert any(v.category == "position" and "Unrealized P&L" in v.message for v in report.violations)


class TestTradeLedgerChecks:
    """Trade ledger consistency checks."""

    def test_trade_count_mismatch_detected(self, consistency_checker):
        ledger = TradeLedger()
        trade = ExecutionTrade(
            trade_id="T-001",
            fill_id="fill-001",
            order_id=uuid4(),
            client_order_id="test-001",
            instrument_token=12345,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150.00"),
            gross_value=Decimal("15000.00"),
            position_impact="OPEN",
            market_timestamp=datetime.now(timezone.utc),
        )
        ledger.record(trade)

        portfolio = PortfolioSnapshot(
            cash=Decimal("85000"),
            equity=Decimal("100000"),
            positions=(),
            market_value=Decimal("15000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            total_pnl=Decimal("0"),
            buying_power=Decimal("85000"),
            margin_used=Decimal("15000"),
            trade_count=0,  # Wrong: should be 1
            turnover=Decimal("15000.00"),
            timestamp=datetime.now(timezone.utc),
        )
        report = consistency_checker.validate(
            portfolio=portfolio,
            positions={},
            cash=Decimal("85000"),
            trade_ledger=ledger,
        )
        assert not report.is_valid
        assert any(v.category == "portfolio" and "trade_count" in v.message for v in report.violations)

    def test_turnover_mismatch_detected(self, consistency_checker):
        ledger = TradeLedger()
        trade = ExecutionTrade(
            trade_id="T-001",
            fill_id="fill-001",
            order_id=uuid4(),
            client_order_id="test-001",
            instrument_token=12345,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150.00"),
            gross_value=Decimal("15000.00"),
            position_impact="OPEN",
            market_timestamp=datetime.now(timezone.utc),
        )
        ledger.record(trade)

        portfolio = PortfolioSnapshot(
            cash=Decimal("85000"),
            equity=Decimal("100000"),
            positions=(),
            market_value=Decimal("15000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            total_pnl=Decimal("0"),
            buying_power=Decimal("85000"),
            margin_used=Decimal("15000"),
            trade_count=1,
            turnover=Decimal("10000.00"),  # Wrong: should be 15000
            timestamp=datetime.now(timezone.utc),
        )
        report = consistency_checker.validate(
            portfolio=portfolio,
            positions={},
            cash=Decimal("85000"),
            trade_ledger=ledger,
        )
        assert not report.is_valid
        assert any(v.category == "trade_ledger" and "turnover" in v.message for v in report.violations)
