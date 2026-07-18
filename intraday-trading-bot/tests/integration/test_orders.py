"""Integration tests for orders."""

import pytest


class TestOrders:
    @pytest.fixture
    def active_session(self, client, auth_headers):
        response = client.post("/sessions/start", headers=auth_headers)
        return response.json()["session_id"]

    def test_place_order(self, client, auth_headers, active_session):
        response = client.post("/trading/place_order", params={"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "order_type": "MARKET", "stop_loss": 2400},
                               headers={**auth_headers, "X-Idempotency-Key": "test-order-1"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["mode"] == "PAPER"
        assert "order_id" in data

    def test_place_order_idempotent(self, client, auth_headers, active_session):
        idem_key = "test-idem-1"
        response1 = client.post("/trading/place_order", params={"symbol": "TCS", "side": "BUY", "quantity": 5, "order_type": "MARKET", "stop_loss": 3200},
                                headers={**auth_headers, "X-Idempotency-Key": idem_key})
        assert response1.status_code == 200
        response2 = client.post("/trading/place_order", params={"symbol": "TCS", "side": "BUY", "quantity": 5, "order_type": "MARKET", "stop_loss": 3200},
                                headers={**auth_headers, "X-Idempotency-Key": idem_key})
        assert response2.status_code == 409

    def test_place_order_no_stop_loss(self, client, auth_headers, active_session):
        response = client.post("/trading/place_order", params={"symbol": "INFY", "side": "BUY", "quantity": 10, "order_type": "MARKET"},
                               headers={**auth_headers, "X-Idempotency-Key": "test-no-sl"})
        assert response.status_code in [400, 403]

    def test_place_order_invalid_quantity(self, client, auth_headers, active_session):
        response = client.post("/trading/place_order", params={"symbol": "HDFC", "side": "BUY", "quantity": -5, "order_type": "MARKET"},
                               headers={**auth_headers, "X-Idempotency-Key": "test-invalid-qty"})
        assert response.status_code == 400

    def test_get_orders(self, client, auth_headers, active_session):
        client.post("/trading/place_order", params={"symbol": "SBIN", "side": "BUY", "quantity": 20, "order_type": "MARKET", "stop_loss": 500},
                    headers={**auth_headers, "X-Idempotency-Key": "test-get-orders"})
        response = client.get("/trading/orders", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "orders" in data
        assert len(data["orders"]) >= 1

    def test_cancel_order(self, client, auth_headers, active_session):
        place_response = client.post("/trading/place_order", params={"symbol": "ITC", "side": "BUY", "quantity": 10, "order_type": "MARKET", "stop_loss": 400},
                                     headers={**auth_headers, "X-Idempotency-Key": "test-cancel"})
        order_id = place_response.json()["order_id"]
        response = client.post("/trading/cancel_order", params={"order_id": order_id}, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
