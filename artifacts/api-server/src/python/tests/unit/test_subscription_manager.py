"""Tests for subscription manager."""
import pytest

from src.market_data.contracts import SubscriptionRequest
from src.market_data.provider import MarketDataProvider
from src.market_data.subscription_manager import SubscriptionManager


class MockProvider(MarketDataProvider):
    """Mock provider for unit tests — no network required."""

    def __init__(self):
        self.subscribed: list[int] = []
        self.unsubscribed: list[int] = []
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
        return []

    async def get_instruments(self, exchange="NSE"):
        return []

    async def health(self):
        return {"status": "healthy"}


class TestSubscriptionManager:
    @pytest.fixture
    def provider(self):
        return MockProvider()

    @pytest.fixture
    def manager(self, provider):
        mgr = SubscriptionManager(provider, max_subscriptions=10, batch_size=3)
        mgr.set_known_tokens({123, 456, 789})
        return mgr

    @pytest.mark.asyncio
    async def test_subscribe_new_token(self, manager, provider):
        req = SubscriptionRequest(instrument_token=123, consumer_id="c1")
        await manager.subscribe(req)
        assert 123 in provider.subscribed
        assert manager.is_subscribed(123)
        assert manager.consumer_count(123) == 1

    @pytest.mark.asyncio
    async def test_duplicate_subscription_deduped(self, manager, provider):
        req1 = SubscriptionRequest(instrument_token=123, consumer_id="c1")
        req2 = SubscriptionRequest(instrument_token=123, consumer_id="c2")
        await manager.subscribe(req1)
        await manager.subscribe(req2)
        # Provider.subscribe should only be called once for token 123
        assert provider.subscribed.count(123) == 1
        assert manager.consumer_count(123) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_reduces_refcount(self, manager, provider):
        req1 = SubscriptionRequest(instrument_token=123, consumer_id="c1")
        req2 = SubscriptionRequest(instrument_token=123, consumer_id="c2")
        await manager.subscribe(req1)
        await manager.subscribe(req2)
        await manager.unsubscribe(123, "c1")
        assert manager.consumer_count(123) == 1
        assert 123 not in provider.unsubscribed  # still has c2
        await manager.unsubscribe(123, "c2")
        assert 123 in provider.unsubscribed
        assert not manager.is_subscribed(123)

    @pytest.mark.asyncio
    async def test_resubscribe_after_reconnect(self, manager, provider):
        req1 = SubscriptionRequest(instrument_token=123, consumer_id="c1")
        req2 = SubscriptionRequest(instrument_token=456, consumer_id="c2")
        await manager.subscribe(req1)
        await manager.subscribe(req2)
        provider.subscribed.clear()
        await manager.resubscribe_all()
        assert 123 in provider.subscribed
        assert 456 in provider.subscribed

    @pytest.mark.asyncio
    async def test_unknown_token_rejected(self, manager):
        req = SubscriptionRequest(instrument_token=999, consumer_id="c1")
        with pytest.raises(ValueError, match="not in the known instrument master"):
            await manager.subscribe(req)

    @pytest.mark.asyncio
    async def test_max_subscriptions_enforced(self, provider):
        mgr = SubscriptionManager(provider, max_subscriptions=2, batch_size=10)
        mgr.set_known_tokens({1, 2, 3})
        await mgr.subscribe(SubscriptionRequest(instrument_token=1, consumer_id="a"))
        await mgr.subscribe(SubscriptionRequest(instrument_token=2, consumer_id="b"))
        with pytest.raises(RuntimeError, match="subscription limit"):
            await mgr.subscribe(SubscriptionRequest(instrument_token=3, consumer_id="c"))

    @pytest.mark.asyncio
    async def test_snapshot(self, manager):
        await manager.subscribe(SubscriptionRequest(instrument_token=123, consumer_id="c1"))
        await manager.subscribe(SubscriptionRequest(instrument_token=456, consumer_id="c2"))
        snap = manager.snapshot()
        assert snap[123] == {"c1"}
        assert snap[456] == {"c2"}

    @pytest.mark.asyncio
    async def test_batch_subscribe(self, provider):
        mgr = SubscriptionManager(provider, max_subscriptions=10, batch_size=2)
        mgr.set_known_tokens({1, 2, 3, 4})
        for i in range(1, 5):
            await mgr.subscribe(SubscriptionRequest(instrument_token=i, consumer_id="c"))
        # 4 tokens with batch_size=2 → 2 subscribe calls
        # Each call extends the list; we verify all tokens are present
        assert set(provider.subscribed) == {1, 2, 3, 4}
