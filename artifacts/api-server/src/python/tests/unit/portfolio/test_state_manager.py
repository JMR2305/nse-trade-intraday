"""Unit tests for PortfolioStateManager (state_manager.py).

Covers:
  - initialise: status=READY, cash set, version=1
  - reserve_order_capital: cash blocked, available reduced
  - release_order_capital: reverses reservation
  - apply_fill (BUY): position opened, cash reduced
  - apply_fill (SELL): position closed, cash increased, daily_pnl updated
  - apply_fill: idempotency via idempotency_key
  - update_market_price: unrealised_pnl recalculated
  - halt/resume: status transitions
  - is_stale: false immediately after update, true when old
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from src.portfolio.config import PortfolioConfig
from src.portfolio.contracts import PortfolioStatus, PositionSide, PositionStatus
from src.portfolio.exceptions import DuplicateEventError, InsufficientCapitalError
from src.portfolio.state_manager import PortfolioStateManager

_NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kw) -> PortfolioConfig:
    defaults = dict(
        initial_capital=Decimal("100000"),
        cash_reserve_pct=Decimal("0.05"),
        max_portfolio_exposure_pct=Decimal("0.90"),
        stale_state_threshold_s=60.0,
    )
    defaults.update(kw)
    return PortfolioConfig(**defaults)


async def _initialised_psm(
    initial_cash: Decimal = Decimal("100000"),
    **config_kw,
) -> PortfolioStateManager:
    config = _make_config(**config_kw)
    psm = PortfolioStateManager(config)
    await psm.initialise(initial_cash)
    return psm


# ===========================================================================
# Initialisation
# ===========================================================================

class TestInitialise:
    @pytest.mark.asyncio
    async def test_status_becomes_ready(self):
        """After initialise, status is READY."""
        psm = await _initialised_psm()
        snap = psm.get_snapshot()
        assert snap.status == PortfolioStatus.READY

    @pytest.mark.asyncio
    async def test_initial_cash_set(self):
        """initialise sets cash total and available to initial_cash."""
        psm = await _initialised_psm(initial_cash=Decimal("50000"))
        snap = psm.get_snapshot()
        assert snap.cash.total == Decimal("50000")
        assert snap.cash.available == Decimal("50000")

    @pytest.mark.asyncio
    async def test_version_incremented(self):
        """Version is incremented after initialise."""
        psm = await _initialised_psm()
        snap = psm.get_snapshot()
        assert snap.version >= 1

    @pytest.mark.asyncio
    async def test_no_open_positions_after_init(self):
        """No open positions after initialise."""
        psm = await _initialised_psm()
        snap = psm.get_snapshot()
        assert len(snap.open_positions) == 0


# ===========================================================================
# Capital reservation
# ===========================================================================

class TestReserveCapital:
    @pytest.mark.asyncio
    async def test_reserve_blocks_cash(self):
        """reserve_order_capital blocks cash from available → blocked."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.reserve_order_capital("order-01", Decimal("10000"))
        snap = psm.get_snapshot()
        assert snap.cash.blocked == Decimal("10000")
        assert snap.cash.available == Decimal("90000")

    @pytest.mark.asyncio
    async def test_reserve_insufficient_cash_raises(self):
        """Reserving more than available → InsufficientCapitalError."""
        psm = await _initialised_psm(initial_cash=Decimal("5000"))
        with pytest.raises(InsufficientCapitalError):
            await psm.reserve_order_capital("order-01", Decimal("10000"))

    @pytest.mark.asyncio
    async def test_reserve_keeps_total_unchanged(self):
        """Reserving cash does not change total (just available→blocked)."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.reserve_order_capital("order-01", Decimal("10000"))
        snap = psm.get_snapshot()
        assert snap.cash.total == Decimal("100000")

    @pytest.mark.asyncio
    async def test_release_reverses_reservation(self):
        """release_order_capital moves blocked back to available."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.reserve_order_capital("order-01", Decimal("10000"))
        await psm.release_order_capital("order-01")
        snap = psm.get_snapshot()
        assert snap.cash.available == Decimal("100000")
        assert snap.cash.blocked == Decimal("0")

    @pytest.mark.asyncio
    async def test_release_idempotent(self):
        """release_order_capital is idempotent (double release is safe)."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.reserve_order_capital("order-01", Decimal("5000"))
        await psm.release_order_capital("order-01")
        snap = await psm.release_order_capital("order-01")  # second call is fine
        assert snap.cash.available == Decimal("100000")


# ===========================================================================
# Apply fill — BUY
# ===========================================================================

class TestApplyFillBuy:
    @pytest.mark.asyncio
    async def test_buy_opens_position(self):
        """BUY fill opens a new position."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.apply_fill(
            idempotency_key="idem-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-01",
            filled_at=_NOW,
        )
        snap = psm.get_snapshot()
        assert len(snap.open_positions) == 1
        pos = snap.open_positions[0]
        assert pos.instrument_token == 738561
        assert pos.open_quantity == 10

    @pytest.mark.asyncio
    async def test_buy_reduces_available_cash(self):
        """BUY fill reduces available cash by order value."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.apply_fill(
            idempotency_key="idem-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-01",
            filled_at=_NOW,
        )
        snap = psm.get_snapshot()
        # order_value = 10*2500 = 25000
        assert snap.cash.total == Decimal("75000")

    @pytest.mark.asyncio
    async def test_buy_idempotency_rejects_duplicate(self):
        """Duplicate idempotency_key raises DuplicateEventError."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.apply_fill(
            idempotency_key="idem-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-01",
            filled_at=_NOW,
        )
        with pytest.raises(DuplicateEventError):
            await psm.apply_fill(
                idempotency_key="idem-01",
                instrument_token=738561,
                instrument_symbol="RELIANCE",
                side=PositionSide.LONG,
                quantity=10,
                price=Decimal("2500"),
                fill_id="fill-01-dup",
                filled_at=_NOW,
            )

    @pytest.mark.asyncio
    async def test_second_buy_increases_position(self):
        """Second BUY fill on same instrument increases position."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.apply_fill(
            idempotency_key="idem-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-01",
            filled_at=_NOW,
        )
        await psm.apply_fill(
            idempotency_key="idem-02",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=5,
            price=Decimal("100"),
            fill_id="fill-02",
            filled_at=_NOW,
        )
        snap = psm.get_snapshot()
        assert snap.open_positions[0].open_quantity == 15


# ===========================================================================
# Apply fill — SELL
# ===========================================================================

class TestApplyFillSell:
    @pytest.mark.asyncio
    async def test_sell_closes_position(self):
        """SELL fill closes the open LONG position."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.apply_fill(
            idempotency_key="buy-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-buy",
            filled_at=_NOW,
        )
        await psm.apply_fill(
            idempotency_key="sell-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.SHORT,
            quantity=10,
            price=Decimal("110"),
            fill_id="fill-sell",
            filled_at=_NOW,
        )
        snap = psm.get_snapshot()
        # Closed position should not appear in open_positions
        assert len(snap.open_positions) == 0

    @pytest.mark.asyncio
    async def test_sell_credits_cash(self):
        """SELL fill adds order value to available cash."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.apply_fill(
            idempotency_key="buy-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-buy",
            filled_at=_NOW,
        )
        await psm.apply_fill(
            idempotency_key="sell-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.SHORT,
            quantity=10,
            price=Decimal("110"),
            fill_id="fill-sell",
            filled_at=_NOW,
        )
        snap = psm.get_snapshot()
        # Started: 100000, paid 1000, received 1100 = 100100
        assert snap.cash.total == Decimal("100100")

    @pytest.mark.asyncio
    async def test_profitable_sell_updates_daily_pnl(self):
        """Profitable sell updates daily_pnl in snapshot."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.apply_fill(
            idempotency_key="buy-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-buy",
            filled_at=_NOW,
        )
        await psm.apply_fill(
            idempotency_key="sell-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.SHORT,
            quantity=10,
            price=Decimal("110"),
            fill_id="fill-sell",
            filled_at=_NOW,
        )
        snap = psm.get_snapshot()
        # daily_pnl = (110-100)*10 = 100
        assert snap.pnl.daily_pnl == Decimal("100")


# ===========================================================================
# update_market_price
# ===========================================================================

class TestUpdateMarketPrice:
    @pytest.mark.asyncio
    async def test_update_market_price_recalculates_unrealised(self):
        """update_market_price recalculates unrealised P&L for positions."""
        psm = await _initialised_psm(initial_cash=Decimal("100000"))
        await psm.apply_fill(
            idempotency_key="buy-01",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-buy",
            filled_at=_NOW,
        )
        await psm.update_market_price(738561, Decimal("110"))
        snap = psm.get_snapshot()
        pos = snap.open_positions[0]
        assert pos.unrealised_pnl == Decimal("100.00")  # (110-100)*10

    @pytest.mark.asyncio
    async def test_update_market_price_no_position_no_error(self):
        """update_market_price for unknown instrument is silent."""
        psm = await _initialised_psm()
        snap = await psm.update_market_price(99999, Decimal("100"))
        assert snap is not None


# ===========================================================================
# Halt / Resume
# ===========================================================================

class TestHaltResume:
    @pytest.mark.asyncio
    async def test_halt_changes_status(self):
        """halt() sets status to HALTED."""
        psm = await _initialised_psm()
        psm.halt("test reason")
        snap = psm.get_snapshot()
        assert snap.status == PortfolioStatus.HALTED

    @pytest.mark.asyncio
    async def test_resume_changes_status_to_ready(self):
        """resume() sets status back to READY."""
        psm = await _initialised_psm()
        psm.halt("test")
        psm.resume()
        snap = psm.get_snapshot()
        assert snap.status == PortfolioStatus.READY

    @pytest.mark.asyncio
    async def test_reserve_capital_when_halted_raises(self):
        """reserve_order_capital on HALTED portfolio raises PortfolioHaltedError."""
        from src.portfolio.exceptions import PortfolioHaltedError
        psm = await _initialised_psm()
        psm.halt("trading day over")
        with pytest.raises(PortfolioHaltedError):
            await psm.reserve_order_capital("order-01", Decimal("1000"))


# ===========================================================================
# is_stale
# ===========================================================================

class TestReservedOrderCashAccounting:
    """Cash invariant (total == available + blocked) must hold under all
    reservation-vs-fill combinations: exact match, partial fill, slippage."""

    @pytest.mark.asyncio
    async def test_reserved_exact_fill_invariant(self):
        """Reserved == fill_value: available unchanged, blocked cleared, total decreases."""
        from src.portfolio.state_manager import PortfolioStateManager
        from src.portfolio.config import PortfolioConfig
        from decimal import Decimal
        from datetime import datetime, timezone
        from src.portfolio.contracts import PositionSide

        cfg = PortfolioConfig(initial_capital=Decimal("100000"))
        sm = PortfolioStateManager(cfg)
        await sm.initialise(Decimal("100000"))

        # Reserve 5000
        await sm.reserve_order_capital("order-exact", Decimal("5000"))
        pre = sm.get_snapshot()
        assert pre.cash.available == Decimal("95000")
        assert pre.cash.blocked == Decimal("5000")
        assert pre.cash.total == Decimal("100000")

        # Fill exactly 5000 (10 shares @ 500)
        await sm.apply_fill(
            idempotency_key="fill-exact",
            instrument_token=1,
            instrument_symbol="TEST",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("500"),
            fill_id="fill-exact",
            filled_at=datetime.now(timezone.utc),
            order_id="order-exact",
        )
        post = sm.get_snapshot()
        assert post.cash.total == post.cash.available + post.cash.blocked, \
            f"Invariant violated: total={post.cash.total} avail={post.cash.available} blocked={post.cash.blocked}"
        assert post.cash.blocked == Decimal("0"), "Reservation should be fully cleared"
        assert post.cash.total == Decimal("95000"), "Total should decrease by fill value"
        assert post.cash.available == Decimal("95000")

    @pytest.mark.asyncio
    async def test_partial_fill_excess_reservation_returned_to_available(self):
        """Partial fill (fill < reserved): excess reservation flows back to available."""
        from src.portfolio.state_manager import PortfolioStateManager
        from src.portfolio.config import PortfolioConfig
        from decimal import Decimal
        from datetime import datetime, timezone
        from src.portfolio.contracts import PositionSide

        cfg = PortfolioConfig(initial_capital=Decimal("100000"))
        sm = PortfolioStateManager(cfg)
        await sm.initialise(Decimal("100000"))

        # Reserve 5000 but fill only 3000 (6 shares @ 500)
        await sm.reserve_order_capital("order-partial", Decimal("5000"))
        await sm.apply_fill(
            idempotency_key="fill-partial",
            instrument_token=2,
            instrument_symbol="TEST2",
            side=PositionSide.LONG,
            quantity=6,
            price=Decimal("500"),  # fill_value = 3000
            fill_id="fill-partial",
            filled_at=datetime.now(timezone.utc),
            order_id="order-partial",
        )
        post = sm.get_snapshot()
        # Invariant must hold
        assert post.cash.total == post.cash.available + post.cash.blocked, \
            f"Invariant violated: total={post.cash.total} avail={post.cash.available} blocked={post.cash.blocked}"
        # 100000 - 3000 (fill) = 97000 total
        assert post.cash.total == Decimal("97000"), \
            f"Total should be 97000, got {post.cash.total}"
        # blocked fully cleared (reservation released on fill)
        assert post.cash.blocked == Decimal("0"), \
            f"Blocked should be 0 after fill, got {post.cash.blocked}"
        # available = total - blocked = 97000
        assert post.cash.available == Decimal("97000"), \
            f"Available should be 97000 (excess 2000 returned), got {post.cash.available}"

    @pytest.mark.asyncio
    async def test_slippage_fill_exceeds_reservation_deducted_from_available(self):
        """Slippage fill (fill > reserved): extra cost taken from available."""
        from src.portfolio.state_manager import PortfolioStateManager
        from src.portfolio.config import PortfolioConfig
        from decimal import Decimal
        from datetime import datetime, timezone
        from src.portfolio.contracts import PositionSide

        cfg = PortfolioConfig(initial_capital=Decimal("100000"))
        sm = PortfolioStateManager(cfg)
        await sm.initialise(Decimal("100000"))

        # Reserve 5000 but fill at 6000 (10 shares @ 600, slippage)
        await sm.reserve_order_capital("order-slip", Decimal("5000"))
        await sm.apply_fill(
            idempotency_key="fill-slip",
            instrument_token=3,
            instrument_symbol="TEST3",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("600"),  # fill_value = 6000 > reserved 5000
            fill_id="fill-slip",
            filled_at=datetime.now(timezone.utc),
            order_id="order-slip",
        )
        post = sm.get_snapshot()
        # Invariant must hold
        assert post.cash.total == post.cash.available + post.cash.blocked, \
            f"Invariant violated: total={post.cash.total} avail={post.cash.available} blocked={post.cash.blocked}"
        # 100000 - 6000 (fill) = 94000 total
        assert post.cash.total == Decimal("94000"), \
            f"Total should be 94000, got {post.cash.total}"
        assert post.cash.blocked == Decimal("0"), \
            f"Blocked should be 0 after fill, got {post.cash.blocked}"
        assert post.cash.available == Decimal("94000"), \
            f"Available should be 94000 (5000 blocked + 1000 from available), got {post.cash.available}"

    @pytest.mark.asyncio
    async def test_no_reservation_fill_debits_available(self):
        """Without a reservation, fill debits available directly; blocked unchanged."""
        from src.portfolio.state_manager import PortfolioStateManager
        from src.portfolio.config import PortfolioConfig
        from decimal import Decimal
        from datetime import datetime, timezone
        from src.portfolio.contracts import PositionSide

        cfg = PortfolioConfig(initial_capital=Decimal("100000"))
        sm = PortfolioStateManager(cfg)
        await sm.initialise(Decimal("100000"))

        # Reserve something for a *different* order so blocked is non-zero
        await sm.reserve_order_capital("order-other", Decimal("10000"))

        # Fill without matching reservation
        await sm.apply_fill(
            idempotency_key="fill-no-res",
            instrument_token=4,
            instrument_symbol="TEST4",
            side=PositionSide.LONG,
            quantity=5,
            price=Decimal("1000"),  # 5000
            fill_id="fill-no-res",
            filled_at=datetime.now(timezone.utc),
            order_id=None,  # no reservation
        )
        post = sm.get_snapshot()
        assert post.cash.total == post.cash.available + post.cash.blocked, \
            f"Invariant violated: total={post.cash.total} avail={post.cash.available} blocked={post.cash.blocked}"
        # blocked unchanged (other order still reserved)
        assert post.cash.blocked == Decimal("10000")
        # available decreased by fill value
        assert post.cash.available == Decimal("85000")  # 90000 - 5000
        assert post.cash.total == Decimal("95000")  # 100000 - 5000


class TestIsStale:
    @pytest.mark.asyncio
    async def test_not_stale_immediately_after_init(self):
        """is_stale returns False immediately after initialise."""
        psm = await _initialised_psm(stale_state_threshold_s=60.0)
        assert psm.is_stale() is False

    @pytest.mark.asyncio
    async def test_stale_with_zero_threshold(self):
        """is_stale returns True with threshold=0 (any age is stale)."""
        psm = await _initialised_psm()
        # 0-second threshold makes everything stale
        assert psm.is_stale(threshold_s=0.0) is True

    @pytest.mark.asyncio
    async def test_stale_before_init(self):
        """is_stale returns True before initialise."""
        config = _make_config()
        psm = PortfolioStateManager(config)
        assert psm.is_stale() is True
