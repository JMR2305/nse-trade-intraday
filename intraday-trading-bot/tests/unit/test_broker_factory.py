"""Tests for RC-10D broker factory (Group J).

Covers:
  - Paper mode is the default (force_paper=True)
  - PaperBroker returned when live conditions not met
  - Factory reads environment variables correctly
  - No live broker returned without all 5 conditions
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from src.brokers.factory import create_broker_adapter
from src.brokers.paper_broker import PaperBroker


class TestBrokerFactory:
    def test_default_returns_paper_broker(self):
        adapter = create_broker_adapter()
        assert isinstance(adapter, PaperBroker)

    def test_force_paper_true_always_paper(self, monkeypatch):
        monkeypatch.setenv("ZERODHA_ENABLED", "true")
        monkeypatch.setenv("ZERODHA_PAPER_TRADING", "false")
        monkeypatch.setenv("ZERODHA_LIVE_TRADING_ENABLED", "true")
        adapter = create_broker_adapter(force_paper=True)
        assert isinstance(adapter, PaperBroker)

    def test_missing_enabled_env_returns_paper(self, monkeypatch):
        monkeypatch.setenv("ZERODHA_ENABLED", "false")
        monkeypatch.setenv("ZERODHA_PAPER_TRADING", "false")
        monkeypatch.setenv("ZERODHA_LIVE_TRADING_ENABLED", "true")
        adapter = create_broker_adapter(force_paper=False)
        assert isinstance(adapter, PaperBroker)

    def test_paper_trading_true_returns_paper(self, monkeypatch):
        monkeypatch.setenv("ZERODHA_ENABLED", "true")
        monkeypatch.setenv("ZERODHA_PAPER_TRADING", "true")
        monkeypatch.setenv("ZERODHA_LIVE_TRADING_ENABLED", "true")
        adapter = create_broker_adapter(force_paper=False)
        assert isinstance(adapter, PaperBroker)

    def test_missing_live_flag_returns_paper(self, monkeypatch):
        monkeypatch.setenv("ZERODHA_ENABLED", "true")
        monkeypatch.setenv("ZERODHA_PAPER_TRADING", "false")
        monkeypatch.setenv("ZERODHA_LIVE_TRADING_ENABLED", "false")
        adapter = create_broker_adapter(force_paper=False)
        assert isinstance(adapter, PaperBroker)

    def test_missing_api_key_returns_paper(self, monkeypatch):
        monkeypatch.setenv("ZERODHA_ENABLED", "true")
        monkeypatch.setenv("ZERODHA_PAPER_TRADING", "false")
        monkeypatch.setenv("ZERODHA_LIVE_TRADING_ENABLED", "true")
        monkeypatch.delenv("ZERODHA_API_KEY", raising=False)
        adapter = create_broker_adapter(force_paper=False)
        assert isinstance(adapter, PaperBroker)

    def test_missing_api_secret_returns_paper(self, monkeypatch):
        monkeypatch.setenv("ZERODHA_ENABLED", "true")
        monkeypatch.setenv("ZERODHA_PAPER_TRADING", "false")
        monkeypatch.setenv("ZERODHA_LIVE_TRADING_ENABLED", "true")
        monkeypatch.setenv("ZERODHA_API_KEY", "key123")
        monkeypatch.delenv("ZERODHA_API_SECRET", raising=False)
        adapter = create_broker_adapter(force_paper=False)
        assert isinstance(adapter, PaperBroker)


class TestPaperBrokerDefaultBehavior:
    """Verify PaperBroker still works identically post-RC-10D."""

    @pytest.mark.asyncio
    async def test_paper_place_order(self):
        from src.brokers.interface import OrderRequest
        from decimal import Decimal
        broker = PaperBroker()
        req = OrderRequest(
            symbol="RELIANCE",
            side="BUY",
            quantity=10,
            order_type="MARKET",
            price=Decimal("2500"),
        )
        resp = await broker.place_order(req)
        assert resp.status == "COMPLETE"
        assert resp.filled_quantity == 10

    @pytest.mark.asyncio
    async def test_paper_cancel_order(self):
        from src.brokers.interface import OrderRequest
        from decimal import Decimal
        broker = PaperBroker()
        req = OrderRequest(symbol="TCS", side="BUY", quantity=5, order_type="MARKET",
                           price=Decimal("3500"))
        resp = await broker.place_order(req)
        result = await broker.cancel_order(resp.broker_order_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_paper_get_margins(self):
        broker = PaperBroker()
        margin = await broker.get_margins()
        assert margin.available_cash > 0
