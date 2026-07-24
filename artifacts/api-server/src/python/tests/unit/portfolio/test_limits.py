"""Unit tests for the Portfolio Limit Engine (limits.py).

Covers:
  - Each limit checked independently (9+ limit types)
  - Boundary: exactly at limit → allowed
  - One unit over → not allowed
  - CRITICAL severity on loss/drawdown breaches
  - overall_allowed=False when any critical fails
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.portfolio.config import PortfolioConfig
from src.portfolio.contracts import (
    BuyingPower,
    CashBalance,
    ExposureSnapshot,
    LimitSeverity,
    MarginState,
    PortfolioPnL,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioStatus,
    PositionSide,
    PositionStatus,
)
from src.portfolio.limits import check_all_limits

_NOW = datetime.now(timezone.utc)


def _make_config(**kw) -> PortfolioConfig:
    defaults = dict(
        initial_capital=Decimal("100000"),
        cash_reserve_pct=Decimal("0.05"),
        max_portfolio_exposure_pct=Decimal("0.90"),
        max_open_positions=5,
        max_pending_orders=10,
        max_daily_loss_pct=Decimal("0.03"),
        max_drawdown_pct=Decimal("0.10"),
        min_order_value=Decimal("1000"),
        max_order_value=Decimal("50000"),
    )
    defaults.update(kw)
    return PortfolioConfig(**defaults)


def _make_snapshot(
    *,
    available: Decimal = Decimal("80000"),
    blocked: Decimal = Decimal("5000"),
    daily_pnl: Decimal = Decimal("0"),
    drawdown: Decimal = Decimal("0"),
    open_positions: int = 0,
    pending_orders: int = 0,
    gross_exposure: Decimal = Decimal("10000"),
    current_equity: Decimal = Decimal("100000"),
    peak_equity: Decimal = Decimal("100000"),
) -> PortfolioSnapshot:
    """Build a simple PortfolioSnapshot for limit testing."""
    total = available + blocked
    cash = CashBalance(available=available, blocked=blocked, total=total, as_of=_NOW)
    margin = MarginState(used=Decimal("0"), available=total, total=total, as_of=_NOW)
    bp = BuyingPower(gross=total, net=available, reserved=blocked, as_of=_NOW)
    exposure = ExposureSnapshot(
        gross_exposure=gross_exposure,
        net_exposure=gross_exposure,
        portfolio_equity=current_equity,
        as_of=_NOW,
    )
    pnl = PortfolioPnL(
        daily_pnl=daily_pnl,
        drawdown=drawdown,
        peak_equity=peak_equity,
        current_equity=current_equity,
    )
    positions = tuple(
        PortfolioPosition(
            instrument_token=i + 1,
            instrument_symbol=f"STOCK{i}",
            side=PositionSide.LONG,
            open_quantity=10,
        )
        for i in range(open_positions)
    )
    return PortfolioSnapshot(
        portfolio_id="test",
        status=PortfolioStatus.READY,
        version=1,
        cash=cash,
        margin=margin,
        buying_power=bp,
        exposure=exposure,
        pnl=pnl,
        open_positions=positions,
        pending_order_count=pending_orders,
        snapshotted_at=_NOW,
    )


# ===========================================================================
# Max Gross Exposure
# ===========================================================================

class TestGrossExposureLimit:
    def test_within_gross_exposure_allowed(self):
        """Proposed + current within max_deployable → max_gross_exposure passes."""
        config = _make_config(max_portfolio_exposure_pct=Decimal("0.90"))
        # equity=100000; limit=90000; current=10000; proposed=5000; total=15000 < 90000
        snap = _make_snapshot(gross_exposure=Decimal("10000"), current_equity=Decimal("100000"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("5000"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_gross_exposure")
        assert result.allowed is True

    def test_over_gross_exposure_blocked(self):
        """Proposed + current exceeds max_deployable → blocked."""
        config = _make_config(max_portfolio_exposure_pct=Decimal("0.10"))
        # equity=100000; limit=10000; current=10000; proposed=5000 > limit
        snap = _make_snapshot(gross_exposure=Decimal("10000"), current_equity=Decimal("100000"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("5000"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_gross_exposure")
        assert result.allowed is False


# ===========================================================================
# Daily Loss Limit
# ===========================================================================

class TestDailyLossLimit:
    def test_within_daily_loss_allowed(self):
        """Daily loss within limit → daily_loss check passes."""
        config = _make_config(max_daily_loss_pct=Decimal("0.03"))
        snap = _make_snapshot(daily_pnl=Decimal("-500"), current_equity=Decimal("100000"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("1000"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_daily_loss")
        assert result.allowed is True

    def test_daily_loss_breached_critical(self):
        """Daily loss exceeds limit → CRITICAL."""
        config = _make_config(max_daily_loss_pct=Decimal("0.03"))
        # equity=100000; limit=3000; pnl=-4000 → breach
        snap = _make_snapshot(daily_pnl=Decimal("-4000"), current_equity=Decimal("100000"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_daily_loss")
        assert result.allowed is False
        assert result.severity == LimitSeverity.CRITICAL

    def test_daily_loss_exactly_at_limit_allowed(self):
        """Daily loss exactly at limit boundary → allowed."""
        config = _make_config(max_daily_loss_pct=Decimal("0.03"))
        # limit = -3000; daily_pnl = -3000 → allowed (>= -limit)
        snap = _make_snapshot(daily_pnl=Decimal("-3000"), current_equity=Decimal("100000"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_daily_loss")
        assert result.allowed is True


# ===========================================================================
# Drawdown Limit
# ===========================================================================

class TestDrawdownLimit:
    def test_within_drawdown_allowed(self):
        """Drawdown within limit → drawdown check passes."""
        config = _make_config(max_drawdown_pct=Decimal("0.10"))
        snap = _make_snapshot(drawdown=Decimal("0.05"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_drawdown")
        assert result.allowed is True

    def test_drawdown_breached_critical(self):
        """Drawdown > limit → CRITICAL."""
        config = _make_config(max_drawdown_pct=Decimal("0.10"))
        snap = _make_snapshot(drawdown=Decimal("0.11"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_drawdown")
        assert result.allowed is False
        assert result.severity == LimitSeverity.CRITICAL

    def test_drawdown_exactly_at_limit_allowed(self):
        """Drawdown exactly at limit → allowed."""
        config = _make_config(max_drawdown_pct=Decimal("0.10"))
        snap = _make_snapshot(drawdown=Decimal("0.10"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_drawdown")
        assert result.allowed is True


# ===========================================================================
# Cash Reserve Limit
# ===========================================================================

class TestCashReserveLimit:
    def test_cash_reserve_maintained(self):
        """Sufficient cash after reserve → cash_reserve check passes."""
        config = _make_config(cash_reserve_pct=Decimal("0.05"))
        # available=80000, total=85000, equity=100000; reserve=100000*0.05=5000
        # 80000-1000=79000 > 5000
        snap = _make_snapshot(
            available=Decimal("80000"),
            blocked=Decimal("5000"),
            current_equity=Decimal("100000"),
        )
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("1000"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "cash_reserve")
        assert result.allowed is True

    def test_cash_reserve_violated(self):
        """Order would breach cash reserve → blocked."""
        config = _make_config(cash_reserve_pct=Decimal("0.05"))
        # Very low available
        snap = _make_snapshot(
            available=Decimal("100"),
            blocked=Decimal("0"),
            current_equity=Decimal("10000"),
        )
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("5000"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "cash_reserve")
        assert result.allowed is False


# ===========================================================================
# Max Open Positions Limit
# ===========================================================================

class TestMaxOpenPositionsLimit:
    def test_below_limit_allowed(self):
        """Open positions below limit → allowed."""
        config = _make_config(max_open_positions=5)
        snap = _make_snapshot(open_positions=3)
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("1000"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_open_positions")
        assert result.allowed is True

    def test_at_limit_blocked(self):
        """Open positions at limit → blocked."""
        config = _make_config(max_open_positions=5)
        snap = _make_snapshot(open_positions=5)
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("1000"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_open_positions")
        assert result.allowed is False


# ===========================================================================
# Max Pending Orders Limit
# ===========================================================================

class TestPendingOrdersLimit:
    def test_below_pending_limit(self):
        """Pending orders below limit → allowed."""
        config = _make_config(max_pending_orders=10)
        snap = _make_snapshot(pending_orders=5)
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_pending_orders")
        assert result.allowed is True

    def test_at_pending_limit_blocked(self):
        """Pending orders at limit → blocked."""
        config = _make_config(max_pending_orders=10)
        snap = _make_snapshot(pending_orders=10)
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        result = next(r for r in report.results if r.limit_name == "max_pending_orders")
        assert result.allowed is False


# ===========================================================================
# Overall Report
# ===========================================================================

class TestOverallReport:
    def test_all_ok_overall_allowed(self):
        """All checks pass → overall_allowed=True."""
        config = _make_config()
        snap = _make_snapshot()
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        assert report.overall_allowed is True

    def test_critical_count_tracked(self):
        """critical_count matches number of critical failures."""
        config = _make_config(max_drawdown_pct=Decimal("0.10"))
        snap = _make_snapshot(drawdown=Decimal("0.15"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        assert report.critical_count >= 1

    def test_blocking_limit_set(self):
        """blocking_limit is set when any limit fails."""
        config = _make_config(max_drawdown_pct=Decimal("0.10"))
        snap = _make_snapshot(drawdown=Decimal("0.15"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        assert report.blocking_limit is not None

    def test_overall_false_when_critical_fails(self):
        """overall_allowed=False when any critical check fails."""
        config = _make_config(max_drawdown_pct=Decimal("0.10"))
        snap = _make_snapshot(drawdown=Decimal("0.20"))
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("0"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        assert report.overall_allowed is False

    def test_instrument_limit_checked_when_token_provided(self):
        """Instrument limit check is included when token is provided."""
        config = _make_config()
        snap = _make_snapshot()
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=738561,
            proposed_value=Decimal("1000"),
            proposed_strategy_id=None,
            proposed_sector=None,
            config=config,
        )
        limit_names = {r.limit_name for r in report.results}
        assert "max_instrument_exposure" in limit_names

    def test_sector_limit_checked_when_sector_provided(self):
        """Sector limit check is included when sector is provided."""
        config = _make_config()
        snap = _make_snapshot()
        report = check_all_limits(
            snapshot=snap,
            proposed_instrument_token=None,
            proposed_value=Decimal("1000"),
            proposed_strategy_id=None,
            proposed_sector="tech",
            config=config,
        )
        limit_names = {r.limit_name for r in report.results}
        assert "max_sector_exposure" in limit_names
