"""Tests for market-data contracts."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.market_data.contracts import (
    CompletedBar,
    DataGap,
    DataQualityEvent,
    DataQualityState,
    DataQualityStatus,
    MarketDepthLevel,
    Quote,
    SubscriptionRequest,
    Tick,
)


class TestTick:
    def test_tick_creation(self):
        tick = Tick(
            instrument_token=123,
            exchange_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            received_at=datetime(2026, 7, 20, 9, 15, 1, tzinfo=timezone.utc),
            last_price=Decimal("100.50"),
            last_quantity=10,
            cumulative_volume=1000,
            average_price=Decimal("100.00"),
            open=Decimal("99.00"),
            high=Decimal("101.00"),
            low=Decimal("98.00"),
            close=Decimal("100.50"),
            change=Decimal("1.50"),
            open_interest=5000,
            buy_quantity=200,
            sell_quantity=150,
        )
        assert tick.instrument_token == 123
        assert tick.last_price == Decimal("100.50")
        assert tick.fingerprint() == (123, datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc), Decimal("100.50"), 1000)

    def test_tick_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            Tick(
                instrument_token=123,
                exchange_timestamp=datetime(2026, 7, 20, 9, 15, 0),  # naive
                received_at=datetime(2026, 7, 20, 9, 15, 1, tzinfo=timezone.utc),
                last_price=Decimal("100"),
                last_quantity=1,
                cumulative_volume=1,
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
            )

    def test_tick_immutable(self):
        tick = Tick(
            instrument_token=123,
            exchange_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            received_at=datetime(2026, 7, 20, 9, 15, 1, tzinfo=timezone.utc),
            last_price=Decimal("100"),
            last_quantity=1,
            cumulative_volume=1,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
        )
        with pytest.raises(ValidationError):
            tick.last_price = Decimal("200")


class TestCompletedBar:
    def test_bar_floors_to_minute(self):
        bar = CompletedBar(
            instrument_token=123,
            timestamp=datetime(2026, 7, 20, 9, 15, 30, tzinfo=timezone.utc),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=100,
        )
        assert bar.timestamp.second == 0
        assert bar.timestamp.microsecond == 0

    def test_bar_backfilled_flag(self):
        bar = CompletedBar(
            instrument_token=123,
            timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=100,
            is_backfilled=True,
            source="backfill",
        )
        assert bar.is_backfilled is True
        assert bar.source == "backfill"


class TestDataGap:
    def test_gap_creation(self):
        gap = DataGap(
            instrument_token=123,
            start=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 20, 9, 16, 0, tzinfo=timezone.utc),
        )
        assert gap.gap_type == "MISSING"
        assert gap.resolution_attempts == 0


class TestDataQualityStatus:
    def test_quality_state_enum(self):
        assert DataQualityState.LIVE.value == "LIVE"
        assert DataQualityState.GAP_DETECTED.value == "GAP_DETECTED"

    def test_quality_event(self):
        event = DataQualityEvent(
            instrument_token=123,
            previous_state=DataQualityState.DISCONNECTED,
            new_state=DataQualityState.LIVE,
            reason="provider reconnected",
            occurred_at=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        assert event.new_state == DataQualityState.LIVE


class TestMarketDepthLevel:
    def test_depth_level(self):
        level = MarketDepthLevel(price=Decimal("100.50"), quantity=100, orders=5)
        assert level.price == Decimal("100.50")
        assert level.orders == 5

    def test_depth_level_negative_quantity_rejected(self):
        with pytest.raises(ValidationError):
            MarketDepthLevel(price=Decimal("100"), quantity=-1)


class TestSubscriptionRequest:
    def test_subscription_request(self):
        req = SubscriptionRequest(instrument_token=123, consumer_id="strategy_1")
        assert req.priority == 0

    def test_subscription_request_with_priority(self):
        req = SubscriptionRequest(instrument_token=123, consumer_id="strategy_1", priority=5)
        assert req.priority == 5
