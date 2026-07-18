"""Tests for idempotency."""

import pytest
from datetime import datetime, timezone, timedelta

from src.core.idempotency import IdempotencyManager


class MockIdempotencyRepository:
    def __init__(self):
        self._records = {}

    async def get_by_key(self, key: str):
        return self._records.get(key)

    async def create(self, key: str, operation: str, expires_at: datetime):
        self._records[key] = {"key": key, "operation": operation, "expires_at": expires_at}
        return self._records[key]

    async def is_duplicate(self, key: str):
        record = self._records.get(key)
        if record and record["expires_at"] > datetime.now(timezone.utc):
            return True
        return False


class TestIdempotency:
    @pytest.fixture
    def manager(self):
        return IdempotencyManager(MockIdempotencyRepository())

    def test_generate_key(self, manager):
        key1 = manager.generate_key("ORDER", "test", "123")
        key2 = manager.generate_key("ORDER", "test", "123")
        assert key1 == key2

    def test_generate_key_different_params(self, manager):
        key1 = manager.generate_key("ORDER", "test", "123")
        key2 = manager.generate_key("ORDER", "test", "456")
        assert key1 != key2

    def test_generate_uuid_key(self, manager):
        key1 = manager.generate_uuid_key()
        key2 = manager.generate_uuid_key()
        assert key1 != key2
        assert len(key1) == 36

    @pytest.mark.asyncio
    async def test_check_and_store_new(self, manager):
        result = await manager.check_and_store("key1", "ORDER")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_and_store_duplicate(self, manager):
        await manager.check_and_store("key1", "ORDER")
        result = await manager.check_and_store("key1", "ORDER")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_duplicate(self, manager):
        await manager.check_and_store("key1", "ORDER")
        assert await manager.is_duplicate("key1") is True
        assert await manager.is_duplicate("key2") is False
