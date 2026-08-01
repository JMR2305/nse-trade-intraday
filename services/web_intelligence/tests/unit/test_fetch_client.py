"""Tests for fetch client behavior."""
import pytest

from app.collectors.fetch_client import FetchClient


@pytest.mark.asyncio
async def test_concurrency_limit():
    client = FetchClient(concurrency_limit=2)
    assert client.concurrency_limit == 2


@pytest.mark.asyncio
async def test_max_response_size():
    client = FetchClient(max_response_size=1024)
    assert client.max_response_size == 1024


@pytest.mark.asyncio
async def test_retry_count():
    client = FetchClient(retry_count=5)
    assert client.retry_count == 5


@pytest.mark.asyncio
async def test_url_validation_blocks_bad_urls():
    client = FetchClient()
    result = await client.fetch("file:///etc/passwd")
    assert result.data_quality_status.value == "blocked"


@pytest.mark.asyncio
async def test_url_validation_blocks_localhost_in_production(monkeypatch):
    monkeypatch.setattr("app.collectors.fetch_client.settings.production_mode", True)
    client = FetchClient()
    result = await client.fetch("https://localhost/test")
    assert result.data_quality_status.value == "blocked"
