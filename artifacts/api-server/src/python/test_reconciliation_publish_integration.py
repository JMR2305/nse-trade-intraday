"""Integration test for the bot→dashboard reconciliation publish bridge.

Covers the isolation-preserving data path end-to-end on the API-server side:
  1. publish_reconciliation_summary() ingests a bot-produced summary with a
     nonzero paper_fallback_count (as POSTed by the bot's publisher via
     /api/broker/reconciliation/publish),
  2. get_reconciliation_status() (backing GET /api/broker/reconciliation)
     exposes that count on db_latest_run — the exact field the Broker
     Execution page's ReconciliationWidget renders.

Skipped when no database is available. Cleans up its rows.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from eod_reconciliation import (
    get_reconciliation_status,
    publish_reconciliation_summary,
)
from scan_state_store import _connect, db_available

pytestmark = pytest.mark.skipif(
    not db_available(), reason="DATABASE_URL not configured"
)


def _cleanup(run_id: str) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM broker_reconciliation_runs WHERE run_id = %s",
                (run_id,),
            )
        conn.commit()
    finally:
        conn.close()


def test_published_paper_fallback_count_flows_to_status():
    run_id = f"test-publish-{uuid.uuid4()}"
    # Far-future started_at so this row is deterministically the latest run.
    started = datetime.now(timezone.utc) + timedelta(days=365)
    try:
        result = publish_reconciliation_summary({
            "run_id": run_id,
            "trigger": "post_reconnect",
            "started_at": started.isoformat(),
            "completed_at": (started + timedelta(minutes=1)).isoformat(),
            "orders_checked": 12,
            "clean": True,
            "discrepancy_count": 0,
            "paper_mode": False,
            "paper_fallback_count": 3,
        })
        assert result["success"] is True
        assert result["paper_fallback_count"] == 3

        status = get_reconciliation_status()
        latest = status["last_run"]["db_latest_run"]
        assert latest["run_id"] == run_id
        assert latest["paper_fallback_count"] == 3
        # Recent-runs history exposes it too
        recent = status["last_run"]["recent_runs"][0]
        assert recent["run_id"] == run_id
        assert recent["paper_fallback_count"] == 3
    finally:
        _cleanup(run_id)


def test_publish_is_idempotent_per_run_id():
    run_id = f"test-publish-{uuid.uuid4()}"
    started = datetime.now(timezone.utc) + timedelta(days=365)
    payload = {
        "run_id": run_id,
        "started_at": started.isoformat(),
        "paper_fallback_count": 2,
    }
    try:
        assert publish_reconciliation_summary(payload)["success"] is True
        # Re-publish (retry) updates in place — no duplicate rows, same count
        payload["paper_fallback_count"] = 5
        assert publish_reconciliation_summary(payload)["success"] is True
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*), MAX(paper_fallback_count) "
                    "FROM broker_reconciliation_runs WHERE run_id = %s",
                    (run_id,),
                )
                count, fallback = cur.fetchone()
        finally:
            conn.close()
        assert count == 1
        assert fallback == 5
    finally:
        _cleanup(run_id)


def test_publish_rejects_missing_fields():
    assert publish_reconciliation_summary({})["success"] is False
    assert publish_reconciliation_summary(
        {"run_id": "x", "started_at": "not-a-date"}
    )["success"] is False
