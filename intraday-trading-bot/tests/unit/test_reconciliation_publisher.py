"""Tests for the reconciliation summary publisher (dashboard bridge).

Verifies:
  - build_summary_payload includes paper_fallback_count / reasons
  - publish_report is a no-op when RECON_PUBLISH_URL/TOKEN are unset
  - publish_report POSTs the payload with the shared-secret header
  - publish_report is fail-open on HTTP errors and exceptions
  - ReconciliationEngine invokes the publisher after a run
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.brokers.contracts import ReconciliationReport
from src.brokers.zerodha.reconciliation_publisher import (
    build_summary_payload,
    publish_report,
)


def _report(paper_fallback: int = 3) -> ReconciliationReport:
    return ReconciliationReport(
        run_id="run-123",
        trigger="periodic",
        started_at=datetime(2026, 8, 9, 4, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 9, 4, 1, tzinfo=timezone.utc),
        discrepancies=[],
        orders_checked=10,
        clean=True,
        paper_mode=False,
        paper_fallback_orders=paper_fallback,
        paper_fallback_reasons={"token_expired": paper_fallback},
    )


def test_payload_includes_paper_fallback_fields():
    payload = build_summary_payload(_report(paper_fallback=4))
    assert payload["run_id"] == "run-123"
    assert payload["paper_fallback_count"] == 4
    assert payload["paper_fallback_reasons"] == {"token_expired": 4}
    assert payload["orders_checked"] == 10
    assert payload["clean"] is True
    assert payload["started_at"].startswith("2026-08-09T04:00")


def test_publish_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("RECON_PUBLISH_URL", raising=False)
    monkeypatch.delenv("RECON_PUBLISH_TOKEN", raising=False)
    assert asyncio.run(publish_report(_report())) is False


def _mock_async_client(status_code: int):
    resp = MagicMock()
    resp.status_code = status_code
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, client


def test_publish_posts_payload_with_token(monkeypatch):
    monkeypatch.setenv("RECON_PUBLISH_URL", "https://dash.example/api/broker/reconciliation/publish")
    monkeypatch.setenv("RECON_PUBLISH_TOKEN", "sekret")
    ctx, client = _mock_async_client(200)
    with patch("httpx.AsyncClient", return_value=ctx):
        ok = asyncio.run(publish_report(_report(paper_fallback=2)))
    assert ok is True
    _, kwargs = client.post.call_args
    assert kwargs["json"]["paper_fallback_count"] == 2
    assert kwargs["headers"]["X-Recon-Publish-Token"] == "sekret"


def test_publish_fail_open_on_http_error(monkeypatch):
    monkeypatch.setenv("RECON_PUBLISH_URL", "https://dash.example/publish")
    monkeypatch.setenv("RECON_PUBLISH_TOKEN", "sekret")
    ctx, _ = _mock_async_client(401)
    with patch("httpx.AsyncClient", return_value=ctx):
        assert asyncio.run(publish_report(_report())) is False


def test_publish_fail_open_on_exception(monkeypatch):
    monkeypatch.setenv("RECON_PUBLISH_URL", "https://dash.example/publish")
    monkeypatch.setenv("RECON_PUBLISH_TOKEN", "sekret")
    with patch("httpx.AsyncClient", side_effect=RuntimeError("boom")):
        assert asyncio.run(publish_report(_report())) is False


@pytest.mark.asyncio
async def test_engine_invokes_publisher_after_run(monkeypatch):
    """A live-mode reconciliation run must publish its summary (fail-open)."""
    from src.brokers.zerodha.config import ZerodhaBrokerConfig
    from src.brokers.zerodha.reconciliation import ReconciliationEngine

    config = ZerodhaBrokerConfig(
        api_key="key", api_secret="secret",
        paper_trading=False, enabled=True, live_trading_enabled=True,
    )
    health = MagicMock()
    health.set_reconciliation_status = AsyncMock()
    gateway = MagicMock()
    gateway.get_order_book = AsyncMock(return_value=[])
    gateway.get_trades = AsyncMock(return_value=[])

    engine = ReconciliationEngine(config, health, gateway)
    published = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "src.brokers.zerodha.reconciliation_publisher.publish_report", published
    )
    report = await engine.run(trigger="manual", local_orders=[])
    published.assert_awaited_once()
    assert published.await_args.args[0].run_id == report.run_id
