"""Tests for backfill coordinator."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.market_data.backfill import BackfillCoordinator, BackfillSettings
from src.market_data.contracts import CompletedBar, DataGap
from src.market_data.provider import MarketDataProvider
from src.database.repositories.minute_bars import MinuteBarRepository


class MockProvider(MarketDataProvider):
    """Mock provider with controllable historical data."""

    def __init__(self, bars=None, raise_on_call=False):
        self._bars = bars or []
        self._raise = raise_on_call
        self.subscribed = []
        self.unsubscribed = []
        self._handler = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def subscribe(self, tokens):
        self.subscribed.extend(tokens)

    async def unsubscribe(self, tokens):
        self.unsubscribed.extend(tokens)

    def set_tick_handler(self, callback):
        self._handler = callback

    async def get_historical_bars(self, token, from_dt, to_dt, interval="minute"):
        if self._raise:
            raise RuntimeError("provider error")
        return [
            b for b in self._bars
            if b.instrument_token == token and b.timestamp >= from_dt and b.timestamp < to_dt
        ]

    async def get_instruments(self, exchange="NSE"):
        return []

    async def health(self):
        return {"status": "healthy"}


class MockMinuteBarRepository:
    """In-memory mock of MinuteBarRepository."""

    def __init__(self):
        self._bars: list[CompletedBar] = []

    async def insert_completed_bar(self, bar, session=None):
        self._bars.append(bar)

    async def insert_many(self, bars, session=None):
        self._bars.extend(bars)

    async def get_range(self, token, start, end, session=None):
        return [b for b in self._bars if b.instrument_token == token and start <= b.timestamp < end]

    async def get_latest(self, token, session=None, before=None):
        candidates = [b for b in self._bars if b.instrument_token == token]
        if before:
            candidates = [b for b in candidates if b.timestamp < before]
        if not candidates:
            return None
        return max(candidates, key=lambda b: b.timestamp)

    async def find_gaps(self, token, start, end, session=None):
        return []

    async def upsert_backfilled_bar(self, bar, policy, session=None):
        existing = await self.get_latest(bar.instrument_token, session, before=bar.timestamp + timedelta(minutes=1))
        if existing and existing.timestamp == bar.timestamp:
            if policy == "OVERWRITE":
                self._bars = [b for b in self._bars if not (b.instrument_token == bar.instrument_token and b.timestamp == bar.timestamp)]
                self._bars.append(bar)
            elif policy == "INSERT_ONLY":
                return
            # SKIP: do nothing
        else:
            self._bars.append(bar)


class TestBackfillCoordinator:
    @pytest.fixture
    def repo(self):
        return MockMinuteBarRepository()

    @pytest.mark.asyncio
    async def test_backfill_merge_no_conflict(self, repo):
        gap = DataGap(
            instrument_token=123,
            start=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 20, 9, 17, 0, tzinfo=timezone.utc),
        )
        bars = [
            CompletedBar(
                instrument_token=123,
                timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
                open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
                volume=100, is_backfilled=True, source="backfill",
            ),
            CompletedBar(
                instrument_token=123,
                timestamp=datetime(2026, 7, 20, 9, 16, 0, tzinfo=timezone.utc),
                open=Decimal("101"), high=Decimal("102"), low=Decimal("100"), close=Decimal("101"),
                volume=200, is_backfilled=True, source="backfill",
            ),
        ]
        provider = MockProvider(bars=bars)
        coordinator = BackfillCoordinator(provider, repo, BackfillSettings(max_retries=1))
        coordinator.queue_gap(gap)
        result = await coordinator.process_queue()
        assert result.bars_inserted == 2
        assert result.bars_skipped == 0
        assert result.conflicts_detected == 0
        assert len(result.unresolved_gaps) == 0

    @pytest.mark.asyncio
    async def test_backfill_conflict_detected(self, repo):
        # Pre-populate with a live bar
        live_bar = CompletedBar(
            instrument_token=123,
            timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
            volume=100, is_backfilled=False, source="live",
        )
        await repo.upsert_backfilled_bar(live_bar, "INSERT_ONLY")

        gap = DataGap(
            instrument_token=123,
            start=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 20, 9, 16, 0, tzinfo=timezone.utc),
        )
        # Backfill bar with different close
        backfill_bar = CompletedBar(
            instrument_token=123,
            timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("105"),  # different!
            volume=100, is_backfilled=True, source="backfill",
        )
        provider = MockProvider(bars=[backfill_bar])
        coordinator = BackfillCoordinator(
            provider, repo, BackfillSettings(conflict_policy="SKIP", max_retries=1)
        )
        coordinator.queue_gap(gap)
        result = await coordinator.process_queue()
        assert result.conflicts_detected == 1
        assert result.bars_skipped == 1
        assert result.bars_inserted == 0

    @pytest.mark.asyncio
    async def test_backfill_conflict_overwrite(self, repo):
        live_bar = CompletedBar(
            instrument_token=123,
            timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
            volume=100, is_backfilled=False, source="live",
        )
        await repo.upsert_backfilled_bar(live_bar, "INSERT_ONLY")

        gap = DataGap(
            instrument_token=123,
            start=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 20, 9, 16, 0, tzinfo=timezone.utc),
        )
        backfill_bar = CompletedBar(
            instrument_token=123,
            timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("105"),
            volume=100, is_backfilled=True, source="backfill",
        )
        provider = MockProvider(bars=[backfill_bar])
        coordinator = BackfillCoordinator(
            provider, repo, BackfillSettings(conflict_policy="OVERWRITE", max_retries=1)
        )
        coordinator.queue_gap(gap)
        result = await coordinator.process_queue()
        assert result.conflicts_detected == 1
        assert result.bars_overwritten == 1
        # Verify the bar was actually overwritten
        latest = await repo.get_latest(123)
        assert latest.close == Decimal("105")

    @pytest.mark.asyncio
    async def test_backfill_retry_on_failure(self, repo):
        gap = DataGap(
            instrument_token=123,
            start=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 20, 9, 16, 0, tzinfo=timezone.utc),
        )
        # Provider that fails first 2 times, succeeds on 3rd
        provider = FailingThenSucceedingProvider(fail_count=2)
        coordinator = BackfillCoordinator(
            provider, repo, BackfillSettings(max_retries=3, base_delay_seconds=0.01)
        )
        coordinator.queue_gap(gap)
        result = await coordinator.process_queue()
        assert result.bars_inserted == 1
        assert len(result.unresolved_gaps) == 0

    @pytest.mark.asyncio
    async def test_unresolved_gap_when_all_retries_fail(self, repo):
        gap = DataGap(
            instrument_token=123,
            start=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 20, 9, 16, 0, tzinfo=timezone.utc),
        )
        provider = MockProvider(raise_on_call=True)
        coordinator = BackfillCoordinator(
            provider, repo, BackfillSettings(max_retries=2, base_delay_seconds=0.01)
        )
        coordinator.queue_gap(gap)
        result = await coordinator.process_queue()
        assert len(result.unresolved_gaps) == 1
        assert result.bars_inserted == 0


class FailingThenSucceedingProvider(MarketDataProvider):
    """Provider that fails N times then returns a bar."""

    def __init__(self, fail_count: int):
        self._fail_count = fail_count
        self._calls = 0
        self.subscribed = []
        self.unsubscribed = []
        self._handler = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def subscribe(self, tokens):
        self.subscribed.extend(tokens)

    async def unsubscribe(self, tokens):
        self.unsubscribed.extend(tokens)

    def set_tick_handler(self, callback):
        self._handler = callback

    async def get_historical_bars(self, token, from_dt, to_dt, interval="minute"):
        self._calls += 1
        if self._calls <= self._fail_count:
            raise RuntimeError(f"simulated failure #{self._calls}")
        return [
            CompletedBar(
                instrument_token=token,
                timestamp=from_dt,
                open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
                volume=100, is_backfilled=True, source="backfill",
            )
        ]

    async def get_instruments(self, exchange="NSE"):
        return []

    async def health(self):
        return {"status": "healthy"}
