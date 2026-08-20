"""Unit coverage for the automatic intraday paper-entry cutoff."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import market_hours
import phase20_executor as executor


def _ist(hour: int, minute: int, second: int = 0) -> datetime:
    # Friday, 2 January 2026 is a normal NSE trading day.
    return datetime(2026, 1, 2, hour, minute, second, tzinfo=market_hours.IST)


def test_automatic_paper_entry_window_stays_open_before_cutoff() -> None:
    status = market_hours.automatic_paper_entry_status(_ist(15, 14, 59))

    assert status["allowed"] is True
    assert status["cutoff_reached"] is False
    assert status["cutoff_ist"] == "15:15"
    with patch.object(market_hours, "now_ist", return_value=_ist(15, 14, 59)):
        assert executor._market_entry_allowed() is True


@pytest.mark.parametrize("minute, second", [(15, 0), (16, 0), (29, 59)])
def test_automatic_paper_entry_window_closes_at_and_after_cutoff(
        minute: int, second: int) -> None:
    status = market_hours.automatic_paper_entry_status(_ist(15, minute, second))

    assert status["allowed"] is False
    assert status["cutoff_reached"] is True
    assert "15:15 IST" in status["reason"]


def test_final_ledger_admission_rejects_at_cutoff_before_any_commit() -> None:
    row = {"status": "OPEN", "symbol": "DRREDDY"}
    with (
        patch.object(market_hours, "now_ist", return_value=_ist(15, 15)),
        patch.object(executor, "db_available", return_value=True),
        patch.object(executor, "_connect") as connect,
    ):
        with pytest.raises(executor.MarketClosedForEntry, match="15:15 IST"):
            executor._insert_row(row)
    connect.assert_not_called()


def test_final_ledger_admission_rechecks_cutoff_after_lock_wait() -> None:
    """A candidate admitted before 15:15 cannot commit after lock contention."""
    class Cursor:
        def __init__(self) -> None:
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, statement, *_args) -> None:
            self.statements.append(statement)

        def fetchone(self):
            statement = self.statements[-1]
            if "phase20_settings" in statement:
                return ({"auto_paper_entries": True,
                         "auto_paper_entries_confirmed_at": "confirmed"},)
            if "SUM(realized_pnl)" in statement:
                return (0.0,)
            return None

        def fetchall(self):
            return []

    class Connection:
        def __init__(self) -> None:
            self.cursor_instance = Cursor()
            self.rolled_back = False
            self.committed = False

        def cursor(self):
            return self.cursor_instance

        def rollback(self) -> None:
            self.rolled_back = True

        def commit(self) -> None:
            self.committed = True

        def close(self) -> None:
            return None

    connection = Connection()
    before_cutoff = {
        "allowed": True, "market_state": "OPEN", "cutoff_ist": "15:15",
    }
    after_cutoff = {
        "allowed": False, "market_state": "OPEN", "cutoff_ist": "15:15",
        "reason": (
            "Automatic intraday paper-entry cutoff (15:15 IST) has been "
            "reached — no new positions may open before 15:20 square-off"
        ),
    }
    row = {
        "status": "OPEN",
        "symbol": "DRREDDY",
        "sector": "PHARMA",
        "quantity": 1,
        "fill_price": 100.0,
        "stop_loss": 95.0,
        "evidence": {},
    }
    revalidation = {
        "allowed": True,
        "quantity": 1,
        "decision": {"tier": "NORMAL"},
    }

    with (
        patch.object(executor, "_market_entry_status",
                     side_effect=[before_cutoff, after_cutoff]),
        patch.object(executor, "db_available", return_value=True),
        patch.object(executor, "_connect", return_value=connection),
        patch.object(executor, "_ensure_schema"),
        patch.object(executor.store, "_ensure_schema"),
        patch("quality_allocation_override.revalidate_final_quantity",
              return_value=revalidation),
    ):
        with pytest.raises(executor.MarketClosedForEntry, match="15:15 IST"):
            executor._insert_row(row)

    assert connection.rolled_back is True
    assert connection.committed is False
    assert not any(
        statement.lstrip().startswith("INSERT INTO phase20_paper_trades")
        for statement in connection.cursor_instance.statements
    )


def test_entry_cutoff_keeps_market_open_for_square_off_and_other_exits() -> None:
    """The cutoff blocks only new entries; the exit engine still sees OPEN."""
    assert market_hours.market_state(_ist(15, 20)) == "OPEN"
    assert market_hours.automatic_paper_entry_allowed(_ist(15, 20)) is False


def test_late_candidate_emits_terminal_event_and_operator_notification() -> None:
    events = []
    notifications = []

    def capture_event(event_type, stage, **kwargs):
        events.append((event_type, stage, kwargs))

    def capture_notification(kind, title, body="", **kwargs):
        notifications.append((kind, title, body, kwargs))

    candidate = {
        "symbol": "DRREDDY",
        "eligible": True,
        "recommendation": "BUY",
    }
    with (
        patch.object(market_hours, "now_ist", return_value=_ist(15, 15)),
        patch("pipeline_events.emit", side_effect=capture_event),
        patch.object(executor.store, "add_notification",
                     side_effect=capture_notification),
    ):
        result = executor._entry_window_rejection(
            candidate,
            "scan-cutoff",
            "AUTO",
            market_hours.automatic_paper_entry_status(),
            auto_entry_attempted=True,
        )

    assert result["created"] is False
    assert "15:15 IST" in result["reason"]
    assert events == [
        ("EXECUTION_SKIPPED_WITH_REASON", "EXECUTION", {
            "scan_id": "scan-cutoff",
            "symbol": "DRREDDY",
            "payload": {
                "gate_name": "automatic_paper_entry_cutoff",
                "action": "BUY",
                "reason": result["reason"],
                "human_readable_reason": result["reason"],
                "market_state": "OPEN",
                "entry_cutoff_ist": "15:15",
                "auto_entry_attempted": True,
                "trigger_source": "AUTO",
                "note": (
                    "Candidate was not committed because the automatic "
                    "intraday paper-entry window is closed"
                ),
            },
        }),
    ]
    assert notifications[0][0] == "ENTRY_BLOCKED_ENTRY_CUTOFF"
    assert "15:15 IST" in notifications[0][2]