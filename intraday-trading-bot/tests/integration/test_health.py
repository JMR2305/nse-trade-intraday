"""Integration tests for health endpoints."""

import pytest


class TestHealth:
    def test_liveness(self, client):
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_readiness_no_db(self, client):
        response = client.get("/health/ready")
        assert response.status_code in [200, 503]

    def test_detailed_health(self, client):
        response = client.get("/health/detailed")
        assert response.status_code in [200, 503]
        if response.status_code == 200:
            data = response.json()
            assert "status" in data
            assert "version" in data
            assert data["trading_mode"] == "PAPER"
