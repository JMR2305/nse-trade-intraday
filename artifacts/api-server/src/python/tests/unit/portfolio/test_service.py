"""Integration tests for PortfolioService (service.py).

Covers:
  - Full E2E: initialise → evaluate_allocation → calculate_position_size
              → apply_order_reservation → apply_fill → get_state (position reflected)
  - Insufficient buying power: evaluate_allocation returns REJECTED
  - apply_fill duplicate: DuplicateEventError on second identical call
  - get_health: readiness=True after init
  - reconcile: critical discrepancy → portfolio_ready=False
  - recover: with mocked snapshot
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from src.portfolio.config import PortfolioConfig
from src.portfolio.contracts import (
    AllocationStatus,
    PortfolioStatus,
    PositionSide,
    PositionSizeRequest,
)
from src.portfolio.exceptions import DuplicateEventError
from src.portfolio.reconciliation import BrokerPositionSnapshot, BrokerSnapshot
from src.portfolio.service import PortfolioService

_NOW = datetime.now(timezone.utc)


def _make_config(**kw) -> PortfolioConfig:
    defaults = dict(
        initial_capital=Decimal("100000"),
        cash_reserve_pct=Decimal("0.05"),
        max_portfolio_exposure_pct=Decimal("0.90"),
        max_strategy_exposure_pct=Decimal("0.40"),
        max_daily_loss_pct=Decimal("0.03"),
        max_drawdown_pct=Decimal("0.10"),
        min_order_value=Decimal("1000"),
        max_order_value=Decimal("50000"),
        default_risk_per_trade_pct=Decimal("0.01"),
        stale_state_threshold_s=60.0,
        allocation_ttl_s=30.0,
    )
    defaults.update(kw)
    return PortfolioConfig(**defaults)


# ===========================================================================
# Full E2E flow
# ===========================================================================

class TestFullE2EFlow:
    @pytest.mark.asyncio
    async def test_e2e_buy_then_check_state(self):
        """Full flow: init → evaluate → reserve → fill → get_state."""
        config = _make_config()
        svc = PortfolioService(config)

        # 1. Initialise
        snap = await svc.initialise(Decimal("100000"))
        assert snap.status == PortfolioStatus.READY

        # 2. Evaluate allocation
        decision = await svc.evaluate_allocation(
            strategy_id="momentum",
            requested_capital=Decimal("5000"),
            instrument_token=738561,
        )
        assert decision.status == AllocationStatus.APPROVED

        # 3. Reserve capital
        snap = await svc.apply_order_reservation("order-001", Decimal("5000"))
        assert snap.cash.blocked == Decimal("5000")

        # 4. Apply fill (BUY)
        snap = await svc.apply_fill(
            idempotency_key="fill-001",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=2,
            price=Decimal("2500"),
            fill_id="fill-001",
            filled_at=_NOW,
            order_id="order-001",
        )

        # 5. Get state — position should be reflected
        state = await svc.get_state()
        assert len(state.open_positions) == 1
        assert state.open_positions[0].instrument_symbol == "RELIANCE"

    @pytest.mark.asyncio
    async def test_e2e_buy_sell_closes_position(self):
        """Buy then sell closes the position."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))

        await svc.apply_fill(
            idempotency_key="fill-buy",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-buy",
            filled_at=_NOW,
        )
        await svc.apply_fill(
            idempotency_key="fill-sell",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.SHORT,
            quantity=10,
            price=Decimal("2600"),
            fill_id="fill-sell",
            filled_at=_NOW,
        )
        state = await svc.get_state()
        assert len(state.open_positions) == 0

    @pytest.mark.asyncio
    async def test_e2e_calculate_position_size(self):
        """calculate_position_size returns an approved decision."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))
        req = PositionSizeRequest(
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            entry_price=Decimal("2500"),
            stop_price=Decimal("2450"),
            lot_size=1,
            requested_at=_NOW,
        )
        decision = await svc.calculate_position_size(req)
        assert decision.approved is True
        assert decision.approved_quantity > 0


# ===========================================================================
# Allocation rejection
# ===========================================================================

class TestAllocationRejection:
    @pytest.mark.asyncio
    async def test_insufficient_buying_power_rejected(self):
        """Requesting more than available → REJECTED."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("1000"))  # tiny capital
        decision = await svc.evaluate_allocation(
            strategy_id="momentum",
            requested_capital=Decimal("50000"),
        )
        assert decision.status == AllocationStatus.REJECTED
        assert "INSUFFICIENT_BUYING_POWER" in decision.reason_codes

    @pytest.mark.asyncio
    async def test_below_min_order_value_rejected(self):
        """Below min_order_value → REJECTED."""
        config = _make_config(min_order_value=Decimal("1000"))
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))
        decision = await svc.evaluate_allocation(
            strategy_id="momentum",
            requested_capital=Decimal("500"),
        )
        assert decision.status == AllocationStatus.REJECTED


# ===========================================================================
# Duplicate fill
# ===========================================================================

class TestDuplicateFill:
    @pytest.mark.asyncio
    async def test_duplicate_fill_raises(self):
        """Applying the same fill twice → DuplicateEventError."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))
        await svc.apply_fill(
            idempotency_key="fill-dup",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=5,
            price=Decimal("2500"),
            fill_id="fill-dup",
            filled_at=_NOW,
        )
        with pytest.raises(DuplicateEventError):
            await svc.apply_fill(
                idempotency_key="fill-dup",
                instrument_token=738561,
                instrument_symbol="RELIANCE",
                side=PositionSide.LONG,
                quantity=5,
                price=Decimal("2500"),
                fill_id="fill-dup",
                filled_at=_NOW,
            )

    @pytest.mark.asyncio
    async def test_duplicate_fill_no_double_position(self):
        """After duplicate fill error, position count is unchanged."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))
        await svc.apply_fill(
            idempotency_key="fill-once",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=5,
            price=Decimal("2500"),
            fill_id="fill-once",
            filled_at=_NOW,
        )
        try:
            await svc.apply_fill(
                idempotency_key="fill-once",
                instrument_token=738561,
                instrument_symbol="RELIANCE",
                side=PositionSide.LONG,
                quantity=5,
                price=Decimal("2500"),
                fill_id="fill-once",
                filled_at=_NOW,
            )
        except DuplicateEventError:
            pass
        state = await svc.get_state()
        assert len(state.open_positions) == 1


# ===========================================================================
# Health
# ===========================================================================

class TestGetHealth:
    @pytest.mark.asyncio
    async def test_readiness_true_after_init(self):
        """get_health readiness=True after successful initialise."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))
        health = await svc.get_health()
        assert health.readiness is True
        assert health.initialized is True

    @pytest.mark.asyncio
    async def test_readiness_false_before_init(self):
        """get_health readiness=False before initialise."""
        config = _make_config()
        svc = PortfolioService(config)
        health = await svc.get_health()
        assert health.readiness is False

    @pytest.mark.asyncio
    async def test_paper_mode_reflected_in_health(self):
        """get_health reflects paper_mode=True."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))
        health = await svc.get_health()
        assert health.paper_mode is True


# ===========================================================================
# Reconciliation
# ===========================================================================

class TestReconcile:
    @pytest.mark.asyncio
    async def test_reconcile_critical_discrepancy_degrades(self):
        """Critical discrepancy → portfolio_ready=False."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))
        # Apply a fill locally but not in broker
        await svc.apply_fill(
            idempotency_key="fill-local",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-local",
            filled_at=_NOW,
        )
        # Broker has no positions
        broker_snap = BrokerSnapshot(positions=[], cash=Decimal("100000"))
        report = await svc.reconcile(broker_snap, dry_run=False)
        assert report.portfolio_ready is False

    @pytest.mark.asyncio
    async def test_reconcile_exact_match_ready(self):
        """Exact match → portfolio_ready=True."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))
        # No positions locally, none in broker
        broker_snap = BrokerSnapshot(positions=[], cash=Decimal("100000"))
        report = await svc.reconcile(broker_snap, dry_run=True)
        assert report.portfolio_ready is True

    @pytest.mark.asyncio
    async def test_reconcile_dry_run(self):
        """Dry run reconciliation is reflected in report."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.initialise(Decimal("100000"))
        broker_snap = BrokerSnapshot(positions=[], cash=Decimal("100000"))
        report = await svc.reconcile(broker_snap, dry_run=True)
        assert report.dry_run is True


# ===========================================================================
# Recovery
# ===========================================================================

class TestRecover:
    @pytest.mark.asyncio
    async def test_recover_with_none_initialises(self):
        """recover(None) initialises to READY with configured initial_capital (not zero)."""
        config = _make_config()
        svc = PortfolioService(config)
        snap = await svc.recover(snapshot=None)
        assert snap.status == PortfolioStatus.READY
        # Must bootstrap from initial_capital, not zero — otherwise all
        # allocations are blocked on first start or after snapshot loss.
        assert snap.cash.total == config.initial_capital, (
            f"Cold-start recovery must use initial_capital={config.initial_capital}, "
            f"not zero; got {snap.cash.total}"
        )

    @pytest.mark.asyncio
    async def test_recover_no_snapshot_uses_initial_capital(self):
        """Cold-start: no snapshot → cash initialized from config.initial_capital."""
        from decimal import Decimal as D
        config = PortfolioConfig(initial_capital=D("250000"))
        svc = PortfolioService(config)
        snap = await svc.recover(snapshot=None)
        assert snap.cash.total == D("250000"), (
            f"Expected 250000 from initial_capital, got {snap.cash.total}"
        )
        assert snap.cash.available == D("250000")
        assert snap.cash.blocked == D("0")

    @pytest.mark.asyncio
    async def test_recover_with_snapshot(self):
        """recover(snapshot) restores health to ready."""
        config = _make_config()
        svc = PortfolioService(config)
        # Build a fake snapshot
        svc2 = PortfolioService(config)
        existing_snap = await svc2.initialise(Decimal("50000"))
        # Recover from the snapshot
        snap = await svc.recover(snapshot=existing_snap)
        health = await svc.get_health()
        assert health.readiness is True

    @pytest.mark.asyncio
    async def test_recover_sets_initialized(self):
        """After recover(), initialized=True in health."""
        config = _make_config()
        svc = PortfolioService(config)
        await svc.recover(snapshot=None)
        health = await svc.get_health()
        assert health.initialized is True

    @pytest.mark.asyncio
    async def test_recover_preserves_open_positions(self):
        """Critical regression: recover(snapshot) must restore open positions,
        not just cash.  A snapshot taken with an open RELIANCE position must
        yield exactly that position after recovery into a fresh service."""
        config = _make_config()

        # --- Session A: trade happens ---
        svc_a = PortfolioService(config)
        await svc_a.initialise(Decimal("100000"))
        await svc_a.apply_fill(
            idempotency_key="fill-reliance-001",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=5,
            price=Decimal("2500"),
            fill_id="fill-reliance-001",
            filled_at=_NOW,
        )
        # Capture the snapshot to simulate what would be persisted to DB
        snapshot_after_trade = await svc_a.get_state()

        assert len(snapshot_after_trade.open_positions) == 1, (
            "Session A should have 1 open position before recovery"
        )

        # --- Session B: restart / recovery ---
        svc_b = PortfolioService(config)  # fresh service, empty state
        pre_recover = await svc_b.get_state()
        assert len(pre_recover.open_positions) == 0, (
            "Fresh service should start with zero positions"
        )

        # Restore from the snapshot captured in session A
        recovered = await svc_b.recover(snapshot=snapshot_after_trade)

        assert recovered.status == PortfolioStatus.READY, (
            f"Expected READY after recovery, got {recovered.status}"
        )
        assert len(recovered.open_positions) == 1, (
            "Recovered portfolio must contain the same open position — "
            "recovery must not discard positions by calling initialise(cash_only)"
        )
        pos = recovered.open_positions[0]
        assert pos.instrument_symbol == "RELIANCE"
        assert pos.open_quantity == 5
        assert pos.average_entry_price == Decimal("2500")

        # Cash should also be correctly restored (not reset to initial_capital)
        assert recovered.cash.total < Decimal("100000"), (
            "Cash should reflect the debit from the BUY fill, not initial capital"
        )

    @pytest.mark.asyncio
    async def test_recover_replay_idempotency_key_differs_from_fill_id(self):
        """Regression: replay must succeed when event.idempotency_key != fill_id.

        Before the fix, restore_from_snapshot() seeded _seen_idempotency_keys
        from lot.fill_id values.  If a replayed event had a different
        idempotency_key, replay skipped the fast-path dedup and called
        apply_fill() again.  position_manager.increase_position() then raised
        InvalidPositionTransitionError (duplicate fill_id), which was not caught
        by ledger.replay(), aborting recovery.
        """
        from src.portfolio.ledger import PortfolioEventLedger
        from src.portfolio.state_manager import PortfolioStateManager
        from src.portfolio.contracts import PortfolioEventType, PortfolioEvent, PortfolioStatus

        config = _make_config()

        # --- Session A: apply a fill (idempotency_key == fill_id here) ---
        svc_a = PortfolioService(config)
        await svc_a.initialise(Decimal("100000"))
        await svc_a.apply_fill(
            idempotency_key="idem-001",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=3,
            price=Decimal("2500"),
            fill_id="fill-001",   # fill_id deliberately different from idempotency_key
            filled_at=_NOW,
        )
        snapshot_with_position = await svc_a.get_state()
        assert len(snapshot_with_position.open_positions) == 1

        # Simulate the fill event as it would be stored with idempotency_key="idem-001"
        # and fill_id="fill-001" in the payload (they differ).
        fill_event = PortfolioEvent(
            idempotency_key="idem-001",
            event_type=PortfolioEventType.FILL_RECEIVED,
            instrument_token=738561,
            strategy_id=None,
            payload={
                "fill_id": "fill-001",   # different from idempotency_key
                "side": "BUY",
                "quantity": "3",
                "price": "2500",
                "fees": "0",
                "instrument_symbol": "RELIANCE",
                "order_id": "",
                "sector": "",
            },
        )

        # --- Session B: restore from snapshot that has the position, then replay ---
        svc_b = PortfolioService(config)
        # restore_from_snapshot seeds _seen_idempotency_keys from lot.fill_id="fill-001"
        svc_b._state_manager.restore_from_snapshot(snapshot_with_position)
        svc_b._state_manager._status = PortfolioStatus.READY

        # Replay must NOT raise — fill_id is already in position lots,
        # state_manager.apply_fill() must detect this and return a no-op.
        replayed = await svc_b._ledger.replay([fill_event], svc_b._state_manager)

        # Event is recorded in the ledger (so it's durable), but state unchanged.
        assert replayed == 1, "Event should be recorded even if state is unchanged"

        state_b = await svc_b.get_state()
        # Position should still have exactly 3 shares (not doubled to 6)
        assert len(state_b.open_positions) == 1
        pos = state_b.open_positions[0]
        assert pos.open_quantity == 3, (
            f"Quantity must remain 3 (not doubled to 6 by replay), got {pos.open_quantity}"
        )

    @pytest.mark.asyncio
    async def test_recover_replay_fill_events_after_snapshot(self):
        """End-to-end replay: snapshot taken before fill, fill event replayed on
        recovery — positions and cash must match as-if the fill ran live.

        This exercises ledger.replay() with a FILL_RECEIVED event, confirming
        Decimal is imported and apply_fill keyword args are correct.
        """
        from src.portfolio.ledger import PortfolioEventLedger
        from src.portfolio.state_manager import PortfolioStateManager
        from src.portfolio.contracts import PortfolioEventType, PortfolioEvent

        config = _make_config()

        # --- Session A: take snapshot BEFORE the fill ---
        svc_a = PortfolioService(config)
        await svc_a.initialise(Decimal("100000"))
        snapshot_pre_fill = await svc_a.get_state()  # no positions yet

        # Simulate a fill that happened AFTER the snapshot was taken
        fill_event = PortfolioEvent(
            idempotency_key="fill-replay-001",
            event_type=PortfolioEventType.FILL_RECEIVED,
            instrument_token=738561,
            strategy_id="strat-1",
            payload={
                "fill_id": "fill-replay-001",
                "side": "BUY",
                "quantity": "4",
                "price": "2500",
                "fees": "0",
                "instrument_symbol": "RELIANCE",
                "order_id": "",
                "sector": "",
            },
        )

        # --- Session B: recover from pre-fill snapshot, then replay the fill ---
        svc_b = PortfolioService(config)
        # Restore state from snapshot (no positions)
        svc_b._state_manager.restore_from_snapshot(snapshot_pre_fill)
        svc_b._state_manager._status = __import__(
            "src.portfolio.contracts", fromlist=["PortfolioStatus"]
        ).PortfolioStatus.READY

        # Replay the post-snapshot fill via the ledger
        # This is the path that was broken (NameError on Decimal)
        replayed = await svc_b._ledger.replay([fill_event], svc_b._state_manager)
        assert replayed == 1, f"Expected 1 event replayed, got {replayed}"

        state_b = await svc_b.get_state()
        assert len(state_b.open_positions) == 1, (
            "Replayed fill must create position in recovered state"
        )
        assert state_b.open_positions[0].open_quantity == 4
        assert state_b.open_positions[0].instrument_symbol == "RELIANCE"

    @pytest.mark.asyncio
    async def test_recover_cash_and_pnl_consistent(self):
        """Recovery restores peak_equity and daily_pnl, not zeros."""
        config = _make_config()
        svc_a = PortfolioService(config)
        await svc_a.initialise(Decimal("100000"))
        # Buy then sell for a profit
        await svc_a.apply_fill(
            idempotency_key="fill-buy-pnl",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-buy-pnl",
            filled_at=_NOW,
        )
        await svc_a.apply_fill(
            idempotency_key="fill-sell-pnl",
            instrument_token=738561,
            instrument_symbol="RELIANCE",
            side=PositionSide.SHORT,
            quantity=10,
            price=Decimal("2600"),  # +100/share profit
            fill_id="fill-sell-pnl",
            filled_at=_NOW,
        )
        snap_a = await svc_a.get_state()
        assert snap_a.pnl.daily_pnl > Decimal("0"), "Session A should show profit"
        assert len(snap_a.open_positions) == 0, "Position should be closed"

        # Recover into fresh service
        svc_b = PortfolioService(config)
        recovered = await svc_b.recover(snapshot=snap_a)

        assert recovered.pnl.daily_pnl == snap_a.pnl.daily_pnl, (
            "daily_pnl must be restored from snapshot"
        )
        assert len(recovered.open_positions) == 0, (
            "Closed positions must stay closed after recovery"
        )


# ===========================================================================
# Corrupt-snapshot fallback & fill-history rebuild
# ===========================================================================

class TestCorruptSnapshotFallback:
    """Tests for the CorruptSnapshotError → fill-history rebuild path.

    Covers task-17 requirements:
    - recover() falls back to fill-history replay when no valid snapshot exists
    - CorruptSnapshotError emits a structured alert instead of just logging
    - rebuild_from_fills() restores correct position quantities
    """

    @pytest.mark.asyncio
    async def test_rebuild_from_fills_restores_position_quantities(self):
        """Core regression: fill-history rebuild produces correct position counts.

        A service with only an event_repo (no snapshot_repo) must be able to
        reconstruct exact open positions from FILL_RECEIVED events alone.
        """
        from src.portfolio.repositories.portfolio_event import PortfolioEventRepository
        from src.portfolio.contracts import PortfolioEventType, PortfolioEvent

        config = _make_config()
        event_repo = PortfolioEventRepository()

        # Seed the event store with two fills: buy 5 RELIANCE, buy 3 INFY
        buy_reliance = PortfolioEvent(
            idempotency_key="rebuild-fill-001",
            event_type=PortfolioEventType.FILL_RECEIVED,
            instrument_token=738561,
            payload={
                "fill_id": "rebuild-fill-001",
                "side": "BUY",
                "quantity": "5",
                "price": "2500",
                "fees": "0",
                "instrument_symbol": "RELIANCE",
                "order_id": "",
                "sector": "Energy",
            },
        )
        buy_infy = PortfolioEvent(
            idempotency_key="rebuild-fill-002",
            event_type=PortfolioEventType.FILL_RECEIVED,
            instrument_token=408065,
            payload={
                "fill_id": "rebuild-fill-002",
                "side": "BUY",
                "quantity": "3",
                "price": "1800",
                "fees": "0",
                "instrument_symbol": "INFY",
                "order_id": "",
                "sector": "IT",
            },
        )
        await event_repo.append(buy_reliance)
        await event_repo.append(buy_infy)

        # Build service with the pre-seeded event_repo; no snapshot_repo
        svc = PortfolioService(config=config, event_repo=event_repo)

        # rebuild_from_fills should reconstruct both positions
        result = await svc.rebuild_from_fills()

        assert result is not None, "rebuild_from_fills must return a snapshot"
        assert result.status.value == "READY", (
            f"Rebuilt portfolio must be READY, got {result.status}"
        )
        assert len(result.open_positions) == 2, (
            f"Expected 2 open positions, got {len(result.open_positions)}"
        )

        by_symbol = {pos.instrument_symbol: pos for pos in result.open_positions}
        assert "RELIANCE" in by_symbol, "RELIANCE position must be rebuilt"
        assert "INFY" in by_symbol, "INFY position must be rebuilt"
        assert by_symbol["RELIANCE"].open_quantity == 5, (
            f"RELIANCE qty should be 5, got {by_symbol['RELIANCE'].open_quantity}"
        )
        assert by_symbol["INFY"].open_quantity == 3, (
            f"INFY qty should be 3, got {by_symbol['INFY'].open_quantity}"
        )

    @pytest.mark.asyncio
    async def test_recover_falls_back_to_fill_history_on_corrupt_snapshot(self):
        """recover() falls back to fill-history replay when CorruptSnapshotError is raised.

        Simulates a corrupt snapshot store by monkey-patching get_latest_valid()
        to raise CorruptSnapshotError.  The service must still produce a READY
        state with correct positions from the event repo.
        """
        from unittest.mock import AsyncMock, patch
        from src.portfolio.exceptions import CorruptSnapshotError
        from src.portfolio.repositories.portfolio_event import PortfolioEventRepository
        from src.portfolio.repositories.portfolio_snapshot import PortfolioSnapshotRepository
        from src.portfolio.contracts import PortfolioEventType, PortfolioEvent

        config = _make_config()
        event_repo = PortfolioEventRepository()
        snapshot_repo = PortfolioSnapshotRepository()

        # Seed the event store with one fill
        fill_event = PortfolioEvent(
            idempotency_key="corrupt-fallback-fill-001",
            event_type=PortfolioEventType.FILL_RECEIVED,
            instrument_token=738561,
            payload={
                "fill_id": "corrupt-fallback-fill-001",
                "side": "BUY",
                "quantity": "7",
                "price": "2500",
                "fees": "0",
                "instrument_symbol": "RELIANCE",
                "order_id": "",
                "sector": "",
            },
        )
        await event_repo.append(fill_event)

        # Capture alerts so we can assert one was emitted
        alerts: list[tuple[str, dict]] = []
        def _alert_hook(kind: str, payload: dict) -> None:
            alerts.append((kind, payload))

        svc = PortfolioService(
            config=config,
            snapshot_repo=snapshot_repo,
            event_repo=event_repo,
            alert_callback=_alert_hook,
        )

        # Force the snapshot repo to raise CorruptSnapshotError
        snapshot_repo.get_latest_valid = AsyncMock(
            side_effect=CorruptSnapshotError("checksum mismatch in test")
        )

        recovered = await svc.recover()

        # Must be READY with correct position rebuilt from fills
        assert recovered.status.value == "READY", (
            f"Expected READY after corrupt-snapshot fallback, got {recovered.status}"
        )
        assert len(recovered.open_positions) == 1, (
            f"Expected 1 position from fill replay, got {len(recovered.open_positions)}"
        )
        assert recovered.open_positions[0].instrument_symbol == "RELIANCE"
        assert recovered.open_positions[0].open_quantity == 7

        # A structured alert must have been emitted
        assert len(alerts) == 1, (
            f"Expected exactly 1 alert for CorruptSnapshotError, got {len(alerts)}"
        )
        kind, payload = alerts[0]
        assert kind == "CORRUPT_SNAPSHOT", f"Alert kind should be CORRUPT_SNAPSHOT, got {kind!r}"
        assert "CRITICAL" == payload.get("severity"), (
            f"Alert severity should be CRITICAL, got {payload.get('severity')!r}"
        )

    @pytest.mark.asyncio
    async def test_corrupt_snapshot_alert_fires_even_without_callback(self):
        """CorruptSnapshotError path must not raise even if no alert_callback is set."""
        from unittest.mock import AsyncMock
        from src.portfolio.exceptions import CorruptSnapshotError
        from src.portfolio.repositories.portfolio_event import PortfolioEventRepository
        from src.portfolio.repositories.portfolio_snapshot import PortfolioSnapshotRepository
        from src.portfolio.contracts import PortfolioEventType, PortfolioEvent

        config = _make_config()
        event_repo = PortfolioEventRepository()
        snapshot_repo = PortfolioSnapshotRepository()

        fill_event = PortfolioEvent(
            idempotency_key="no-callback-fill-001",
            event_type=PortfolioEventType.FILL_RECEIVED,
            instrument_token=738561,
            payload={
                "fill_id": "no-callback-fill-001",
                "side": "BUY",
                "quantity": "2",
                "price": "2500",
                "fees": "0",
                "instrument_symbol": "RELIANCE",
                "order_id": "",
                "sector": "",
            },
        )
        await event_repo.append(fill_event)

        # No alert_callback — must not raise
        svc = PortfolioService(
            config=config,
            snapshot_repo=snapshot_repo,
            event_repo=event_repo,
        )
        snapshot_repo.get_latest_valid = AsyncMock(
            side_effect=CorruptSnapshotError("simulated corrupt snapshot")
        )

        # Should complete without raising
        recovered = await svc.recover()
        assert recovered.status.value == "READY"
        assert len(recovered.open_positions) == 1

    @pytest.mark.asyncio
    async def test_rebuild_from_fills_returns_none_without_event_repo(self):
        """rebuild_from_fills returns None when no event_repo is configured."""
        config = _make_config()
        svc = PortfolioService(config=config)  # no event_repo

        result = await svc.rebuild_from_fills()
        assert result is None, (
            "rebuild_from_fills must return None when event_repo is not configured"
        )

    @pytest.mark.asyncio
    async def test_rebuild_from_fills_returns_none_with_empty_event_store(self):
        """rebuild_from_fills returns None when event_repo has no fill events."""
        from src.portfolio.repositories.portfolio_event import PortfolioEventRepository

        config = _make_config()
        event_repo = PortfolioEventRepository()  # empty
        svc = PortfolioService(config=config, event_repo=event_repo)

        result = await svc.rebuild_from_fills()
        assert result is None, (
            "rebuild_from_fills must return None when no FILL_RECEIVED events exist"
        )

    @pytest.mark.asyncio
    async def test_recover_uses_initial_capital_as_last_resort(self):
        """When both snapshot and fill history are absent, recover() uses initial_capital."""
        config = _make_config(initial_capital=Decimal("75000"))
        svc = PortfolioService(config=config)  # no repos at all

        recovered = await svc.recover()
        assert recovered.status.value == "READY"
        assert recovered.cash.total == Decimal("75000"), (
            f"Last-resort recovery must use initial_capital=75000, got {recovered.cash.total}"
        )

    @pytest.mark.asyncio
    async def test_snapshot_checksum_validation_passes_for_valid_snapshot(self):
        """validate_snapshot() does not raise for a snapshot without checksum."""
        from src.portfolio.repositories.portfolio_snapshot import validate_snapshot

        config = _make_config()
        svc = PortfolioService(config)
        snap = await svc.initialise(Decimal("100000"))

        # snapshot has no checksum — should pass silently
        validate_snapshot(snap)  # must not raise

    @pytest.mark.asyncio
    async def test_snapshot_checksum_validation_fails_for_corrupt_checksum(self):
        """validate_snapshot() raises CorruptSnapshotError for a bad checksum."""
        from src.portfolio.repositories.portfolio_snapshot import validate_snapshot
        from src.portfolio.exceptions import CorruptSnapshotError

        config = _make_config()
        svc = PortfolioService(config)
        snap = await svc.initialise(Decimal("100000"))

        # Inject a deliberately wrong checksum
        snap_with_bad_checksum = snap.model_copy(
            update={"checksum": "deadbeef000000000000000000000000000000000000000000000000000000ff"}
        )

        with pytest.raises(CorruptSnapshotError, match="checksum"):
            validate_snapshot(snap_with_bad_checksum)
