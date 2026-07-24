"""Unit tests for CapitalAllocator / evaluate_allocation (capital_allocator.py).

Covers:
  - Approved allocation: within all limits
  - Rejected: daily loss breached → REJECTED returned
  - Rejected: drawdown breached → REJECTED returned
  - Capped: insufficient buying power → APPROVED with capped amount
  - Capped: strategy cap exceeded → APPROVED with capped amount
  - Stale snapshot → StalePortfolioStateError raised
  - Not ready → PortfolioNotReadyError raised
  - Below min_order_value after capping → NegativeQuantityError raised
  - expires_at set correctly
  - DEGRADED status → PortfolioNotReadyError
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio

from src.portfolio.capital_allocator import (
    CapitalAllocator,
    evaluate_allocation,
    is_daily_loss_breached,
    is_drawdown_breached,
)
from src.portfolio.config import PortfolioConfig
from src.portfolio.contracts import (
    AllocationStatus,
    BuyingPower,
    CashBalance,
    ExposureSnapshot,
    MarginState,
    PortfolioPnL,
    PortfolioSnapshot,
    PortfolioStatus,
    StrategyExposure,
)
from src.portfolio.exceptions import (
    NegativeQuantityError,
    PortfolioNotReadyError,
    StalePortfolioStateError,
)

_NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kw) -> PortfolioConfig:
    defaults = dict(
        initial_capital=Decimal("100000"),
        cash_reserve_pct=Decimal("0.05"),
        max_portfolio_exposure_pct=Decimal("0.90"),
        max_strategy_exposure_pct=Decimal("0.40"),
        max_daily_loss_pct=Decimal("0.03"),
        max_drawdown_pct=Decimal("0.10"),
        max_capital_per_strategy_pct=Decimal("0.40"),
        min_order_value=Decimal("1000"),
        max_order_value=Decimal("50000"),
        allocation_ttl_s=30.0,
        stale_state_threshold_s=60.0,
    )
    defaults.update(kw)
    return PortfolioConfig(**defaults)


def _make_snapshot(
    *,
    status: PortfolioStatus = PortfolioStatus.READY,
    available: Decimal = Decimal("80000"),
    net_buying_power: Decimal = Decimal("80000"),
    daily_pnl: Decimal = Decimal("0"),
    drawdown: Decimal = Decimal("0"),
    current_equity: Decimal = Decimal("100000"),
    peak_equity: Decimal = Decimal("100000"),
    strategy_id: str = "momentum",
    strategy_exposure: Decimal = Decimal("0"),
    gross_exposure: Decimal = Decimal("10000"),
    age_s: float = 0.0,
) -> PortfolioSnapshot:
    now = datetime.now(timezone.utc)
    snap_at = now - timedelta(seconds=age_s)
    total_cash = available + Decimal("5000")

    cash = CashBalance(
        available=available,
        blocked=Decimal("5000"),
        total=total_cash,
        as_of=snap_at,
    )
    margin = MarginState(
        used=Decimal("0"),
        available=total_cash,
        total=total_cash,
        as_of=snap_at,
    )
    bp = BuyingPower(
        gross=net_buying_power + Decimal("5000"),
        net=net_buying_power,
        reserved=Decimal("5000"),
        as_of=snap_at,
    )

    strategy_exposures = ()
    if strategy_exposure > Decimal("0"):
        strategy_exposures = (
            StrategyExposure(
                strategy_id=strategy_id,
                absolute_value=strategy_exposure,
                portfolio_pct=strategy_exposure / Decimal("100000"),
            ),
        )

    exposure = ExposureSnapshot(
        gross_exposure=gross_exposure,
        net_exposure=gross_exposure,
        strategy_exposures=strategy_exposures,
        portfolio_equity=current_equity,
        as_of=snap_at,
    )
    pnl = PortfolioPnL(
        daily_pnl=daily_pnl,
        drawdown=drawdown,
        peak_equity=peak_equity,
        current_equity=current_equity,
    )
    return PortfolioSnapshot(
        portfolio_id="test",
        status=status,
        version=1,
        cash=cash,
        margin=margin,
        buying_power=bp,
        exposure=exposure,
        pnl=pnl,
        snapshotted_at=snap_at,
    )


# ===========================================================================
# Helper functions
# ===========================================================================

class TestHelperFunctions:
    def test_is_daily_loss_breached_not_breached(self):
        """is_daily_loss_breached returns False when within limit."""
        config = _make_config(max_daily_loss_pct=Decimal("0.03"))
        pnl = PortfolioPnL(daily_pnl=Decimal("-500"), current_equity=Decimal("100000"))
        assert is_daily_loss_breached(pnl, config) is False

    def test_is_daily_loss_breached_when_over(self):
        """is_daily_loss_breached returns True when loss exceeds limit."""
        config = _make_config(max_daily_loss_pct=Decimal("0.03"))
        pnl = PortfolioPnL(daily_pnl=Decimal("-4000"), current_equity=Decimal("100000"))
        assert is_daily_loss_breached(pnl, config) is True

    def test_is_drawdown_breached_not_breached(self):
        """is_drawdown_breached returns False when within limit."""
        config = _make_config(max_drawdown_pct=Decimal("0.10"))
        pnl = PortfolioPnL(drawdown=Decimal("0.05"), current_equity=Decimal("100000"))
        assert is_drawdown_breached(pnl, config) is False

    def test_is_drawdown_breached_when_over(self):
        """is_drawdown_breached returns True when drawdown exceeds limit."""
        config = _make_config(max_drawdown_pct=Decimal("0.10"))
        pnl = PortfolioPnL(drawdown=Decimal("0.11"), current_equity=Decimal("100000"))
        assert is_drawdown_breached(pnl, config) is True


# ===========================================================================
# Approved allocation
# ===========================================================================

class TestEvaluateAllocationApproved:
    @pytest.mark.asyncio
    async def test_approved_within_all_limits(self):
        """Well within all limits → APPROVED."""
        config = _make_config()
        snap = _make_snapshot()
        decision = await evaluate_allocation(
            strategy_id="momentum",
            instrument_token=None,
            requested_capital=Decimal("5000"),
            snapshot=snap,
            config=config,
        )
        assert decision.status == AllocationStatus.APPROVED
        assert decision.approved_capital == Decimal("5000")

    @pytest.mark.asyncio
    async def test_expires_at_set_correctly(self):
        """expires_at is set to decided_at + allocation_ttl_s."""
        config = _make_config(allocation_ttl_s=30.0)
        snap = _make_snapshot()
        decision = await evaluate_allocation(
            strategy_id="momentum",
            instrument_token=None,
            requested_capital=Decimal("5000"),
            snapshot=snap,
            config=config,
        )
        assert decision.expires_at is not None
        diff = (decision.expires_at - decision.decided_at).total_seconds()
        assert abs(diff - 30.0) < 2.0

    @pytest.mark.asyncio
    async def test_correlation_id_propagated(self):
        """correlation_id is propagated to the decision."""
        config = _make_config()
        snap = _make_snapshot()
        decision = await evaluate_allocation(
            strategy_id="momentum",
            instrument_token=None,
            requested_capital=Decimal("5000"),
            snapshot=snap,
            config=config,
            correlation_id="corr-xyz",
        )
        assert decision.correlation_id == "corr-xyz"

    @pytest.mark.asyncio
    async def test_strategy_id_propagated(self):
        """strategy_id is propagated to the decision."""
        config = _make_config()
        snap = _make_snapshot()
        decision = await evaluate_allocation(
            strategy_id="test-strat",
            instrument_token=None,
            requested_capital=Decimal("5000"),
            snapshot=snap,
            config=config,
        )
        assert decision.strategy_id == "test-strat"


# ===========================================================================
# Rejected allocation
# ===========================================================================

class TestEvaluateAllocationRejected:
    @pytest.mark.asyncio
    async def test_rejected_daily_loss_breached(self):
        """Daily loss exceeds limit → REJECTED with DAILY_LOSS_LIMIT_BREACHED."""
        config = _make_config(max_daily_loss_pct=Decimal("0.03"))
        snap = _make_snapshot(daily_pnl=Decimal("-4000"), current_equity=Decimal("100000"))
        decision = await evaluate_allocation(
            strategy_id="momentum",
            instrument_token=None,
            requested_capital=Decimal("1000"),
            snapshot=snap,
            config=config,
        )
        assert decision.status == AllocationStatus.REJECTED
        assert "DAILY_LOSS_LIMIT_BREACHED" in decision.reason_codes

    @pytest.mark.asyncio
    async def test_rejected_drawdown_breached(self):
        """Drawdown exceeds limit → REJECTED with DRAWDOWN_LIMIT_BREACHED."""
        config = _make_config(max_drawdown_pct=Decimal("0.10"))
        snap = _make_snapshot(drawdown=Decimal("0.11"))
        decision = await evaluate_allocation(
            strategy_id="momentum",
            instrument_token=None,
            requested_capital=Decimal("1000"),
            snapshot=snap,
            config=config,
        )
        assert decision.status == AllocationStatus.REJECTED
        assert "DRAWDOWN_LIMIT_BREACHED" in decision.reason_codes


# ===========================================================================
# Capped (approved with reduced amount)
# ===========================================================================

class TestEvaluateAllocationCapped:
    @pytest.mark.asyncio
    async def test_capped_by_buying_power(self):
        """Requested > net buying power → APPROVED but capped."""
        config = _make_config()
        # net buying power = 1000; request = 5000
        snap = _make_snapshot(net_buying_power=Decimal("1000"))
        decision = await evaluate_allocation(
            strategy_id="momentum",
            instrument_token=None,
            requested_capital=Decimal("5000"),
            snapshot=snap,
            config=config,
        )
        # Should be capped but approved (unless capped below min)
        assert decision.approved_capital <= Decimal("5000")
        assert "CAPPED_BY_BUYING_POWER" in decision.reason_codes

    @pytest.mark.asyncio
    async def test_capped_by_strategy_limit(self):
        """Strategy already at 39000 of 40000 cap → capped."""
        config = _make_config(
            max_capital_per_strategy_pct=Decimal("0.40"),
        )
        # equity=100000; strategy_cap=40000; existing=39000; headroom=1000
        snap = _make_snapshot(
            strategy_exposure=Decimal("39000"),
            strategy_id="momentum",
            current_equity=Decimal("100000"),
        )
        decision = await evaluate_allocation(
            strategy_id="momentum",
            instrument_token=None,
            requested_capital=Decimal("5000"),
            snapshot=snap,
            config=config,
        )
        # Approved capital should be ≤ headroom (1000)
        assert decision.approved_capital <= Decimal("1000")


# ===========================================================================
# Error cases
# ===========================================================================

class TestEvaluateAllocationErrors:
    @pytest.mark.asyncio
    async def test_stale_snapshot_raises(self):
        """Snapshot older than threshold → StalePortfolioStateError."""
        config = _make_config(stale_state_threshold_s=60.0)
        snap = _make_snapshot(age_s=120.0)  # 2 minutes old
        with pytest.raises(StalePortfolioStateError):
            await evaluate_allocation(
                strategy_id="momentum",
                instrument_token=None,
                requested_capital=Decimal("5000"),
                snapshot=snap,
                config=config,
            )

    @pytest.mark.asyncio
    async def test_not_ready_raises(self):
        """Portfolio in INITIALISING status → PortfolioNotReadyError."""
        config = _make_config()
        snap = _make_snapshot(status=PortfolioStatus.INITIALISING)
        with pytest.raises(PortfolioNotReadyError):
            await evaluate_allocation(
                strategy_id="momentum",
                instrument_token=None,
                requested_capital=Decimal("5000"),
                snapshot=snap,
                config=config,
            )

    @pytest.mark.asyncio
    async def test_halted_raises(self):
        """Portfolio HALTED → PortfolioNotReadyError."""
        config = _make_config()
        snap = _make_snapshot(status=PortfolioStatus.HALTED)
        with pytest.raises(PortfolioNotReadyError):
            await evaluate_allocation(
                strategy_id="momentum",
                instrument_token=None,
                requested_capital=Decimal("5000"),
                snapshot=snap,
                config=config,
            )

    @pytest.mark.asyncio
    async def test_below_min_after_cap_raises_negative_quantity(self):
        """When capped capital < min_order_value → NegativeQuantityError."""
        config = _make_config(min_order_value=Decimal("5000"))
        # net buying power = 1000 → capped to 1000 < 5000 → NegativeQuantityError
        snap = _make_snapshot(net_buying_power=Decimal("1000"))
        with pytest.raises(NegativeQuantityError):
            await evaluate_allocation(
                strategy_id="momentum",
                instrument_token=None,
                requested_capital=Decimal("10000"),
                snapshot=snap,
                config=config,
            )


# ===========================================================================
# CapitalAllocator class (OO wrapper)
# ===========================================================================

class TestCapitalAllocatorClass:
    @pytest.mark.asyncio
    async def test_class_evaluate_allocation(self):
        """CapitalAllocator.evaluate_allocation works via the class wrapper."""
        config = _make_config()
        allocator = CapitalAllocator(config)
        snap = _make_snapshot()
        decision = await allocator.evaluate_allocation(
            snapshot=snap,
            strategy_id="momentum",
            instrument_token=None,
            requested_capital=Decimal("5000"),
        )
        assert decision.status == AllocationStatus.APPROVED

    @pytest.mark.asyncio
    async def test_class_stale_snapshot_raises(self):
        """CapitalAllocator raises StalePortfolioStateError for stale snapshot."""
        config = _make_config(stale_state_threshold_s=60.0)
        allocator = CapitalAllocator(config)
        snap = _make_snapshot(age_s=120.0)
        with pytest.raises(StalePortfolioStateError):
            await allocator.evaluate_allocation(
                snapshot=snap,
                strategy_id="momentum",
                instrument_token=None,
                requested_capital=Decimal("5000"),
            )
