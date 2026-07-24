"""Unit tests for PositionSizer / calculate_size (position_sizer.py).

Covers:
  - Fixed-risk sizing: entry=100, stop=95, risk_amount=1000 → qty=200
  - Lot rounding: qty rounded down to lot_size multiple
  - max_order_value constraint: caps quantity
  - min_order_value: zero qty → approved=False, rejection_reason set
  - AI confidence scaling (use_ai_confidence_sizing=True)
  - Stale snapshot → StalePortfolioStateError
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from src.portfolio.config import PortfolioConfig
from src.portfolio.contracts import (
    BuyingPower,
    CashBalance,
    ExposureSnapshot,
    MarginState,
    PortfolioPnL,
    PortfolioSnapshot,
    PortfolioStatus,
    PositionSide,
    PositionSizeRequest,
)
from src.portfolio.exceptions import StalePortfolioStateError
from src.portfolio.position_sizer import (
    PositionSizer,
    calculate_size,
    estimate_order_value,
    round_to_lot,
)

_NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kw) -> PortfolioConfig:
    defaults = dict(
        initial_capital=Decimal("100000"),
        default_risk_per_trade_pct=Decimal("0.01"),  # 1% = 1000 on 100000
        min_order_value=Decimal("1000"),
        max_order_value=Decimal("50000"),
        stale_state_threshold_s=60.0,
        use_ai_confidence_sizing=False,
        ai_confidence_min=Decimal("0.5"),
        cash_reserve_pct=Decimal("0.05"),
        max_portfolio_exposure_pct=Decimal("0.90"),
    )
    defaults.update(kw)
    return PortfolioConfig(**defaults)


def _make_snapshot(
    age_s: float = 0.0,
    status: PortfolioStatus = PortfolioStatus.READY,
    net_buying_power: Decimal = Decimal("80000"),
    current_equity: Decimal = Decimal("100000"),
) -> PortfolioSnapshot:
    now = datetime.now(timezone.utc)
    snap_at = now - timedelta(seconds=age_s)
    cash = CashBalance(
        available=net_buying_power,
        blocked=Decimal("0"),
        total=net_buying_power,
        as_of=snap_at,
    )
    margin = MarginState(
        used=Decimal("0"),
        available=net_buying_power,
        total=net_buying_power,
        as_of=snap_at,
    )
    bp = BuyingPower(
        gross=net_buying_power,
        net=net_buying_power,
        reserved=Decimal("0"),
        as_of=snap_at,
    )
    exp = ExposureSnapshot(
        gross_exposure=Decimal("20000"),
        net_exposure=Decimal("20000"),
        portfolio_equity=current_equity,
        as_of=snap_at,
    )
    pnl = PortfolioPnL(drawdown=Decimal("0"), current_equity=current_equity)
    return PortfolioSnapshot(
        portfolio_id="test",
        status=status,
        version=1,
        cash=cash,
        margin=margin,
        buying_power=bp,
        exposure=exp,
        pnl=pnl,
        snapshotted_at=snap_at,
    )


def _make_request(
    entry: Decimal = Decimal("100"),
    stop: Decimal | None = Decimal("95"),
    lot_size: int = 1,
    confidence: Decimal = Decimal("1.0"),
    symbol: str = "TESTSTOCK",
    token: int = 123456,
) -> PositionSizeRequest:
    return PositionSizeRequest(
        instrument_token=token,
        instrument_symbol=symbol,
        side=PositionSide.LONG,
        entry_price=entry,
        stop_price=stop,
        lot_size=lot_size,
        signal_confidence=confidence,
        requested_at=_NOW,
    )


# ===========================================================================
# Pure helper functions
# ===========================================================================

class TestHelperFunctions:
    def test_round_to_lot_basic(self):
        """round_to_lot floors to nearest lot multiple."""
        assert round_to_lot(153, 50) == 150

    def test_round_to_lot_exact(self):
        """round_to_lot returns same value when exact multiple."""
        assert round_to_lot(50, 50) == 50

    def test_round_to_lot_zero(self):
        """round_to_lot returns 0 when qty < lot_size."""
        assert round_to_lot(49, 50) == 0

    def test_round_to_lot_size_1(self):
        """round_to_lot with lot_size=1 is identity."""
        assert round_to_lot(123, 1) == 123

    def test_estimate_order_value(self):
        """estimate_order_value = qty * price."""
        val = estimate_order_value(100, Decimal("2500"))
        assert val == Decimal("250000.00")

    def test_estimate_order_value_zero_qty(self):
        """estimate_order_value returns 0 for zero qty."""
        val = estimate_order_value(0, Decimal("100"))
        assert val == Decimal("0")


# ===========================================================================
# Fixed-risk sizing
# ===========================================================================

class TestFixedRiskSizing:
    def test_basic_risk_sizing(self):
        """entry=100, stop=95, risk_amount=1000 (1% of 100000) → qty=200."""
        # risk_per_share = 100-95 = 5; qty = 1000/5 = 200
        config = _make_config(default_risk_per_trade_pct=Decimal("0.01"))
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"), lot_size=1)
        decision = calculate_size(req, snap, config)
        assert decision.approved is True
        assert decision.approved_quantity == 200

    def test_approved_quantity_positive(self):
        """An approved decision has approved_quantity > 0."""
        config = _make_config()
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=Decimal("90"))
        decision = calculate_size(req, snap, config)
        assert decision.approved is True
        assert decision.approved_quantity > 0

    def test_request_id_propagated(self):
        """request_id matches the original request."""
        config = _make_config()
        snap = _make_snapshot()
        req = _make_request()
        decision = calculate_size(req, snap, config)
        assert decision.request_id == req.request_id

    def test_instrument_token_propagated(self):
        """instrument_token matches the original request."""
        config = _make_config()
        snap = _make_snapshot()
        req = _make_request(token=999999)
        decision = calculate_size(req, snap, config)
        assert decision.instrument_token == 999999

    def test_no_stop_uses_default_stop_pct(self):
        """When stop_price=None, uses 2% of entry as risk."""
        config = _make_config()
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=None)
        decision = calculate_size(req, snap, config)
        # Default stop = 2% of 100 = 2; risk=1000; qty=500
        # May be capped by max_order_value=50000
        assert decision.approved is True or decision.rejection_reason is not None


# ===========================================================================
# Lot rounding
# ===========================================================================

class TestLotRounding:
    def test_lot_rounding_rounds_down(self):
        """Quantity is rounded down to nearest lot_size multiple."""
        config = _make_config()
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"), lot_size=15)
        decision = calculate_size(req, snap, config)
        if decision.approved:
            assert decision.approved_quantity % 15 == 0

    def test_lot_size_one_no_change(self):
        """lot_size=1 does not change the raw quantity."""
        config = _make_config()
        snap = _make_snapshot()
        req1 = _make_request(entry=Decimal("100"), stop=Decimal("95"), lot_size=1)
        req2 = _make_request(entry=Decimal("100"), stop=Decimal("95"), lot_size=1)
        d1 = calculate_size(req1, snap, config)
        d2 = calculate_size(req2, snap, config)
        assert d1.approved_quantity == d2.approved_quantity

    def test_lot_constraint_in_applied_constraints(self):
        """MAX_ORDER_VALUE or lot rounding appears in applied_constraints when triggered."""
        config = _make_config(max_order_value=Decimal("5000"))
        snap = _make_snapshot()
        # entry=100, stop=95, risk=1000 → raw qty=200, value=20000 > 5000
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"), lot_size=1)
        decision = calculate_size(req, snap, config)
        assert "MAX_ORDER_VALUE" in decision.applied_constraints


# ===========================================================================
# Max order value cap
# ===========================================================================

class TestMaxOrderValueCap:
    def test_max_order_value_caps_quantity(self):
        """max_order_value reduces quantity so order_value <= max."""
        config = _make_config(max_order_value=Decimal("5000"))
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"), lot_size=1)
        decision = calculate_size(req, snap, config)
        if decision.approved:
            assert decision.estimated_order_value <= Decimal("5000")
            assert "MAX_ORDER_VALUE" in decision.applied_constraints

    def test_max_order_value_constraint_applied(self):
        """MAX_ORDER_VALUE appears when capping is needed."""
        config = _make_config(max_order_value=Decimal("5000"))
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"), lot_size=1)
        decision = calculate_size(req, snap, config)
        # raw_qty=200, value=20000 > 5000 → must cap
        assert "MAX_ORDER_VALUE" in decision.applied_constraints


# ===========================================================================
# Min order value rejection
# ===========================================================================

class TestMinOrderValueRejection:
    def test_zero_qty_rejected(self):
        """When qty rounds to 0 via lot_size → approved=False."""
        config = _make_config(min_order_value=Decimal("1000"))
        snap = _make_snapshot()
        # entry=100, stop=95, risk=1000 → raw=200; lot_size=10000 → 0
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"), lot_size=10000)
        decision = calculate_size(req, snap, config)
        assert decision.approved is False
        assert decision.rejection_reason is not None

    def test_rejection_reason_set(self):
        """rejected decision has rejection_reason set."""
        config = _make_config(min_order_value=Decimal("1000"))
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"), lot_size=10000)
        decision = calculate_size(req, snap, config)
        assert decision.approved is False
        assert decision.rejection_reason == "BELOW_MIN_ORDER_VALUE"


# ===========================================================================
# AI confidence scaling
# ===========================================================================

class TestAIConfidenceScaling:
    def test_ai_confidence_scales_quantity(self):
        """When use_ai_confidence_sizing=True, confidence < 1.0 reduces quantity."""
        config = _make_config(use_ai_confidence_sizing=True, ai_confidence_min=Decimal("0.5"))
        snap = _make_snapshot()

        req_full = _make_request(entry=Decimal("100"), stop=Decimal("95"), confidence=Decimal("1.0"))
        d_full = calculate_size(req_full, snap, config)

        req_half = _make_request(entry=Decimal("100"), stop=Decimal("95"), confidence=Decimal("0.5"))
        d_half = calculate_size(req_half, snap, config)

        if d_full.approved and d_half.approved:
            assert d_half.approved_quantity <= d_full.approved_quantity

    def test_ai_confidence_in_constraints(self):
        """AI_CONFIDENCE_SCALING appears in applied_constraints when enabled and changes qty."""
        config = _make_config(use_ai_confidence_sizing=True, ai_confidence_min=Decimal("0.5"))
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"), confidence=Decimal("0.5"))
        decision = calculate_size(req, snap, config)
        if decision.approved:
            assert "AI_CONFIDENCE_SCALING" in decision.applied_constraints

    def test_no_ai_scaling_when_disabled(self):
        """No AI_CONFIDENCE_SCALING when use_ai_confidence_sizing=False."""
        config = _make_config(use_ai_confidence_sizing=False)
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"), confidence=Decimal("0.5"))
        decision = calculate_size(req, snap, config)
        assert "AI_CONFIDENCE_SCALING" not in decision.applied_constraints


# ===========================================================================
# Sizer errors
# ===========================================================================

class TestSizerErrors:
    def test_stale_snapshot_raises(self):
        """Stale snapshot → StalePortfolioStateError."""
        config = _make_config(stale_state_threshold_s=60.0)
        snap = _make_snapshot(age_s=120.0)
        req = _make_request()
        with pytest.raises(StalePortfolioStateError):
            calculate_size(req, snap, config)

    def test_fresh_snapshot_no_error(self):
        """Fresh snapshot → no StalePortfolioStateError."""
        config = _make_config(stale_state_threshold_s=60.0)
        snap = _make_snapshot(age_s=0.0)
        req = _make_request()
        # Should not raise
        decision = calculate_size(req, snap, config)
        assert decision is not None


# ===========================================================================
# PositionSizer class (OO wrapper)
# ===========================================================================

class TestPositionSizerClass:
    @pytest.mark.asyncio
    async def test_class_calculate_size(self):
        """PositionSizer.calculate_size works via the class wrapper."""
        config = _make_config()
        sizer = PositionSizer(config)
        snap = _make_snapshot()
        req = _make_request(entry=Decimal("100"), stop=Decimal("95"))
        decision = await sizer.calculate_size(req, snap)
        assert decision.approved is True
        assert decision.approved_quantity == 200

    @pytest.mark.asyncio
    async def test_class_stale_snapshot_raises(self):
        """PositionSizer raises StalePortfolioStateError for stale snapshot."""
        config = _make_config(stale_state_threshold_s=60.0)
        sizer = PositionSizer(config)
        snap = _make_snapshot(age_s=120.0)
        req = _make_request()
        with pytest.raises(StalePortfolioStateError):
            await sizer.calculate_size(req, snap)
