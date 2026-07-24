"""pytest configuration and shared fixtures for portfolio unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure src is importable
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
import pytest_asyncio
from decimal import Decimal
from datetime import datetime, timezone

from src.portfolio.contracts import (
    BuyingPower,
    CashBalance,
    ExposureSnapshot,
    MarginState,
    PortfolioPosition,
    PortfolioPnL,
    PortfolioSnapshot,
    PortfolioStatus,
    PositionSide,
    PositionStatus,
)
from src.portfolio.config import PortfolioConfig
from src.portfolio.exceptions import (
    DuplicateEventError,
    ExposureLimitBreachedError,
    InsufficientCapitalError,
    InvalidPositionTransitionError,
    PortfolioHaltedError,
    PortfolioNotReadyError,
    StalePortfolioStateError,
)


# ---------------------------------------------------------------------------
# Config fixture — tight limits make breach scenarios easy to trigger
# ---------------------------------------------------------------------------

@pytest.fixture
def portfolio_config() -> PortfolioConfig:
    """PortfolioConfig with small limits suitable for unit tests."""
    return PortfolioConfig(
        initial_capital=Decimal("100000"),
        cash_reserve_pct=Decimal("0.05"),
        max_portfolio_exposure_pct=Decimal("0.90"),
        max_instrument_exposure_pct=Decimal("0.20"),
        max_sector_exposure_pct=Decimal("0.35"),
        max_strategy_exposure_pct=Decimal("0.40"),
        max_open_positions=5,
        max_pending_orders=10,
        max_daily_loss_pct=Decimal("0.03"),
        max_drawdown_pct=Decimal("0.10"),
        max_capital_per_strategy_pct=Decimal("0.40"),
        default_risk_per_trade_pct=Decimal("0.01"),
        min_order_value=Decimal("1000"),
        max_order_value=Decimal("50000"),
        stale_state_threshold_s=60.0,
        stale_broker_threshold_s=120.0,
        stale_price_threshold_s=30.0,
        allocation_ttl_s=30.0,
        use_ai_confidence_sizing=False,
        ai_confidence_min=Decimal("0.5"),
    )


# ---------------------------------------------------------------------------
# Position fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_position() -> PortfolioPosition:
    """A simple LONG position in RELIANCE with 10 shares."""
    return PortfolioPosition(
        instrument_token=738561,
        instrument_symbol="RELIANCE",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        open_quantity=10,
        closed_quantity=0,
        average_entry_price=Decimal("2500.00"),
        last_market_price=Decimal("2550.00"),
        last_price_as_of=datetime.now(timezone.utc),
        unrealised_pnl=Decimal("500.00"),
        realised_pnl=Decimal("0"),
        total_fees=Decimal("20.00"),
        lots=[],
        strategy_id="momentum",
        sector="energy",
        opened_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Snapshot fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_snapshot(portfolio_config: PortfolioConfig) -> PortfolioSnapshot:
    """A minimal valid PortfolioSnapshot in READY state."""
    now = datetime.now(timezone.utc)
    cash = make_cash(available=Decimal("50000"), blocked=Decimal("0"))
    margin = make_margin(used=Decimal("0"), available=Decimal("100000"))
    bp = make_buying_power(net=Decimal("50000"))
    exp = make_exposure(gross=Decimal("10000"))
    pnl = make_pnl(daily=Decimal("-500"))
    return PortfolioSnapshot(
        portfolio_id="test",
        status=PortfolioStatus.READY,
        version=1,
        cash=cash,
        margin=margin,
        buying_power=bp,
        exposure=exp,
        pnl=pnl,
        open_positions=(),
        snapshotted_at=now,
    )


# ---------------------------------------------------------------------------
# Helper factory functions (not fixtures — call directly in tests)
# ---------------------------------------------------------------------------

def make_cash(
    available: Decimal = Decimal("50000"),
    blocked: Decimal = Decimal("0"),
) -> CashBalance:
    """Build a CashBalance with total = available + blocked."""
    return CashBalance(
        available=available,
        blocked=blocked,
        total=available + blocked,
        as_of=datetime.now(timezone.utc),
    )


def make_margin(
    used: Decimal = Decimal("0"),
    available: Decimal = Decimal("100000"),
) -> MarginState:
    """Build a MarginState."""
    return MarginState(
        used=used,
        available=available,
        total=used + available,
        as_of=datetime.now(timezone.utc),
    )


def make_buying_power(net: Decimal = Decimal("50000")) -> BuyingPower:
    """Build a BuyingPower with gross = net + 5000 reserve."""
    reserved = Decimal("5000")
    return BuyingPower(
        gross=net + reserved,
        net=net,
        reserved=reserved,
        as_of=datetime.now(timezone.utc),
    )


def make_exposure(gross: Decimal = Decimal("10000")) -> ExposureSnapshot:
    """Build a simple ExposureSnapshot."""
    return ExposureSnapshot(
        gross_exposure=gross,
        net_exposure=gross,
        long_exposure=gross,
        short_exposure=Decimal("0"),
        portfolio_equity=Decimal("100000"),
        as_of=datetime.now(timezone.utc),
    )


def make_pnl(daily: Decimal = Decimal("-500")) -> PortfolioPnL:
    """Build a PortfolioPnL with given daily P&L."""
    return PortfolioPnL(
        daily_pnl=daily,
        peak_equity=Decimal("100000"),
        current_equity=Decimal("99500"),
        drawdown=Decimal("0.005"),
    )
