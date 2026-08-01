"""Tests for RobotsChecker — covering fail-closed behaviour, policy override, and caching."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.security.robots_checker import RobotsChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Policy override
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_allow_override_skips_robots_fetch():
    """robots_policy='allow' must skip the robots.txt fetch entirely."""
    checker = RobotsChecker()
    # No HTTP calls should happen — if they did the test would hang/fail.
    result = await checker.is_allowed(
        "https://example.com/news", robots_policy="allow"
    )
    assert result is True


# ---------------------------------------------------------------------------
# 404 = no robots.txt = allow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_404_returns_true():
    """404 on robots.txt means no restrictions — should return True."""
    checker = RobotsChecker()
    mock_response = _make_response(404)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await checker.is_allowed("https://example.com/allowed")
    assert result is True


# ---------------------------------------------------------------------------
# Disallow rule
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disallow_rule_returns_false():
    """Explicit Disallow: / must return False."""
    robots_txt = "User-agent: *\nDisallow: /\n"
    checker = RobotsChecker()
    mock_response = _make_response(200, robots_txt)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await checker.is_allowed("https://example.com/news")
    assert result is False


# ---------------------------------------------------------------------------
# Fetch failure → fail closed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_failure_fails_closed():
    """Any exception fetching robots.txt must fail closed (return False)."""
    checker = RobotsChecker()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client_cls.return_value = mock_client

        result = await checker.is_allowed("https://example.com/page")
    assert result is False


# ---------------------------------------------------------------------------
# Non-404 4xx → fail closed and cached
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_404_4xx_fails_closed():
    """Non-404 4xx (e.g. 403) must fail closed."""
    checker = RobotsChecker()
    mock_response = _make_response(403)

    call_count = 0

    async def fake_get(*a, **kw):
        nonlocal call_count
        call_count += 1
        return mock_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_client_cls.return_value = mock_client

        result = await checker.is_allowed("https://example.com/page1")
    assert result is False


@pytest.mark.asyncio
async def test_non_404_4xx_cached_avoids_rehit():
    """After a 403 the result is cached — subsequent calls must NOT re-fetch."""
    checker = RobotsChecker()
    mock_response = _make_response(403)
    call_count = 0

    async def fake_get(*a, **kw):
        nonlocal call_count
        call_count += 1
        return mock_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_client_cls.return_value = mock_client

        await checker.is_allowed("https://example.com/page1")
        await checker.is_allowed("https://example.com/page2")

    assert call_count == 1  # Only one fetch — second call served from cache


# ---------------------------------------------------------------------------
# Parse failure → fail closed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parse_failure_fails_closed():
    """Malformed robots.txt (e.g. binary garbage) must fail closed, not open."""
    checker = RobotsChecker()
    # Return 200 but inject a side effect on _check_path to simulate parse error
    robots_txt = "User-agent: *\nDisallow: /\n"
    mock_response = _make_response(200, robots_txt)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with patch.object(checker, "_check_path", side_effect=RuntimeError("parse error")):
            result = await checker.is_allowed("https://example.com/page")
    assert result is False


# ---------------------------------------------------------------------------
# Cached result reused
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_fetch_is_cached():
    """A successful robots.txt fetch must be cached — only one HTTP call for same domain."""
    robots_txt = "User-agent: *\nAllow: /\n"
    checker = RobotsChecker()
    call_count = 0

    async def fake_get(*a, **kw):
        nonlocal call_count
        call_count += 1
        return _make_response(200, robots_txt)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_client_cls.return_value = mock_client

        await checker.is_allowed("https://example.com/page1")
        await checker.is_allowed("https://example.com/page2")

    assert call_count == 1
