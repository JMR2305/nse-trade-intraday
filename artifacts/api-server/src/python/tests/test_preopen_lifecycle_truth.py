"""Focused lifecycle truth tests for Phase 5A/5C tick outcomes."""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch


class TestPreopenCollectCounts(unittest.TestCase):
    def test_tick_reports_engine_symbol_count_and_visible_persistence_mismatch(self):
        import preopen_intelligence_tick as tick

        engine = types.SimpleNamespace(collect_snapshot=lambda **_: {
            "success": True, "symbol_count": 12, "stale_count": 1,
            "provider_status": "LIVE",
        })
        database = types.SimpleNamespace(get_session=lambda _: {"symbol_count": 10})
        with patch.dict(sys.modules, {"preopen_engine": engine, "preopen_db": database}):
            result = tick._run_collect("session-1")

        self.assertEqual(result["symbol_count"], 12)
        self.assertEqual(result["symbols_captured"], 12)  # compatibility alias
        self.assertEqual(result["persisted_symbol_count"], 10)
        self.assertEqual(result["persistence_status"], "MISMATCH")


class TestForwardOnlySessionWrites(unittest.TestCase):
    def test_5a_collection_cannot_regress_frozen_or_reconciled_statuses(self):
        from preopen_db import _forward_session_status

        self.assertEqual(_forward_session_status("FROZEN", "COLLECTING"), "FROZEN")
        self.assertEqual(_forward_session_status("RECONCILED", "COLLECTING"), "RECONCILED")
        self.assertEqual(_forward_session_status("RECONCILED_0930", "INITIALISING"),
                         "RECONCILED_0930")
        self.assertEqual(_forward_session_status("FROZEN", "RECONCILED"), "RECONCILED")
        self.assertEqual(_forward_session_status("RECONCILED", "RECONCILED_0930"),
                         "RECONCILED_0930")

    def test_5b_partial_writes_cannot_reopen_terminal_sessions(self):
        from preopen_validation_db import _forward_session_status

        self.assertEqual(_forward_session_status("COMPLETE", "COLLECTING"), "COMPLETE")
        self.assertEqual(_forward_session_status("NO_CANDIDATES", "PENDING"),
                         "NO_CANDIDATES")
        self.assertEqual(_forward_session_status("COLLECTING", None), "COLLECTING")
        self.assertEqual(_forward_session_status("COLLECTING", "COMPLETE"), "COMPLETE")


class TestSignalValidationEodTruth(unittest.TestCase):
    def test_missing_close_does_not_rewrite_record_or_complete_session(self):
        import signal_validation_tick as tick
        from signal_validation_model import LifecycleState

        class Db:
            sessions = []
            record_writes = 0

            @staticmethod
            def get_records(**_):
                return [{
                    "validation_id": "v1", "trading_date": "2026-01-02",
                    "session_id": "s1", "signal_id": "sig1", "symbol": "ABC",
                    "validation_status": LifecycleState.OPEN_POSITION,
                    "entry_price": "100",
                }]

            @staticmethod
            def upsert_session(data):
                Db.sessions.append(data)

            @staticmethod
            def upsert_record(_):
                Db.record_writes += 1

        # yfinance download failure is the same safe outcome as an empty
        # provider response and exercises the no-history-rewrite branch.
        yf = types.SimpleNamespace(download=lambda *_, **__: (_ for _ in ()).throw(RuntimeError("unavailable")))
        with patch.dict(sys.modules, {"signal_validation_db": Db, "yfinance": yf}):
            result = tick._run_eod_close("s1", "2026-01-02")

        self.assertTrue(result["retry_required"])
        self.assertEqual(result["session_status"], "EOD_RETRY_REQUIRED")
        self.assertEqual(result["missing_close_records"], 1)
        self.assertEqual(Db.record_writes, 0)
        self.assertEqual(Db.sessions[-1]["status"], "EOD_RETRY_REQUIRED")
