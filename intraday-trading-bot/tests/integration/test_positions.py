"""Integration tests for positions."""

import pytest


class TestPositions:
    @pytest.fixture
    def active_session(self, client, auth_headers):
        response = client.post("/sessions/start", headers=auth_headers)
        return response.json()["session_id"]

    def test_get_positions_empty(self, client, auth_headers, active_session):
        response = client.get("/positions/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["open_positions"] == 0

    def test_get_positions_after_order(self, client, auth_headers, active_session):
        client.post("/trading/place_order", params={"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "order_type": "MARKET", "stop_loss": 2400},
                    headers={**auth_headers, "X-Idempotency-Key": "test-pos-buy"})
        response = client.get("/positions/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["open_positions"] >= 1
        assert "positions" in data
        assert len(data["positions"]) >= 1

    def test_position_summary(self, client, auth_headers, active_session):
        client.post("/trading/place_order", params={"symbol": "TCS", "side": "BUY", "quantity": 5, "order_type": "MARKET", "stop_loss": 3200},
                    headers={**auth_headers, "X-Idempotency-Key": "test-pos-summary"})
        response = client.get("/positions/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_unrealized_pnl" in data
        assert "total_realized_pnl" in data
        assert isinstance(data["open_positions"], int)
