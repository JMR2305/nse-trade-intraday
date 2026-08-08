"""Task: Portfolio page must not show stale positions after an API-server
restart.

Verifies the snapshot builder's source ordering:
1. PortfolioService (Postgres-backed snapshot repo) is the primary source.
2. If the service is unavailable, the endpoint gracefully falls back to the
   canonical/legacy paths (no regression).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = "1"

_PY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

import portfolio_snapshot as ps  # noqa: E402


class TestServiceSourceFallback(unittest.TestCase):
    def test_falls_back_when_service_unavailable(self):
        with patch.object(
            ps, "_positions_from_portfolio_service",
            side_effect=RuntimeError("service down"),
        ):
            snap = ps.get_portfolio_snapshot()
        # Endpoint must still return a complete snapshot payload.
        self.assertIn("open_positions", snap)
        self.assertIn("equity", snap)
        self.assertNotEqual(snap.get("position_source"), "portfolio_service")

    def test_valid_empty_service_book_does_not_fall_back(self):
        # A service that successfully reports ZERO positions is authoritative;
        # stale canonical/legacy sources must not repopulate the page.
        with patch.object(
            ps, "_positions_from_portfolio_service",
            return_value=([], {"cash": 50000.0, "invested_cost": 0.0,
                               "unrealised_pnl": 0.0, "initial_capital": 50000.0}),
        ):
            snap = ps.get_portfolio_snapshot()
        self.assertEqual(snap["open_positions"], [])
        self.assertEqual(snap["position_source"], "portfolio_service")
        # Aggregates must come from the same (service) source
        self.assertEqual(snap["cash"], 50000.0)
        self.assertEqual(snap["invested_value"], 0.0)

    def test_all_corrupt_db_rows_raise_corrupt_snapshot_error(self):
        import asyncio
        from src.portfolio.repositories import portfolio_snapshot as repo_mod
        from src.portfolio.exceptions import CorruptSnapshotError
        repo = repo_mod.PortfolioSnapshotRepository()
        with patch.object(repo_mod, "_db_available", return_value=True), \
             patch.object(repo, "_db_fetch", return_value=([], 3)):
            with self.assertRaises(CorruptSnapshotError):
                asyncio.run(repo.get_latest_valid("default"))

    def test_service_positions_win_when_available(self):
        rows = [{
            "symbol": "TESTSYM", "quantity": 1, "avg_entry_price": 100.0,
            "last_price": 101.0, "market_value": 101.0, "unrealised_pnl": 1.0,
            "unrealised_pnl_pct": 1.0, "side": "LONG", "strategy_id": None,
            "sector": None, "opened_at": None,
            "mark_source": "portfolio_service", "status": "OPEN",
        }]
        aggs = {"cash": 49899.0, "invested_cost": 100.0,
                "unrealised_pnl": 1.0, "initial_capital": 50000.0}
        with patch.object(
            ps, "_positions_from_portfolio_service", return_value=(rows, aggs)
        ):
            snap = ps.get_portfolio_snapshot()
        self.assertEqual(snap["position_source"], "portfolio_service")
        self.assertEqual(snap["cash"], 49899.0)
        self.assertEqual(snap["invested_value"], 100.0)
        self.assertEqual(snap["unrealised_pnl"], 1.0)
        self.assertEqual(
            [p["symbol"] for p in snap["open_positions"]], ["TESTSYM"]
        )


class TestRepositoryDbToggle(unittest.TestCase):
    def test_db_disabled_flag_respected(self):
        from src.portfolio.repositories import portfolio_snapshot as repo
        with patch.dict(os.environ, {
            "PORTFOLIO_SNAPSHOT_DB_DISABLED": "1",
            "DATABASE_URL": "postgres://example/db",
        }):
            self.assertFalse(repo._db_available())

    def test_db_enabled_with_database_url(self):
        from src.portfolio.repositories import portfolio_snapshot as repo
        env = {"DATABASE_URL": "postgres://example/db"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("PORTFOLIO_SNAPSHOT_DB_DISABLED", None)
            self.assertTrue(repo._db_available())
        os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = "1"


if __name__ == "__main__":
    unittest.main()
