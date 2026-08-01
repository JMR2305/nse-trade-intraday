"""Tests for source registry."""
import pytest

from app.domain.enums import SourceType
from app.domain.models import ApprovedSource
from app.repositories.source_registry import SourceRegistry, create_default_registry


def test_register_and_get():
    reg = SourceRegistry()
    src = ApprovedSource(
        id="test-1", name="Test", base_url="https://example.com",
        source_type=SourceType.GENERIC_STATIC_PAGE, user_agent="Test/1.0",
        parser_name="test_parser",
    )
    reg.register(src)
    assert reg.get("test-1") == src


def test_list_enabled():
    reg = SourceRegistry()
    reg.register(ApprovedSource(
        id="e1", name="Enabled", base_url="https://a.com",
        source_type=SourceType.GENERIC_STATIC_PAGE, enabled=True,
        user_agent="Test", parser_name="p",
    ))
    reg.register(ApprovedSource(
        id="d1", name="Disabled", base_url="https://b.com",
        source_type=SourceType.GENERIC_STATIC_PAGE, enabled=False,
        user_agent="Test", parser_name="p",
    ))
    enabled = reg.list_enabled()
    assert len(enabled) == 1
    assert enabled[0].id == "e1"


@pytest.mark.asyncio
async def test_disable_source():
    reg = create_default_registry()
    assert await reg.disable("generic_test_page") is True
    src = reg.get("generic_test_page")
    assert src.enabled is False


@pytest.mark.asyncio
async def test_enable_source():
    reg = create_default_registry()
    await reg.disable("generic_test_page")
    assert await reg.enable("generic_test_page") is True
    assert reg.get("generic_test_page").enabled is True


@pytest.mark.asyncio
async def test_disable_unknown_source():
    reg = SourceRegistry()
    assert await reg.disable("unknown") is False
