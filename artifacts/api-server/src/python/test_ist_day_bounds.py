"""Tests for scan_state_store.ist_day_bounds_utc — the IST day boundary used
by the cadence counter and count_scans_today_ist.

Covers the UTC/IST rollover bug: after 18:30 UTC the IST calendar day has
already advanced, so the window must start at 18:30 of the CURRENT UTC date,
not the previous one.
"""
import unittest
from datetime import datetime, timedelta, timezone

from scan_state_store import ist_day_bounds_utc


class TestIstDayBounds(unittest.TestCase):
    def test_mid_ist_session(self):
        # 07:00 UTC = 12:30 IST → IST day started at 18:30 UTC the prior day.
        now = datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)
        start, end = ist_day_bounds_utc(now)
        self.assertEqual(start, datetime(2026, 8, 17, 18, 30, tzinfo=timezone.utc))
        self.assertEqual(end - start, timedelta(days=1))

    def test_after_ist_midnight_rollover(self):
        # 20:00 UTC = 01:30 IST NEXT day → window starts 18:30 UTC same day.
        now = datetime(2026, 8, 18, 20, 0, tzinfo=timezone.utc)
        start, _ = ist_day_bounds_utc(now)
        self.assertEqual(start, datetime(2026, 8, 18, 18, 30, tzinfo=timezone.utc))

    def test_exactly_ist_midnight(self):
        # 18:30 UTC == 00:00 IST → new IST day begins exactly now.
        now = datetime(2026, 8, 18, 18, 30, tzinfo=timezone.utc)
        start, _ = ist_day_bounds_utc(now)
        self.assertEqual(start, now)

    def test_just_before_ist_midnight(self):
        # 18:29 UTC = 23:59 IST → still the previous IST day.
        now = datetime(2026, 8, 18, 18, 29, tzinfo=timezone.utc)
        start, _ = ist_day_bounds_utc(now)
        self.assertEqual(start, datetime(2026, 8, 17, 18, 30, tzinfo=timezone.utc))

    def test_now_always_inside_window(self):
        for hour in range(24):
            now = datetime(2026, 8, 18, hour, 0, tzinfo=timezone.utc)
            start, end = ist_day_bounds_utc(now)
            self.assertTrue(start <= now < end, f"hour={hour}")


if __name__ == "__main__":
    unittest.main()
