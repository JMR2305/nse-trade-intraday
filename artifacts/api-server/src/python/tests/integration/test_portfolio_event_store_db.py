"""Integration tests — Postgres-backed portfolio event + reconciliation stores.

Use the real development database, isolated under a unique portfolio_id and
cleaned up in tearDown.  Skipped when DATABASE_URL is unset.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

HAVE_DB = bool(os.environ.get("DATABASE_URL"))


@unittest.skipUnless(HAVE_DB, "DATABASE_URL not configured")
class TestDurableEventStore(unittest.TestCase):
    def setUp(self):
        self.pid = f"it-{uuid.uuid4().hex[:12]}"
        self._prev = {}
        for key in ("PORTFOLIO_EVENT_DB_DISABLED", "PORTFOLIO_RECON_DB_DISABLED"):
            self._prev[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key, val in self._prev.items():
            if val is not None:
                os.environ[key] = val
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn.cursor() as cur:
            for table in ("portfolio_events", "reconciliation_runs"):
                cur.execute(
                    f"DELETE FROM {table} WHERE portfolio_id = %s", (self.pid,))
        conn.commit()
        conn.close()

    def _event(self, idem: str, occurred_at=None):
        from src.portfolio.contracts import PortfolioEvent, PortfolioEventType
        return PortfolioEvent(
            idempotency_key=idem,
            event_type=PortfolioEventType.FILL_RECEIVED,
            portfolio_id=self.pid,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    def test_events_visible_across_processes_with_durable_sequence(self):
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        writer = PortfolioEventRepository()   # "process 1"
        asyncio.run(writer.append(self._event("e1")))
        asyncio.run(writer.append(self._event("e2")))

        reader = PortfolioEventRepository()   # "process 2" (fresh memory)
        events = asyncio.run(reader.list_all(self.pid))
        self.assertEqual([e.idempotency_key for e in events], ["e1", "e2"])
        # Durable sequence: serial table ids, strictly increasing.
        self.assertTrue(events[0].sequence < events[1].sequence)
        after = asyncio.run(reader.get_events_after_sequence(
            self.pid, events[0].sequence))
        self.assertEqual([e.idempotency_key for e in after], ["e2"])

    def test_duplicate_idempotency_key_stored_once(self):
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        writer1 = PortfolioEventRepository()
        writer2 = PortfolioEventRepository()  # simulates a restarted process
        asyncio.run(writer1.append(self._event("seed-t1")))
        asyncio.run(writer2.append(self._event("seed-t1")))  # distinct event_id

        reader = PortfolioEventRepository()
        events = asyncio.run(reader.list_all(self.pid))
        self.assertEqual(len(events), 1)

    def test_get_events_after_timestamp_filters(self):
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        now = datetime.now(timezone.utc)
        writer = PortfolioEventRepository()
        asyncio.run(writer.append(self._event("old", now - timedelta(hours=2))))
        asyncio.run(writer.append(self._event("new", now)))
        reader = PortfolioEventRepository()
        events = asyncio.run(reader.get_events_after(
            self.pid, now - timedelta(hours=1)))
        self.assertEqual([e.idempotency_key for e in events], ["new"])

    def test_recovery_replays_post_snapshot_event_with_older_timestamp(self):
        """A fill committed AFTER the snapshot but carrying an occurrence
        time OLDER than the snapshot must still be replayed — the durable
        serial-id cursor, not wall-clock time, is the replay boundary."""
        import psycopg2
        from decimal import Decimal
        from src.portfolio.config import PortfolioConfig
        from src.portfolio.contracts import PositionSide
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        from src.portfolio.repositories.portfolio_snapshot import (
            PortfolioSnapshotRepository,
        )
        from src.portfolio.repositories.reconciliation import (
            ReconciliationRepository,
        )
        from src.portfolio.service import PortfolioService

        prev_snap = os.environ.pop("PORTFOLIO_SNAPSHOT_DB_DISABLED", None)
        try:
            def make_service():
                return PortfolioService(
                    config=PortfolioConfig(
                        initial_capital=Decimal("50000"),
                        portfolio_id=self.pid,
                    ),
                    event_repo=PortfolioEventRepository(),
                    reconciliation_repo=ReconciliationRepository(),
                )

            def fill(svc, symbol, tid, qty, price, when):
                asyncio.run(svc.apply_fill(
                    idempotency_key=f"fill-{tid}",
                    instrument_token=hash(symbol) % 100000,
                    instrument_symbol=symbol,
                    side=PositionSide.LONG,
                    quantity=qty,
                    price=Decimal(price),
                    fill_id=tid,
                    filled_at=when,
                    order_id=tid,
                ))

            now = datetime.now(timezone.utc)
            # Process 1: one fill, snapshot persisted (cursor recorded).
            svc1 = make_service()
            svc1._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc1.initialise(Decimal("50000")))
            fill(svc1, "AAA", "t1", 5, "100", now)
            asyncio.run(svc1.create_snapshot())

            # Process 1 (continued): a second fill committed after the
            # snapshot but with an occurrence time in the PAST — patch the
            # event repo to backdate occurred_at on append.
            repo = svc1._event_repo
            orig_append = repo.append

            async def backdating_append(event):
                if event.event_type.value == "fill_received" \
                        and "t2" in event.idempotency_key:
                    event = event.model_copy(
                        update={"occurred_at": now - timedelta(hours=3)})
                await orig_append(event)
            repo.append = backdating_append
            fill(svc1, "BBB", "t2", 2, "200", now - timedelta(hours=3))

            # Process 2: fresh service recovers from snapshot + cursor.
            svc2 = make_service()
            svc2._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc2.recover())
            snap = asyncio.run(svc2.get_snapshot())
            symbols = sorted(p.instrument_symbol for p in snap.open_positions)
            self.assertEqual(symbols, ["AAA", "BBB"],
                             "backdated post-snapshot fill was dropped — "
                             "replay boundary must be the serial-id cursor")
        finally:
            if prev_snap is not None:
                os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = prev_snap
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots WHERE portfolio_id = %s",
                    (self.pid,))
            conn.commit()
            conn.close()

    def test_auto_snapshot_from_apply_fill_carries_cursor_and_replays_backdated_fill(self):
        """The AUTOMATIC snapshot persisted by apply_fill (no explicit
        create_snapshot call) must carry the event cursor, so a backdated
        fill committed afterwards is still replayed on recovery."""
        import psycopg2
        from decimal import Decimal
        from src.portfolio.config import PortfolioConfig
        from src.portfolio.contracts import PositionSide
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        from src.portfolio.repositories.portfolio_snapshot import (
            PortfolioSnapshotRepository,
        )
        from src.portfolio.service import PortfolioService

        prev_snap = os.environ.pop("PORTFOLIO_SNAPSHOT_DB_DISABLED", None)
        try:
            def make_service():
                return PortfolioService(
                    config=PortfolioConfig(
                        initial_capital=Decimal("50000"),
                        portfolio_id=self.pid,
                    ),
                    event_repo=PortfolioEventRepository(),
                )

            def fill(svc, symbol, tid, qty, price, when):
                asyncio.run(svc.apply_fill(
                    idempotency_key=f"fill-{tid}",
                    instrument_token=hash(symbol) % 100000,
                    instrument_symbol=symbol,
                    side=PositionSide.LONG,
                    quantity=qty,
                    price=Decimal(price),
                    fill_id=tid,
                    filled_at=when,
                    order_id=tid,
                ))

            now = datetime.now(timezone.utc)
            svc1 = make_service()
            svc1._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc1.initialise(Decimal("50000")))
            fill(svc1, "AAA", "t1", 5, "100", now)
            # NO create_snapshot(): rely on apply_fill's automatic save.
            latest = asyncio.run(
                PortfolioSnapshotRepository().get_latest_valid(self.pid))
            self.assertIsNotNone(latest.event_cursor,
                                 "auto snapshot missing event cursor")

            # Backdated fill committed AFTER the automatic snapshot.
            repo = svc1._event_repo
            orig = repo.append

            async def backdating_append(event):
                event = event.model_copy(update={
                    "occurred_at": now - timedelta(hours=6)})
                return await orig(event)

            repo.append = backdating_append
            fill(svc1, "BBB", "t2", 2, "200", now - timedelta(hours=6))
            repo.append = orig

            # Restart: recover from the AUTO snapshot (delete newer ones).
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots WHERE portfolio_id=%s "
                    "AND id > (SELECT MIN(id) FROM portfolio_snapshots "
                    "WHERE portfolio_id=%s AND event_cursor IS NOT NULL)",
                    (self.pid, self.pid))
            conn.commit()
            conn.close()

            svc2 = make_service()
            svc2._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc2.recover())
            snap = asyncio.run(svc2.get_snapshot())
            symbols = sorted(
                p.instrument_symbol for p in snap.open_positions)
            self.assertIn("BBB", symbols,
                          "backdated post-auto-snapshot fill lost")
        finally:
            if prev_snap is not None:
                os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = prev_snap
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots WHERE portfolio_id=%s",
                    (self.pid,))
            conn.commit()
            conn.close()

    def test_post_snapshot_reservation_survives_restart(self):
        """A capital reservation committed after the last snapshot must be
        replayed on restart — snapshot-write failure must not lose it."""
        import psycopg2
        from decimal import Decimal
        from src.portfolio.config import PortfolioConfig
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        from src.portfolio.repositories.portfolio_snapshot import (
            PortfolioSnapshotRepository,
        )
        from src.portfolio.service import PortfolioService

        prev_snap = os.environ.pop("PORTFOLIO_SNAPSHOT_DB_DISABLED", None)
        try:
            def make_service():
                return PortfolioService(
                    config=PortfolioConfig(
                        initial_capital=Decimal("50000"),
                        portfolio_id=self.pid,
                    ),
                    event_repo=PortfolioEventRepository(),
                )

            svc1 = make_service()
            svc1._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc1.initialise(Decimal("50000")))
            asyncio.run(svc1.create_snapshot())
            # Reservation AFTER the explicit snapshot — auto-persisted in a
            # new snapshot that carries reservation IDENTITY (order_id →
            # amount), not just the blocked-cash total.
            asyncio.run(svc1.apply_order_reservation(
                "ord-1", Decimal("1000")))
            latest = asyncio.run(
                PortfolioSnapshotRepository().get_latest_valid(self.pid))
            self.assertEqual(latest.pending_reservations, {"ord-1": "1000"})

            svc2 = make_service()
            svc2._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc2.recover())
            snap = asyncio.run(svc2.get_snapshot())
            self.assertEqual(snap.pending_order_count, 1,
                             "post-snapshot reservation lost on restart")
            self.assertEqual(str(snap.cash.blocked), "1000")

            # Identity restored: the RESTARTED service can release it and
            # capital unblocks (not stranded forever).
            rel = asyncio.run(svc2.release_order_reservation("ord-1"))
            self.assertEqual(rel.pending_order_count, 0)
            self.assertEqual(str(rel.cash.blocked), "0")

            # A release on the ORIGINAL service is durable for the next
            # restart too (snapshot save + event replay both cover it).
            asyncio.run(svc1.release_order_reservation("ord-1"))
            svc3 = make_service()
            svc3._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc3.recover())
            snap3 = asyncio.run(svc3.get_snapshot())
            self.assertEqual(snap3.pending_order_count, 0)
            self.assertEqual(str(snap3.cash.blocked), "0")
        finally:
            if prev_snap is not None:
                os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = prev_snap
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots WHERE portfolio_id=%s",
                    (self.pid,))
            conn.commit()
            conn.close()

    def test_rebuild_without_snapshot_restores_outstanding_reservation(self):
        """Snapshot-loss rebuild must replay reservation/release events too —
        dropping them would silently release capital that must stay blocked."""
        from decimal import Decimal
        from src.portfolio.config import PortfolioConfig
        from src.portfolio.contracts import PositionSide
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        from src.portfolio.service import PortfolioService

        def make_service():
            return PortfolioService(
                config=PortfolioConfig(
                    initial_capital=Decimal("50000"),
                    portfolio_id=self.pid,
                ),
                event_repo=PortfolioEventRepository(),
            )

        svc1 = make_service()
        asyncio.run(svc1.initialise(Decimal("50000")))
        asyncio.run(svc1.apply_fill(
            idempotency_key="fill-r1",
            instrument_token=1,
            instrument_symbol="AAA",
            side=PositionSide.LONG,
            quantity=5,
            price=Decimal("100"),
            fill_id="r1",
            filled_at=datetime.now(timezone.utc),
            order_id="r1",
        ))
        asyncio.run(svc1.apply_order_reservation("ord-a", Decimal("1000")))
        asyncio.run(svc1.apply_order_reservation("ord-b", Decimal("500")))
        asyncio.run(svc1.release_order_reservation("ord-b"))

        # Restart with NO snapshot repo (snapshot unavailable) → rebuild.
        svc2 = make_service()
        asyncio.run(svc2.recover())
        snap = asyncio.run(svc2.get_snapshot())
        self.assertEqual(snap.pending_order_count, 1,
                         "outstanding reservation dropped by rebuild")
        self.assertEqual(str(snap.cash.blocked), "1000")
        self.assertEqual(
            sorted(p.instrument_symbol for p in snap.open_positions),
            ["AAA"])

    def test_local_only_events_returned_after_durable_stream(self):
        """Events whose DB persist failed (local-only) must be returned
        after the durable stream and must not be filtered by comparing
        their per-process sequences against the DB serial cursor."""
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        repo = PortfolioEventRepository()
        asyncio.run(repo.append(self._event("d1")))
        asyncio.run(repo.append(self._event("d2")))
        durable = asyncio.run(repo.list_all(self.pid))
        cursor = durable[-1].sequence

        # Simulate a DB persist failure: append while writes are disabled.
        os.environ["PORTFOLIO_EVENT_DB_DISABLED"] = "1"
        try:
            local_evt = self._event("local-1")
            # Give it a small per-process sequence, far below the cursor.
            local_evt = local_evt.model_copy(update={"sequence": 1})
            asyncio.run(repo.append(local_evt))
        finally:
            os.environ.pop("PORTFOLIO_EVENT_DB_DISABLED", None)

        after = asyncio.run(
            repo.get_events_after_sequence(self.pid, cursor))
        self.assertEqual([e.idempotency_key for e in after], ["local-1"],
                         "local-only event lost against serial-id cursor")
        merged = asyncio.run(repo.list_all(self.pid))
        self.assertEqual([e.idempotency_key for e in merged],
                         ["d1", "d2", "local-1"])

    def test_schema_matches_canonical_orm_models(self):
        """The repositories' tables must satisfy the canonical ORM contract
        (src/database/models/portfolio_models.py): every ORM column exists
        with compatible nullability, so both persistence paths share one
        schema."""
        import psycopg2
        from src.database.models.portfolio_models import (
            PortfolioEventModel,
            PortfolioSnapshotModel,
            ReconciliationRunModel,
        )
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        from src.portfolio.repositories.reconciliation import (
            ReconciliationRepository,
        )
        # Force schema bootstrap/migration for both repositories.
        asyncio.run(PortfolioEventRepository().append(self._event("orm-1")))
        from src.portfolio.contracts import PortfolioReconciliationReport
        report = PortfolioReconciliationReport(
            portfolio_id=self.pid, dry_run=True, critical_count=0,
            warning_count=0, portfolio_ready=True,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        recon = ReconciliationRepository()
        asyncio.run(recon.save(report))

        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        try:
            def columns(table):
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT column_name, is_nullable FROM "
                        "information_schema.columns WHERE table_name=%s",
                        (table,))
                    return {r[0]: r[1] for r in cur.fetchall()}

            for model in (PortfolioEventModel, PortfolioSnapshotModel,
                          ReconciliationRunModel):
                cols = columns(model.__tablename__)
                self.assertTrue(cols, f"{model.__tablename__} missing")
                for col in model.__table__.columns:
                    self.assertIn(
                        col.name, cols,
                        f"{model.__tablename__}.{col.name} missing in DB")
            # Legacy repository-owned table must be gone.
            self.assertFalse(columns("portfolio_reconciliations"),
                             "legacy portfolio_reconciliations still exists")

            # Round-trip through the canonical tables (fresh repo instances
            # = cross-process read).
            fetched = asyncio.run(
                PortfolioEventRepository().list_all(self.pid))
            self.assertIn("orm-1", [e.idempotency_key for e in fetched])
            latest = asyncio.run(
                ReconciliationRepository().get_latest(self.pid))
            self.assertIsNotNone(latest)
            self.assertEqual(str(latest.run_id), str(report.run_id))
        finally:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM reconciliation_runs WHERE portfolio_id=%s",
                    (self.pid,))
            conn.commit()
            conn.close()

    def test_interleaved_concurrent_write_pins_cursor_below_unseen_event(self):
        """B durably writes id N, THEN A durably writes id N+1 and snapshots.
        A's cursor must stay BELOW N (contiguous incorporated prefix), so
        B's event is replayed on the next recovery — a max-of-own-writes
        cursor would leap to N+1 and skip B forever."""
        from decimal import Decimal
        from src.portfolio.config import PortfolioConfig
        from src.portfolio.contracts import PositionSide
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        from src.portfolio.repositories.portfolio_snapshot import (
            PortfolioSnapshotRepository,
        )
        from src.portfolio.service import PortfolioService

        prev_snap = os.environ.pop("PORTFOLIO_SNAPSHOT_DB_DISABLED", None)
        try:
            def make_service():
                return PortfolioService(
                    config=PortfolioConfig(
                        initial_capital=Decimal("50000"),
                        portfolio_id=self.pid,
                    ),
                    event_repo=PortfolioEventRepository(),
                )

            def fill(svc, symbol, tid, qty, price):
                asyncio.run(svc.apply_fill(
                    idempotency_key=f"fill-{tid}",
                    instrument_token=hash(symbol) % 100000,
                    instrument_symbol=symbol,
                    side=PositionSide.LONG,
                    quantity=qty,
                    price=Decimal(price),
                    fill_id=tid,
                    filled_at=datetime.now(timezone.utc),
                    order_id=tid,
                ))

            # Service A initialises (durable init event) — snapshot later.
            svc_a = make_service()
            svc_a._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc_a.initialise(Decimal("50000")))

            # Concurrent writer B durably inserts id N (unseen by A).
            from src.portfolio.contracts import (
                PortfolioEvent, PortfolioEventType,
            )
            b_event = PortfolioEvent(
                idempotency_key="fill-b",
                event_type=PortfolioEventType.FILL_RECEIVED,
                portfolio_id=self.pid,
                instrument_token=1,
                payload={"instrument_symbol": "BBB", "side": "BUY",
                         "quantity": 2, "price": "200", "fill_id": "b"},
            )
            asyncio.run(PortfolioEventRepository().append(b_event))

            # A durably writes id N+1 (its own fill) and snapshots.
            fill(svc_a, "AAA", "a1", 5, "100")
            asyncio.run(svc_a.create_snapshot())
            latest = asyncio.run(
                PortfolioSnapshotRepository().get_latest_valid(self.pid))
            b_id = asyncio.run(
                PortfolioEventRepository().list_all(self.pid))
            b_serial = next(e.sequence for e in b_id
                            if e.idempotency_key == "fill-b")
            self.assertTrue(latest.event_cursor is None
                            or latest.event_cursor < b_serial,
                            "cursor leapt past unseen concurrent event")

            # Next recovery must replay B's event.
            svc_c = make_service()
            svc_c._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc_c.recover())
            snap = asyncio.run(svc_c.get_snapshot())
            symbols = sorted(
                p.instrument_symbol for p in snap.open_positions)
            self.assertIn("BBB", symbols,
                          "concurrent writer's event lost on recovery")
            self.assertIn("AAA", symbols)
        finally:
            if prev_snap is not None:
                os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = prev_snap
            import psycopg2
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots WHERE portfolio_id=%s",
                    (self.pid,))
            conn.commit()
            conn.close()

    def test_gap_pinned_cursor_does_not_double_block_reservation(self):
        """Concurrent writer B creates an earlier durable event, so A's
        snapshot cursor is pinned BELOW it. A's own reservation event sits
        above the pinned cursor and is replayed on recovery — the restored
        reservation must be blocked exactly ONCE, never doubled."""
        from decimal import Decimal
        from src.portfolio.config import PortfolioConfig
        from src.portfolio.contracts import (
            PortfolioEvent, PortfolioEventType,
        )
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        from src.portfolio.repositories.portfolio_snapshot import (
            PortfolioSnapshotRepository,
        )
        from src.portfolio.service import PortfolioService

        prev_snap = os.environ.pop("PORTFOLIO_SNAPSHOT_DB_DISABLED", None)
        try:
            def make_service():
                return PortfolioService(
                    config=PortfolioConfig(
                        initial_capital=Decimal("50000"),
                        portfolio_id=self.pid,
                    ),
                    event_repo=PortfolioEventRepository(),
                )

            svc_a = make_service()
            svc_a._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc_a.initialise(Decimal("50000")))

            # Unseen concurrent event B (earlier durable id than A's next).
            asyncio.run(PortfolioEventRepository().append(PortfolioEvent(
                idempotency_key="fill-bx",
                event_type=PortfolioEventType.FILL_RECEIVED,
                portfolio_id=self.pid,
                instrument_token=1,
                payload={"instrument_symbol": "BBB", "side": "BUY",
                         "quantity": 1, "price": "100", "fill_id": "bx"},
            )))

            # A reserves (durable event above B) and snapshots — the
            # cursor is pinned below B, so the reservation event will be
            # in the replay window on recovery.
            asyncio.run(svc_a.apply_order_reservation(
                "ord-dbl", Decimal("1000")))
            asyncio.run(svc_a.create_snapshot())

            svc_r = make_service()
            svc_r._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc_r.recover())
            snap = asyncio.run(svc_r.get_snapshot())
            self.assertEqual(snap.pending_order_count, 1)
            self.assertEqual(str(snap.cash.blocked), "1000",
                             "reservation double-blocked on replay")
            # B's fill was picked up.
            self.assertIn("BBB", [
                p.instrument_symbol for p in snap.open_positions])
            # Releasing once fully unblocks — proves it was blocked once.
            rel = asyncio.run(svc_r.release_order_reservation("ord-dbl"))
            self.assertEqual(str(rel.cash.blocked), "0")
        finally:
            if prev_snap is not None:
                os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = prev_snap
            import psycopg2
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots WHERE portfolio_id=%s",
                    (self.pid,))
            conn.commit()
            conn.close()

    def test_rebuild_reservation_only_book_keeps_capital_blocked(self):
        """Snapshot-loss rebuild of a portfolio with a reservation but NO
        fills must still restore the reservation (not release the capital)."""
        from decimal import Decimal
        from src.portfolio.config import PortfolioConfig
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        from src.portfolio.service import PortfolioService

        def make_service():
            return PortfolioService(
                config=PortfolioConfig(
                    initial_capital=Decimal("50000"),
                    portfolio_id=self.pid,
                ),
                event_repo=PortfolioEventRepository(),
            )

        svc1 = make_service()
        asyncio.run(svc1.initialise(Decimal("50000")))
        asyncio.run(svc1.apply_order_reservation("ord-only", Decimal("750")))

        svc2 = make_service()  # restart, no snapshot at all
        asyncio.run(svc2.recover())
        snap = asyncio.run(svc2.get_snapshot())
        self.assertEqual(snap.pending_order_count, 1,
                         "reservation-only book lost on rebuild")
        self.assertEqual(str(snap.cash.blocked), "750")

    def test_local_only_event_cannot_advance_cursor_past_durable_rows(self):
        """Snapshot cursor N; recovery replays durable N+1 plus a local-only
        event with a much HIGHER local sequence; the next snapshot's cursor
        must not leap past durable rows — a durable N+2 committed by another
        writer must still be replayed on the following recovery."""
        import psycopg2
        from decimal import Decimal
        from src.portfolio.config import PortfolioConfig
        from src.portfolio.contracts import PositionSide
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        from src.portfolio.repositories.portfolio_snapshot import (
            PortfolioSnapshotRepository,
        )
        from src.portfolio.service import PortfolioService

        prev_snap = os.environ.pop("PORTFOLIO_SNAPSHOT_DB_DISABLED", None)
        try:
            def make_service():
                return PortfolioService(
                    config=PortfolioConfig(
                        initial_capital=Decimal("50000"),
                        portfolio_id=self.pid,
                    ),
                    event_repo=PortfolioEventRepository(),
                )

            def fill_event(tid, symbol, qty, price):
                from src.portfolio.contracts import (
                    PortfolioEvent, PortfolioEventType,
                )
                return PortfolioEvent(
                    idempotency_key=f"fill-{tid}",
                    event_type=PortfolioEventType.FILL_RECEIVED,
                    portfolio_id=self.pid,
                    instrument_token=hash(symbol) % 100000,
                    payload={
                        "instrument_symbol": symbol, "side": "BUY",
                        "quantity": qty, "price": price, "fill_id": tid,
                    },
                )

            # Process 1: snapshot with cursor N.
            svc1 = make_service()
            svc1._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc1.initialise(Decimal("50000")))
            asyncio.run(svc1.create_snapshot())

            # Durable N+1 from another writer.
            asyncio.run(PortfolioEventRepository().append(
                fill_event("n1", "AAA", 5, "100")))

            # Process 2 recovers (replays N+1) while holding a LOCAL-ONLY
            # event whose per-process sequence is far beyond any serial id.
            svc2 = make_service()
            svc2._snapshot_repo = PortfolioSnapshotRepository()
            local = fill_event("local-hi", "LLL", 1, "10").model_copy(
                update={"sequence": 10_000_000})
            os.environ["PORTFOLIO_EVENT_DB_DISABLED"] = "1"
            try:
                asyncio.run(svc2._event_repo.append(local))
            finally:
                os.environ.pop("PORTFOLIO_EVENT_DB_DISABLED", None)
            asyncio.run(svc2.recover())
            asyncio.run(svc2.create_snapshot())
            latest = asyncio.run(
                PortfolioSnapshotRepository().get_latest_valid(self.pid))
            self.assertLess(latest.event_cursor, 1_000_000,
                            "cursor advanced from a local-only sequence")

            # Durable N+2 from another writer AFTER that snapshot.
            asyncio.run(PortfolioEventRepository().append(
                fill_event("n2", "BBB", 2, "200")))

            # Next recovery must replay N+2.
            svc3 = make_service()
            svc3._snapshot_repo = PortfolioSnapshotRepository()
            asyncio.run(svc3.recover())
            snap = asyncio.run(svc3.get_snapshot())
            symbols = sorted(p.instrument_symbol for p in snap.open_positions)
            self.assertIn("BBB", symbols,
                          "durable event skipped: cursor leapt past it")
        finally:
            if prev_snap is not None:
                os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = prev_snap
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots WHERE portfolio_id=%s",
                    (self.pid,))
            conn.commit()
            conn.close()

    def test_snapshot_cursor_excludes_concurrent_writers_event(self):
        """An event committed by a SECOND service while the first persists
        its snapshot must stay above the snapshot's cursor and be replayed
        on recovery — the cursor reflects only incorporated events."""
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        repo_a = PortfolioEventRepository()   # process A
        repo_b = PortfolioEventRepository()   # concurrent process B
        asyncio.run(repo_a.append(self._event("a1")))
        # B commits between A's last incorporated event and A's snapshot.
        asyncio.run(repo_b.append(self._event("b1")))

        cursor_a = repo_a.incorporated_cursor(self.pid)
        self.assertIsNotNone(cursor_a)
        # A's cursor must NOT cover B's event.
        after = asyncio.run(
            PortfolioEventRepository().get_events_after_sequence(
                self.pid, cursor_a))
        self.assertEqual([e.idempotency_key for e in after], ["b1"])

    def test_prune_is_cursor_based_and_keeps_backdated_post_cursor_events(self):
        """A later process's first write triggers pruning; an old-timestamped
        event ABOVE the replay-baseline cursor must survive."""
        import psycopg2
        from src.portfolio.repositories.portfolio_event import (
            PortfolioEventRepository,
        )
        old = datetime.now(timezone.utc) - timedelta(days=90)
        writer = PortfolioEventRepository()
        # Below-cursor, past-window event: prunable.
        asyncio.run(writer.append(self._event("pre", old)))
        baseline = writer.incorporated_cursor(self.pid)
        # Simulate a persisted snapshot whose cursor covers only "pre".
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO portfolio_snapshots (
                    snapshot_id, portfolio_id, status, version, paper_mode,
                    cash_available, cash_blocked, cash_total,
                    buying_power_net, equity, open_position_count,
                    pending_order_count, realised_pnl, unrealised_pnl,
                    daily_pnl, drawdown, snapshot_payload, checksum,
                    snapshotted_at, event_cursor
                ) VALUES (%s,%s,'ready',1,true,'0','0','0','0','0',0,0,
                          '0','0','0','0',NULL,NULL,NOW(),%s)
                """,
                (str(uuid.uuid4()), self.pid, baseline),
            )
        conn.commit()
        try:
            # Post-cursor event with a BACKDATED occurrence time.
            asyncio.run(writer.append(self._event("post-backdated", old)))
            # Fresh process (fresh prune guard) writes → prune runs.
            PortfolioEventRepository._PRUNED_PIDS.discard(self.pid)
            asyncio.run(PortfolioEventRepository().append(self._event("new")))

            events = asyncio.run(PortfolioEventRepository().list_all(self.pid))
            keys = sorted(e.idempotency_key for e in events)
            self.assertNotIn("pre", keys, "below-cursor aged event kept")
            self.assertIn("post-backdated", keys,
                          "replay-required backdated event was pruned")
            self.assertIn("new", keys)
        finally:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots WHERE portfolio_id=%s",
                    (self.pid,))
            conn.commit()
            conn.close()

    def test_reconciliation_reports_durable_across_processes(self):
        from src.portfolio.repositories.reconciliation import (
            ReconciliationRepository,
        )
        from src.portfolio.contracts import PortfolioReconciliationReport
        writer = ReconciliationRepository()
        asyncio.run(writer.save(PortfolioReconciliationReport(
            portfolio_id=self.pid, critical_count=3,
            completed_at=datetime.now(timezone.utc))))

        reader = ReconciliationRepository()
        latest = asyncio.run(reader.get_latest(self.pid))
        self.assertIsNotNone(latest)
        self.assertEqual(latest.critical_count, 3)
        self.assertEqual(asyncio.run(reader.count_unresolved(self.pid)), 3)


if __name__ == "__main__":
    unittest.main()
