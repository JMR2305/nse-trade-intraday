"""
test_perf_cache_invalidation.py — Task 168

Confirm that the performance analytics cache is cleared immediately when
portfolio_store.save_state() is called (i.e. when a new paper trade is
recorded), not just after the 30-second TTL expires.

Run: python -m pytest portfolio_performance/test_perf_cache_invalidation.py -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, call

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_DIR = os.path.dirname(_HERE)
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)


class TestPerfCacheInvalidatedOnSave(unittest.TestCase):
    """
    _clear_perf_cache() must be called exactly once by save_state() after
    every successful portfolio write — both in DB mode and in local-dev
    (no-DATABASE_URL) mode.
    """

    def _make_state(self):
        return {
            "cash": 49_000.0,
            "positions": {},
            "trades": [],
            "pnl_history": [],
        }

    # ── DB-mode path ──────────────────────────────────────────────────────────

    def test_cache_cleared_after_db_write(self):
        """save_state() calls _clear_perf_cache() once after a successful DB commit."""
        import portfolio_store as ps

        clear_calls = []

        def _fake_clear():
            clear_calls.append(1)

        with patch.object(ps, "db_available", return_value=True), \
             patch.object(ps, "_connect") as mock_connect, \
             patch.object(ps, "_ensure_schema"), \
             patch.object(ps, "_upsert_portfolio_row"), \
             patch.object(ps, "_insert_new_trades"), \
             patch.object(ps, "_write_json_fallback"), \
             patch.object(ps, "_invalidate_perf_cache", side_effect=_fake_clear):

            mock_conn = mock_connect.return_value.__enter__ = lambda s: s
            mock_connect.return_value.commit = lambda: None
            mock_connect.return_value.rollback = lambda: None
            mock_connect.return_value.close = lambda: None
            mock_connect.return_value.__exit__ = lambda s, *a: None

            ps.save_state(self._make_state())

        self.assertEqual(len(clear_calls), 1,
            "Expected _invalidate_perf_cache() to be called exactly once after DB write, "
            f"but it was called {len(clear_calls)} time(s).")

    # ── Local-dev (no-DB) path ────────────────────────────────────────────────

    def test_cache_cleared_after_local_write(self):
        """save_state() calls _clear_perf_cache() once in local-dev mode too."""
        import portfolio_store as ps

        clear_calls = []

        def _fake_clear():
            clear_calls.append(1)

        with patch.object(ps, "db_available", return_value=False), \
             patch.object(ps, "_write_json_fallback"), \
             patch.object(ps, "_invalidate_perf_cache", side_effect=_fake_clear):

            ps.save_state(self._make_state())

        self.assertEqual(len(clear_calls), 1,
            "Expected _invalidate_perf_cache() to be called once in local-dev mode, "
            f"but it was called {len(clear_calls)} time(s).")

    # ── Cache is NOT cleared on DB failure ────────────────────────────────────

    def test_cache_not_cleared_when_db_write_fails(self):
        """If the DB commit raises, _invalidate_perf_cache() must NOT be called
        (the trade was not persisted so there is nothing new to reflect)."""
        import portfolio_store as ps

        clear_calls = []

        def _fake_clear():
            clear_calls.append(1)

        def _boom(*a, **kw):
            raise RuntimeError("DB write failed")

        with patch.object(ps, "db_available", return_value=True), \
             patch.object(ps, "_connect") as mock_connect, \
             patch.object(ps, "_ensure_schema"), \
             patch.object(ps, "_upsert_portfolio_row", side_effect=_boom), \
             patch.object(ps, "_write_json_fallback"), \
             patch.object(ps, "_invalidate_perf_cache", side_effect=_fake_clear):

            mock_conn = mock_connect.return_value
            mock_conn.commit = lambda: None
            mock_conn.rollback = lambda: None
            mock_conn.close = lambda: None

            with self.assertRaises(RuntimeError):
                ps.save_state(self._make_state())

        self.assertEqual(len(clear_calls), 0,
            "_invalidate_perf_cache() must not be called when the DB write fails.")

    # ── _invalidate_perf_cache delegates to _clear_perf_cache ────────────────

    def test_invalidate_calls_engine_clear(self):
        """_invalidate_perf_cache() must import and call _clear_perf_cache()
        from performance_engine when that module is importable."""
        import portfolio_store as ps

        engine_clears = []

        with patch.dict("sys.modules", {}):
            import importlib

            # Build a stub performance_engine with a spy on _clear_perf_cache
            import types
            stub_engine = types.ModuleType(
                "portfolio_performance.performance_engine")

            def _stub_clear():
                engine_clears.append(1)

            stub_engine._clear_perf_cache = _stub_clear

            with patch.dict("sys.modules",
                            {"portfolio_performance.performance_engine": stub_engine}):
                ps._invalidate_perf_cache()

        self.assertEqual(len(engine_clears), 1,
            "_invalidate_perf_cache() must delegate to "
            "performance_engine._clear_perf_cache().")

    # ── _invalidate_perf_cache is fault-tolerant ──────────────────────────────

    def test_invalidate_survives_import_error(self):
        """If performance_engine is unavailable, _invalidate_perf_cache()
        must not raise — it must be silently swallowed."""
        import portfolio_store as ps

        import sys
        saved = sys.modules.pop("portfolio_performance.performance_engine", None)
        try:
            with patch.dict("sys.modules",
                            {"portfolio_performance.performance_engine": None}):
                # Should not raise even if the import fails
                ps._invalidate_perf_cache()
        finally:
            if saved is not None:
                sys.modules["portfolio_performance.performance_engine"] = saved


if __name__ == "__main__":
    unittest.main()
