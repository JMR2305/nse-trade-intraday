"""Integration tests for sessions."""

import pytest


class TestSessions:
    def test_start_session(self, client, auth_headers):
        response = client.post("/sessions/start", params={"recovery_mode": "auto"}, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["status"] == "ACTIVE"
        assert data["trading_mode"] == "PAPER"

    def test_start_session_idempotent(self, client, auth_headers):
        response1 = client.post("/sessions/start", params={"recovery_mode": "auto"}, headers=auth_headers)
        session_id_1 = response1.json()["session_id"]
        response2 = client.post("/sessions/start", params={"recovery_mode": "auto"}, headers=auth_headers)
        session_id_2 = response2.json()["session_id"]
        assert session_id_1 == session_id_2

    def test_get_active_session(self, client, auth_headers):
        client.post("/sessions/start", headers=auth_headers)
        response = client.get("/sessions/active", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["active"] is True
        assert "session_id" in data

    def test_end_session(self, client, auth_headers):
        start_response = client.post("/sessions/start", headers=auth_headers)
        session_id = start_response.json()["session_id"]
        response = client.post("/sessions/end", params={"session_id": session_id, "mode": "graceful"}, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "ended"

    def test_get_session_state(self, client, auth_headers):
        start_response = client.post("/sessions/start", headers=auth_headers)
        session_id = start_response.json()["session_id"]
        response = client.get(f"/sessions/{session_id}/state", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert "order_count" in data
        assert "open_position_count" in data
