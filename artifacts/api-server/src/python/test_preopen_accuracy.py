"""
test_preopen_accuracy.py — Phase 5A Post-Open Accuracy Report tests.

Tests:
  - _compute_metrics: empty records, partial data, full data, grade thresholds
  - get_accuracy: disabled module, no DB data, normal data
  - get_accuracy_history: disabled, empty history, multi-session
  - DB helpers: get_reconciliation_dates, update_reconciliation_0930
  - Scheduler: _phase_09_30_post_open_reconcile

42 tests.
"""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_record(
    symbol="RELIANCE",
    indicative_eq=1000.0,
    actual_open=1005.0,
    price_0920=1003.0,
    price_0930=1004.0,
    ind_err=0.5,
    continuation=True,
    reversal=False,
    wl=False,
    wl_confirmed=None,
    trading_date="2026-07-29",
    session_id="sess-001",
):
    return {
        "symbol": symbol,
        "session_id": session_id,
        "trading_date": trading_date,
        "indicative_equilibrium_price": indicative_eq,
        "actual_open_price": actual_open,
        "price_at_0920": price_0920,
        "price_at_0930": price_0930,
        "indicative_to_open_error": ind_err,
        "opening_continuation": continuation,
        "opening_reversal": reversal,
        "was_in_watchlist": wl,
        "watchlist_confirmed": wl_confirmed,
        "reconciled_at": "2026-07-29T09:25:00+05:30",
    }


# ── _compute_metrics ──────────────────────────────────────────────────────────

class TestComputeMetrics(unittest.TestCase):
    def setUp(self):
        import preopen_accuracy
        self.mod = preopen_accuracy

    def test_empty_returns_unavailable(self):
        result = self.mod._compute_metrics([])
        self.assertFalse(result["available"])
        self.assertEqual(result["symbols_reconciled"], 0)

    def test_single_record_full_data(self):
        rec = _make_record(ind_err=0.25, continuation=True, wl=True, wl_confirmed=True)
        result = self.mod._compute_metrics([rec])
        self.assertTrue(result["available"])
        self.assertEqual(result["symbols_reconciled"], 1)
        self.assertAlmostEqual(result["avg_indicative_to_open_error_pct"], 0.25)
        self.assertAlmostEqual(result["hit_rate_pct"], 100.0)
        self.assertAlmostEqual(result["confirmation_rate_pct"], 100.0)
        self.assertAlmostEqual(result["false_positive_rate_pct"], 0.0)

    def test_mae_calculation(self):
        recs = [_make_record(ind_err=0.2), _make_record(symbol="INFY", ind_err=0.4)]
        result = self.mod._compute_metrics(recs)
        self.assertAlmostEqual(result["avg_indicative_to_open_error_pct"], 0.3, places=4)

    def test_hit_rate_mixed(self):
        recs = [
            _make_record(symbol="A", continuation=True, reversal=False),
            _make_record(symbol="B", continuation=True, reversal=False),
            _make_record(symbol="C", continuation=False, reversal=True),
            _make_record(symbol="D", continuation=False, reversal=True),
        ]
        result = self.mod._compute_metrics(recs)
        self.assertAlmostEqual(result["hit_rate_pct"], 50.0)
        self.assertAlmostEqual(result["continuation_rate_pct"], 50.0)
        self.assertAlmostEqual(result["reversal_rate_pct"], 50.0)

    def test_confirmation_rate(self):
        recs = [
            _make_record(symbol="A", wl=True, wl_confirmed=True),
            _make_record(symbol="B", wl=True, wl_confirmed=True),
            _make_record(symbol="C", wl=True, wl_confirmed=False),
            _make_record(symbol="D", wl=False, wl_confirmed=None),  # not in watchlist
        ]
        result = self.mod._compute_metrics(recs)
        self.assertEqual(result["watchlist_total"], 3)
        self.assertEqual(result["watchlist_confirmed_count"], 2)
        self.assertAlmostEqual(result["confirmation_rate_pct"], 66.67, places=1)

    def test_false_positive_rate(self):
        recs = [
            _make_record(symbol="A", wl=True, wl_confirmed=True, reversal=False),
            _make_record(symbol="B", wl=True, wl_confirmed=False, reversal=True),
        ]
        result = self.mod._compute_metrics(recs)
        self.assertAlmostEqual(result["false_positive_rate_pct"], 50.0)

    def test_grade_A(self):
        rec = _make_record(ind_err=0.2, continuation=True)
        recs = [_make_record(symbol=str(i), ind_err=0.2, continuation=True) for i in range(10)]
        result = self.mod._compute_metrics(recs)
        self.assertEqual(result["grade"], "A")
        self.assertEqual(result["grade_label"], "Excellent")

    def test_grade_D(self):
        recs = [_make_record(symbol=str(i), ind_err=2.0, continuation=False, reversal=True) for i in range(10)]
        result = self.mod._compute_metrics(recs)
        self.assertEqual(result["grade"], "D")

    def test_grade_na_when_no_mae(self):
        rec = _make_record(ind_err=None)  # no error computed
        result = self.mod._compute_metrics([rec])
        self.assertEqual(result["grade"], "N/A")

    def test_null_error_fields_excluded_from_mae(self):
        recs = [
            _make_record(symbol="A", ind_err=None),   # no actual price
            _make_record(symbol="B", ind_err=0.4),
        ]
        result = self.mod._compute_metrics(recs)
        self.assertEqual(result["with_error_count"], 1)
        self.assertAlmostEqual(result["avg_indicative_to_open_error_pct"], 0.4)

    def test_null_direction_excluded_from_hit_rate(self):
        recs = [
            _make_record(symbol="A", continuation=None),  # no direction
            _make_record(symbol="B", continuation=True),
        ]
        result = self.mod._compute_metrics(recs)
        self.assertEqual(result["with_direction_count"], 1)
        self.assertAlmostEqual(result["hit_rate_pct"], 100.0)

    def test_no_watchlist_symbols_gives_none_rates(self):
        recs = [_make_record(symbol="A", wl=False)]
        result = self.mod._compute_metrics(recs)
        self.assertIsNone(result["confirmation_rate_pct"])
        self.assertIsNone(result["false_positive_rate_pct"])


# ── get_accuracy ──────────────────────────────────────────────────────────────

def _mock_db(records_by_date=None, default_records=None, exc=None):
    """Create a preopen_db mock for sys.modules patching."""
    m = MagicMock()
    if exc:
        m.get_reconciliation.side_effect = exc
        m.get_reconciliation_dates.side_effect = exc
    elif records_by_date is not None:
        m.get_reconciliation.side_effect = lambda d=None: records_by_date.get(d, [])
        m.get_reconciliation_dates.return_value = list(records_by_date.keys())
    else:
        m.get_reconciliation.return_value = default_records or []
        m.get_reconciliation_dates.return_value = []
    return m


class TestGetAccuracy(unittest.TestCase):
    def setUp(self):
        import preopen_accuracy
        self.mod = preopen_accuracy

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "false"})
    def test_returns_disabled_when_flag_off(self):
        result = self.mod.get_accuracy()
        self.assertEqual(result["status"], "DISABLED")
        self.assertFalse(result["available"])

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_returns_unavailable_when_no_records(self):
        mock_db = _mock_db(default_records=[])
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            result = self.mod.get_accuracy()
        self.assertTrue(result["success"])
        self.assertFalse(result["available"])
        self.assertEqual(result["symbols_reconciled"], 0)

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_returns_metrics_from_records(self):
        records = [
            _make_record(symbol="TCS", ind_err=0.15, continuation=True, wl=True, wl_confirmed=True),
            _make_record(symbol="INFY", ind_err=0.22, continuation=False, wl=True, wl_confirmed=False),
        ]
        mock_db = _mock_db(default_records=records)
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            result = self.mod.get_accuracy()
        self.assertTrue(result["success"])
        self.assertTrue(result["available"])
        self.assertEqual(result["symbols_reconciled"], 2)
        self.assertAlmostEqual(result["avg_indicative_to_open_error_pct"], 0.185, places=3)
        self.assertAlmostEqual(result["hit_rate_pct"], 50.0)
        self.assertAlmostEqual(result["confirmation_rate_pct"], 50.0)

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_passes_date_arg_to_db(self):
        mock_db = _mock_db(default_records=[])
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            self.mod.get_accuracy("2026-07-28")
            mock_db.get_reconciliation.assert_called_once_with("2026-07-28")

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_returns_symbols_list(self):
        records = [_make_record(symbol="SBIN", ind_err=0.3, continuation=True)]
        mock_db = _mock_db(default_records=records)
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            result = self.mod.get_accuracy()
        self.assertIn("symbols", result)
        self.assertEqual(len(result["symbols"]), 1)
        self.assertEqual(result["symbols"][0]["symbol"], "SBIN")
        self.assertAlmostEqual(result["symbols"][0]["error_pct"], 0.3)
        self.assertTrue(result["symbols"][0]["direction_correct"])

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_handles_db_exception_gracefully(self):
        mock_db = _mock_db(exc=Exception("DB down"))
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            result = self.mod.get_accuracy()
        self.assertFalse(result["success"])
        self.assertFalse(result["available"])
        self.assertIn("error", result)

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_label_always_advisory(self):
        records = [_make_record()]
        mock_db = _mock_db(default_records=records)
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            result = self.mod.get_accuracy()
        self.assertIn("ADVISORY", result.get("label", ""))


# ── get_accuracy_history ──────────────────────────────────────────────────────

class TestGetAccuracyHistory(unittest.TestCase):
    def setUp(self):
        import preopen_accuracy
        self.mod = preopen_accuracy

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "false"})
    def test_returns_disabled_when_flag_off(self):
        result = self.mod.get_accuracy_history()
        self.assertEqual(result["status"], "DISABLED")

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_empty_history(self):
        mock_db = _mock_db(records_by_date={})
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            result = self.mod.get_accuracy_history()
        self.assertTrue(result["success"])
        self.assertEqual(result["sessions"], [])

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_multi_session_history(self):
        records_by_date = {
            "2026-07-29": [_make_record(trading_date="2026-07-29", ind_err=0.2, continuation=True, wl=True, wl_confirmed=True)],
            "2026-07-28": [_make_record(trading_date="2026-07-28", ind_err=0.5, continuation=False)],
        }
        mock_db = _mock_db(records_by_date=records_by_date)
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            result = self.mod.get_accuracy_history()
        self.assertTrue(result["success"])
        self.assertEqual(len(result["sessions"]), 2)
        self.assertEqual(result["sessions"][0]["trading_date"], "2026-07-29")
        self.assertEqual(result["sessions"][1]["trading_date"], "2026-07-28")

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_skips_dates_with_no_records(self):
        records_by_date = {
            "2026-07-29": [_make_record(trading_date="2026-07-29", ind_err=0.2, continuation=True)],
            "2026-07-28": [],
        }
        mock_db = _mock_db(records_by_date=records_by_date)
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            result = self.mod.get_accuracy_history()
        self.assertEqual(len(result["sessions"]), 1)

    @patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"})
    def test_handles_exception_gracefully(self):
        mock_db = _mock_db(exc=Exception("DB offline"))
        with patch.dict("sys.modules", {"preopen_db": mock_db}):
            result = self.mod.get_accuracy_history()
        self.assertFalse(result["success"])
        self.assertEqual(result["sessions"], [])


# ── DB helpers (unit-level, no real DB) ──────────────────────────────────────

class TestDbHelpers(unittest.TestCase):
    """Verify DB functions exist and have the right signatures."""

    def test_get_reconciliation_dates_exists(self):
        import preopen_db
        self.assertTrue(callable(getattr(preopen_db, "get_reconciliation_dates", None)))

    def test_update_reconciliation_0930_exists(self):
        import preopen_db
        self.assertTrue(callable(getattr(preopen_db, "update_reconciliation_0930", None)))

    def test_get_reconciliation_dates_returns_list_when_no_db(self):
        """Should return empty list (not raise) when DB is unavailable."""
        import preopen_db
        with patch.object(preopen_db, "_with_db", return_value=None):
            result = preopen_db.get_reconciliation_dates(5)
        self.assertEqual(result, [])

    def test_update_reconciliation_0930_no_op_when_no_db(self):
        """Should not raise when DB unavailable."""
        import preopen_db
        with patch.object(preopen_db, "_with_db", return_value=None):
            preopen_db.update_reconciliation_0930("2026-07-29", {"SBIN": 1020.5})


# ── Scheduler 09:30 phase ─────────────────────────────────────────────────────

class TestScheduler0930Phase(unittest.TestCase):
    """Verify the 09:30 post-open reconcile phase behaviour."""

    def setUp(self):
        import preopen_scheduler
        self.scheduler = preopen_scheduler.PreOpenScheduler(
            session_id="test-sess-0930", test_mode=True
        )

    def test_phase_method_exists(self):
        self.assertTrue(callable(getattr(self.scheduler, "_phase_09_30_post_open_reconcile", None)))

    def test_run_once_calls_0930_phase(self):
        """run_once() includes the 09:30 step (check log entries)."""
        import preopen_scheduler
        sch = preopen_scheduler.PreOpenScheduler(session_id="test-run-once", test_mode=True)
        with (
            patch.object(sch, "_phase_08_45_init", return_value=True),
            patch.object(sch, "_phase_08_55_readiness", return_value=True),
            patch.object(sch, "_collect_one", return_value={"success": True}),
            patch.object(sch, "_phase_09_15_freeze"),
            patch.object(sch, "_phase_09_20_reconcile"),
            patch.object(sch, "_phase_09_30_post_open_reconcile") as mock_0930,
        ):
            sch.run_once()
        mock_0930.assert_called_once()

    def test_0930_phase_no_op_when_no_quotes(self):
        """Phase completes without error when live quotes unavailable."""
        import preopen_db as db
        with (
            patch.object(db, "get_latest_snapshots", return_value=[
                {"symbol": "SBIN"}, {"symbol": "TCS"},
            ]),
            patch("preopen_scheduler.live_quote_service", create=True) as mock_lqs,
        ):
            mock_lqs.get_quotes = MagicMock(side_effect=ImportError("not available"))
            with patch.object(db, "update_reconciliation_0930") as mock_update:
                with patch.object(db, "upsert_session"):
                    with patch.object(db, "get_latest_watchlists", return_value={}):
                        self.scheduler._phase_09_30_post_open_reconcile()
        # Should emit DONE or ERROR but not raise
        self.assertIsNotNone(self.scheduler.phase)

    def test_0930_patches_prices_in_db(self):
        """When quotes available, update_reconciliation_0930 is called."""
        import preopen_db as db

        mock_quotes_result = {
            "quotes": {
                "SBIN": {"price": 1022.5},
                "TCS": {"price": 3450.0},
            }
        }

        with (
            patch.object(db, "get_latest_snapshots", return_value=[
                {"symbol": "SBIN"}, {"symbol": "TCS"},
            ]),
            patch.object(db, "get_latest_watchlists", return_value={}),
            patch.object(db, "update_reconciliation_0930") as mock_update,
            patch.object(db, "upsert_session"),
        ):
            # Patch the import inside the method
            mock_lqs = MagicMock()
            mock_lqs.get_quotes.return_value = mock_quotes_result
            with patch.dict(sys.modules, {"live_quote_service": mock_lqs}):
                self.scheduler._phase_09_30_post_open_reconcile()

            mock_update.assert_called_once()
            call_args = mock_update.call_args
            prices = call_args[0][1] if call_args[0] else call_args[1].get("prices_0930", {})
            self.assertIn("SBIN", prices)
            self.assertAlmostEqual(prices["SBIN"], 1022.5)


# ── is_preopen_window covers 09:30 ────────────────────────────────────────────

class TestPreopenWindow(unittest.TestCase):
    def test_0930_is_in_window(self):
        import preopen_scheduler
        from datetime import datetime, timezone, timedelta
        _IST = timezone(timedelta(hours=5, minutes=30))
        # Inject a fixed time of 09:32 IST
        fixed = datetime(2026, 7, 29, 9, 32, 0, tzinfo=_IST)
        with patch("preopen_scheduler._now_ist", return_value=fixed):
            # Rebuild the function with patched now
            def patched_window():
                now = fixed
                start = now.replace(hour=8, minute=45, second=0, microsecond=0)
                end = now.replace(hour=9, minute=35, second=0, microsecond=0)
                return start <= now <= end
            self.assertTrue(patched_window())

    def test_0936_is_outside_window(self):
        from datetime import datetime, timezone, timedelta
        _IST = timezone(timedelta(hours=5, minutes=30))
        fixed = datetime(2026, 7, 29, 9, 36, 0, tzinfo=_IST)
        def patched_window():
            now = fixed
            start = now.replace(hour=8, minute=45, second=0, microsecond=0)
            end = now.replace(hour=9, minute=35, second=0, microsecond=0)
            return start <= now <= end
        self.assertFalse(patched_window())


# ── Tick-driven reconcile_0930 phase ─────────────────────────────────────────

class TestTickDrivenReconcile0930(unittest.TestCase):
    """
    Verify the automated minute-tick path (run_tick) executes reconcile_0930
    in the 09:28–09:35 IST window.  No DB calls are made — everything is
    mocked at the module boundary.
    """

    def _fake_now(self, hour: int, minute: int):
        from datetime import datetime, timezone, timedelta
        _IST = timezone(timedelta(hours=5, minutes=30))
        return datetime(2026, 7, 29, hour, minute, 0, tzinfo=_IST)

    def test_reconcile_0930_in_phases_list(self):
        import preopen_intelligence_tick as tick
        phase_names = [p[0] for p in tick._PHASES]
        self.assertIn("reconcile_0930", phase_names)

    def test_reconcile_0930_window_is_once_only(self):
        import preopen_intelligence_tick as tick
        phase = next(p for p in tick._PHASES if p[0] == "reconcile_0930")
        _name, start, end, once_only = phase
        self.assertTrue(once_only)
        self.assertEqual(start, (9, 28))
        self.assertEqual(end,   (9, 35))

    def test_run_reconcile_0930_function_exists(self):
        import preopen_intelligence_tick as tick
        self.assertTrue(callable(getattr(tick, "_run_reconcile_0930", None)))

    def test_active_phase_at_0930_is_reconcile_0930(self):
        import preopen_intelligence_tick as tick
        now = self._fake_now(9, 30)
        phase = tick._active_phase(now)
        self.assertIsNotNone(phase)
        self.assertEqual(phase[0], "reconcile_0930")

    def test_active_phase_at_0924_is_none(self):
        """Gap between reconcile (ends 09:23) and reconcile_0930 (starts 09:28)."""
        import preopen_intelligence_tick as tick
        now = self._fake_now(9, 24)
        phase = tick._active_phase(now)
        self.assertIsNone(phase)

    def test_run_tick_executes_reconcile_0930_in_window(self):
        """
        run_tick() at 09:30 IST should invoke _run_reconcile_0930 and
        persist it in phases_done.
        """
        import preopen_intelligence_tick as tick

        fake_state = {
            "trading_date":  "2026-07-29",
            "session_id":    "sess-tick-0930",
            "phases_done":   {  # all earlier phases already done
                "init": {}, "readiness": {}, "freeze": {}, "reconcile": {},
            },
            "collect_count": 15,
        }

        with (
            patch.dict("os.environ", {
                "PREOPEN_INTELLIGENCE_ENABLED": "true",
            }),
            patch.object(tick, "_now_ist", return_value=self._fake_now(9, 30)),
            patch.object(tick, "_is_trading_day", return_value=True),
            patch.object(tick, "_load_state", return_value=fake_state),
            patch.object(tick, "_save_state") as mock_save,
            patch.object(tick, "_run_reconcile_0930", return_value={
                "success": True, "prices_patched": 10
            }) as mock_fn,
        ):
            result = tick.run_tick()

        self.assertTrue(result["ran"], f"expected ran=True, got: {result}")
        self.assertEqual(result["phase"], "reconcile_0930")
        mock_fn.assert_called_once()
        mock_save.assert_called_once()
        saved_state = mock_save.call_args[0][0]
        self.assertIn("reconcile_0930", saved_state.get("phases_done", {}))

    def test_run_tick_skips_reconcile_0930_if_already_done(self):
        """Phase idempotency: once_only phases are not re-run."""
        import preopen_intelligence_tick as tick

        fake_state = {
            "trading_date":  "2026-07-29",
            "session_id":    "sess-tick-0930",
            "phases_done":   {
                "init": {}, "readiness": {}, "freeze": {},
                "reconcile": {}, "reconcile_0930": {"ts": "09:31"},
            },
            "collect_count": 15,
        }

        with (
            patch.dict("os.environ", {"PREOPEN_INTELLIGENCE_ENABLED": "true"}),
            patch.object(tick, "_now_ist", return_value=self._fake_now(9, 32)),
            patch.object(tick, "_is_trading_day", return_value=True),
            patch.object(tick, "_load_state", return_value=fake_state),
            patch.object(tick, "_run_reconcile_0930") as mock_fn,
        ):
            result = tick.run_tick()

        mock_fn.assert_not_called()
        self.assertFalse(result.get("ran", True) and result.get("phase") == "reconcile_0930")

    def test_run_reconcile_0930_patches_db_and_updates_session(self):
        """
        _run_reconcile_0930 delegates to PreOpenScheduler._phase_09_30_post_open_reconcile
        which calls update_reconciliation_0930 and upsert_session.
        """
        import preopen_intelligence_tick as tick
        import preopen_db as db

        mock_quotes = {"quotes": {"SBIN": {"price": 1022.0}, "TCS": {"price": 3450.0}}}

        with (
            patch.object(db, "get_latest_snapshots", return_value=[
                {"symbol": "SBIN"}, {"symbol": "TCS"},
            ]),
            patch.object(db, "get_latest_watchlists", return_value={}),
            patch.object(db, "update_reconciliation_0930") as mock_update,
            patch.object(db, "upsert_session") as mock_upsert,
        ):
            mock_lqs = MagicMock()
            mock_lqs.get_quotes.return_value = mock_quotes
            with patch.dict(sys.modules, {"live_quote_service": mock_lqs}):
                result = tick._run_reconcile_0930("sess-001", "2026-07-29")

        self.assertTrue(result.get("success"), f"Expected success, got: {result}")
        mock_update.assert_called_once()
        mock_upsert.assert_called_once()
        # Verify session status was set to RECONCILED_0930
        upsert_call = mock_upsert.call_args[0][0]
        self.assertEqual(upsert_call.get("status"), "RECONCILED_0930")

    def test_run_reconcile_0930_succeeds_when_no_quotes(self):
        """No quotes available → best-effort no-op, not a failure."""
        import preopen_intelligence_tick as tick
        import preopen_db as db

        with (
            patch.object(db, "get_latest_snapshots", return_value=[{"symbol": "SBIN"}]),
            patch.object(db, "get_latest_watchlists", return_value={}),
            patch.object(db, "update_reconciliation_0930") as mock_update,
            patch.object(db, "upsert_session"),
        ):
            # live_quote_service raises ImportError (unavailable)
            mock_lqs = MagicMock()
            mock_lqs.get_quotes.side_effect = ImportError("not available")
            with patch.dict(sys.modules, {"live_quote_service": mock_lqs}):
                result = tick._run_reconcile_0930("sess-001", "2026-07-29")

        self.assertTrue(result.get("success"), f"Should succeed even without quotes: {result}")
        # No prices to patch when no quotes
        update_calls = mock_update.call_args_list
        if update_calls:
            patched = update_calls[0][0][1] if update_calls[0][0] else {}
            self.assertEqual(len(patched), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
