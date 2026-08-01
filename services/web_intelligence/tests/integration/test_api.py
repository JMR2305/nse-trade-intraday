"""Integration tests for API endpoints."""
import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_ready_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "checks" in data
        assert data["checks"]["database"] is True
        assert data["checks"]["storage"] is True


@pytest.mark.asyncio
async def test_list_sources():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/sources")
        assert response.status_code == 200
        data = response.json()
        assert "sources" in data
        assert len(data["sources"]) >= 2


@pytest.mark.asyncio
async def test_get_source():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/sources/generic_test_page")
        assert response.status_code == 200
        assert response.json()["id"] == "generic_test_page"


@pytest.mark.asyncio
async def test_get_source_not_found():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/sources/nonexistent")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_pagination_limits():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/intelligence?limit=200")
        assert response.status_code == 422
