"""Tests for market calendar."""

from datetime import datetime, time

import pytest

from src.core.market_calendar import MarketCalendar, IST


class TestMarketCalendar:
    @pytest.fixture
    def calendar(self):
        return MarketCalendar()

    def test_market_hours(self, calendar):
        assert calendar.open == time(9, 15)
        assert calendar.close == time(15, 30)

    def test_is_market_open_weekday(self, calendar):
        dt = datetime(2026, 7, 20, 10, 0, tzinfo=IST)
        assert calendar.is_market_open(dt) is True

    def test_is_market_open_weekend(self, calendar):
        dt = datetime(2026, 7, 18, 10, 0, tzinfo=IST)
        assert calendar.is_market_open(dt) is False

    def test_is_market_open_before_hours(self, calendar):
        dt = datetime(2026, 7, 20, 8, 0, tzinfo=IST)
        assert calendar.is_market_open(dt) is False

    def test_is_market_open_after_hours(self, calendar):
        dt = datetime(2026, 7, 20, 16, 0, tzinfo=IST)
        assert calendar.is_market_open(dt) is False

    def test_is_pre_open(self, calendar):
        dt = datetime(2026, 7, 20, 9, 5, tzinfo=IST)
        assert calendar.is_pre_open(dt) is True

    def test_is_post_close(self, calendar):
        dt = datetime(2026, 7, 20, 15, 35, tzinfo=IST)
        assert calendar.is_post_close(dt) is True

    def test_to_utc(self, calendar):
        ist = datetime(2026, 7, 20, 10, 0, tzinfo=IST)
        utc = calendar.to_utc(ist)
        assert utc.hour == 4

    def test_get_session_date(self, calendar):
        dt = datetime(2026, 7, 20, 10, 0, tzinfo=IST)
        assert calendar.get_session_date(dt) == "20260720"
