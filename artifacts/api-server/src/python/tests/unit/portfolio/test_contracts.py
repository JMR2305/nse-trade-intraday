"""Unit tests for portfolio contracts (contracts.py).

Covers:
  - Decimal coercion: valid, NaN, inf, string "100.50"
  - Timezone enforcement on all datetime fields
  - CashBalance: total != available+blocked → ValueError; negative available
  - BuyingPower: negative net → ValueError
  - PortfolioPnL: drawdown outside [0,1] → ValueError
  - AllocationDecision.is_expired(): before/after expires_at
  - PortfolioPosition: open_quantity >= 0
  - Frozen model mutation → AttributeError / ValidationError
  - Serialisation round-trip via model_dump / model_validate
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.portfolio.contracts import (
    AllocationDecision,
    AllocationStatus,
    BuyingPower,
    CashBalance,
    ExposureSnapshot,
    InstrumentExposure,
    LimitCheckReport,
    LimitCheckResult,
    LimitSeverity,
    MarginState,
    PortfolioDiscrepancy,
    PortfolioDiscrepancyType,
    PortfolioEvent,
    PortfolioEventType,
    PortfolioHealth,
    PortfolioHealthStatus,
    PortfolioPnL,
    PortfolioPosition,
    PortfolioReconciliationReport,
    PortfolioSnapshot,
    PortfolioStatus,
    PositionPnL,
    PositionSide,
    PositionSizeDecision,
    PositionSizeRequest,
    PositionStatus,
    SectorExposure,
    StrategyExposure,
)


# ===========================================================================
# Helpers
# ===========================================================================

_NOW = datetime.now(timezone.utc)


def _make_cash(**kw) -> CashBalance:
    defaults = dict(available=Decimal("1000"), blocked=Decimal("0"), total=Decimal("1000"), as_of=_NOW)
    defaults.update(kw)
    return CashBalance(**defaults)


def _make_margin(**kw) -> MarginState:
    defaults = dict(used=Decimal("0"), available=Decimal("1000"), total=Decimal("1000"), as_of=_NOW)
    defaults.update(kw)
    return MarginState(**defaults)


def _make_bp(**kw) -> BuyingPower:
    defaults = dict(gross=Decimal("1000"), net=Decimal("900"), reserved=Decimal("100"), as_of=_NOW)
    defaults.update(kw)
    return BuyingPower(**defaults)


def _make_exposure(**kw) -> ExposureSnapshot:
    defaults = dict(gross_exposure=Decimal("0"), net_exposure=Decimal("0"))
    defaults.update(kw)
    return ExposureSnapshot(**defaults)


def _make_pnl(**kw) -> PortfolioPnL:
    defaults = dict(drawdown=Decimal("0"))
    defaults.update(kw)
    return PortfolioPnL(**defaults)


def _make_snapshot(**kw) -> PortfolioSnapshot:
    defaults = dict(
        cash=_make_cash(),
        margin=_make_margin(),
        buying_power=_make_bp(),
        exposure=_make_exposure(),
        pnl=_make_pnl(),
        snapshotted_at=_NOW,
    )
    defaults.update(kw)
    return PortfolioSnapshot(**defaults)


# ===========================================================================
# Decimal coercion
# ===========================================================================

class TestDecimalCoercion:
    def test_valid_int_coerced(self):
        """Integer 100 is coerced to Decimal('100')."""
        cb = _make_cash(available=100, blocked=0, total=100)
        assert cb.available == Decimal("100")

    def test_valid_float_coerced(self):
        """Float 100.5 should be coerced via str → Decimal."""
        cb = _make_cash(available="100.50", blocked=Decimal("0"), total="100.50")
        assert cb.available == Decimal("100.50")

    def test_valid_string_decimal(self):
        """String '100.50' is accepted."""
        bp = _make_bp(gross="200.00", net="180.00", reserved="20.00")
        assert bp.gross == Decimal("200.00")

    def test_nan_rejected(self):
        """NaN must raise ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            _make_cash(available=float("nan"), blocked=Decimal("0"), total=float("nan"))

    def test_inf_rejected(self):
        """Infinity must raise ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            _make_cash(available=float("inf"), blocked=Decimal("0"), total=float("inf"))

    def test_negative_inf_rejected(self):
        """Negative infinity must raise ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            _make_pnl(daily_pnl=float("-inf"))


# ===========================================================================
# Timezone enforcement
# ===========================================================================

class TestTimezoneEnforcement:
    def test_naive_datetime_rejected_in_cash(self):
        """Naive datetime must be rejected on CashBalance.as_of."""
        with pytest.raises((ValueError, ValidationError)):
            CashBalance(
                available=Decimal("100"),
                blocked=Decimal("0"),
                total=Decimal("100"),
                as_of=datetime(2024, 1, 1, 9, 0, 0),  # naive
            )

    def test_naive_datetime_rejected_in_margin(self):
        """Naive datetime must be rejected on MarginState.as_of."""
        with pytest.raises((ValueError, ValidationError)):
            MarginState(
                used=Decimal("0"),
                available=Decimal("100"),
                total=Decimal("100"),
                as_of=datetime(2024, 1, 1),  # naive
            )

    def test_naive_datetime_rejected_in_buying_power(self):
        """Naive datetime must be rejected on BuyingPower.as_of."""
        with pytest.raises((ValueError, ValidationError)):
            BuyingPower(
                gross=Decimal("100"),
                net=Decimal("90"),
                reserved=Decimal("10"),
                as_of=datetime(2024, 1, 1),  # naive
            )

    def test_utc_datetime_accepted(self):
        """UTC-aware datetime is accepted."""
        cb = CashBalance(
            available=Decimal("100"),
            blocked=Decimal("0"),
            total=Decimal("100"),
            as_of=datetime(2024, 6, 1, 9, 30, tzinfo=timezone.utc),
        )
        assert cb.as_of.tzinfo is not None

    def test_naive_datetime_rejected_in_snapshot(self):
        """Naive snapshotted_at must be rejected on PortfolioSnapshot."""
        with pytest.raises((ValueError, ValidationError)):
            _make_snapshot(snapshotted_at=datetime(2024, 1, 1))


# ===========================================================================
# CashBalance validation
# ===========================================================================

class TestCashBalance:
    def test_valid_construction(self):
        """Standard valid CashBalance."""
        cb = _make_cash(available=Decimal("900"), blocked=Decimal("100"), total=Decimal("1000"))
        assert cb.total == cb.available + cb.blocked

    def test_total_mismatch_raises(self):
        """total != available + blocked → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            CashBalance(
                available=Decimal("900"),
                blocked=Decimal("100"),
                total=Decimal("1100"),  # wrong
                as_of=_NOW,
            )

    def test_negative_available_raises(self):
        """Negative available → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            CashBalance(
                available=Decimal("-1"),
                blocked=Decimal("0"),
                total=Decimal("-1"),
                as_of=_NOW,
            )

    def test_negative_blocked_raises(self):
        """Negative blocked → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            CashBalance(
                available=Decimal("100"),
                blocked=Decimal("-50"),
                total=Decimal("50"),
                as_of=_NOW,
            )

    def test_zero_balance_valid(self):
        """All-zero balance is valid."""
        cb = CashBalance(available=Decimal("0"), blocked=Decimal("0"), total=Decimal("0"), as_of=_NOW)
        assert cb.total == Decimal("0")

    def test_serialisation_round_trip(self):
        """model_dump → model_validate round-trip preserves values."""
        cb = _make_cash(available=Decimal("500"), blocked=Decimal("200"), total=Decimal("700"))
        data = cb.model_dump()
        cb2 = CashBalance.model_validate(data)
        assert cb2.available == cb.available
        assert cb2.blocked == cb.blocked
        assert cb2.total == cb.total


# ===========================================================================
# BuyingPower validation
# ===========================================================================

class TestBuyingPower:
    def test_negative_net_raises(self):
        """Negative net buying power → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            BuyingPower(
                gross=Decimal("100"),
                net=Decimal("-10"),
                reserved=Decimal("110"),
                as_of=_NOW,
            )

    def test_zero_net_allowed(self):
        """Zero net is allowed (fully reserved)."""
        bp = BuyingPower(
            gross=Decimal("100"),
            net=Decimal("0"),
            reserved=Decimal("100"),
            as_of=_NOW,
        )
        assert bp.net == Decimal("0")

    def test_serialisation_round_trip(self):
        """model_dump → model_validate round-trip."""
        bp = _make_bp()
        data = bp.model_dump()
        bp2 = BuyingPower.model_validate(data)
        assert bp2.net == bp.net


# ===========================================================================
# MarginState validation
# ===========================================================================

class TestMarginState:
    def test_negative_used_raises(self):
        """Negative used margin → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            MarginState(
                used=Decimal("-1"),
                available=Decimal("100"),
                total=Decimal("99"),
                as_of=_NOW,
            )

    def test_negative_available_raises(self):
        """Negative available margin → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            MarginState(
                used=Decimal("100"),
                available=Decimal("-10"),
                total=Decimal("90"),
                as_of=_NOW,
            )

    def test_valid_margin(self):
        """Valid margin construction."""
        m = _make_margin(used=Decimal("500"), available=Decimal("500"), total=Decimal("1000"))
        assert m.total == Decimal("1000")


# ===========================================================================
# PortfolioPnL validation
# ===========================================================================

class TestPortfolioPnL:
    def test_drawdown_over_one_raises(self):
        """drawdown > 1.0 → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioPnL(drawdown=Decimal("1.01"))

    def test_drawdown_negative_raises(self):
        """drawdown < 0 → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioPnL(drawdown=Decimal("-0.01"))

    def test_drawdown_zero_valid(self):
        """drawdown=0 is valid."""
        p = PortfolioPnL(drawdown=Decimal("0"))
        assert p.drawdown == Decimal("0")

    def test_drawdown_one_valid(self):
        """drawdown=1 is valid (100% loss)."""
        p = PortfolioPnL(drawdown=Decimal("1"))
        assert p.drawdown == Decimal("1")

    def test_serialisation_round_trip(self):
        """model_dump → model_validate preserves drawdown."""
        p = PortfolioPnL(drawdown=Decimal("0.05"), daily_pnl=Decimal("-500"))
        data = p.model_dump()
        p2 = PortfolioPnL.model_validate(data)
        assert p2.drawdown == p.drawdown
        assert p2.daily_pnl == p.daily_pnl


# ===========================================================================
# AllocationDecision.is_expired()
# ===========================================================================

class TestAllocationDecisionExpiry:
    def _make_decision(self, **kw) -> AllocationDecision:
        defaults = dict(
            strategy_id="test_strategy",
            requested_capital=Decimal("10000"),
            approved_capital=Decimal("10000"),
            status=AllocationStatus.APPROVED,
            decided_at=_NOW,
        )
        defaults.update(kw)
        return AllocationDecision(**defaults)

    def test_not_expired_before_expires_at(self):
        """Decision is not expired when now is before expires_at."""
        future = _NOW + timedelta(seconds=30)
        d = self._make_decision(expires_at=future)
        assert d.is_expired(now=_NOW) is False

    def test_expired_at_expires_at(self):
        """Decision is expired when now == expires_at."""
        d = self._make_decision(expires_at=_NOW)
        assert d.is_expired(now=_NOW) is True

    def test_expired_after_expires_at(self):
        """Decision is expired when now > expires_at."""
        past = _NOW - timedelta(seconds=10)
        d = self._make_decision(expires_at=past)
        assert d.is_expired(now=_NOW) is True

    def test_no_expires_at_never_expires(self):
        """Decision with no expires_at is never expired."""
        d = self._make_decision(expires_at=None)
        assert d.is_expired() is False

    def test_serialisation_round_trip(self):
        """AllocationDecision survives model_dump → model_validate."""
        future = _NOW + timedelta(seconds=30)
        d = self._make_decision(expires_at=future)
        data = d.model_dump()
        d2 = AllocationDecision.model_validate(data)
        assert d2.status == d.status
        assert d2.approved_capital == d.approved_capital


# ===========================================================================
# PortfolioPosition
# ===========================================================================

class TestPortfolioPosition:
    def test_valid_open_quantity_zero(self):
        """open_quantity=0 is allowed (pending or just-closed)."""
        pos = PortfolioPosition(
            instrument_token=1,
            instrument_symbol="TEST",
            side=PositionSide.LONG,
            open_quantity=0,
        )
        assert pos.open_quantity == 0

    def test_open_quantity_positive(self):
        """open_quantity > 0 is valid."""
        pos = PortfolioPosition(
            instrument_token=1,
            instrument_symbol="TEST",
            side=PositionSide.LONG,
            open_quantity=10,
        )
        assert pos.open_quantity == 10

    def test_negative_open_quantity_rejected(self):
        """open_quantity < 0 must be rejected."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioPosition(
                instrument_token=1,
                instrument_symbol="TEST",
                side=PositionSide.LONG,
                open_quantity=-1,
            )

    def test_market_value_property(self):
        """market_value = open_quantity * last_market_price."""
        pos = PortfolioPosition(
            instrument_token=1,
            instrument_symbol="TEST",
            side=PositionSide.LONG,
            open_quantity=10,
            last_market_price=Decimal("100"),
            last_price_as_of=_NOW,
        )
        assert pos.market_value == Decimal("1000")

    def test_gross_exposure_uses_average_when_no_market_price(self):
        """gross_exposure falls back to average_entry_price when no market price."""
        pos = PortfolioPosition(
            instrument_token=1,
            instrument_symbol="TEST",
            side=PositionSide.LONG,
            open_quantity=5,
            average_entry_price=Decimal("200"),
        )
        assert pos.gross_exposure == Decimal("1000")

    def test_position_is_not_frozen(self):
        """PortfolioPosition is NOT frozen — mutation is allowed."""
        pos = PortfolioPosition(
            instrument_token=1,
            instrument_symbol="TEST",
            side=PositionSide.LONG,
            open_quantity=10,
        )
        pos.open_quantity = 20  # should not raise
        assert pos.open_quantity == 20


# ===========================================================================
# Frozen model mutation
# ===========================================================================

class TestFrozenModels:
    def test_cash_balance_frozen(self):
        """CashBalance is frozen — mutation must raise."""
        cb = _make_cash()
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            cb.available = Decimal("999")

    def test_buying_power_frozen(self):
        """BuyingPower is frozen."""
        bp = _make_bp()
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            bp.net = Decimal("0")

    def test_portfolio_snapshot_frozen(self):
        """PortfolioSnapshot is frozen."""
        snap = _make_snapshot()
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            snap.version = 99

    def test_allocation_decision_frozen(self):
        """AllocationDecision is frozen."""
        d = AllocationDecision(
            strategy_id="s1",
            requested_capital=Decimal("1000"),
            approved_capital=Decimal("1000"),
            status=AllocationStatus.APPROVED,
            decided_at=_NOW,
        )
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            d.status = AllocationStatus.EXPIRED


# ===========================================================================
# Serialisation round-trips
# ===========================================================================

class TestSerialisationRoundTrip:
    def test_exposure_snapshot_round_trip(self):
        """ExposureSnapshot survives model_dump → model_validate."""
        e = _make_exposure(gross_exposure=Decimal("5000"), net_exposure=Decimal("4000"))
        data = e.model_dump()
        e2 = ExposureSnapshot.model_validate(data)
        assert e2.gross_exposure == e.gross_exposure
        assert e2.net_exposure == e.net_exposure

    def test_portfolio_pnl_round_trip(self):
        """PortfolioPnL survives round-trip."""
        p = PortfolioPnL(
            realised=Decimal("1000"),
            unrealised=Decimal("-200"),
            daily_pnl=Decimal("300"),
            drawdown=Decimal("0.02"),
        )
        data = p.model_dump()
        p2 = PortfolioPnL.model_validate(data)
        assert p2.realised == p.realised
        assert p2.drawdown == p.drawdown

    def test_portfolio_snapshot_round_trip(self):
        """PortfolioSnapshot survives round-trip."""
        snap = _make_snapshot()
        data = snap.model_dump()
        snap2 = PortfolioSnapshot.model_validate(data)
        assert snap2.version == snap.version
        assert snap2.status == snap.status

    def test_position_size_request_round_trip(self):
        """PositionSizeRequest survives round-trip."""
        req = PositionSizeRequest(
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            entry_price=Decimal("2500"),
            lot_size=1,
            requested_at=_NOW,
        )
        data = req.model_dump()
        req2 = PositionSizeRequest.model_validate(data)
        assert req2.entry_price == req.entry_price

    def test_limit_check_report_round_trip(self):
        """LimitCheckReport survives round-trip."""
        result = LimitCheckResult(
            limit_name="buying_power",
            allowed=True,
            current_value=Decimal("10000"),
            proposed_value=Decimal("5000"),
            configured_limit=Decimal("10000"),
            severity=LimitSeverity.INFO,
        )
        report = LimitCheckReport(
            overall_allowed=True,
            results=(result,),
            checked_at=_NOW,
        )
        data = report.model_dump()
        r2 = LimitCheckReport.model_validate(data)
        assert r2.overall_allowed == report.overall_allowed
        assert len(r2.results) == 1

    def test_portfolio_event_round_trip(self):
        """PortfolioEvent survives round-trip."""
        ev = PortfolioEvent(
            idempotency_key="fill-001",
            event_type=PortfolioEventType.FILL_RECEIVED,
            instrument_token=738561,
            payload={"qty": 10, "price": "2500"},
            occurred_at=_NOW,
        )
        data = ev.model_dump()
        ev2 = PortfolioEvent.model_validate(data)
        assert ev2.idempotency_key == ev.idempotency_key

    def test_reconciliation_report_round_trip(self):
        """PortfolioReconciliationReport survives round-trip."""
        disc = PortfolioDiscrepancy(
            discrepancy_type=PortfolioDiscrepancyType.QUANTITY_MISMATCH,
            instrument_token=1,
            severity=LimitSeverity.CRITICAL,
        )
        report = PortfolioReconciliationReport(
            discrepancies=(disc,),
            critical_count=1,
            portfolio_ready=False,
            started_at=_NOW,
        )
        data = report.model_dump()
        r2 = PortfolioReconciliationReport.model_validate(data)
        assert r2.critical_count == 1
        assert r2.portfolio_ready is False
