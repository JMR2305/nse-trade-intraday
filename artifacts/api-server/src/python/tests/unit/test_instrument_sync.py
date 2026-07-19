"""Tests for instrument synchronisation."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.market_data.instrument_sync import InstrumentSync, InstrumentSyncResult
from src.market_data.provider import MarketDataProvider


class MockInstrumentRepository:
    """In-memory mock of the instrument repository."""

    def __init__(self):
        self._instruments: list[dict] = []
        self._deactivated: set[int] = set()

    async def get_all_for_exchange(self, exchange: str):
        return [
            MockInstrument(**inst)
            for inst in self._instruments
            if inst["exchange"] == exchange and inst["instrument_token"] not in self._deactivated
        ]

    async def insert(self, item: dict):
        self._instruments.append(dict(item))

    async def update_by_uq(self, key, item: dict):
        for inst in self._instruments:
            if (inst["exchange"], inst["tradingsymbol"], inst.get("expiry"), inst.get("strike")) == key:
                inst.update(item)
                return

    async def deactivate(self, instrument_token: int):
        self._deactivated.add(instrument_token)

    async def update_refresh_timestamp(self, exchange: str):
        pass


class MockInstrument:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockProvider(MarketDataProvider):
    def __init__(self, instruments=None):
        self._instruments = instruments or []
        self.subscribed = []
        self.unsubscribed = []
        self._handler = None

    async def connect(self): pass
    async def disconnect(self): pass
    async def subscribe(self, tokens): self.subscribed.extend(tokens)
    async def unsubscribe(self, tokens): self.unsubscribed.extend(tokens)
    def set_tick_handler(self, callback): self._handler = callback

    async def get_historical_bars(self, token, from_dt, to_dt, interval="minute"):
        return []

    async def get_instruments(self, exchange="NSE"):
        return self._instruments

    async def health(self):
        return {"status": "healthy"}


class TestInstrumentSync:
    @pytest.fixture
    def repo(self):
        return MockInstrumentRepository()

    @pytest.mark.asyncio
    async def test_sync_insert_new(self, repo):
        provider = MockProvider([
            {"instrument_token": 1, "exchange": "NSE", "tradingsymbol": "RELIANCE",
             "lot_size": 1, "tick_size": 0.05},
        ])
        sync = InstrumentSync(provider, repo)
        result = await sync.sync("NSE")
        assert result.inserted == 1
        assert result.updated == 0
        assert result.deactivated == 0
        assert result.rejected == 0

    @pytest.mark.asyncio
    async def test_sync_update_existing(self, repo):
        # Pre-populate
        await repo.insert({
            "instrument_token": 1, "exchange": "NSE", "tradingsymbol": "RELIANCE",
            "lot_size": 1, "tick_size": 0.05, "expiry": None, "strike": None,
        })
        provider = MockProvider([
            {"instrument_token": 1, "exchange": "NSE", "tradingsymbol": "RELIANCE",
             "lot_size": 2, "tick_size": 0.05},  # lot_size changed
        ])
        sync = InstrumentSync(provider, repo)
        result = await sync.sync("NSE")
        assert result.inserted == 0
        assert result.updated == 1
        assert result.deactivated == 0

    @pytest.mark.asyncio
    async def test_sync_deactivate_missing(self, repo):
        await repo.insert({
            "instrument_token": 1, "exchange": "NSE", "tradingsymbol": "RELIANCE",
            "lot_size": 1, "tick_size": 0.05, "expiry": None, "strike": None,
        })
        provider = MockProvider([
            {"instrument_token": 2, "exchange": "NSE", "tradingsymbol": "TCS",
             "lot_size": 1, "tick_size": 0.05},
        ])
        sync = InstrumentSync(provider, repo)
        result = await sync.sync("NSE")
        assert result.inserted == 1
        assert result.deactivated == 1

    @pytest.mark.asyncio
    async def test_sync_rejects_invalid(self, repo):
        provider = MockProvider([
            {"instrument_token": -1, "exchange": "NSE", "tradingsymbol": "BAD",
             "lot_size": 1, "tick_size": 0.05},
        ])
        sync = InstrumentSync(provider, repo)
        result = await sync.sync("NSE")
        assert result.rejected == 1
        assert result.inserted == 0

    @pytest.mark.asyncio
    async def test_sync_rejects_exchange_mismatch(self, repo):
        provider = MockProvider([
            {"instrument_token": 1, "exchange": "BSE", "tradingsymbol": "RELIANCE",
             "lot_size": 1, "tick_size": 0.05},
        ])
        sync = InstrumentSync(provider, repo)
        result = await sync.sync("NSE")
        assert result.rejected == 1

    @pytest.mark.asyncio
    async def test_sync_rejects_missing_symbol(self, repo):
        provider = MockProvider([
            {"instrument_token": 1, "exchange": "NSE", "tradingsymbol": "",
             "lot_size": 1, "tick_size": 0.05},
        ])
        sync = InstrumentSync(provider, repo)
        result = await sync.sync("NSE")
        assert result.rejected == 1
