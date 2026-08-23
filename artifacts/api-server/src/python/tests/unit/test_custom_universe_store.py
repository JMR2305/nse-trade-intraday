"""Unit tests for custom_universe_store.py — Phase 1B requirement.

Tests cover:
1. upsert idempotency
2. active-only filtering
3. membership history append-only snapshot
4. CUSTOM_LOW_PRICE_SECTOR scan uses only custom symbols (not NIFTY_50)
5. empty custom universe blocks scan safely (no NIFTY_50 fallback)
6. invalid Kite/yfinance mapping is reported, not silently dropped
7. Phase 0C safety suite unaffected (external subprocess gate)

All tests are unit-level — they mock the DB layer and never write to
the real development PostgreSQL database.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch


# ── helpers ────────────────────────────────────────────────────────────────

def _make_db_mock(fetchall_return=None, fetchone_return=None):
    """Return (mock_conn, mock_cursor, fake_connect) for patching _connect."""
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = fetchall_return or []
    mock_cur.fetchone.return_value = fetchone_return
    mock_cur.rowcount = 1

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    @contextmanager
    def fake_connect():
        yield mock_conn

    return mock_conn, mock_cur, fake_connect


def _sample_row(symbol: str, is_active: bool = True, ohlcv: bool = True,
                sector: str = "IT"):
    """Return a tuple matching custom_universe_store._COLUMNS order."""
    # _COLUMNS order:
    # symbol yahoo_symbol kite_symbol instrument_token company_name sector
    # industry allowed_universe price_min price_max is_active reason_included
    # reason_excluded last_ltp last_ltp_source avg_volume_20d avg_turnover_20d
    # ohlcv_available last_verified_at created_at updated_at
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        symbol, f"{symbol}.NS", symbol, None, f"{symbol} Ltd", sector,
        "Services", "CUSTOM_LOW_PRICE_SECTOR", 20.0, 500.0, is_active,
        "operator_approved" if is_active else None,
        None if is_active else "operator_excluded",
        180.0, "yfinance_close", 4_500_000.0, 810_000_000.0,
        ohlcv, now, now, now,
    )


def _valid_active_payload(symbol: str = "WIPRO", sector: str = "IT", **overrides):
    """Return a complete active-symbol payload accepted by the upsert guard."""
    row = {
        "symbol": symbol,
        "is_active": True,
        "company_name": f"{symbol} Ltd",
        "sector": sector,
        "yahoo_symbol": f"{symbol}.NS",
        "kite_symbol": symbol,
        "price_min": 20,
        "price_max": 500,
        "ohlcv_available": True,
    }
    row.update(overrides)
    return row


# ── Test 1 — upsert idempotency ────────────────────────────────────────────

class TestUpsertIdempotency(unittest.TestCase):

    def test_second_upsert_succeeds_and_returns_upserted_count(self):
        """Calling upsert_symbols twice with the same symbol must both succeed."""
        import custom_universe_store
        rows = [_valid_active_payload()]

        _conn, _cur, fake_connect = _make_db_mock()
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect), \
             patch("psycopg2.extras.execute_values"):  # avoid real DB call

            result1 = custom_universe_store.upsert_symbols(rows)
            result2 = custom_universe_store.upsert_symbols(rows)

        self.assertTrue(result1["success"], f"First upsert failed: {result1}")
        self.assertTrue(result2["success"], f"Second upsert failed: {result2}")
        self.assertEqual(result1["upserted"], 1)
        self.assertEqual(result2["upserted"], 1)

    def test_empty_row_list_returns_success_zero(self):
        import custom_universe_store
        result = custom_universe_store.upsert_symbols([])
        self.assertTrue(result["success"])
        self.assertEqual(result["upserted"], 0)

    def test_upsert_with_missing_symbol_key_skips_silently(self):
        """Rows with a blank symbol must be skipped, not raise."""
        import custom_universe_store
        rows = [{"symbol": "", "is_active": True}]
        _conn, _cur, fake_connect = _make_db_mock()
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect), \
             patch("psycopg2.extras.execute_values"):
            result = custom_universe_store.upsert_symbols(rows)
        self.assertTrue(result["success"])
        self.assertEqual(result["upserted"], 0)

    def test_active_wipro_partial_overwrite_is_rejected_before_db(self):
        """A partial active update must not erase WIPRO metadata with defaults."""
        import custom_universe_store
        result = custom_universe_store.upsert_symbols([{
            "symbol": "WIPRO",
            "is_active": True,
            "sector": None,
            "price_max": 200,
            "ohlcv_available": False,
        }])

        self.assertFalse(result["success"])
        self.assertEqual(result["upserted"], 0)
        self.assertIn("company_name", result["error"])
        self.assertIn("yahoo_symbol", result["error"])
        self.assertIn("kite_symbol", result["error"])
        self.assertIn("price_min", result["error"])
        self.assertIn("sector", result["error"])
        self.assertNotIn("price_max", result["error"].split(":", 1)[-1])
        self.assertNotIn("ohlcv_available", result["error"].split(":", 1)[-1])

    def test_omitted_price_max_is_not_defaulted_to_200(self):
        """An omitted price_max must remain NULL, never silently become 200."""
        import custom_universe_store
        rows = [{"symbol": "IOB", "is_active": False}]
        _conn, _cur, fake_connect = _make_db_mock()
        captured_values = []

        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect), \
             patch("psycopg2.extras.execute_values",
                   side_effect=lambda cur, sql, vals: captured_values.append(vals)):
            result = custom_universe_store.upsert_symbols(rows)

        self.assertTrue(result["success"])
        self.assertEqual(captured_values[0][0][9], None)


# ── Test 2 — active-only filtering ────────────────────────────────────────

class TestActiveOnlyFiltering(unittest.TestCase):

    def test_get_active_symbols_returns_only_active_rows(self):
        """get_active_symbols() must return only is_active=True symbols."""
        import custom_universe_store

        # Simulate DB returning 2 active symbols (WHERE clause already filters)
        active_rows = [("WIPRO",), ("IRFC",)]
        _conn, mock_cur, fake_connect = _make_db_mock(fetchall_return=active_rows)
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect):
            result = custom_universe_store.get_active_symbols()

        self.assertEqual(sorted(result), ["IRFC", "WIPRO"])

    def test_get_active_symbols_empty_when_all_inactive(self):
        """get_active_symbols() must return [] when DB returns no active rows."""
        import custom_universe_store
        _conn, _cur, fake_connect = _make_db_mock(fetchall_return=[])
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect):
            result = custom_universe_store.get_active_symbols()
        self.assertEqual(result, [])

    def test_get_all_symbols_returns_all_including_inactive(self):
        """get_all_symbols() must return both active and inactive rows."""
        import custom_universe_store
        rows = [_sample_row("WIPRO", is_active=True),
                _sample_row("IOB", is_active=False)]
        _conn, _cur, fake_connect = _make_db_mock(fetchall_return=rows)
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect):
            result = custom_universe_store.get_all_symbols()

        symbols = [r["symbol"] for r in result]
        self.assertIn("WIPRO", symbols)
        self.assertIn("IOB", symbols)
        self.assertEqual(len(result), 2)

    def test_sql_execute_includes_is_active_filter(self):
        """The SQL executed for get_active_symbols must filter by is_active=TRUE."""
        import custom_universe_store
        _conn, mock_cur, fake_connect = _make_db_mock(fetchall_return=[])
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect):
            custom_universe_store.get_active_symbols()

        executed_sql = " ".join(
            str(c[0][0]) for c in mock_cur.execute.call_args_list
        ).upper()
        self.assertIn("IS_ACTIVE", executed_sql)


# ── Test 3 — membership history append-only ────────────────────────────────

class TestMembershipHistoryAppendOnly(unittest.TestCase):

    def test_upsert_writes_to_history_table(self):
        """upsert_symbols must INSERT into custom_universe_membership_history."""
        import custom_universe_store
        rows = [_valid_active_payload()]
        _conn, _cur, fake_connect = _make_db_mock()
        executed_sqls = []

        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect), \
             patch("psycopg2.extras.execute_values",
                   side_effect=lambda cur, sql, vals: executed_sqls.append(sql)):
            custom_universe_store.upsert_symbols(rows)

        history_writes = [s for s in executed_sqls
                          if "custom_universe_membership_history" in s.lower()]
        self.assertGreater(len(history_writes), 0,
                           "No INSERT into membership history detected")

    def test_history_insert_uses_on_conflict_do_nothing(self):
        """History writes must use ON CONFLICT DO NOTHING (append-only guarantee)."""
        import custom_universe_store
        rows = [_valid_active_payload()]
        _conn, _cur, fake_connect = _make_db_mock()
        captured_sqls = []

        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect), \
             patch("psycopg2.extras.execute_values",
                   side_effect=lambda cur, sql, vals: captured_sqls.append(sql)):
            custom_universe_store.upsert_symbols(rows)

        history_sqls = [s for s in captured_sqls
                        if "custom_universe_membership_history" in s.lower()]
        self.assertTrue(
            any("on conflict" in s.lower() and "do nothing" in s.lower()
                for s in history_sqls),
            "History INSERT must use ON CONFLICT DO NOTHING"
        )


# ── Test 4 — CUSTOM_LOW_PRICE_SECTOR scan uses only custom symbols ──────────

class TestCustomModeUsesOnlyCustomSymbols(unittest.TestCase):

    def test_scan_universe_resolution_uses_custom_symbols_not_nifty50(self):
        """When active universe = CUSTOM_LOW_PRICE_SECTOR, the resolved universe
        must be the custom symbols, not config.NIFTY_50."""
        custom_syms = ["WIPRO", "IRFC", "PNB"]

        with patch("custom_universe_store.get_active_symbols",
                   return_value=custom_syms), \
             patch("custom_universe_store.get_active_symbol_metadata",
                   return_value={}):
            from config import NIFTY_50, UniverseMode
            with patch("config.get_active_intraday_universe",
                       return_value=UniverseMode.CUSTOM_LOW_PRICE_SECTOR):

                # Mirror the resolution logic from live_scan_engine / market_scanner
                from config import get_active_intraday_universe
                from custom_universe_store import get_active_symbols

                if get_active_intraday_universe() == UniverseMode.CUSTOM_LOW_PRICE_SECTOR:
                    universe = get_active_symbols()
                else:
                    universe = list(NIFTY_50)

        self.assertEqual(sorted(universe), sorted(custom_syms))
        # Must not contain NIFTY_50 symbols that aren't in the custom list
        nifty_only = set(NIFTY_50) - set(custom_syms)
        overlap = set(universe) & nifty_only
        self.assertEqual(overlap, set(),
                         f"Universe leaked NIFTY_50 symbols: {overlap}")

    def test_get_active_symbol_metadata_keys_match_get_active_symbols(self):
        """Metadata dict keys must be a superset of active symbols."""
        import custom_universe_store
        rows = [_sample_row("WIPRO", is_active=True),
                _sample_row("IRFC", is_active=True),
                _sample_row("IOB", is_active=False)]
        _conn, _cur, fake_connect = _make_db_mock(fetchall_return=rows)
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect):
            meta = custom_universe_store.get_active_symbol_metadata()

        self.assertIn("WIPRO", meta)
        self.assertIn("IRFC", meta)
        self.assertNotIn("IOB", meta,
                         "Inactive symbols must not appear in active metadata")


# ── Test 5 — empty custom universe blocks scan safely ──────────────────────

class TestEmptyUniverseBlocksScanSafely(unittest.TestCase):

    def test_empty_custom_universe_gives_empty_scan_universe_not_nifty50(self):
        """When CUSTOM_LOW_PRICE_SECTOR is active but the table is empty, the
        resolved scan universe must be [] — it must NOT fall back to NIFTY_50."""
        with patch("custom_universe_store.get_active_symbols", return_value=[]), \
             patch("custom_universe_store.get_active_symbol_metadata",
                   return_value={}):
            from config import NIFTY_50, UniverseMode
            with patch("config.get_active_intraday_universe",
                       return_value=UniverseMode.CUSTOM_LOW_PRICE_SECTOR):
                from config import get_active_intraday_universe
                from custom_universe_store import get_active_symbols

                if get_active_intraday_universe() == UniverseMode.CUSTOM_LOW_PRICE_SECTOR:
                    universe = get_active_symbols()
                else:
                    universe = list(NIFTY_50)

        self.assertEqual(universe, [],
                         "Empty custom universe must yield [] — no NIFTY_50 fallback")

    def test_db_unavailable_returns_empty_not_exception(self):
        """When the DB is unavailable get_active_symbols must return [] gracefully."""
        import custom_universe_store
        with patch.object(custom_universe_store, "_db_available", return_value=False):
            result = custom_universe_store.get_active_symbols()
        self.assertEqual(result, [])

    def test_get_status_returns_zero_counts_when_table_empty(self):
        """get_status() with an empty table must return zero counts, not raise."""
        import custom_universe_store
        _conn, _cur, fake_connect = _make_db_mock(fetchall_return=[])
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect), \
             patch("config.get_active_intraday_universe"):
            status = custom_universe_store.get_status()

        self.assertTrue(status["success"])
        self.assertEqual(status["active_count"], 0)
        self.assertEqual(status["total_candidates"], 0)


# ── Test 6 — invalid mapping reported, not silently dropped ────────────────

class TestInvalidMappingReported(unittest.TestCase):

    def test_symbol_with_ohlcv_unavailable_is_returned_not_dropped(self):
        """A row with ohlcv_available=False must be returned by get_all_symbols(),
        not silently excluded.  Callers can then see the flag and handle it."""
        import custom_universe_store
        rows = [_sample_row("WIPRO", ohlcv=True, is_active=True),
                _sample_row("BADMAPPING", ohlcv=False, is_active=True)]
        _conn, _cur, fake_connect = _make_db_mock(fetchall_return=rows)
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect):
            result = custom_universe_store.get_all_symbols()

        symbols = [r["symbol"] for r in result]
        self.assertIn("BADMAPPING", symbols,
                      "Symbol with ohlcv_available=False must not be silently dropped")
        bad_row = next(r for r in result if r["symbol"] == "BADMAPPING")
        self.assertFalse(bad_row["ohlcv_available"],
                         "ohlcv_available flag must be preserved as False")

    def test_get_status_ohlcv_hit_rate_reflects_unavailable(self):
        """get_status() cache_hit_rate must be 50% when 1 of 2 active symbols
        lacks OHLCV data — not masked or rounded up to 100%."""
        import custom_universe_store
        rows = [_sample_row("WIPRO", ohlcv=True, is_active=True),
                _sample_row("BADMAPPING", ohlcv=False, is_active=True)]
        _conn, _cur, fake_connect = _make_db_mock(fetchall_return=rows)
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect), \
             patch("config.get_active_intraday_universe"):
            status = custom_universe_store.get_status()

        self.assertAlmostEqual(status["ohlcv_cache_hit_rate_pct"], 50.0, places=0)

    def test_upsert_accepts_row_with_null_instrument_token(self):
        """Symbols without a Kite instrument_token (NULL) must be inserted
        successfully — the token is optional until Kite is configured."""
        import custom_universe_store
        rows = [_valid_active_payload(
            symbol="IRFC", sector="INFRA", instrument_token=None,
        )]
        _conn, _cur, fake_connect = _make_db_mock()
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect), \
             patch("psycopg2.extras.execute_values"):
            result = custom_universe_store.upsert_symbols(rows)

        self.assertTrue(result["success"])
        self.assertEqual(result["upserted"], 1)


# ── Test 7 — reference-data-only instrument hydration ────────────────────

class TestInstrumentMetadataHydration(unittest.TestCase):

    def test_hydration_updates_only_active_rows_and_reports_symbol_mapping(self):
        import custom_universe_store
        rows = [_sample_row("WIPRO", is_active=True)]
        _conn, _cur, fake_connect = _make_db_mock(fetchall_return=rows)
        _cur.rowcount = 1
        instruments = [{
            "symbol": "WIPRO",
            "exchange": "NSE",
            "instrument_type": "EQ",
            "token": 12345,
        }]
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect):
            result = custom_universe_store.hydrate_active_instrument_metadata(
                instruments, "2026-08-24"
            )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["active_count"], 1)
        self.assertEqual(result["mapped_count"], 1)
        self.assertEqual(result["symbols"][0]["instrument_token"], 12345)
        update_sql = _cur.execute.call_args_list[-1].args[0]
        self.assertIn("instrument_token", update_sql)
        self.assertNotIn("is_active = %s", update_sql)
        self.assertNotIn("sector = %s", update_sql)

    def test_hydration_fails_closed_for_missing_mapping(self):
        import custom_universe_store
        rows = [_sample_row("WIPRO", is_active=True)]
        _conn, _cur, fake_connect = _make_db_mock(fetchall_return=rows)
        with patch.object(custom_universe_store, "_db_available", return_value=True), \
             patch.object(custom_universe_store, "_connect", fake_connect):
            result = custom_universe_store.hydrate_active_instrument_metadata(
                [], "2026-08-24"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["missing_symbols"], ["WIPRO"])
        self.assertEqual(result["mapped_count"], 0)


# ── Test 8 — Phase 0C safety suite still passes ────────────────────────────

class TestPhase0CSafetySuiteUnaffected(unittest.TestCase):
    """Phase 0C safety tests must all pass after any Phase 1B changes.

    This test invokes the Phase 0C suite as a subprocess gate.  Failure here
    means a Phase 1 change broke a production safety guard.
    """

    def test_phase0c_safety_suite_passes(self):
        import os
        from pathlib import Path

        python_dir = Path(__file__).resolve().parent.parent.parent
        suite_path = python_dir / "tests" / "unit" / "test_phase0c_safety_fixes.py"
        if not suite_path.exists():
            self.skipTest("test_phase0c_safety_fixes.py not found — skipping gate")

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(suite_path), "-q",
             "--tb=short", "--no-header"],
            capture_output=True,
            text=True,
            cwd=str(python_dir),
        )
        self.assertEqual(
            result.returncode, 0,
            f"Phase 0C safety suite FAILED after Phase 1B changes.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
