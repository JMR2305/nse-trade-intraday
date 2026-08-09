"""Hermetic tests — portfolio_bridge startup prefers snapshot recovery.

Verifies the Task-#521 startup strategy: when a valid persisted snapshot
exists, the bridge recovers from it (preserving durable event history)
instead of re-seeding from the canonical ledger; a CRITICAL reconciliation
discrepancy against the canonical ledger discards the recovered state and
falls back to ledger re-seeding.

No database is used: durable cross-restart storage is simulated by
sharing single repository instances across simulated process starts.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

_PY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

# Hermetic: never touch Postgres even when DATABASE_URL is set.
os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = "1"
os.environ["PORTFOLIO_EVENT_DB_DISABLED"] = "1"
os.environ["PORTFOLIO_RECON_DB_DISABLED"] = "1"
os.environ["PORTFOLIO_OVERRIDES_DISABLED"] = "1"

import portfolio_bridge
from portfolio_bridge import instrument_token_for


def _make_service(snap_repo=None, event_repo=None, recon_repo=None):
    from src.portfolio.config import PortfolioConfig
    from src.portfolio.service import PortfolioService
    from src.portfolio.repositories.portfolio_event import PortfolioEventRepository
    from src.portfolio.repositories.reconciliation import ReconciliationRepository
    cfg = PortfolioConfig(initial_capital=Decimal("50000"),
                          min_order_value=Decimal("50"))
    return PortfolioService(
        config=cfg,
        event_repo=event_repo or PortfolioEventRepository(),
        reconciliation_repo=recon_repo or ReconciliationRepository(),
    )


def _apply_fill(svc, symbol: str, qty: int, price: str, trade_id: str):
    from src.portfolio.contracts import PositionSide
    asyncio.run(svc.apply_fill(
        idempotency_key=f"fill-{trade_id}",
        instrument_token=instrument_token_for(symbol),
        instrument_symbol=symbol,
        side=PositionSide.LONG,
        quantity=qty,
        price=Decimal(price),
        fill_id=trade_id,
        filled_at=datetime.now(timezone.utc),
        order_id=trade_id,
    ))


def _canon(positions, cash: float):
    return {
        "initial_capital": 50000,
        "cash": cash,
        "positions": positions,
    }


class BridgeRecoveryBase(unittest.TestCase):
    """Shared harness: durable repos + monkeypatched bridge internals."""

    def setUp(self):
        from src.portfolio.repositories.portfolio_snapshot import (
            PortfolioSnapshotRepository,
        )
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        # "Durable" repos shared across simulated process restarts.
        self.snap_repo = PortfolioSnapshotRepository()
        self.event_repo = PortfolioEventRepository()

        def fake_build_service():
            return (
                _make_service(event_repo=self.event_repo),
                self.snap_repo,
            )

        self._patches = [
            mock.patch.object(portfolio_bridge, "_build_service",
                              side_effect=fake_build_service),
            mock.patch.object(portfolio_bridge, "_canonical_state",
                              side_effect=lambda: self.canonical),
        ]
        for p in self._patches:
            p.start()
        # Reset bridge process-level singletons.
        portfolio_bridge._service = None
        portfolio_bridge._started = False
        portfolio_bridge._startup_error = None
        self.canonical = _canon([], 50000.0)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        portfolio_bridge._service = None
        portfolio_bridge._started = False

    def _persist_book(self, positions):
        """Simulate a prior process: seed fills + persist a snapshot."""
        svc = _make_service(event_repo=self.event_repo)
        svc._snapshot_repo = self.snap_repo
        asyncio.run(svc.initialise(Decimal("50000")))
        for sym, qty, price, tid in positions:
            _apply_fill(svc, sym, qty, price, tid)
        asyncio.run(svc.create_snapshot())
        return asyncio.run(svc.get_snapshot())


class TestSnapshotRecoveryPreferred(BridgeRecoveryBase):
    def test_recovers_from_valid_snapshot_when_ledger_matches(self):
        prior = self._persist_book([("RELIANCE", 5, "2500", "t1")])
        self.canonical = _canon(
            [{"symbol": "RELIANCE", "quantity": 5, "avg_price": 2500.0,
              "trade_id": "t1"}],
            cash=float(prior.cash.total),
        )

        self.assertTrue(portfolio_bridge.startup(force=True))
        snap = asyncio.run(portfolio_bridge._service.get_snapshot())

        self.assertEqual(len(snap.open_positions), 1)
        self.assertEqual(snap.open_positions[0].open_quantity, 5)
        # Recovery path — no synthetic seed fills were applied.
        seen = portfolio_bridge._service._state_manager._seen_idempotency_keys
        self.assertFalse(any(k.startswith("seed-") for k in seen))

    def test_recovery_replays_durable_events_after_snapshot(self):
        prior = self._persist_book([("RELIANCE", 5, "2500", "t1")])
        # A later fill in another process wrote a durable event but no
        # newer snapshot (e.g. snapshot persist failed).
        svc2 = _make_service(event_repo=self.event_repo)
        asyncio.run(svc2.recover(snapshot=prior))
        _apply_fill(svc2, "TCS", 3, "4000", "t2")
        expected_cash = asyncio.run(svc2.get_snapshot()).cash.total

        self.canonical = _canon(
            [{"symbol": "RELIANCE", "quantity": 5, "avg_price": 2500.0,
              "trade_id": "t1"},
             {"symbol": "TCS", "quantity": 3, "avg_price": 4000.0,
              "trade_id": "t2"}],
            cash=float(expected_cash),
        )

        self.assertTrue(portfolio_bridge.startup(force=True))
        snap = asyncio.run(portfolio_bridge._service.get_snapshot())
        self.assertEqual(
            sorted(p.instrument_symbol for p in snap.open_positions),
            ["RELIANCE", "TCS"],
        )

    def test_critical_discrepancy_falls_back_to_ledger_seed(self):
        self._persist_book([("RELIANCE", 5, "2500", "t1")])
        # Canonical ledger says 10, snapshot says 5 → QUANTITY_MISMATCH
        # (CRITICAL) → the stale recovered book must be discarded.
        self.canonical = _canon(
            [{"symbol": "RELIANCE", "quantity": 10, "avg_price": 2500.0,
              "trade_id": "t1"}],
            cash=25000.0,
        )

        self.assertTrue(portfolio_bridge.startup(force=True))
        snap = asyncio.run(portfolio_bridge._service.get_snapshot())

        self.assertEqual(len(snap.open_positions), 1)
        self.assertEqual(snap.open_positions[0].open_quantity, 10)
        # Seed path was taken.
        seen = portfolio_bridge._service._state_manager._seen_idempotency_keys
        self.assertTrue(any(k.startswith("seed-") for k in seen))

    def test_no_snapshot_seeds_from_ledger(self):
        self.canonical = _canon(
            [{"symbol": "INFY", "quantity": 4, "avg_price": 1500.0,
              "trade_id": "t9"}],
            cash=44000.0,
        )
        self.assertTrue(portfolio_bridge.startup(force=True))
        snap = asyncio.run(portfolio_bridge._service.get_snapshot())
        self.assertEqual(len(snap.open_positions), 1)
        self.assertEqual(snap.open_positions[0].instrument_symbol, "INFY")
        seen = portfolio_bridge._service._state_manager._seen_idempotency_keys
        self.assertTrue(any(k.startswith("seed-") for k in seen))

    def test_empty_persisted_book_recovers_empty_when_ledger_agrees(self):
        # An empty (but valid) persisted book with a matching empty ledger
        # must recover clean — an empty service book is authoritative.
        self._persist_book([])
        self.canonical = _canon([], 50000.0)
        self.assertTrue(portfolio_bridge.startup(force=True))
        snap = asyncio.run(portfolio_bridge._service.get_snapshot())
        self.assertEqual(len(snap.open_positions), 0)


class TestRepoDbFallbacks(unittest.TestCase):
    """DB-layer failures must degrade to in-memory, never raise."""

    def test_event_repo_read_merges_db_and_memory(self):
        from src.portfolio.repositories import portfolio_event as pe
        from src.portfolio.contracts import PortfolioEvent, PortfolioEventType
        repo = pe.PortfolioEventRepository()
        db_event = PortfolioEvent(
            idempotency_key="db-1",
            event_type=PortfolioEventType.FILL_RECEIVED,
        )
        local_only = PortfolioEvent(
            idempotency_key="mem-1",
            event_type=PortfolioEventType.FILL_RECEIVED,
        )
        dup_local = PortfolioEvent(
            idempotency_key="db-1",  # also in DB — must dedupe
            event_type=PortfolioEventType.FILL_RECEIVED,
        )
        repo._events.extend([local_only, dup_local])
        with mock.patch.object(pe, "_db_available", return_value=True), \
             mock.patch.object(repo, "_db_fetch", return_value=[db_event]):
            events = asyncio.run(repo.list_all("default"))
        self.assertEqual(
            sorted(e.idempotency_key for e in events), ["db-1", "mem-1"])

    def test_event_repo_read_falls_back_on_db_error(self):
        from src.portfolio.repositories import portfolio_event as pe
        from src.portfolio.contracts import PortfolioEvent, PortfolioEventType
        repo = pe.PortfolioEventRepository()
        asyncio.run(repo.append(PortfolioEvent(
            idempotency_key="k1",
            event_type=PortfolioEventType.FILL_RECEIVED,
        )))
        with mock.patch.object(pe, "_db_available", return_value=True), \
             mock.patch.object(repo, "_db_fetch",
                               side_effect=RuntimeError("db down")):
            events = asyncio.run(repo.list_all("default"))
        self.assertEqual(len(events), 1)

    def test_event_repo_write_survives_db_error(self):
        from src.portfolio.repositories import portfolio_event as pe
        from src.portfolio.contracts import PortfolioEvent, PortfolioEventType
        repo = pe.PortfolioEventRepository()
        with mock.patch.object(pe, "_db_available", return_value=True), \
             mock.patch.object(repo, "_db_save_many",
                               side_effect=RuntimeError("db down")):
            asyncio.run(repo.append(PortfolioEvent(
                idempotency_key="k1",
                event_type=PortfolioEventType.FILL_RECEIVED,
            )))
        self.assertEqual(len(repo._events), 1)

    def test_recon_repo_write_and_read_survive_db_error(self):
        from src.portfolio.repositories import reconciliation as rr
        from src.portfolio.contracts import PortfolioReconciliationReport
        repo = rr.ReconciliationRepository()
        report = PortfolioReconciliationReport(critical_count=2)
        with mock.patch.object(rr, "_db_available", return_value=True), \
             mock.patch.object(repo, "_db_save",
                               side_effect=RuntimeError("db down")), \
             mock.patch.object(repo, "_db_fetch",
                               side_effect=RuntimeError("db down")):
            asyncio.run(repo.save(report))
            latest = asyncio.run(repo.get_latest("default"))
            self.assertEqual(latest.run_id, report.run_id)
            self.assertEqual(asyncio.run(repo.count_unresolved("default")), 2)


if __name__ == "__main__":
    unittest.main()
