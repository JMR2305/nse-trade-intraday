"""Unit tests for the Exposure Engine (exposure.py).

Covers:
  - calculate_exposure: single LONG position
  - calculate_exposure: pending reservations included
  - calculate_exposure: sector grouping
  - calculate_exposure: stale_prices=True when price old
  - check_instrument_exposure: within/over limit
  - check_sector_exposure: within/over limit
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.portfolio.config import PortfolioConfig
from src.portfolio.contracts import (
    ExposureSnapshot,
    InstrumentExposure,
    PortfolioPosition,
    PositionSide,
    PositionStatus,
    SectorExposure,
)
from src.portfolio.exposure import (
    calculate_exposure,
    check_instrument_exposure,
    check_sector_exposure,
)

_NOW = datetime.now(timezone.utc)


def _make_config(**kw) -> PortfolioConfig:
    defaults = dict(
        max_instrument_exposure_pct=Decimal("0.20"),
        max_sector_exposure_pct=Decimal("0.35"),
        cash_reserve_pct=Decimal("0.05"),
        max_portfolio_exposure_pct=Decimal("0.90"),
    )
    defaults.update(kw)
    return PortfolioConfig(**defaults)


def _make_position(
    token: int = 1,
    symbol: str = "TESTSTOCK",
    qty: int = 10,
    price: Decimal = Decimal("100"),
    side: PositionSide = PositionSide.LONG,
    sector: str | None = None,
    strategy_id: str | None = None,
    price_age_s: float = 0.0,
) -> PortfolioPosition:
    """Create a test PortfolioPosition."""
    price_as_of = _NOW - timedelta(seconds=price_age_s) if price_age_s > 0 else _NOW
    return PortfolioPosition(
        instrument_token=token,
        instrument_symbol=symbol,
        side=side,
        status=PositionStatus.OPEN,
        open_quantity=qty,
        average_entry_price=price,
        last_market_price=price,
        last_price_as_of=price_as_of,
        sector=sector,
        strategy_id=strategy_id,
        opened_at=_NOW,
    )


def _empty_exposure() -> ExposureSnapshot:
    return ExposureSnapshot(gross_exposure=Decimal("0"), net_exposure=Decimal("0"))


class TestCalculateExposure:
    def test_single_long_position(self):
        """Single LONG position: gross_exposure = qty * price."""
        config = _make_config()
        pos = _make_position(qty=10, price=Decimal("100"))
        snap = calculate_exposure(
            positions=[pos],
            pending_reservations={},
            portfolio_equity=Decimal("10000"),
            config=config,
            stale_price_threshold_s=30.0,
        )
        assert snap.gross_exposure == Decimal("1000")
        assert snap.long_exposure == Decimal("1000")
        assert snap.short_exposure == Decimal("0")

    def test_pending_reservations_included(self):
        """Pending reservations appear in pending_order_exposure."""
        config = _make_config()
        pos = _make_position(qty=5, price=Decimal("200"), token=1)
        reservations = {
            "order-001": {
                "instrument_token": 1,
                "instrument_symbol": "TESTSTOCK",
                "estimated_value": "500",
            }
        }
        snap = calculate_exposure(
            positions=[pos],
            pending_reservations=reservations,
            portfolio_equity=Decimal("10000"),
            config=config,
            stale_price_threshold_s=30.0,
        )
        assert snap.pending_order_exposure == Decimal("500")

    def test_sector_grouping(self):
        """Positions in same sector are grouped in sector_exposures."""
        config = _make_config()
        pos1 = _make_position(token=1, symbol="A", qty=10, price=Decimal("100"), sector="tech")
        pos2 = _make_position(token=2, symbol="B", qty=5, price=Decimal("200"), sector="tech")
        snap = calculate_exposure(
            positions=[pos1, pos2],
            pending_reservations={},
            portfolio_equity=Decimal("10000"),
            config=config,
            stale_price_threshold_s=30.0,
        )
        # Filter UNKNOWN (from no-sector positions) and find tech
        tech_sectors = [s for s in snap.sector_exposures if s.sector == "tech"]
        assert len(tech_sectors) == 1
        assert tech_sectors[0].absolute_value == Decimal("2000")  # 1000+1000
        assert tech_sectors[0].position_count == 2

    def test_two_sectors_separate(self):
        """Positions in different sectors produce separate sector_exposures."""
        config = _make_config()
        pos1 = _make_position(token=1, symbol="A", qty=10, price=Decimal("100"), sector="tech")
        pos2 = _make_position(token=2, symbol="B", qty=10, price=Decimal("100"), sector="energy")
        snap = calculate_exposure(
            positions=[pos1, pos2],
            pending_reservations={},
            portfolio_equity=Decimal("10000"),
            config=config,
            stale_price_threshold_s=30.0,
        )
        sectors = {s.sector for s in snap.sector_exposures}
        assert "tech" in sectors
        assert "energy" in sectors

    def test_stale_prices_true_when_old(self):
        """stale_prices=True when any position price is older than threshold."""
        config = _make_config()
        pos = _make_position(price_age_s=60.0)  # older than 30s default threshold
        snap = calculate_exposure(
            positions=[pos],
            pending_reservations={},
            portfolio_equity=Decimal("10000"),
            config=config,
            stale_price_threshold_s=30.0,
        )
        assert snap.stale_prices is True

    def test_stale_prices_false_when_fresh(self):
        """stale_prices=False when all prices are recent."""
        config = _make_config()
        pos = _make_position(price_age_s=5.0)
        snap = calculate_exposure(
            positions=[pos],
            pending_reservations={},
            portfolio_equity=Decimal("10000"),
            config=config,
            stale_price_threshold_s=30.0,
        )
        assert snap.stale_prices is False

    def test_empty_positions(self):
        """No positions → zero gross and net exposure."""
        config = _make_config()
        snap = calculate_exposure(
            positions=[],
            pending_reservations={},
            portfolio_equity=Decimal("10000"),
            config=config,
            stale_price_threshold_s=30.0,
        )
        assert snap.gross_exposure == Decimal("0")
        assert snap.net_exposure == Decimal("0")

    def test_short_position_exposure(self):
        """SHORT position contributes to short_exposure."""
        config = _make_config()
        pos = _make_position(qty=10, price=Decimal("100"), side=PositionSide.SHORT)
        snap = calculate_exposure(
            positions=[pos],
            pending_reservations={},
            portfolio_equity=Decimal("10000"),
            config=config,
            stale_price_threshold_s=30.0,
        )
        assert snap.short_exposure == Decimal("1000")
        assert snap.long_exposure == Decimal("0")

    def test_instrument_exposure_pct(self):
        """portfolio_pct is computed for instrument exposures."""
        config = _make_config()
        pos = _make_position(qty=10, price=Decimal("100"), token=1)
        snap = calculate_exposure(
            positions=[pos],
            pending_reservations={},
            portfolio_equity=Decimal("10000"),
            config=config,
            stale_price_threshold_s=30.0,
        )
        inst_exp = next(
            ie for ie in snap.instrument_exposures if ie.instrument_token == 1
        )
        assert inst_exp.portfolio_pct == Decimal("0.1000")  # 1000/10000


class TestCheckInstrumentExposure:
    def test_within_limit(self):
        """Instrument exposure within limit → allowed=True."""
        config = _make_config(max_instrument_exposure_pct=Decimal("0.20"))
        exposure = _empty_exposure()
        result = check_instrument_exposure(
            instrument_token=1,
            proposed_value=Decimal("1000"),
            snapshot=exposure,
            config=config,
            equity=Decimal("10000"),  # limit = 2000; proposed = 1000 < 2000
        )
        assert result.allowed is True

    def test_over_limit(self):
        """Instrument exposure over limit → allowed=False."""
        config = _make_config(max_instrument_exposure_pct=Decimal("0.20"))
        # Build exposure snapshot with existing exposure
        inst_exp = InstrumentExposure(
            instrument_token=1,
            instrument_symbol="TEST",
            absolute_value=Decimal("1500"),
            portfolio_pct=Decimal("0.15"),
            pending_value=Decimal("0"),
        )
        exposure = ExposureSnapshot(
            gross_exposure=Decimal("1500"),
            net_exposure=Decimal("1500"),
            instrument_exposures=(inst_exp,),
        )
        result = check_instrument_exposure(
            instrument_token=1,
            proposed_value=Decimal("1000"),
            snapshot=exposure,
            config=config,
            equity=Decimal("10000"),  # limit=2000; current=1500+1000=2500 > 2000
        )
        assert result.allowed is False

    def test_exactly_at_limit(self):
        """Exactly at limit → allowed."""
        config = _make_config(max_instrument_exposure_pct=Decimal("0.20"))
        exposure = _empty_exposure()
        result = check_instrument_exposure(
            instrument_token=1,
            proposed_value=Decimal("2000"),
            snapshot=exposure,
            config=config,
            equity=Decimal("10000"),  # limit=2000; proposed=2000 == limit
        )
        assert result.allowed is True


class TestCheckSectorExposure:
    def test_within_sector_limit(self):
        """Sector exposure within limit → allowed=True."""
        config = _make_config(max_sector_exposure_pct=Decimal("0.35"))
        exposure = _empty_exposure()
        result = check_sector_exposure(
            sector="tech",
            proposed_value=Decimal("3000"),
            snapshot=exposure,
            config=config,
            equity=Decimal("10000"),  # limit=3500; proposed=3000 < 3500
        )
        assert result.allowed is True

    def test_over_sector_limit(self):
        """Sector exposure over limit → allowed=False."""
        config = _make_config(max_sector_exposure_pct=Decimal("0.35"))
        sector_exp = SectorExposure(
            sector="tech",
            absolute_value=Decimal("3000"),
            portfolio_pct=Decimal("0.30"),
        )
        exposure = ExposureSnapshot(
            gross_exposure=Decimal("3000"),
            net_exposure=Decimal("3000"),
            sector_exposures=(sector_exp,),
        )
        result = check_sector_exposure(
            sector="tech",
            proposed_value=Decimal("1000"),
            snapshot=exposure,
            config=config,
            equity=Decimal("10000"),  # limit=3500; current=3000+1000=4000 > 3500
        )
        assert result.allowed is False
        assert "tech" in result.reason

    def test_sector_limit_name(self):
        """check_sector_exposure uses 'max_sector_exposure' as limit_name."""
        config = _make_config()
        exposure = _empty_exposure()
        result = check_sector_exposure(
            sector="energy",
            proposed_value=Decimal("100"),
            snapshot=exposure,
            config=config,
            equity=Decimal("10000"),
        )
        assert result.limit_name == "max_sector_exposure"
