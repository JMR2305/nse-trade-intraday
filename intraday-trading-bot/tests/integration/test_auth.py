"""Integration tests for authentication."""

import pytest


class TestAuth:
    def test_register(self, client):
        response = client.post("/auth/register", params={"user_id": "testuser", "password": "testpass123"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "registered"

    def test_login(self, client):
        client.post("/auth/register", params={"user_id": "logintest", "password": "testpass123"})
        response = client.post("/auth/login", params={"user_id": "logintest", "password": "testpass123"})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid(self, client):
        response = client.post("/auth/login", params={"user_id": "invalid", "password": "wrong"})
        assert response.status_code == 401

    def test_me_authenticated(self, client, auth_headers):
        response = client.get("/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "user_id" in data

    def test_me_unauthenticated(self, client):
        response = client.get("/auth/me")
        assert response.status_code == 403
