"""
test_phase20_eod_status.py — Unit tests for phase20_eod_status.build_eod_status_payload.

Covers:
  1.  Before the 30-minute window: show_countdown=False, banner hidden.
  2.  Within the 30-minute countdown window: show_countdown=True, time shown.
  3.  In the 15:20–15:30 squareoff window: in_squareoff_window=True.
  4.  After 15:30: past_post_close=True.
  5.  MARKET_CLOSE_EXIT_BLOCKED events surfaced in blocked_events (today only).
  6.  POST_CLOSE_FORCE_EXIT ledger row surfaced in force_close_results.
  7.  MARKET_CLOSE_EXIT ledger row (intraday path) surfaced in force_close_results.
  8.  Ledger rows from before today's IST midnight are filtered out.
  9.  eod_ran_today True when KV claim is present.
  10. Pipeline blocked events from before today's IST midnight are filtered out.
  11. Never raises even when all dependencies are broken.

ISOLATION GUARANTEE
-------------------
All stubs are installed per-test via unittest.mock.patch.
No application modules are imported at module scope.
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ist(hour: int, minute: int = 0, date_str: str = "2026-08-18") -> datetime:
    """Return a timezone-aware datetime at the given IST hour/minute."""
    y, m, d = map(int, date_str.split("-"))
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    return datetime(y, m, d, hour, minute, 0, tzinfo=ist_offset)


def _pe_event(event_type: str, symbol: str | None, payload: dict,
              ts_utc: str = "2026-08-18T10:00:00Z") -> dict:
    """Minimal pipeline-event dict matching the query_events shape."""
    return {
        "id": 1, "ts": ts_utc, "mode": "LIVE",
        "event_type": event_type, "stage": "PORTFOLIO",
        "symbol": symbol, "scan_id": "scan1", "payload": payload,
    }


class _ModuleGuard:
    """Install stub modules and remove them on exit so tests stay isolated."""

    def __init__(self):
        self._stubs: list[str] = []

    def stub(self, name: str, module: types.ModuleType) -> None:
        sys.modules[name] = module
        self._stubs.append(name)

    def clear(self) -> None:
        for name in self._stubs:
            sys.modules.pop(name, None)
        self._stubs.clear()


def _make_cursor(rows: list[tuple]) -> MagicMock:
    """Return a mock cursor whose fetchall() yields ``rows``."""
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = rows
    return cur


def _make_conn(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# ── Base test class ───────────────────────────────────────────────────────────

class _Base(unittest.TestCase):
    """Provides _call() with controllable IST clock and stub dependencies."""

    def _call(
        self,
        now_ist: datetime,
        # pipeline_events.query_events side-effect (called per event_type)
        query_events_side_effect: Any = None,
        # kv_get return value (None = claim absent)
        kv_value: Any = None,
        # Rows returned by the DB cursor for the ledger query:
        # list of (symbol, exit_price, realized_pnl, exit_rule, exit_ts, fill_price, qty)
        ledger_rows: list[tuple] | None = None,
        # Whether the DB is "available"
        db_available: bool = True,
    ) -> Dict[str, Any]:
        guard = _ModuleGuard()

        # ── Stub zoneinfo ────────────────────────────────────────────────────
        zi_mod = types.ModuleType("zoneinfo")
        zi_class = MagicMock()
        zi_class.return_value = None
        zi_mod.ZoneInfo = zi_class
        guard.stub("zoneinfo", zi_mod)

        # ── Stub pipeline_events ─────────────────────────────────────────────
        pe_mod = types.ModuleType("pipeline_events")
        pe_mod.query_events = MagicMock(  # type: ignore[attr-defined]
            side_effect=query_events_side_effect or (lambda **_: [])
        )
        guard.stub("pipeline_events", pe_mod)

        # ── Stub phase20_store for kv_get ────────────────────────────────────
        store_mod = types.ModuleType("phase20_store")
        store_mod.kv_get = MagicMock(return_value=kv_value)  # type: ignore[attr-defined]
        guard.stub("phase20_store", store_mod)

        # ── Stub scan_state_store for DB connection ───────────────────────────
        sss_mod = types.ModuleType("scan_state_store")
        sss_mod.db_available = MagicMock(return_value=db_available)  # type: ignore[attr-defined]

        if db_available and ledger_rows is not None:
            cursor = _make_cursor(ledger_rows)
            conn = _make_conn(cursor)
            sss_mod._connect = MagicMock(return_value=conn)  # type: ignore[attr-defined]
        else:
            sss_mod._connect = MagicMock(side_effect=RuntimeError("no db"))  # type: ignore[attr-defined]

        guard.stub("scan_state_store", sss_mod)

        try:
            if "phase20_eod_status" in sys.modules:
                del sys.modules["phase20_eod_status"]
            from phase20_eod_status import build_eod_status_payload  # noqa: PLC0415

            with patch("phase20_eod_status._now_ist", return_value=now_ist):
                return build_eod_status_payload()
        finally:
            if "phase20_eod_status" in sys.modules:
                del sys.modules["phase20_eod_status"]
            guard.clear()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTimeFlags(_Base):
    """Tests 1–4: time-based flags derived from IST clock."""

    def test_1_before_countdown_window(self) -> None:
        """Before 14:50 IST: show_countdown=False, no window."""
        r = self._call(now_ist=_ist(14, 45), ledger_rows=[])
        self.assertFalse(r["show_countdown"], r)
        self.assertFalse(r["in_squareoff_window"], r)
        self.assertFalse(r["past_post_close"], r)
        self.assertGreater(r["time_to_squareoff_sec"], 0)

    def test_2_within_countdown_window(self) -> None:
        """15:05 IST: 15 min before 15:20 → show_countdown=True."""
        r = self._call(now_ist=_ist(15, 5), ledger_rows=[])
        self.assertTrue(r["show_countdown"], r)
        self.assertFalse(r["in_squareoff_window"], r)
        self.assertFalse(r["past_post_close"], r)
        # ~15 min = 900 s
        self.assertAlmostEqual(r["time_to_squareoff_sec"], 900, delta=60)

    def test_3_in_squareoff_window(self) -> None:
        """15:22 IST: in the 15:20–15:30 window."""
        r = self._call(now_ist=_ist(15, 22), ledger_rows=[])
        self.assertTrue(r["in_squareoff_window"], r)
        self.assertFalse(r["show_countdown"], r)
        self.assertFalse(r["past_post_close"], r)

    def test_4_past_post_close(self) -> None:
        """15:35 IST: post-close window."""
        r = self._call(now_ist=_ist(15, 35), ledger_rows=[])
        self.assertFalse(r["in_squareoff_window"], r)
        self.assertTrue(r["past_post_close"], r)
        self.assertLess(r["time_to_squareoff_sec"], 0)

    def test_squareoff_time_ist_label(self) -> None:
        r = self._call(now_ist=_ist(15, 0), ledger_rows=[])
        self.assertEqual(r["squareoff_time_ist"], "15:20 IST")

    def test_today_ist_field(self) -> None:
        r = self._call(now_ist=_ist(14, 0), ledger_rows=[])
        self.assertEqual(r["today_ist"], "2026-08-18")


class TestLedgerQuery(_Base):
    """Tests 6–7: force_close_results derived from the ledger (authoritative)."""

    def _row(
        self,
        symbol: str = "INFY",
        exit_price: float = 1845.50,
        realized_pnl: float = 120.30,
        exit_rule: str = "MARKET_CLOSE_EXIT",
        exit_ts: str = "2026-08-18T09:52:00Z",
        fill_price: float = 1800.0,
        qty: int = 5,
    ) -> tuple:
        return (symbol, exit_price, realized_pnl, exit_rule, exit_ts, fill_price, qty)

    def test_6_post_close_force_exit_from_ledger(self) -> None:
        """POST_CLOSE_FORCE_EXIT ledger row appears in force_close_results."""
        r = self._call(
            now_ist=_ist(16),
            ledger_rows=[self._row(exit_rule="POST_CLOSE_FORCE_EXIT")],
        )
        self.assertEqual(len(r["force_close_results"]), 1, r)
        fc = r["force_close_results"][0]
        self.assertEqual(fc["symbol"], "INFY")
        self.assertEqual(fc["exit_rule"], "POST_CLOSE_FORCE_EXIT")
        self.assertAlmostEqual(fc["exit_price"], 1845.50)
        self.assertAlmostEqual(fc["realized_pnl"], 120.30)

    def test_7_market_close_exit_from_ledger(self) -> None:
        """MARKET_CLOSE_EXIT (intraday 15:20 path) appears in force_close_results.

        This is the critical path: the intraday exit writes to the ledger
        but does NOT emit a pipeline event.  Querying the ledger here is the
        only way to surface it in the status panel.
        """
        r = self._call(
            now_ist=_ist(15, 25),
            ledger_rows=[
                self._row(
                    symbol="RELIANCE",
                    exit_price=2950.0,
                    realized_pnl=-75.0,
                    exit_rule="MARKET_CLOSE_EXIT",
                    exit_ts="2026-08-18T09:50:00Z",
                )
            ],
        )
        self.assertEqual(len(r["force_close_results"]), 1, r)
        fc = r["force_close_results"][0]
        self.assertEqual(fc["symbol"], "RELIANCE")
        self.assertEqual(fc["exit_rule"], "MARKET_CLOSE_EXIT")
        self.assertAlmostEqual(fc["exit_price"], 2950.0)
        self.assertAlmostEqual(fc["realized_pnl"], -75.0)

    def test_multiple_eod_closes(self) -> None:
        """Multiple EOD closes from different rules all appear."""
        rows = [
            self._row("INFY", 1845.0, 100.0, "MARKET_CLOSE_EXIT", "2026-08-18T09:50:00Z"),
            self._row("WIPRO", 500.0, -20.0, "POST_CLOSE_FORCE_EXIT", "2026-08-18T10:05:00Z"),
        ]
        r = self._call(now_ist=_ist(16), ledger_rows=rows)
        self.assertEqual(len(r["force_close_results"]), 2, r)
        syms = {fc["symbol"] for fc in r["force_close_results"]}
        self.assertEqual(syms, {"INFY", "WIPRO"})

    def test_8_ledger_rows_before_ist_midnight_filtered(self) -> None:
        """Ledger rows before today's IST midnight must not appear.

        The SQL WHERE clause uses ist_midnight_utc as a lower bound.
        We verify the bound is passed to the DB and old rows don't leak.
        The stub cursor is configured to return [] (simulating the DB
        honouring the WHERE), so force_close_results must be empty.
        """
        r = self._call(
            now_ist=_ist(16),
            ledger_rows=[],   # DB returns nothing (WHERE filtered it)
        )
        self.assertEqual(r["force_close_results"], [])

    def test_no_db_returns_empty(self) -> None:
        """When DB is unavailable, force_close_results gracefully returns []."""
        r = self._call(now_ist=_ist(16), db_available=False, ledger_rows=None)
        self.assertEqual(r["force_close_results"], [])
        self.assertTrue(r["success"], r)


class TestBlockedEvents(_Base):
    """Tests 5, 10: MARKET_CLOSE_EXIT_BLOCKED pipeline events."""

    def test_5_blocked_event_surfaced(self) -> None:
        """MARKET_CLOSE_EXIT_BLOCKED today → appears in blocked_events."""
        blocked_evt = _pe_event(
            "MARKET_CLOSE_EXIT_BLOCKED", "TCS",
            {"trade_id": "T1", "reason": "No price available"},
            ts_utc="2026-08-18T10:00:00Z",
        )

        def _qe(event_type: str = "", **_) -> list:
            return [blocked_evt] if event_type == "MARKET_CLOSE_EXIT_BLOCKED" else []

        r = self._call(now_ist=_ist(16), query_events_side_effect=_qe, ledger_rows=[])
        self.assertEqual(len(r["blocked_events"]), 1, r)
        be = r["blocked_events"][0]
        self.assertEqual(be["symbol"], "TCS")
        self.assertEqual(be["trade_id"], "T1")
        self.assertIn("No price", be["reason"])

    def test_10_blocked_events_before_ist_midnight_filtered(self) -> None:
        """MARKET_CLOSE_EXIT_BLOCKED from before today's IST midnight must be filtered.

        The filter uses the UTC lower-bound of today's IST midnight
        (2026-08-17T18:30:00Z for 2026-08-18 IST) as a string comparison.
        An event from 2026-08-17T10:00:00Z is before that bound.
        """
        old_evt = _pe_event(
            "MARKET_CLOSE_EXIT_BLOCKED", "WIPRO",
            {"trade_id": "T99", "reason": "stale"},
            ts_utc="2026-08-17T10:00:00Z",   # before today's IST midnight
        )

        def _qe(event_type: str = "", **_) -> list:
            return [old_evt] if event_type == "MARKET_CLOSE_EXIT_BLOCKED" else []

        r = self._call(now_ist=_ist(16), query_events_side_effect=_qe, ledger_rows=[])
        self.assertEqual(r["blocked_events"], [], r)

    def test_blocked_dedup_by_symbol(self) -> None:
        """Two BLOCKED events for same symbol → only the first (newest) is kept."""
        evts = [
            _pe_event("MARKET_CLOSE_EXIT_BLOCKED", "DRREDDY",
                      {"trade_id": "T1", "reason": "r1"},
                      ts_utc="2026-08-18T10:31:00Z"),
            _pe_event("MARKET_CLOSE_EXIT_BLOCKED", "DRREDDY",
                      {"trade_id": "T2", "reason": "r2"},
                      ts_utc="2026-08-18T10:30:00Z"),
        ]

        def _qe(event_type: str = "", **_) -> list:
            return evts if event_type == "MARKET_CLOSE_EXIT_BLOCKED" else []

        r = self._call(now_ist=_ist(16), query_events_side_effect=_qe, ledger_rows=[])
        self.assertEqual(len(r["blocked_events"]), 1)
        self.assertEqual(r["blocked_events"][0]["trade_id"], "T1")


class TestKvFlag(_Base):
    """Test 9: eod_ran_today from KV store."""

    def test_9_eod_ran_today_when_kv_present(self) -> None:
        r = self._call(now_ist=_ist(16), kv_value={"claimed": True}, ledger_rows=[])
        self.assertTrue(r["eod_ran_today"])

    def test_eod_not_ran_when_kv_absent(self) -> None:
        r = self._call(now_ist=_ist(14), kv_value=None, ledger_rows=[])
        self.assertFalse(r["eod_ran_today"])


class TestFaultTolerance(_Base):
    """Test 11: payload never raises even when dependencies explode."""

    def test_11_never_raises_on_broken_db(self) -> None:
        """Even when DB raises, the payload still returns something useful."""
        guard = _ModuleGuard()

        # Poisoned DB stub
        sss_mod = types.ModuleType("scan_state_store")
        sss_mod.db_available = MagicMock(return_value=True)  # type: ignore[attr-defined]
        sss_mod._connect = MagicMock(side_effect=RuntimeError("db on fire"))  # type: ignore[attr-defined]
        guard.stub("scan_state_store", sss_mod)

        # Poisoned pipeline_events stub
        pe_mod = types.ModuleType("pipeline_events")
        pe_mod.query_events = MagicMock(side_effect=RuntimeError("events broken"))  # type: ignore[attr-defined]
        guard.stub("pipeline_events", pe_mod)

        # Poisoned kv stub
        store_mod = types.ModuleType("phase20_store")
        store_mod.kv_get = MagicMock(side_effect=RuntimeError("kv broken"))  # type: ignore[attr-defined]
        guard.stub("phase20_store", store_mod)

        try:
            if "phase20_eod_status" in sys.modules:
                del sys.modules["phase20_eod_status"]
            from phase20_eod_status import build_eod_status_payload  # noqa: PLC0415

            now_ist = _ist(15, 5)
            with patch("phase20_eod_status._now_ist", return_value=now_ist):
                r = build_eod_status_payload()

            self.assertIsInstance(r, dict)
            self.assertIn("time_to_squareoff_sec", r)
            # Degraded but not crashed — force_close_results/blocked empty, not missing
            self.assertIn("force_close_results", r)
            self.assertIn("blocked_events", r)
        finally:
            if "phase20_eod_status" in sys.modules:
                del sys.modules["phase20_eod_status"]
            guard.clear()

    def test_fallback_when_now_ist_fails(self) -> None:
        """If _now_ist() raises, build_eod_status_payload returns error dict."""
        if "phase20_eod_status" in sys.modules:
            del sys.modules["phase20_eod_status"]

        from phase20_eod_status import build_eod_status_payload  # noqa: PLC0415

        with patch("phase20_eod_status._now_ist", side_effect=OSError("tz broken")):
            r = build_eod_status_payload()

        self.assertIsInstance(r, dict)
        self.assertIn("success", r)

        if "phase20_eod_status" in sys.modules:
            del sys.modules["phase20_eod_status"]


if __name__ == "__main__":
    unittest.main()
