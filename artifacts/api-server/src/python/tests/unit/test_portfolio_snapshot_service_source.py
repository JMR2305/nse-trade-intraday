"""RTV-1: PortfolioLive financial truth is the canonical Phase-20 portfolio."""
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


class TestCanonicalSource(unittest.TestCase):
    def test_canonical_snapshot_does_not_depend_on_service(self):
        with patch.object(ps, "_positions_from_portfolio_service",
                          side_effect=AssertionError("service must not be read")):
            snap = ps.get_portfolio_snapshot()
        self.assertIn("open_positions", snap)
        self.assertIn("equity", snap)
        self.assertNotEqual(snap.get("position_source"), "portfolio_service")

    def test_all_corrupt_db_rows_raise_corrupt_snapshot_error(self):
        import asyncio
        from src.portfolio.repositories import portfolio_snapshot as repo_mod
        from src.portfolio.exceptions import CorruptSnapshotError
        repo = repo_mod.PortfolioSnapshotRepository()
        with patch.object(repo_mod, "_db_available", return_value=True), \
             patch.object(repo, "_db_fetch", return_value=([], 3)):
            with self.assertRaises(CorruptSnapshotError):
                asyncio.run(repo.get_latest_valid("default"))

    def test_canonical_book_wins_over_independently_capitalized_service(self):
        import canonical_portfolio
        canonical = {
            "source": "phase20_ledger",
            "initial_capital": 100_000.0, "cash": 89_000.0,
            "invested_value": 10_000.0, "unrealized_pnl": 1_000.0,
            "equity": 101_000.0, "positions": [{
                "symbol": "CANON", "quantity": 100, "avg_price": 100.0,
                "mark_price": 110.0, "market_value": 11_000.0,
                "unrealized_pnl": 1_000.0, "status": "OPEN",
                "strategy_id": "test", "sector": "TECH", "opened_at": None,
                "mark_source": "scan",
            }],
        }
        # This deliberately contradictory service book must never be observed.
        with patch.object(canonical_portfolio, "build_canonical_portfolio",
                          return_value=canonical), \
             patch.object(ps, "_positions_from_portfolio_service",
                          side_effect=AssertionError("service must not be read")):
            snap = ps.get_portfolio_snapshot()
        self.assertEqual(snap["source"], "phase20_ledger")
        self.assertEqual(snap["initial_capital"], 100_000.0)
        self.assertEqual(snap["cash"], 89_000.0)
        self.assertEqual(snap["invested_value"], 10_000.0)
        self.assertEqual(snap["current_value"], 11_000.0)
        self.assertEqual(snap["equity"], 101_000.0)
        self.assertEqual(snap["total_pnl"], 1_000.0)
        self.assertEqual(snap["utilisation_pct"], round(11_000 / 101_000 * 100, 2))
        self.assertEqual(snap["largest_position"]["symbol"], "CANON")
        self.assertTrue(snap["calculated_at"])


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
