"""
tests/unit/test_pipeline_stats_next_scan.py

Unit tests for the next_scan_expected_ist computation inside
pipeline_stats.get_pipeline_stats().

These tests mock out every external dependency so the module works
without a running database or network.
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# ── Minimal stubs for every import pipeline_stats relies on ───────────────────

def _make_stub(name: str, attrs: dict | None = None) -> types.ModuleType:
    m = types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(m, k, v)
    return m


def _patch_deps(
    scan_interval_minutes: int = 30,
    scheduler_next_due: str | None = None,
) -> None:
    """Install minimal stub modules so pipeline_stats can be imported."""

    # market_hours — provide the real helpers from market_hours.py so the
    # holiday / weekend logic runs properly.  We mock only the clock.
    import importlib.util, os, pathlib
    root = pathlib.Path(__file__).parents[2]  # artifacts/api-server/src/python
    mh_path = root / "market_hours.py"
    spec = importlib.util.spec_from_file_location("market_hours", mh_path)
    mh = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mh)  # type: ignore[union-attr]
    sys.modules["market_hours"] = mh

    # phase20_store stubs
    def _fake_get_settings():
        return {"scan_interval_minutes": scan_interval_minutes}

    def _fake_get_scheduler_health():
        # get_scheduler_health() returns a flat dict; next_due_at is at the
        # top level (not nested under "state").
        if scheduler_next_due is not None:
            return {"next_due_at": scheduler_next_due}
        # Simulate DB unavailable or no row yet — no next_due_at key
        return {}

    def _fake_kv_get(_key):
        return None

    ps_stub = _make_stub("phase20_store", {
        "get_settings": _fake_get_settings,
        "get_scheduler_health": _fake_get_scheduler_health,
        "kv_get": _fake_kv_get,
    })
    sys.modules["phase20_store"] = ps_stub

    # phase20_gates stub
    sys.modules["phase20_gates"] = _make_stub("phase20_gates", {
        "evaluate_entries": lambda: {"global_pass": False, "global_gates": [], "candidates": [], "eligible_count": 0},
    })

    # phase20_executor stub
    sys.modules["phase20_executor"] = _make_stub("phase20_executor", {
        "get_ledger": lambda _n: [],
        "get_open_trades": lambda: [],
    })

    # phase15_scan_context stub — no scan available
    sys.modules["phase15_scan_context"] = _make_stub("phase15_scan_context", {
        "build_scan_context": lambda: {"available": False},
    })


def _next_scan_from_stats() -> str | None:
    """Import + call get_pipeline_stats() and return next_scan_expected_ist."""
    # Remove cached module so each test gets a fresh import
    sys.modules.pop("pipeline_stats", None)
    import pipeline_stats  # noqa: PLC0415
    result = pipeline_stats.get_pipeline_stats()
    return result.get("next_scan_expected_ist")


def _ist(h: int, m: int, d: date | None = None) -> datetime:
    target_date = d or date.today()
    return datetime(target_date.year, target_date.month, target_date.day, h, m, 0, tzinfo=IST)


class TestNextScanExpectedIst(unittest.TestCase):
    """next_scan_expected_ist edge cases."""

    def setUp(self) -> None:
        # Remove any stale cached module
        sys.modules.pop("pipeline_stats", None)

    def tearDown(self) -> None:
        # Clean up stubs to avoid polluting other test modules
        for mod in [
            "pipeline_stats", "market_hours", "phase20_store",
            "phase20_gates", "phase20_executor", "phase15_scan_context",
        ]:
            sys.modules.pop(mod, None)

    # ── Scenario 1: before market open on a regular trading day ──────────────

    def test_before_open_returns_today_0915(self) -> None:
        """08:00 IST on a Mon–Fri non-holiday → next scan at 09:15 today."""
        _patch_deps()
        # Pick a known trading day: Monday 2026-08-17 (not a holiday)
        today = date(2026, 8, 17)
        fake_now = _ist(8, 0, today)

        import importlib.util as _ilu
        import pathlib
        import sys as _sys
        import unittest.mock as mock

        root = pathlib.Path(__file__).parents[2]
        spec = _ilu.spec_from_file_location("market_hours", root / "market_hours.py")
        mh = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mh)  # type: ignore[union-attr]
        mh.now_ist = lambda: fake_now
        _sys.modules["market_hours"] = mh

        _sys.modules.pop("pipeline_stats", None)
        import pipeline_stats  # noqa: PLC0415
        with mock.patch("pipeline_stats.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            result = pipeline_stats.get_pipeline_stats()

        val = result.get("next_scan_expected_ist")
        self.assertIsNotNone(val, "next_scan_expected_ist should be set")
        dt_ist = datetime.fromisoformat(val).astimezone(IST)  # type: ignore[arg-type]
        self.assertEqual(dt_ist.date(), today)
        self.assertEqual(dt_ist.hour, 9)
        self.assertEqual(dt_ist.minute, 15)

    # ── Scenario 2: scheduler provides next_due_at ───────────────────────────

    def test_scheduler_next_due_takes_priority(self) -> None:
        """When the scheduler has next_due_at, that value is returned verbatim."""
        expected = "2026-08-17T05:30:00Z"  # arbitrary scheduler-computed time
        _patch_deps(scheduler_next_due=expected)
        _sys_ref = sys  # avoid shadowing in inner scope
        _sys_ref.modules.pop("pipeline_stats", None)
        import pipeline_stats  # noqa: PLC0415
        result = pipeline_stats.get_pipeline_stats()
        self.assertEqual(result.get("next_scan_expected_ist"), expected)

    # ── Scenario 3: after market close on a Friday → Monday 09:15 ────────────

    def test_after_close_friday_skips_weekend(self) -> None:
        """After 15:30 IST on a Friday → next scan is Monday 09:15, not Saturday."""
        _patch_deps()
        # 2026-08-21 is a Friday (weekday() == 4)
        friday = date(2026, 8, 21)
        assert friday.weekday() == 4, f"Expected Friday, got weekday {friday.weekday()}"
        fake_now = _ist(16, 0, friday)  # 16:00 IST — after post-close

        import importlib.util as _ilu, pathlib, sys as _sys
        root = pathlib.Path(__file__).parents[2]
        spec = _ilu.spec_from_file_location("market_hours", root / "market_hours.py")
        mh = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mh)
        mh.now_ist = lambda: fake_now
        _sys.modules["market_hours"] = mh

        _sys.modules.pop("pipeline_stats", None)
        import pipeline_stats  # noqa: PLC0415
        import unittest.mock as mock
        with mock.patch("pipeline_stats.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            result = pipeline_stats.get_pipeline_stats()

        val = result.get("next_scan_expected_ist")
        self.assertIsNotNone(val)
        dt_ist = datetime.fromisoformat(val).astimezone(IST)  # type: ignore[arg-type]
        monday = date(2026, 8, 24)
        self.assertEqual(dt_ist.date(), monday, f"Expected Monday {monday}, got {dt_ist.date()}")
        self.assertEqual(dt_ist.hour, 9)
        self.assertEqual(dt_ist.minute, 15)

    # ── Scenario 4: during market hours uses the configured interval ──────────

    def test_during_market_hours_uses_interval(self) -> None:
        """10:00 IST with a 30-min interval → next slot at 10:15 (next 30-min boundary)."""
        _patch_deps(scan_interval_minutes=30)
        today = date(2026, 8, 17)  # Monday — trading day
        fake_now = _ist(10, 0, today)  # 10:00 IST

        import importlib.util as _ilu, pathlib, sys as _sys
        root = pathlib.Path(__file__).parents[2]
        spec = _ilu.spec_from_file_location("market_hours", root / "market_hours.py")
        mh = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mh)
        mh.now_ist = lambda: fake_now
        _sys.modules["market_hours"] = mh

        _sys.modules.pop("pipeline_stats", None)
        import pipeline_stats  # noqa: PLC0415
        import unittest.mock as mock
        with mock.patch("pipeline_stats.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            result = pipeline_stats.get_pipeline_stats()

        val = result.get("next_scan_expected_ist")
        self.assertIsNotNone(val)
        dt_ist = datetime.fromisoformat(val).astimezone(IST)  # type: ignore[arg-type]
        self.assertEqual(dt_ist.date(), today)
        # 10:00 → elapsed = 45 min since 09:15 → next 30-min slot = 60 min → 10:15
        self.assertEqual(dt_ist.hour, 10)
        self.assertEqual(dt_ist.minute, 15)

    # ── Scenario 5: holiday → skip to next trading day ───────────────────────

    def test_holiday_skips_to_next_trading_day(self) -> None:
        """Independence Day (2026-08-15, Saturday) — next trading day is Mon 2026-08-17."""
        _patch_deps()
        # 2026-08-15 is a Saturday AND a holiday; next trading day should be Mon 08-17
        holiday = date(2026, 8, 15)
        fake_now = _ist(10, 0, holiday)

        import importlib.util as _ilu, pathlib, sys as _sys
        root = pathlib.Path(__file__).parents[2]
        spec = _ilu.spec_from_file_location("market_hours", root / "market_hours.py")
        mh = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mh)
        mh.now_ist = lambda: fake_now
        _sys.modules["market_hours"] = mh

        _sys.modules.pop("pipeline_stats", None)
        import pipeline_stats  # noqa: PLC0415
        import unittest.mock as mock
        with mock.patch("pipeline_stats.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            result = pipeline_stats.get_pipeline_stats()

        val = result.get("next_scan_expected_ist")
        self.assertIsNotNone(val)
        dt_ist = datetime.fromisoformat(val).astimezone(IST)  # type: ignore[arg-type]
        self.assertEqual(dt_ist.date(), date(2026, 8, 17))  # Monday after holiday weekend
        self.assertEqual(dt_ist.hour, 9)
        self.assertEqual(dt_ist.minute, 15)


if __name__ == "__main__":
    unittest.main()
