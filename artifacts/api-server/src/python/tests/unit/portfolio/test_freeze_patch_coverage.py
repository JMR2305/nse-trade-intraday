"""RC-10C1 Freeze Patch — targeted coverage tests.

Covers the gaps identified in the final production audit:
  - All four repository classes (capital_allocation, portfolio_event,
    portfolio_snapshot, reconciliation)
  - health.py stale-state / stale-broker / DOWN / failure-reason branches
  - ledger.py get_events_after, get_all, replay skip paths, event_count,
    last_sequence
  - service.py persistence paths (snapshot_repo, event_repo, recon_repo)
  - reconciliation.py malformed broker fields (F-02 regression tests)
  - reconciliation.detect_stale_state
  - exposure.py stale price, pending reservations, standalone check helpers

All tests are pure unit tests using in-memory implementations — no DB,
no broker, no network.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from src.portfolio.config import PortfolioConfig
from src.portfolio.contracts import (
    AllocationDecision,
    AllocationStatus,
    BuyingPower,
    CashBalance,
    ExposureSnapshot,
    LimitSeverity,
    MarginState,
    PortfolioDiscrepancyType,
    PortfolioEvent,
    PortfolioEventType,
    PortfolioHealth,
    PortfolioPnL,
    PortfolioPosition,
    PortfolioReconciliationReport,
    PortfolioSnapshot,
    PortfolioStatus,
    PositionSide,
    PositionStatus,
)
from src.portfolio.exceptions import CorruptSnapshotError
from src.portfolio.health import PortfolioHealthMonitor, compute_health
from src.portfolio.ledger import PortfolioEventLedger
from src.portfolio.reconciliation import (
    PortfolioReconciliationEngine,
    detect_stale_state,
)
from src.portfolio.repositories.capital_allocation import CapitalAllocationRepository
from src.portfolio.repositories.portfolio_event import PortfolioEventRepository
from src.portfolio.repositories.portfolio_snapshot import (
    PortfolioSnapshotRepository,
    compute_snapshot_checksum,
    validate_snapshot,
)
from src.portfolio.repositories.reconciliation import ReconciliationRepository
from src.portfolio.service import PortfolioService
from src.portfolio.state_manager import PortfolioStateManager
from src.portfolio.exposure import (
    ExposureEngine,
    calculate_exposure,
    check_instrument_exposure,
    check_sector_exposure,
    check_strategy_exposure,
    _exposure_severity,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = None


@pytest.fixture(autouse=True)
def _refresh_fixture_timestamp(monkeypatch):
    # Preserve the production thresholds while refreshing this test's inputs.
    monkeypatch.setitem(globals(), "_NOW", datetime.now(timezone.utc))


def _cfg(**kw) -> PortfolioConfig:
    defaults = dict(
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
    defaults.update(kw)
    return PortfolioConfig(**defaults)


def _snap(status=PortfolioStatus.READY, snapshotted_at=None, **kw) -> PortfolioSnapshot:
    now = snapshotted_at or _NOW
    cash = CashBalance(
        available=Decimal("50000"), blocked=Decimal("0"),
        total=Decimal("50000"), as_of=now,
    )
    margin = MarginState(
        used=Decimal("0"), available=Decimal("100000"),
        total=Decimal("100000"), as_of=now,
    )
    bp = BuyingPower(
        gross=Decimal("55000"), net=Decimal("50000"),
        reserved=Decimal("5000"), as_of=now,
    )
    exp = ExposureSnapshot(
        gross_exposure=Decimal("0"), net_exposure=Decimal("0"),
        long_exposure=Decimal("0"), short_exposure=Decimal("0"),
        portfolio_equity=Decimal("100000"), as_of=now,
    )
    pnl = PortfolioPnL(
        peak_equity=Decimal("100000"), current_equity=Decimal("100000"),
    )
    return PortfolioSnapshot(
        portfolio_id=kw.pop("portfolio_id", "test"),
        status=status,
        version=kw.pop("version", 1),
        cash=cash, margin=margin, buying_power=bp,
        exposure=exp, pnl=pnl,
        open_positions=kw.pop("open_positions", ()),
        snapshotted_at=now,
        **kw,
    )


def _alloc(strategy_id="s1", approved=Decimal("10000"), status=AllocationStatus.APPROVED) -> AllocationDecision:
    return AllocationDecision(
        strategy_id=strategy_id,
        requested_capital=approved,
        approved_capital=approved,
        rejected_capital=Decimal("0"),
        status=status,
        reason_codes=(),
        portfolio_state_version=1,
    )


def _recon_report(portfolio_id="test", critical=0, warnings=0) -> PortfolioReconciliationReport:
    now = datetime.now(timezone.utc)
    return PortfolioReconciliationReport(
        portfolio_id=portfolio_id,
        dry_run=True,
        discrepancies=(),
        critical_count=critical,
        warning_count=warnings,
        portfolio_ready=critical == 0,
        notes="",
        started_at=now,
        completed_at=now,
        state_version=1,
    )


# ---------------------------------------------------------------------------
# CapitalAllocationRepository  (0% → 100%)
# ---------------------------------------------------------------------------

class TestCapitalAllocationRepository:
    @pytest.fixture
    def repo(self) -> CapitalAllocationRepository:
        return CapitalAllocationRepository()

    @pytest.mark.asyncio
    async def test_save_and_get_by_decision_id(self, repo):
        d = _alloc()
        await repo.save(d)
        result = await repo.get_by_decision_id(str(d.decision_id))
        assert result is not None
        assert result.decision_id == d.decision_id

    @pytest.mark.asyncio
    async def test_get_by_decision_id_missing(self, repo):
        result = await repo.get_by_decision_id("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_for_strategy_approved(self, repo):
        d = _alloc(strategy_id="alpha", status=AllocationStatus.APPROVED)
        await repo.save(d)
        active = await repo.get_active_for_strategy("alpha")
        assert len(active) == 1

    @pytest.mark.asyncio
    async def test_get_active_for_strategy_rejected_excluded(self, repo):
        d = _alloc(strategy_id="beta", status=AllocationStatus.REJECTED)
        await repo.save(d)
        active = await repo.get_active_for_strategy("beta")
        assert active == []

    @pytest.mark.asyncio
    async def test_get_active_for_strategy_different_strategy(self, repo):
        d = _alloc(strategy_id="gamma")
        await repo.save(d)
        active = await repo.get_active_for_strategy("delta")
        assert active == []

    @pytest.mark.asyncio
    async def test_list_for_strategy_respects_limit(self, repo):
        for i in range(5):
            await repo.save(_alloc(strategy_id="s"))
        results = await repo.list_for_strategy("s", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_list_for_strategy_empty(self, repo):
        results = await repo.list_for_strategy("nobody")
        assert results == []

    @pytest.mark.asyncio
    async def test_save_multiple_decisions(self, repo):
        for i in range(4):
            await repo.save(_alloc(strategy_id="multi"))
        results = await repo.list_for_strategy("multi")
        assert len(results) == 4


# ---------------------------------------------------------------------------
# PortfolioEventRepository  (81% → 100%)
# ---------------------------------------------------------------------------

class TestPortfolioEventRepository:
    @pytest.fixture
    def repo(self) -> PortfolioEventRepository:
        return PortfolioEventRepository()

    def _event(self, idem="k1", pid="test") -> PortfolioEvent:
        return PortfolioEvent(
            idempotency_key=idem,
            portfolio_id=pid,
            event_type=PortfolioEventType.FILL_RECEIVED,
            payload={},
        )

    @pytest.mark.asyncio
    async def test_append_many(self, repo):
        events = [self._event(f"k{i}") for i in range(3)]
        await repo.append_many(events)
        all_ev = await repo.list_all("test")
        assert len(all_ev) == 3

    @pytest.mark.asyncio
    async def test_get_events_after_sequence(self, repo):
        for i in range(5):
            e = self._event(f"seq{i}")
            e = e.model_copy(update={"sequence": i + 1})
            await repo.append(e)
        result = await repo.get_events_after_sequence("test", sequence=2)
        seqs = [e.sequence for e in result]
        assert all(s > 2 for s in seqs if s is not None)

    @pytest.mark.asyncio
    async def test_get_events_after_datetime(self, repo):
        old_ts = _NOW - timedelta(hours=2)
        new_ts = _NOW
        e_old = PortfolioEvent(
            idempotency_key="old",
            portfolio_id="test",
            event_type=PortfolioEventType.FILL_RECEIVED,
            payload={},
            occurred_at=old_ts,
        )
        e_new = PortfolioEvent(
            idempotency_key="new",
            portfolio_id="test",
            event_type=PortfolioEventType.FILL_RECEIVED,
            payload={},
            occurred_at=new_ts,
        )
        await repo.append(e_old)
        await repo.append(e_new)
        cutoff = _NOW - timedelta(hours=1)
        result = await repo.get_events_after("test", cutoff)
        assert len(result) == 1
        assert result[0].idempotency_key == "new"


# ---------------------------------------------------------------------------
# PortfolioSnapshotRepository  (62% → 90%+)
# ---------------------------------------------------------------------------

class TestPortfolioSnapshotRepository:
    @pytest.fixture
    def repo(self) -> PortfolioSnapshotRepository:
        return PortfolioSnapshotRepository()

    @pytest.mark.asyncio
    async def test_save_and_get_latest(self, repo):
        s = _snap()
        await repo.save(s)
        result = await repo.get_latest("test")
        assert result is not None
        assert result.snapshot_id == s.snapshot_id

    @pytest.mark.asyncio
    async def test_get_latest_none_when_empty(self, repo):
        assert await repo.get_latest("nobody") is None

    @pytest.mark.asyncio
    async def test_get_latest_valid_no_checksum(self, repo):
        s = _snap()
        await repo.save(s)
        result = await repo.get_latest_valid("test")
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_latest_valid_with_correct_checksum(self, repo):
        s = _snap()
        checksum = compute_snapshot_checksum(s)
        s_with_sum = s.model_copy(update={"checksum": checksum})
        await repo.save(s_with_sum)
        result = await repo.get_latest_valid("test")
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_latest_valid_wrong_checksum_raises(self, repo):
        s = _snap()
        bad = s.model_copy(update={"checksum": "deadbeef" * 8})
        await repo.save(bad)
        with pytest.raises(CorruptSnapshotError):
            await repo.get_latest_valid("test")

    @pytest.mark.asyncio
    async def test_get_latest_valid_falls_back_to_older(self, repo):
        old = _snap(snapshotted_at=_NOW - timedelta(minutes=5), version=1)
        new_snap = _snap(snapshotted_at=_NOW, version=2)
        bad = new_snap.model_copy(update={"checksum": "badhash" * 8})
        await repo.save(old)
        await repo.save(bad)
        result = await repo.get_latest_valid("test")
        assert result is not None
        assert result.version == 1

    @pytest.mark.asyncio
    async def test_get_latest_valid_returns_none_when_empty(self, repo):
        result = await repo.get_latest_valid("nobody")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_after(self, repo):
        old = _snap(snapshotted_at=_NOW - timedelta(hours=2), version=1)
        new_snap = _snap(snapshotted_at=_NOW, version=2)
        await repo.save(old)
        await repo.save(new_snap)
        cutoff = _NOW - timedelta(hours=1)
        results = await repo.list_after("test", cutoff)
        assert len(results) == 1
        assert results[0].version == 2

    def test_compute_snapshot_checksum_is_deterministic(self):
        s = _snap()
        c1 = compute_snapshot_checksum(s)
        c2 = compute_snapshot_checksum(s)
        assert c1 == c2

    def test_validate_snapshot_passes_no_checksum(self):
        validate_snapshot(_snap())  # should not raise

    def test_validate_snapshot_passes_correct_checksum(self):
        s = _snap()
        checksum = compute_snapshot_checksum(s)
        validate_snapshot(s.model_copy(update={"checksum": checksum}))

    def test_validate_snapshot_raises_on_wrong_checksum(self):
        s = _snap().model_copy(update={"checksum": "wrongwrong" * 6 + "01234567"})
        with pytest.raises(CorruptSnapshotError):
            validate_snapshot(s)


# ---------------------------------------------------------------------------
# ReconciliationRepository  (50% → 100%)
# ---------------------------------------------------------------------------

class TestReconciliationRepository:
    @pytest.fixture
    def repo(self) -> ReconciliationRepository:
        return ReconciliationRepository()

    @pytest.mark.asyncio
    async def test_save_and_get_latest(self, repo):
        r = _recon_report()
        await repo.save(r)
        result = await repo.get_latest("test")
        assert result is not None
        assert result.run_id == r.run_id

    @pytest.mark.asyncio
    async def test_get_latest_none_when_empty(self, repo):
        assert await repo.get_latest("nobody") is None

    @pytest.mark.asyncio
    async def test_list_after(self, repo):
        old = _recon_report()
        old = old.model_copy(update={"started_at": _NOW - timedelta(hours=2)})
        new_r = _recon_report()
        await repo.save(old)
        await repo.save(new_r)
        cutoff = _NOW - timedelta(hours=1)
        results = await repo.list_after("test", cutoff)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_count_unresolved_zero_when_empty(self, repo):
        assert await repo.count_unresolved("nobody") == 0

    @pytest.mark.asyncio
    async def test_count_unresolved_uses_latest(self, repo):
        r = _recon_report(critical=3)
        await repo.save(r)
        count = await repo.count_unresolved("test")
        assert count == 3


# ---------------------------------------------------------------------------
# PortfolioHealthMonitor — missing branches
# ---------------------------------------------------------------------------

class TestHealthMonitorBranches:
    @pytest.fixture
    def cfg(self) -> PortfolioConfig:
        return _cfg(stale_state_threshold_s=10.0, stale_broker_threshold_s=20.0)

    def test_stale_state_triggers_degraded(self, cfg):
        old_snap = _snap(
            snapshotted_at=datetime.now(timezone.utc) - timedelta(seconds=120),
        )
        health = compute_health(old_snap, cfg)
        assert not health.readiness
        assert "stale" in (health.failure_reason or "").lower()

    def test_stale_broker_triggers_degraded(self, cfg):
        broker_ts = datetime.now(timezone.utc) - timedelta(seconds=300)
        health = compute_health(_snap(), cfg, broker_snapshot_at=broker_ts)
        assert not health.readiness
        assert "broker" in (health.failure_reason or "").lower()

    def test_halted_status_is_down(self, cfg):
        s = _snap(status=PortfolioStatus.HALTED)
        health = compute_health(s, cfg)
        assert health.status.value == "DOWN"
        assert "HALTED" in (health.failure_reason or "")

    def test_unavailable_status_is_down(self, cfg):
        s = _snap(status=PortfolioStatus.UNAVAILABLE)
        health = compute_health(s, cfg)
        assert health.status.value == "DOWN"
        assert not health.liveness

    def test_unresolved_discrepancies_prevents_readiness(self, cfg):
        health = compute_health(_snap(), cfg, unresolved_discrepancies=2)
        assert not health.readiness
        assert health.degraded
        assert "2" in (health.failure_reason or "")

    def test_degraded_portfolio_status(self, cfg):
        s = _snap(status=PortfolioStatus.DEGRADED)
        health = compute_health(s, cfg)
        assert health.degraded

    def test_ready_no_issues_is_healthy(self, cfg):
        health = compute_health(_snap(), cfg)
        assert health.status.value == "HEALTHY"
        assert health.readiness
        assert health.liveness

    def test_record_broker_snapshot(self):
        monitor = PortfolioHealthMonitor(_cfg())
        ts = datetime.now(timezone.utc)
        monitor.record_broker_snapshot(ts)
        assert monitor._broker_snapshot_at == ts

    @pytest.mark.asyncio
    async def test_compute_health_via_monitor(self):
        monitor = PortfolioHealthMonitor(_cfg())
        monitor.record_recovery(success=True)
        monitor.record_reconciliation(critical_count=0, warning_count=0)
        health = await monitor.compute_health(_snap())
        assert health.status.value == "HEALTHY"

    def test_initialising_status_in_failure_reason(self, cfg):
        s = _snap(status=PortfolioStatus.INITIALISING)
        health = compute_health(s, cfg)
        assert not health.readiness
        assert health.failure_reason is not None


# ---------------------------------------------------------------------------
# PortfolioEventLedger — missing branches
# ---------------------------------------------------------------------------

class TestLedgerMissingBranches:
    @pytest.mark.asyncio
    async def test_get_events_after_returns_subset(self):
        ledger = PortfolioEventLedger("test")
        for i in range(5):
            await ledger.append(PortfolioEvent(
                idempotency_key=f"ev{i}",
                event_type=PortfolioEventType.FILL_RECEIVED,
                payload={},
            ))
        after = await ledger.get_events_after(sequence=3)
        seqs = [e.sequence for e in after]
        assert all(s > 3 for s in seqs)
        assert len(after) == 2

    @pytest.mark.asyncio
    async def test_get_all_returns_all_events(self):
        ledger = PortfolioEventLedger("test")
        for i in range(4):
            await ledger.append(PortfolioEvent(
                idempotency_key=f"all{i}",
                event_type=PortfolioEventType.FILL_RECEIVED,
                payload={},
            ))
        all_ev = await ledger.get_all()
        assert len(all_ev) == 4

    @pytest.mark.asyncio
    async def test_event_count_and_last_sequence(self):
        ledger = PortfolioEventLedger("test")
        assert ledger.event_count() == 0
        assert ledger.last_sequence() is None
        for i in range(3):
            await ledger.append(PortfolioEvent(
                idempotency_key=f"cnt{i}",
                event_type=PortfolioEventType.FILL_RECEIVED,
                payload={},
            ))
        assert ledger.event_count() == 3
        assert ledger.last_sequence() == 3

    @pytest.mark.asyncio
    async def test_replay_skips_already_in_ledger(self):
        ledger = PortfolioEventLedger("test")
        ev = PortfolioEvent(
            idempotency_key="dup",
            event_type=PortfolioEventType.SNAPSHOT_TAKEN,
            payload={},
        )
        await ledger.append(ev)
        sm = PortfolioStateManager(_cfg())
        await sm.initialise(Decimal("100000"), "test")
        applied = await ledger.replay([ev], sm)
        # already in ledger → skipped entirely
        assert applied == 0

    @pytest.mark.asyncio
    async def test_replay_skips_already_in_state_manager(self):
        """Event already applied to state_manager is added to ledger but not re-applied."""
        ledger = PortfolioEventLedger("test")
        sm = PortfolioStateManager(_cfg())
        await sm.initialise(Decimal("100000"), "test")

        ev = PortfolioEvent(
            idempotency_key="already-in-sm",
            event_type=PortfolioEventType.SNAPSHOT_TAKEN,
            payload={},
        )
        # Manually seed state_manager's seen set
        sm._seen_idempotency_keys.add("already-in-sm")

        applied = await ledger.replay([ev], sm)
        # The already-in-state path records the event in the ledger, then
        # does `continue` — so applied counter stays 0 (the fill was skipped,
        # not re-applied), but the event IS now in the ledger.
        assert applied == 0
        assert ledger.event_count() == 1


# ---------------------------------------------------------------------------
# Reconciliation — malformed broker field regression tests (F-02)
# ---------------------------------------------------------------------------

@pytest.fixture
def recon_engine() -> PortfolioReconciliationEngine:
    return PortfolioReconciliationEngine(_cfg())


def _snap_with_position(token=738561, symbol="RELIANCE", qty=10,
                        avg_price="2500", cash="50000") -> PortfolioSnapshot:
    from src.portfolio.contracts import PortfolioLot
    lot = PortfolioLot(
        fill_id="f1", quantity=qty,
        entry_price=Decimal(avg_price),
        filled_at=_NOW,
    )
    pos = PortfolioPosition(
        instrument_token=token,
        instrument_symbol=symbol,
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        open_quantity=qty,
        closed_quantity=0,
        average_entry_price=Decimal(avg_price),
        lots=[lot],
        opened_at=_NOW,
    )
    now = _NOW
    cash_bal = CashBalance(
        available=Decimal(cash), blocked=Decimal("0"),
        total=Decimal(cash), as_of=now,
    )
    margin = MarginState(
        used=Decimal("0"), available=Decimal("100000"),
        total=Decimal("100000"), as_of=now,
    )
    bp = BuyingPower(
        gross=Decimal("55000"), net=Decimal("50000"),
        reserved=Decimal("5000"), as_of=now,
    )
    exp = ExposureSnapshot(
        gross_exposure=Decimal("0"), net_exposure=Decimal("0"),
        long_exposure=Decimal("0"), short_exposure=Decimal("0"),
        portfolio_equity=Decimal("100000"), as_of=now,
    )
    pnl = PortfolioPnL(peak_equity=Decimal("100000"), current_equity=Decimal("100000"))
    return PortfolioSnapshot(
        portfolio_id="test",
        status=PortfolioStatus.READY,
        version=1,
        cash=cash_bal, margin=margin, buying_power=bp,
        exposure=exp, pnl=pnl,
        open_positions=(pos,),
        snapshotted_at=now,
    )


class TestReconciliationMalformedFields:
    """Regression tests for F-02: malformed broker fields must create discrepancies."""

    @pytest.mark.asyncio
    async def test_malformed_avg_price_creates_discrepancy(self, recon_engine):
        local = _snap_with_position(token=100, avg_price="2500")
        broker = {
            "positions": [
                {"instrument_token": 100, "quantity": 10, "average_price": "NOT_A_NUMBER"},
            ],
            "funds": {"available_cash": "50000", "used_margin": "0"},
            "as_of": _NOW.isoformat(),
        }
        report = await recon_engine.reconcile(local, broker)
        types = [d.discrepancy_type for d in report.discrepancies]
        assert PortfolioDiscrepancyType.AVG_PRICE_MISMATCH in types
        parse_error = next(
            d for d in report.discrepancies
            if d.discrepancy_type == PortfolioDiscrepancyType.AVG_PRICE_MISMATCH
        )
        assert parse_error.broker_value == "PARSE_ERROR"

    @pytest.mark.asyncio
    async def test_malformed_cash_creates_discrepancy(self, recon_engine):
        local = _snap()
        broker = {
            "positions": [],
            "funds": {"available_cash": "GARBAGE", "used_margin": "0"},
            "as_of": _NOW.isoformat(),
        }
        report = await recon_engine.reconcile(local, broker)
        types = [d.discrepancy_type for d in report.discrepancies]
        assert PortfolioDiscrepancyType.CASH_MISMATCH in types
        pe = next(d for d in report.discrepancies
                  if d.discrepancy_type == PortfolioDiscrepancyType.CASH_MISMATCH)
        assert pe.broker_value == "PARSE_ERROR"

    @pytest.mark.asyncio
    async def test_malformed_margin_creates_discrepancy(self, recon_engine):
        local = _snap()
        broker = {
            "positions": [],
            "funds": {"available_cash": "50000", "used_margin": [1, 2, 3]},
            "as_of": _NOW.isoformat(),
        }
        report = await recon_engine.reconcile(local, broker)
        types = [d.discrepancy_type for d in report.discrepancies]
        assert PortfolioDiscrepancyType.MARGIN_MISMATCH in types
        pe = next(d for d in report.discrepancies
                  if d.discrepancy_type == PortfolioDiscrepancyType.MARGIN_MISMATCH)
        assert pe.broker_value == "PARSE_ERROR"

    @pytest.mark.asyncio
    async def test_valid_avg_price_no_parse_error(self, recon_engine):
        local = _snap_with_position(token=200, avg_price="2500")
        broker = {
            "positions": [
                {"instrument_token": 200, "quantity": 10, "average_price": "2500.00"},
            ],
            "funds": {"available_cash": "50000", "used_margin": "0"},
            "as_of": _NOW.isoformat(),
        }
        report = await recon_engine.reconcile(local, broker)
        parse_errors = [
            d for d in report.discrepancies if d.broker_value == "PARSE_ERROR"
        ]
        assert parse_errors == []


# ---------------------------------------------------------------------------
# detect_stale_state
# ---------------------------------------------------------------------------

class TestDetectStaleState:
    @pytest.mark.asyncio
    async def test_fresh_snapshot_not_stale(self):
        cfg = _cfg(stale_state_threshold_s=300.0)
        snap = _snap(snapshotted_at=datetime.now(timezone.utc))
        assert await detect_stale_state(snap, cfg) is False

    @pytest.mark.asyncio
    async def test_old_snapshot_is_stale(self):
        cfg = _cfg(stale_state_threshold_s=10.0)
        snap = _snap(snapshotted_at=datetime.now(timezone.utc) - timedelta(seconds=120))
        assert await detect_stale_state(snap, cfg) is True


# ---------------------------------------------------------------------------
# ExposureEngine — missing branches
# ---------------------------------------------------------------------------

class TestExposureMissingBranches:
    @pytest.fixture
    def cfg(self) -> PortfolioConfig:
        return _cfg()

    def _make_position(self, token=100, qty=10, price="2500",
                       last_price_as_of=None, stale=False) -> PortfolioPosition:
        if stale:
            ts = datetime.now(timezone.utc) - timedelta(seconds=3600)
        elif last_price_as_of is not None:
            ts = last_price_as_of
        else:
            ts = datetime.now(timezone.utc)

        from src.portfolio.contracts import PortfolioLot
        lot = PortfolioLot(
            fill_id="f1", quantity=qty,
            entry_price=Decimal(price),
            filled_at=_NOW,
        )
        return PortfolioPosition(
            instrument_token=token,
            instrument_symbol=f"SYM{token}",
            side=PositionSide.LONG,
            status=PositionStatus.OPEN,
            open_quantity=qty,
            closed_quantity=0,
            average_entry_price=Decimal(price),
            last_market_price=Decimal(price),
            last_price_as_of=ts if not (last_price_as_of is None and not stale) else None,
            lots=[lot],
            opened_at=_NOW,
        )

    def test_stale_price_via_none_last_price_as_of(self, cfg):
        pos = PortfolioPosition(
            instrument_token=1,
            instrument_symbol="X",
            side=PositionSide.LONG,
            status=PositionStatus.OPEN,
            open_quantity=10,
            closed_quantity=0,
            average_entry_price=Decimal("100"),
            last_price_as_of=None,  # triggers stale_prices=True
            lots=[],
            opened_at=_NOW,
        )
        snap = calculate_exposure(
            positions=[pos],
            pending_reservations={},
            portfolio_equity=Decimal("100000"),
            config=cfg,
            stale_price_threshold_s=30.0,
        )
        assert snap.stale_prices is True

    def test_stale_price_via_old_timestamp(self, cfg):
        pos = self._make_position(stale=True)
        snap = calculate_exposure(
            positions=[pos],
            pending_reservations={},
            portfolio_equity=Decimal("100000"),
            config=cfg,
            stale_price_threshold_s=30.0,
        )
        assert snap.stale_prices is True

    def test_pending_reservation_creates_new_instrument_entry(self, cfg):
        reservations = {
            "r1": {
                "instrument_token": 9999,
                "instrument_symbol": "NEWSTOCK",
                "estimated_value": Decimal("5000"),
            }
        }
        snap = calculate_exposure(
            positions=[],
            pending_reservations=reservations,
            portfolio_equity=Decimal("100000"),
            config=cfg,
            stale_price_threshold_s=30.0,
        )
        assert snap.pending_order_exposure == Decimal("5000")
        tokens = [ie.instrument_token for ie in snap.instrument_exposures]
        assert 9999 in tokens

    def test_check_instrument_exposure_allowed(self, cfg):
        exp = calculate_exposure([], {}, Decimal("100000"), cfg, 30.0)
        result = check_instrument_exposure(
            instrument_token=1,
            proposed_value=Decimal("10000"),
            snapshot=exp,
            config=cfg,
            equity=Decimal("100000"),
        )
        assert result.allowed

    def test_check_instrument_exposure_blocked(self, cfg):
        exp = calculate_exposure([], {}, Decimal("100000"), cfg, 30.0)
        result = check_instrument_exposure(
            instrument_token=1,
            proposed_value=Decimal("25000"),  # > 20% limit
            snapshot=exp,
            config=cfg,
            equity=Decimal("100000"),
        )
        assert not result.allowed
        assert result.severity == LimitSeverity.CRITICAL

    def test_check_sector_exposure_warning(self, cfg):
        exp = calculate_exposure([], {}, Decimal("100000"), cfg, 30.0)
        result = check_sector_exposure(
            sector="IT",
            proposed_value=Decimal("30000"),  # 30% — ≥80% of 35% limit → WARNING
            snapshot=exp,
            config=cfg,
            equity=Decimal("100000"),
        )
        assert result.severity in (LimitSeverity.WARNING, LimitSeverity.CRITICAL)

    def test_check_strategy_exposure_allowed(self, cfg):
        exp = calculate_exposure([], {}, Decimal("100000"), cfg, 30.0)
        result = check_strategy_exposure(
            strategy_id="momentum",
            proposed_value=Decimal("5000"),
            snapshot=exp,
            config=cfg,
            equity=Decimal("100000"),
        )
        assert result.allowed

    def test_exposure_severity_zero_limit_returns_info(self):
        result = _exposure_severity(projected=Decimal("100"), limit=Decimal("0"))
        assert result == LimitSeverity.INFO

    def test_exposure_severity_warning_band(self):
        # 80% of limit → WARNING
        result = _exposure_severity(projected=Decimal("80"), limit=Decimal("100"))
        assert result == LimitSeverity.WARNING

    def test_exposure_severity_critical(self):
        result = _exposure_severity(projected=Decimal("110"), limit=Decimal("100"))
        assert result == LimitSeverity.CRITICAL


# ---------------------------------------------------------------------------
# PortfolioService — persistence paths
# ---------------------------------------------------------------------------

class TestServicePersistencePaths:
    @pytest.fixture
    def svc_with_repos(self) -> PortfolioService:
        cfg = _cfg()
        snapshot_repo = PortfolioSnapshotRepository()
        event_repo = PortfolioEventRepository()
        recon_repo = ReconciliationRepository()
        return PortfolioService(
            config=cfg,
            snapshot_repo=snapshot_repo,
            event_repo=event_repo,
            reconciliation_repo=recon_repo,
        )

    @pytest.mark.asyncio
    async def test_initialise_saves_to_snapshot_repo(self, svc_with_repos):
        svc = svc_with_repos
        await svc.initialise()
        saved = await svc._snapshot_repo.get_latest("default")
        assert saved is not None

    @pytest.mark.asyncio
    async def test_apply_fill_saves_to_snapshot_repo(self, svc_with_repos):
        svc = svc_with_repos
        await svc.initialise()
        await svc.apply_fill(
            idempotency_key="fill-persist-1",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=5,
            price=Decimal("2500"),
            fill_id="fp1",
            filled_at=datetime.now(timezone.utc),
        )
        saved = await svc._snapshot_repo.get_latest("default")
        assert saved is not None

    @pytest.mark.asyncio
    async def test_apply_fill_persists_fill_event(self, svc_with_repos):
        svc = svc_with_repos
        await svc.initialise()
        await svc.apply_fill(
            idempotency_key="fill-evt-1",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=3,
            price=Decimal("2500"),
            fill_id="fe1",
            filled_at=datetime.now(timezone.utc),
        )
        events = await svc._event_repo.list_all("default")
        types = [e.event_type for e in events]
        assert PortfolioEventType.FILL_RECEIVED in types

    @pytest.mark.asyncio
    async def test_reconcile_saves_report_to_repo(self, svc_with_repos):
        svc = svc_with_repos
        await svc.initialise()
        broker = {
            "positions": [],
            "funds": {"available_cash": "95000", "used_margin": "0"},
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
        await svc.reconcile(broker, dry_run=True)
        report = await svc._reconciliation_repo.get_latest("default")
        assert report is not None

    @pytest.mark.asyncio
    async def test_create_snapshot_saves_to_repo(self, svc_with_repos):
        svc = svc_with_repos
        await svc.initialise()
        snap = await svc.create_snapshot()
        saved = await svc._snapshot_repo.get_latest("default")
        assert saved is not None

    @pytest.mark.asyncio
    async def test_recover_restores_from_snapshot_repo(self, svc_with_repos):
        svc = svc_with_repos
        await svc.initialise(Decimal("200000"))
        await svc.create_snapshot()

        # New service with same repo should recover state
        svc2 = PortfolioService(
            config=_cfg(initial_capital=Decimal("200000")),
            snapshot_repo=svc._snapshot_repo,
            event_repo=svc._event_repo,
        )
        recovered = await svc2.recover(portfolio_id="default")
        assert recovered is not None

    @pytest.mark.asyncio
    async def test_rebuild_from_fills_with_events(self, svc_with_repos):
        svc = svc_with_repos
        await svc.initialise()
        # Apply a fill so there is a FILL_RECEIVED event
        await svc.apply_fill(
            idempotency_key="rbf-fill-1",
            instrument_token=500,
            instrument_symbol="TCS",
            side=PositionSide.LONG,
            quantity=2,
            price=Decimal("3500"),
            fill_id="rbf1",
            filled_at=datetime.now(timezone.utc),
        )
        # Rebuild should replay the fill
        rebuilt = await svc.rebuild_from_fills(portfolio_id="default")
        assert rebuilt is not None
        # Position should be present
        pos_symbols = [p.instrument_symbol for p in rebuilt.open_positions]
        assert "TCS" in pos_symbols

    @pytest.mark.asyncio
    async def test_rebuild_from_fills_no_events_returns_none(self):
        svc = PortfolioService(
            config=_cfg(),
            event_repo=PortfolioEventRepository(),
        )
        result = await svc.rebuild_from_fills()
        assert result is None

    @pytest.mark.asyncio
    async def test_recover_no_snapshot_no_events_uses_initial_capital(self):
        cfg = _cfg(initial_capital=Decimal("75000"))
        svc = PortfolioService(config=cfg)
        snap = await svc.recover()
        assert snap.cash.total == Decimal("75000")

    @pytest.mark.asyncio
    async def test_reconcile_critical_not_dry_run_halts(self, svc_with_repos):
        """Critical reconciliation discrepancy + dry_run=False → state halted."""
        svc = svc_with_repos
        await svc.initialise()
        # Inject a position locally that broker doesn't know about → LOCAL_ONLY_POSITION (CRITICAL)
        await svc.apply_fill(
            idempotency_key="halt-fill",
            instrument_token=9999,
            instrument_symbol="GHOST",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("500"),
            fill_id="hf1",
            filled_at=datetime.now(timezone.utc),
        )
        broker = {
            "positions": [],  # broker has no positions → LOCAL_ONLY_POSITION
            "funds": {"available_cash": "90000", "used_margin": "0"},
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
        report = await svc.reconcile(broker, dry_run=False)
        assert report.critical_count > 0
        state = await svc.get_state()
        assert state.status == PortfolioStatus.HALTED
