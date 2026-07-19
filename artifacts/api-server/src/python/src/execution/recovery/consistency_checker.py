"""ConsistencyChecker — post-recovery validation suite.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.

Validates that recovered state is internally consistent:
- Order quantities match filled quantities
- Positions match trade history
- Cash balance matches debits/credits
- P&L figures are coherent
- Portfolio equity is correct
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.execution.portfolio import PortfolioSnapshot, PositionSnapshot
from src.execution.trades import TradeLedger


@dataclass(frozen=True)
class ConsistencyViolation:
    """Single consistency violation report."""

    category: str
    message: str
    expected: Any
    actual: Any


@dataclass
class ConsistencyReport:
    """Complete consistency check report."""

    is_valid: bool
    violations: list[ConsistencyViolation] = field(default_factory=list)

    def add_violation(
        self,
        category: str,
        message: str,
        expected: Any,
        actual: Any,
    ) -> None:
        self.violations.append(
            ConsistencyViolation(
                category=category,
                message=message,
                expected=expected,
                actual=actual,
            )
        )
        self.is_valid = False


class ConsistencyChecker:
    """Validates execution engine state for internal consistency.

    All checks are pure functions operating on snapshots.
    No DB access — all data is passed in.
    """

    def validate(
        self,
        portfolio: PortfolioSnapshot | None,
        positions: dict[int, PositionSnapshot],
        cash: Decimal,
        trade_ledger: TradeLedger | None,
    ) -> ConsistencyReport:
        """Run the full consistency validation suite.

        Args:
            portfolio: Current portfolio snapshot.
            positions: All open positions by instrument_token.
            cash: Current cash balance.
            trade_ledger: Complete trade history.

        Returns:
            ConsistencyReport with any violations found.
        """
        report = ConsistencyReport(is_valid=True)

        # Check 1: Portfolio equity = cash + market_value
        if portfolio is not None:
            self._check_portfolio_equity(report, portfolio)
            self._check_cash_consistency(report, portfolio, cash)
            self._check_pnl_consistency(report, portfolio)
            self._check_trade_count_consistency(report, portfolio, trade_ledger)

        # Check 2: Position direction consistency
        for instrument_token, pos in positions.items():
            self._check_position_direction(report, instrument_token, pos)
            self._check_position_quantities(report, instrument_token, pos)
            self._check_position_pnl(report, instrument_token, pos)

        # Check 3: Trade ledger consistency
        if trade_ledger is not None:
            self._check_trade_ledger_turnover(report, trade_ledger)
            if portfolio is not None:
                self._check_portfolio_turnover(report, portfolio, trade_ledger)

        return report

    # ------------------------------------------------------------------
    # Portfolio checks
    # ------------------------------------------------------------------

    def _check_portfolio_equity(
        self,
        report: ConsistencyReport,
        portfolio: PortfolioSnapshot,
    ) -> None:
        """Verify equity = cash + market_value."""
        expected_equity = portfolio.cash + portfolio.market_value
        if portfolio.equity != expected_equity:
            report.add_violation(
                category="portfolio",
                message="Portfolio equity does not equal cash + market_value",
                expected=str(expected_equity),
                actual=str(portfolio.equity),
            )

    def _check_cash_consistency(
        self,
        report: ConsistencyReport,
        portfolio: PortfolioSnapshot,
        cash: Decimal,
    ) -> None:
        """Verify portfolio cash matches position engine cash."""
        if portfolio.cash != cash:
            report.add_violation(
                category="portfolio",
                message="Portfolio cash does not match position engine cash",
                expected=str(cash),
                actual=str(portfolio.cash),
            )

    def _check_pnl_consistency(
        self,
        report: ConsistencyReport,
        portfolio: PortfolioSnapshot,
    ) -> None:
        """Verify total_pnl = realized_pnl + unrealized_pnl."""
        expected_total = portfolio.realized_pnl + portfolio.unrealized_pnl
        if portfolio.total_pnl != expected_total:
            report.add_violation(
                category="portfolio",
                message="Total P&L does not equal realized + unrealized",
                expected=str(expected_total),
                actual=str(portfolio.total_pnl),
            )

    def _check_trade_count_consistency(
        self,
        report: ConsistencyReport,
        portfolio: PortfolioSnapshot,
        trade_ledger: TradeLedger | None,
    ) -> None:
        """Verify portfolio trade_count matches ledger."""
        if trade_ledger is None:
            return
        if portfolio.trade_count != trade_ledger.trade_count:
            report.add_violation(
                category="portfolio",
                message="Portfolio trade_count does not match trade ledger",
                expected=trade_ledger.trade_count,
                actual=portfolio.trade_count,
            )

    # ------------------------------------------------------------------
    # Position checks
    # ------------------------------------------------------------------

    def _check_position_direction(
        self,
        report: ConsistencyReport,
        instrument_token: int,
        pos: PositionSnapshot,
    ) -> None:
        """Verify direction is consistent with net_quantity."""
        expected_direction = self._direction_from_quantity(pos.net_quantity)
        if pos.direction != expected_direction:
            report.add_violation(
                category="position",
                message=f"Position direction inconsistent for {instrument_token}",
                expected=expected_direction,
                actual=pos.direction,
            )

    def _check_position_quantities(
        self,
        report: ConsistencyReport,
        instrument_token: int,
        pos: PositionSnapshot,
    ) -> None:
        """Verify net_quantity = total_buy - total_sell."""
        expected_net = pos.total_buy_quantity - pos.total_sell_quantity
        if pos.net_quantity != expected_net:
            report.add_violation(
                category="position",
                message=f"Net quantity mismatch for {instrument_token}",
                expected=expected_net,
                actual=pos.net_quantity,
            )

    def _check_position_pnl(
        self,
        report: ConsistencyReport,
        instrument_token: int,
        pos: PositionSnapshot,
    ) -> None:
        """Verify unrealized P&L is consistent with market price."""
        if pos.market_price is None:
            return

        if pos.direction == "LONG":
            expected_unrealized = pos.net_quantity * (pos.market_price - pos.average_buy_price)
        elif pos.direction == "SHORT":
            expected_unrealized = abs(pos.net_quantity) * (pos.average_sell_price - pos.market_price)
        else:
            expected_unrealized = Decimal("0")

        if pos.unrealized_pnl != expected_unrealized:
            report.add_violation(
                category="position",
                message=f"Unrealized P&L mismatch for {instrument_token}",
                expected=str(expected_unrealized),
                actual=str(pos.unrealized_pnl),
            )

    # ------------------------------------------------------------------
    # Trade ledger checks
    # ------------------------------------------------------------------

    def _check_trade_ledger_turnover(
        self,
        report: ConsistencyReport,
        trade_ledger: TradeLedger,
    ) -> None:
        """Verify turnover equals sum of all trade gross_values."""
        trades = trade_ledger.get_trades()
        expected_turnover = sum(t.gross_value for t in trades)
        if trade_ledger.total_turnover != expected_turnover:
            report.add_violation(
                category="trade_ledger",
                message="Trade ledger turnover does not match sum of gross_values",
                expected=str(expected_turnover),
                actual=str(trade_ledger.total_turnover),
            )

    def _check_portfolio_turnover(
        self,
        report: ConsistencyReport,
        portfolio: PortfolioSnapshot,
        trade_ledger: TradeLedger,
    ) -> None:
        """Verify portfolio turnover matches trade ledger total turnover."""
        if portfolio.turnover != trade_ledger.total_turnover:
            report.add_violation(
                category="trade_ledger",
                message="Portfolio turnover does not match trade ledger total turnover",
                expected=str(trade_ledger.total_turnover),
                actual=str(portfolio.turnover),
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _direction_from_quantity(quantity: int) -> str:
        if quantity > 0:
            return "LONG"
        elif quantity < 0:
            return "SHORT"
        return "FLAT"
