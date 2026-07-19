"""Tests for data quality tracker."""
from datetime import datetime, timedelta, timezone

import pytest

from src.market_data.quality import DataQualitySettings, DataQualityTracker
from src.market_data.contracts import DataQualityState


class TestDataQualityTracker:
    @pytest.fixture
    def tracker(self):
        return DataQualityTracker()

    @pytest.mark.asyncio
    async def test_initial_state_is_disconnected(self, tracker):
        status = await tracker.get_status(123)
        assert status is None  # not yet tracked

    @pytest.mark.asyncio
    async def test_live_tick_sets_live(self, tracker):
        now = datetime.now(timezone.utc)
        await tracker.record_tick(123, now, now)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.LIVE

    @pytest.mark.asyncio
    async def test_delayed_tick(self, tracker):
        now = datetime.now(timezone.utc)
        exchange_ts = now - timedelta(seconds=6)  # >5s threshold
        await tracker.record_tick(123, exchange_ts, now)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.DELAYED

    @pytest.mark.asyncio
    async def test_stale_tick(self, tracker):
        now = datetime.now(timezone.utc)
        exchange_ts = now - timedelta(seconds=31)  # >30s threshold
        await tracker.record_tick(123, exchange_ts, now)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.STALE

    @pytest.mark.asyncio
    async def test_disconnected_tick(self, tracker):
        now = datetime.now(timezone.utc)
        exchange_ts = now - timedelta(seconds=61)  # >60s threshold
        await tracker.record_tick(123, exchange_ts, now)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_gap_detected(self, tracker):
        now = datetime.now(timezone.utc)
        await tracker.record_gap(123, now)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.GAP_DETECTED

    @pytest.mark.asyncio
    async def test_out_of_order(self, tracker):
        now = datetime.now(timezone.utc)
        await tracker.record_out_of_order(123, now)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.OUT_OF_ORDER

    @pytest.mark.asyncio
    async def test_backfill_start_end(self, tracker):
        await tracker.record_backfill_start(123)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.BACKFILLING
        await tracker.record_backfill_end(123)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.LIVE

    @pytest.mark.asyncio
    async def test_disconnect_reconnect(self, tracker):
        await tracker.record_disconnect(123)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.DISCONNECTED
        await tracker.record_reconnect(123)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.LIVE

    @pytest.mark.asyncio
    async def test_event_callback(self, tracker):
        events = []
        tracker.on_event(lambda e: events.append(e))
        now = datetime.now(timezone.utc)
        await tracker.record_tick(123, now, now)
        await tracker.record_gap(123, now)
        assert len(events) == 1  # only the gap transition (LIVE→GAP_DETECTED)
        assert events[0].previous_state == DataQualityState.LIVE
        assert events[0].new_state == DataQualityState.GAP_DETECTED

    @pytest.mark.asyncio
    async def test_no_duplicate_events_on_same_state(self, tracker):
        events = []
        tracker.on_event(lambda e: events.append(e))
        now = datetime.now(timezone.utc)
        await tracker.record_tick(123, now, now)
        await tracker.record_tick(123, now, now)
        assert len(events) == 0  # both are LIVE, no transition

    @pytest.mark.asyncio
    async def test_get_all_statuses(self, tracker):
        now = datetime.now(timezone.utc)
        await tracker.record_tick(111, now, now)
        await tracker.record_tick(222, now, now)
        statuses = await tracker.get_all_statuses()
        assert len(statuses) == 2
        tokens = {s.instrument_token for s in statuses}
        assert tokens == {111, 222}

    @pytest.mark.asyncio
    async def test_custom_settings(self):
        settings = DataQualitySettings(
            delayed_threshold_ms=1_000,
            stale_threshold_ms=5_000,
            disconnected_threshold_ms=10_000,
        )
        tracker = DataQualityTracker(settings)
        now = datetime.now(timezone.utc)
        exchange_ts = now - timedelta(seconds=2)
        await tracker.record_tick(123, exchange_ts, now)
        status = await tracker.get_status(123)
        assert status.state == DataQualityState.DELAYED
