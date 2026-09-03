"""Unit tests for PortfolioReconciliationEngine (reconciliation.py).

Covers:
  - Perfect match → no discrepancies, portfolio_ready=True
  - QUANTITY_MISMATCH when local qty ≠ broker qty
  - LOCAL_ONLY_POSITION when local has position but broker doesn't
  - BROKER_ONLY_POSITION when broker has position but local doesn't
  - CASH_MISMATCH when |local_cash - broker_cash| > tolerance (1 rupee)
  - AVG_PRICE_MISMATCH when |local_price - broker_price| > tolerance (0.01)
  - portfolio_ready=False when critical_count > 0
  - dry_run=True (default): no state mutation
  - STALE_BROKER_SNAPSHOT discrepancy for old broker snapshot
  - ReconciliationEngine (legacy alias) works via BrokerSnapshot object
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.portfolio.config import PortfolioConfig
from src.portfolio.contracts import (
    BuyingPower,
    CashBalance,
    ExposureSnapshot,
    MarginState,
    PortfolioPnL,
    PortfolioPosition,
    PortfolioReconciliationReport,
    PortfolioSnapshot,
    PortfolioStatus,
    PortfolioDiscrepancyType,
    PositionSide,
    PositionStatus,
)
from src.portfolio.reconciliation import (
    BrokerPositionSnapshot,
    BrokerSnapshot,
    PortfolioReconciliationEngine,
    ReconciliationEngine,
)

_NOW = None


@pytest.fixture(autouse=True)
def _refresh_fixture_timestamp(monkeypatch):
    monkeypatch.setitem(globals(), "_NOW", datetime.now(timezone.utc))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kw) -> PortfolioConfig:
    defaults = dict(
        initial_capital=Decimal("100000"),
        stale_state_threshold_s=60.0,
        stale_broker_threshold_s=120.0,
    )
    defaults.update(kw)
    return PortfolioConfig(**defaults)


def _make_position(
    token: int = 738561,
    symbol: str = "RELIANCE",
    qty: int = 10,
    avg_price: Decimal = Decimal("2500"),
) -> PortfolioPosition:
    return PortfolioPosition(
        instrument_token=token,
        instrument_symbol=symbol,
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        open_quantity=qty,
        average_entry_price=avg_price,
        opened_at=_NOW,
    )


def _make_local_snapshot(
    positions: list[PortfolioPosition] | None = None,
    available_cash: Decimal = Decimal("75000"),
    used_margin: Decimal = Decimal("0"),
) -> PortfolioSnapshot:
    positions = positions or []
    cash = CashBalance(
        available=available_cash,
        blocked=Decimal("0"),
        total=available_cash,
        as_of=_NOW,
    )
    margin = MarginState(
        used=used_margin,
        available=available_cash,
        total=available_cash,
        as_of=_NOW,
    )
    bp = BuyingPower(
        gross=available_cash,
        net=available_cash,
        reserved=Decimal("0"),
        as_of=_NOW,
    )
    exp = ExposureSnapshot(gross_exposure=Decimal("0"), net_exposure=Decimal("0"))
    pnl = PortfolioPnL()
    return PortfolioSnapshot(
        portfolio_id="test-portfolio",
        status=PortfolioStatus.READY,
        version=1,
        cash=cash,
        margin=margin,
        buying_power=bp,
        exposure=exp,
        pnl=pnl,
        open_positions=tuple(positions),
        snapshotted_at=_NOW,
    )


def _make_broker_snapshot(
    positions: list[dict[str, Any]] | None = None,
    available_cash: str = "75000",
    used_margin: str = "0",
    age_s: float = 0.0,
) -> dict[str, Any]:
    as_of = (_NOW - timedelta(seconds=age_s)).isoformat()
    return {
        "as_of": as_of,
        "positions": positions or [],
        "orders": [],
        "funds": {
            "available_cash": available_cash,
            "used_margin": used_margin,
        },
    }


def _broker_pos(
    token: int = 738561,
    qty: int = 10,
    avg_price: str = "2500",
) -> dict[str, Any]:
    return {
        "instrument_token": token,
        "quantity": qty,
        "average_price": avg_price,
        "product": "CNC",
    }


# ===========================================================================
# Perfect match
# ===========================================================================

class TestPerfectMatch:
    @pytest.mark.asyncio
    async def test_no_discrepancies_when_match(self):
        """Perfect match → 0 discrepancies, portfolio_ready=True."""
        config = _make_config()
        engine = PortfolioReconciliationEngine(config)

        local = _make_local_snapshot(
            positions=[_make_position(qty=10, avg_price=Decimal("2500"))],
            available_cash=Decimal("75000"),
        )
        broker = _make_broker_snapshot(
            positions=[_broker_pos(qty=10, avg_price="2500")],
            available_cash="75000",
        )
        report = await engine.reconcile(local, broker, dry_run=True)
        assert report.portfolio_ready is True
        assert report.critical_count == 0

    @pytest.mark.asyncio
    async def test_dry_run_returns_report(self):
        """reconcile always returns a PortfolioReconciliationReport."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot()
        broker = _make_broker_snapshot()
        report = await engine.reconcile(local, broker, dry_run=True)
        assert isinstance(report, PortfolioReconciliationReport)
        assert report.dry_run is True

    @pytest.mark.asyncio
    async def test_portfolio_id_propagated(self):
        """portfolio_id from local snapshot is reflected in report."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot()
        broker = _make_broker_snapshot()
        report = await engine.reconcile(local, broker)
        assert report.portfolio_id == "test-portfolio"

    @pytest.mark.asyncio
    async def test_no_positions_no_discrepancies(self):
        """Empty local and empty broker → no discrepancies."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(positions=[])
        broker = _make_broker_snapshot(positions=[])
        report = await engine.reconcile(local, broker)
        assert len(report.discrepancies) == 0


# ===========================================================================
# Quantity mismatch
# ===========================================================================

class TestQuantityMismatch:
    @pytest.mark.asyncio
    async def test_quantity_mismatch_detected(self):
        """QUANTITY_MISMATCH detected when local qty ≠ broker qty."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(
            positions=[_make_position(qty=10, avg_price=Decimal("2500"))]
        )
        broker = _make_broker_snapshot(
            positions=[_broker_pos(qty=15, avg_price="2500")]  # 15 ≠ 10
        )
        report = await engine.reconcile(local, broker)
        discrepancy_types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.QUANTITY_MISMATCH in discrepancy_types
        assert report.portfolio_ready is False  # QUANTITY_MISMATCH is CRITICAL

    @pytest.mark.asyncio
    async def test_quantity_mismatch_critical(self):
        """QUANTITY_MISMATCH has CRITICAL severity."""
        from src.portfolio.contracts import LimitSeverity
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(
            positions=[_make_position(qty=10)]
        )
        broker = _make_broker_snapshot(
            positions=[_broker_pos(qty=5)]  # 5 ≠ 10
        )
        report = await engine.reconcile(local, broker)
        mismatch = next(
            d for d in report.discrepancies
            if d.discrepancy_type == PortfolioDiscrepancyType.QUANTITY_MISMATCH
        )
        assert mismatch.severity == LimitSeverity.CRITICAL


# ===========================================================================
# Local-only position
# ===========================================================================

class TestLocalOnlyPosition:
    @pytest.mark.asyncio
    async def test_local_only_position_detected(self):
        """LOCAL_ONLY_POSITION when local has position but broker doesn't."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(
            positions=[_make_position(token=738561, qty=10)]
        )
        broker = _make_broker_snapshot(positions=[])  # broker has nothing
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.LOCAL_ONLY_POSITION in types
        assert report.critical_count >= 1

    @pytest.mark.asyncio
    async def test_local_only_instrument_token_in_discrepancy(self):
        """LOCAL_ONLY_POSITION discrepancy includes the instrument_token."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(
            positions=[_make_position(token=738561, qty=10)]
        )
        broker = _make_broker_snapshot(positions=[])
        report = await engine.reconcile(local, broker)
        local_only = next(
            d for d in report.discrepancies
            if d.discrepancy_type == PortfolioDiscrepancyType.LOCAL_ONLY_POSITION
        )
        assert local_only.instrument_token == 738561


# ===========================================================================
# Broker-only position
# ===========================================================================

class TestBrokerOnlyPosition:
    @pytest.mark.asyncio
    async def test_broker_only_position_detected(self):
        """BROKER_ONLY_POSITION when broker has position but local doesn't."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(positions=[])
        broker = _make_broker_snapshot(
            positions=[_broker_pos(token=999999, qty=5)]  # broker only
        )
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.BROKER_ONLY_POSITION in types

    @pytest.mark.asyncio
    async def test_broker_zero_qty_ignored(self):
        """Broker position with qty=0 is ignored (closed position)."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(positions=[])
        broker = _make_broker_snapshot(
            positions=[_broker_pos(token=738561, qty=0)]  # closed
        )
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.BROKER_ONLY_POSITION not in types


# ===========================================================================
# Cash mismatch
# ===========================================================================

class TestCashMismatch:
    @pytest.mark.asyncio
    async def test_cash_mismatch_within_tolerance_ok(self):
        """Cash mismatch within 1 rupee tolerance → no CASH_MISMATCH."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(available_cash=Decimal("75000"))
        broker = _make_broker_snapshot(available_cash="75000.50")  # 50p diff
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.CASH_MISMATCH not in types

    @pytest.mark.asyncio
    async def test_cash_mismatch_over_tolerance_detected(self):
        """Cash mismatch > 1 rupee → CASH_MISMATCH detected."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(available_cash=Decimal("75000"))
        broker = _make_broker_snapshot(available_cash="70000")  # 5000 rupee diff
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.CASH_MISMATCH in types


# ===========================================================================
# Avg price mismatch
# ===========================================================================

class TestAvgPriceMismatch:
    @pytest.mark.asyncio
    async def test_price_mismatch_within_tolerance_ok(self):
        """Avg price within 1 paisa tolerance → no AVG_PRICE_MISMATCH."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(
            positions=[_make_position(avg_price=Decimal("2500.00"))]
        )
        broker = _make_broker_snapshot(
            positions=[_broker_pos(avg_price="2500.005")]  # 0.5 paisa diff
        )
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.AVG_PRICE_MISMATCH not in types

    @pytest.mark.asyncio
    async def test_price_mismatch_over_tolerance_detected(self):
        """Avg price > 1 paisa off → AVG_PRICE_MISMATCH detected."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(
            positions=[_make_position(avg_price=Decimal("2500.00"))]
        )
        broker = _make_broker_snapshot(
            positions=[_broker_pos(avg_price="2510.00")]  # ₹10 diff
        )
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.AVG_PRICE_MISMATCH in types


# ===========================================================================
# Stale broker snapshot
# ===========================================================================

class TestStaleBrokerSnapshot:
    @pytest.mark.asyncio
    async def test_stale_broker_snapshot_discrepancy(self):
        """STALE_BROKER_SNAPSHOT added when broker snapshot is too old."""
        config = _make_config(stale_broker_threshold_s=120.0)
        engine = PortfolioReconciliationEngine(config)
        local = _make_local_snapshot()
        broker = _make_broker_snapshot(age_s=200.0)  # 200s old > 120s threshold
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.STALE_BROKER_SNAPSHOT in types

    @pytest.mark.asyncio
    async def test_fresh_broker_snapshot_no_staleness_discrepancy(self):
        """Fresh broker snapshot → no STALE_BROKER_SNAPSHOT."""
        config = _make_config(stale_broker_threshold_s=120.0)
        engine = PortfolioReconciliationEngine(config)
        local = _make_local_snapshot()
        broker = _make_broker_snapshot(age_s=5.0)
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.STALE_BROKER_SNAPSHOT not in types


class TestStalenessKeyFormats:
    """Regression: staleness detection must accept both 'snapshot_at' (RC-10D
    broker-neutral schema) and 'as_of' (legacy backward-compat key)."""

    @pytest.mark.asyncio
    async def test_stale_detected_via_snapshot_at_key(self):
        """'snapshot_at' key (RC-10D schema) triggers STALE_BROKER_SNAPSHOT."""
        config = _make_config(stale_broker_threshold_s=60.0)
        engine = PortfolioReconciliationEngine(config)
        local = _make_local_snapshot()
        stale_ts = (_NOW - timedelta(seconds=300)).isoformat()
        broker = {
            "snapshot_at": stale_ts,   # RC-10D key — NOT 'as_of'
            "positions": [],
            "orders": [],
            "funds": {"available_cash": "75000"},
        }
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.STALE_BROKER_SNAPSHOT in types, (
            "STALE_BROKER_SNAPSHOT must fire when 'snapshot_at' key is stale"
        )

    @pytest.mark.asyncio
    async def test_fresh_snapshot_at_key_not_flagged(self):
        """Fresh 'snapshot_at' must NOT trigger STALE_BROKER_SNAPSHOT."""
        config = _make_config(stale_broker_threshold_s=60.0)
        engine = PortfolioReconciliationEngine(config)
        local = _make_local_snapshot()
        fresh_ts = (_NOW - timedelta(seconds=5)).isoformat()
        broker = {
            "snapshot_at": fresh_ts,
            "positions": [],
            "orders": [],
            "funds": {"available_cash": "75000"},
        }
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.STALE_BROKER_SNAPSHOT not in types, (
            f"Fresh 'snapshot_at' should not trigger staleness, got {types}"
        )

    @pytest.mark.asyncio
    async def test_snapshot_at_takes_precedence_over_as_of(self):
        """When both 'snapshot_at' (fresh) and 'as_of' (stale) are present,
        'snapshot_at' wins → no staleness flag."""
        config = _make_config(stale_broker_threshold_s=60.0)
        engine = PortfolioReconciliationEngine(config)
        local = _make_local_snapshot()
        fresh_ts = (_NOW - timedelta(seconds=5)).isoformat()
        stale_ts = (_NOW - timedelta(seconds=500)).isoformat()
        broker = {
            "snapshot_at": fresh_ts,   # fresh — should win
            "as_of": stale_ts,          # stale — should be ignored
            "positions": [],
            "orders": [],
            "funds": {"available_cash": "75000"},
        }
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.STALE_BROKER_SNAPSHOT not in types, (
            "'snapshot_at' (fresh) must take precedence over stale 'as_of'"
        )

    @pytest.mark.asyncio
    async def test_legacy_as_of_still_triggers_stale(self):
        """Backward-compat: stale 'as_of' key still triggers STALE_BROKER_SNAPSHOT."""
        config = _make_config(stale_broker_threshold_s=60.0)
        engine = PortfolioReconciliationEngine(config)
        local = _make_local_snapshot()
        stale_ts = (_NOW - timedelta(seconds=300)).isoformat()
        broker = {
            "as_of": stale_ts,   # legacy key, no 'snapshot_at'
            "positions": [],
            "orders": [],
            "funds": {"available_cash": "75000"},
        }
        report = await engine.reconcile(local, broker)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.STALE_BROKER_SNAPSHOT in types, (
            "Legacy 'as_of' key must still trigger STALE_BROKER_SNAPSHOT"
        )


# ===========================================================================
# portfolio_ready flag
# ===========================================================================

class TestPortfolioReady:
    @pytest.mark.asyncio
    async def test_ready_false_when_critical(self):
        """portfolio_ready=False when any CRITICAL discrepancy exists."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(
            positions=[_make_position(qty=10)]
        )
        broker = _make_broker_snapshot(positions=[])  # LOCAL_ONLY → CRITICAL
        report = await engine.reconcile(local, broker)
        assert report.portfolio_ready is False

    @pytest.mark.asyncio
    async def test_ready_true_with_only_warnings(self):
        """portfolio_ready=True even when warnings exist (cash/price mismatch)."""
        engine = PortfolioReconciliationEngine()
        local = _make_local_snapshot(
            positions=[_make_position(qty=10, avg_price=Decimal("2500.00"))],
            available_cash=Decimal("75000"),
        )
        broker = _make_broker_snapshot(
            positions=[_broker_pos(qty=10, avg_price="2510.00")],  # price warn
            available_cash="70000",  # cash warn > 1 rupee
        )
        report = await engine.reconcile(local, broker)
        # Only WARNINGS, no CRITICAL → portfolio_ready=True
        assert report.portfolio_ready is True
        assert report.warning_count >= 1


# ===========================================================================
# ReconciliationEngine (legacy alias)
# ===========================================================================

class TestReconciliationEngineLegacy:
    @pytest.mark.asyncio
    async def test_legacy_with_broker_snapshot_object(self):
        """ReconciliationEngine works with typed BrokerSnapshot."""
        engine = ReconciliationEngine()
        bp = BrokerPositionSnapshot(
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            quantity=10,
            average_price=Decimal("2500"),
        )
        broker_snap = BrokerSnapshot(
            positions=[bp],
            cash=Decimal("75000"),
        )
        local = _make_local_snapshot(
            positions=[_make_position(qty=10, avg_price=Decimal("2500"))],
            available_cash=Decimal("75000"),
        )
        report = await engine.reconcile(local, broker_snap, dry_run=True)
        assert isinstance(report, PortfolioReconciliationReport)
        assert report.portfolio_ready is True

    @pytest.mark.asyncio
    async def test_legacy_detects_quantity_mismatch(self):
        """ReconciliationEngine correctly detects QUANTITY_MISMATCH."""
        engine = ReconciliationEngine()
        bp = BrokerPositionSnapshot(
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            quantity=15,  # mismatch
            average_price=Decimal("2500"),
        )
        broker_snap = BrokerSnapshot(positions=[bp], cash=Decimal("75000"))
        local = _make_local_snapshot(
            positions=[_make_position(qty=10)],
            available_cash=Decimal("75000"),
        )
        report = await engine.reconcile(local, broker_snap)
        types = {d.discrepancy_type for d in report.discrepancies}
        assert PortfolioDiscrepancyType.QUANTITY_MISMATCH in types

    @pytest.mark.asyncio
    async def test_legacy_with_dict_also_works(self):
        """ReconciliationEngine also accepts raw dict as broker_snapshot."""
        engine = ReconciliationEngine()
        local = _make_local_snapshot()
        broker = _make_broker_snapshot()
        report = await engine.reconcile(local, broker)
        assert report is not None
