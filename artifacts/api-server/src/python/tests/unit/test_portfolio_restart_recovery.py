"""Integration tests — restart recovery from the Postgres-backed
portfolio_snapshots table.

These tests use the real development database (isolated under a unique
portfolio_id, cleaned up in tearDown).  Skipped when DATABASE_URL is unset.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

_PY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

HAVE_DB = bool(os.environ.get("DATABASE_URL"))


def _build_service(pid: str):
    from src.portfolio.config import PortfolioConfig
    from src.portfolio.service import PortfolioService
    from src.portfolio.repositories.portfolio_snapshot import (
        PortfolioSnapshotRepository,
    )
    cfg = PortfolioConfig(portfolio_id=pid, initial_capital=Decimal("50000"),
                          min_order_value=Decimal("50"))
    return PortfolioService(config=cfg,
                            snapshot_repo=PortfolioSnapshotRepository())


@unittest.skipUnless(HAVE_DB, "DATABASE_URL not configured")
class TestRestartRecovery(unittest.TestCase):
    def setUp(self):
        self.pid = f"it-{uuid.uuid4().hex[:12]}"
        # DB-backed integration test — temporarily lift the hermetic
        # kill-switch other suites set, restoring it afterwards.
        self._prev_disabled = os.environ.pop(
            "PORTFOLIO_SNAPSHOT_DB_DISABLED", None)

    def tearDown(self):
        if self._prev_disabled is not None:
            os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = self._prev_disabled
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM portfolio_snapshots WHERE portfolio_id = %s",
                (self.pid,),
            )
        conn.commit()
        conn.close()

    def _fill(self, svc, symbol: str, qty: int, price: str, trade_id: str):
        from src.portfolio.contracts import PositionSide
        asyncio.run(svc.apply_fill(
            idempotency_key=f"fill-{trade_id}",
            instrument_token=abs(hash(symbol)) % 10_000_000,
            instrument_symbol=symbol,
            side=PositionSide.LONG,
            quantity=qty,
            price=Decimal(price),
            fill_id=trade_id,
            filled_at=datetime.now(timezone.utc),
            order_id=trade_id,
        ))

    def test_fill_after_snapshot_survives_restart(self):
        # Process 1: initialise, snapshot, then a LATER fill + snapshot.
        svc1 = _build_service(self.pid)
        asyncio.run(svc1.initialise())
        asyncio.run(svc1.create_snapshot())
        self._fill(svc1, "RELIANCE", 5, "2500", f"{self.pid}-t1")
        asyncio.run(svc1.create_snapshot())  # what the bridge persist hook does

        # Process 2 (simulated restart): fresh service, recover from DB.
        svc2 = _build_service(self.pid)
        recovered = asyncio.run(svc2.recover(portfolio_id=self.pid))
        self.assertEqual(len(recovered.open_positions), 1)
        pos = recovered.open_positions[0]
        self.assertEqual(pos.instrument_symbol, "RELIANCE")
        self.assertEqual(pos.open_quantity, 5)
        # Cash reflects the post-fill state, not the initial snapshot.
        self.assertEqual(recovered.cash.total, Decimal("50000") - Decimal("12500"))

    def test_recovery_selects_latest_write_despite_timestamp_regression(self):
        # A snapshot written LATER but carrying an OLDER snapshotted_at
        # (create_snapshot reuses the state's last-update timestamp) must
        # still win: durable ordering is write order (serial id), not
        # timestamp.
        import psycopg2
        from src.portfolio.repositories.portfolio_snapshot import (
            PortfolioSnapshotRepository,
        )
        svc1 = _build_service(self.pid)
        asyncio.run(svc1.initialise())
        self._fill(svc1, "TCS", 2, "3000", f"{self.pid}-t1")
        asyncio.run(svc1.create_snapshot())
        self._fill(svc1, "INFY", 3, "1500", f"{self.pid}-t2")
        asyncio.run(svc1.create_snapshot())

        # Force a timestamp regression on the newest written row.
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE portfolio_snapshots
                SET snapshotted_at = snapshotted_at - INTERVAL '1 hour'
                WHERE portfolio_id = %s
                  AND id = (SELECT MAX(id) FROM portfolio_snapshots
                            WHERE portfolio_id = %s)
                """,
                (self.pid, self.pid),
            )
        conn.commit()
        conn.close()

        repo = PortfolioSnapshotRepository()
        latest = asyncio.run(repo.get_latest_valid(self.pid))
        self.assertEqual(
            sorted(p.instrument_symbol for p in latest.open_positions),
            ["INFY", "TCS"],
        )

    def test_bridge_startup_recovers_latest_fill_after_restart(self):
        # Full bridge path: process 1 seeds + fills via the bridge hooks;
        # process 2 (simulated restart) hits a canonical-ledger outage and
        # must recover the latest fill from Postgres.
        import portfolio_bridge as pb
        import psycopg2
        from unittest.mock import patch

        # The real bridge (and its unpatched final restore) writes snapshots
        # for the 'default' portfolio — record a watermark so every row this
        # test adds under 'default' is removed afterwards. Leaving fixture
        # books in the store would make the next real process start noisy
        # (recover → critical discrepancies → re-seed).
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(id),0) FROM portfolio_snapshots")
            watermark = cur.fetchone()[0]
        conn.close()

        def fake_build():
            from src.portfolio.repositories.portfolio_snapshot import (
                PortfolioSnapshotRepository,
            )
            return _build_service(self.pid), PortfolioSnapshotRepository()

        canon = {"initial_capital": 50000.0, "positions": [
            {"symbol": "RELIANCE", "quantity": 5, "avg_price": 2500.0,
             "trade_id": f"{self.pid}-seed", "mark_price": 2510.0},
        ]}
        with patch.object(pb, "_build_service", side_effect=fake_build), \
             patch.object(pb, "_canonical_state", return_value=canon), \
             patch.object(pb, "_broker_like_snapshot", return_value={"positions": [], "cash": 50000.0}), \
             patch.object(pb, "is_enabled", return_value=True):
            self.assertTrue(pb.startup(force=True))
            # A fill AFTER the startup snapshot (bridge persists it too).
            pb.on_fill("INFY", "BUY", 3, 1500.0, f"{self.pid}-late")

        # Simulated restart: canonical ledger now unreadable.
        def boom():
            raise RuntimeError("ledger down (simulated)")

        try:
            with patch.object(pb, "_build_service", side_effect=fake_build), \
                 patch.object(pb, "_canonical_state", side_effect=boom), \
                 patch.object(pb, "is_enabled", return_value=True):
                self.assertTrue(pb.startup(force=True))
                snap = pb._run(pb.get_service().get_snapshot())
            symbols = sorted(p.instrument_symbol for p in snap.open_positions)
            self.assertEqual(symbols, ["INFY", "RELIANCE"])
        finally:
            # Remove every 'default' snapshot this test wrote, then restore
            # real bridge state (which re-persists a clean canonical book).
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots "
                    "WHERE portfolio_id = 'default' AND id > %s",
                    (watermark,),
                )
            conn.commit()
            conn.close()
            pb.startup(force=True)  # restore real bridge state for this process

    def test_all_corrupt_rows_raise_and_recovery_survives(self):
        from src.portfolio.exceptions import CorruptSnapshotError
        from src.portfolio.repositories.portfolio_snapshot import (
            PortfolioSnapshotRepository,
        )
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO portfolio_snapshots (
                    snapshot_id, portfolio_id, status, version, paper_mode,
                    cash_available, cash_blocked, cash_total,
                    buying_power_net, equity, snapshot_payload, snapshotted_at
                ) VALUES (%s,%s,'READY',3,TRUE,0,0,0,0,0,%s,NOW())
                """,
                (str(uuid.uuid4()), self.pid, json.dumps({"garbage": True})),
            )
        conn.commit()
        conn.close()

        repo = PortfolioSnapshotRepository()
        with self.assertRaises(CorruptSnapshotError):
            asyncio.run(repo.get_latest_valid(self.pid))

        # recover() must survive the corruption (alert + fall through to
        # fresh initialisation), never crash the bridge startup.
        alerts = []
        svc = _build_service(self.pid)
        svc._alert_callback = lambda kind, payload: alerts.append(kind)
        recovered = asyncio.run(svc.recover(portfolio_id=self.pid))
        self.assertEqual(len(recovered.open_positions), 0)
        self.assertIn("CORRUPT_SNAPSHOT", alerts)


if __name__ == "__main__":
    unittest.main()
