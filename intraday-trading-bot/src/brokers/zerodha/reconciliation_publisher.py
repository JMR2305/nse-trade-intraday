"""Publish reconciliation run summaries to the dashboard API server.

Isolation-preserving bridge: the intraday bot runs against its own database
(INTRADAY_DATABASE_URL) which the dashboard must never read directly.  After
each reconciliation run the bot POSTs a compact summary — including
paper_fallback_count — to the API server's authenticated
``/api/broker/reconciliation/publish`` endpoint, which is the single source
of truth for the Broker Execution page.

Configuration (both must be set for publishing to activate):
  RECON_PUBLISH_URL    e.g. https://<dashboard-host>/api/broker/reconciliation/publish
  RECON_PUBLISH_TOKEN  shared secret, sent as X-Recon-Publish-Token

Publishing is strictly fail-open: any error is logged and never propagates —
a dashboard outage must never break reconciliation itself.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src.brokers.contracts import ReconciliationReport
from src.core.logging import logger

_TIMEOUT_SECONDS = 10.0


def _config() -> Optional[Dict[str, str]]:
    url = os.environ.get("RECON_PUBLISH_URL", "").strip()
    token = os.environ.get("RECON_PUBLISH_TOKEN", "").strip()
    if not url or not token:
        return None
    return {"url": url, "token": token}


def build_summary_payload(report: ReconciliationReport) -> Dict[str, Any]:
    """Build the JSON payload for the publish endpoint from a report."""
    return {
        "run_id": report.run_id,
        "trigger": report.trigger,
        "started_at": report.started_at.isoformat(),
        "completed_at": (
            report.completed_at.isoformat() if report.completed_at else None
        ),
        "orders_checked": report.orders_checked,
        "clean": report.clean,
        "discrepancy_count": len(report.discrepancies),
        "paper_mode": report.paper_mode,
        "paper_fallback_count": report.paper_fallback_orders,
        "paper_fallback_reasons": dict(report.paper_fallback_reasons or {}),
    }


async def publish_report(report: ReconciliationReport) -> bool:
    """POST the report summary to the dashboard API server.

    Returns True when the summary was accepted, False otherwise (including
    when publishing is not configured).  Never raises.
    """
    cfg = _config()
    if cfg is None:
        logger.debug(
            "Reconciliation publish skipped: RECON_PUBLISH_URL/TOKEN not configured"
        )
        return False
    try:
        import httpx

        payload = build_summary_payload(report)
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                cfg["url"],
                json=payload,
                headers={"X-Recon-Publish-Token": cfg["token"]},
            )
        if resp.status_code == 200:
            logger.info(
                "Reconciliation summary published to dashboard",
                extra={
                    "event_type": "RECONCILIATION_SUMMARY_PUBLISHED",
                    "run_id": report.run_id,
                    "paper_fallback_count": report.paper_fallback_orders,
                },
            )
            return True
        logger.warning(
            f"Reconciliation summary publish rejected: HTTP {resp.status_code}",
            extra={
                "event_type": "RECONCILIATION_SUMMARY_PUBLISH_REJECTED",
                "run_id": report.run_id,
                "status_code": resp.status_code,
            },
        )
        return False
    except Exception as exc:  # fail-open — never break reconciliation
        logger.warning(
            f"Reconciliation summary publish failed: {type(exc).__name__}",
            extra={
                "event_type": "RECONCILIATION_SUMMARY_PUBLISH_FAILED",
                "run_id": report.run_id,
            },
        )
        return False
