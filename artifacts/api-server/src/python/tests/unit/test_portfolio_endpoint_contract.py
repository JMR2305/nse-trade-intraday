"""Regression tests for the shared canonical paper-portfolio API contract."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main
import portfolio_snapshot
from phase20_store import operating_universe_verification


_CLOSED_LEDGER_SNAPSHOT = {
    "source": "phase20_ledger",
    "scan_id": "closed-ledger-scan",
    "portfolio_version": "6:2026-08-21T00:06:36Z",
    "mark_basis": "scan",
    "equity_complete": True,
    "initial_capital": 100_000.0,
    "cash": 99_721.26,
    "invested_value": 0.0,
    "equity": 99_721.26,
    "realized_pnl": -278.74,
    "unrealized_pnl": 0.0,
    "open_position_count": 0,
    "closed_trade_count": 6,
    "positions": [],
    "sector_exposure": {},
}


def test_closed_ledger_trade_has_identical_financial_truth_in_both_endpoints() -> None:
    """A closed trade must never disappear from one paper-portfolio endpoint."""
    import canonical_portfolio
    import paper_trader

    with (
        patch.object(
            canonical_portfolio,
            "build_canonical_portfolio",
            return_value=_CLOSED_LEDGER_SNAPSHOT,
        ),
        patch.object(
            paper_trader,
            "_load_state",
            return_value={
                "cash": 100_000.0,
                "pnl_history": [{"timestamp": "legacy", "value": 500_000.0}],
            },
        ),
        patch.object(paper_trader, "get_trades", return_value=[]),
        patch.object(paper_trader, "get_all_trades", return_value=[]),
    ):
        canonical_api = main.cmd_portfolio()
        snapshot_api = portfolio_snapshot.get_portfolio_snapshot()

    shared_fields = (
        "financial_contract_version",
        "source",
        "initial_capital",
        "cash",
        "equity",
        "total_equity",
        "total_value",
        "invested_value",
        "current_market_value",
        "realized_pnl",
        "realised_pnl",
        "unrealized_pnl",
        "unrealised_pnl",
        "total_pnl",
        "open_position_count",
        "portfolio_version",
    )
    for field in shared_fields:
        assert canonical_api[field] == snapshot_api[field], field

    assert canonical_api["cash"] == 99_721.26
    assert canonical_api["realized_pnl"] == -278.74
    assert canonical_api["total_pnl"] == -278.74
    assert canonical_api["pnl_history"] == []
    assert snapshot_api["pnl_history"] == []


def test_universe_variance_is_visible_without_changing_the_operator_setting() -> None:
    verification = operating_universe_verification(
        {"active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR"}
    )

    assert verification == {
        "approved_baseline": "NIFTY_50",
        "active_universe": "CUSTOM_LOW_PRICE_SECTOR",
        "active_universe_valid": True,
        "matches_approved_baseline": False,
        "status": "REVIEW_REQUIRED",
        "detail": (
            "Active universe differs from the approved operating baseline; "
            "review the persisted operator setting before the next session. "
            "No setting was changed by this verification."
        ),
    }


def test_missing_mark_remains_explicit_in_both_portfolio_endpoints() -> None:
    """Incomplete MTM must never silently become a zero unrealized P&L."""
    import canonical_portfolio
    import paper_trader

    unmarked_snapshot = {
        **_CLOSED_LEDGER_SNAPSHOT,
        "portfolio_version": "7:unmarked",
        "cash": 99_000.0,
        "invested_value": 1_000.0,
        "equity": 100_000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": None,
        "equity_complete": False,
        "open_position_count": 1,
        "positions": [{
            "trade_id": "P20-unmarked",
            "symbol": "INFY",
            "quantity": 10,
            "avg_price": 100.0,
            "mark_price": None,
            "market_value": 1_000.0,
            "unrealized_pnl": None,
            "status": "OPEN",
            "strategy_id": "test",
            "sector": "IT",
            "opened_at": None,
            "mark_source": None,
        }],
    }
    with (
        patch.object(
            canonical_portfolio,
            "build_canonical_portfolio",
            return_value=unmarked_snapshot,
        ),
        patch.object(paper_trader, "_load_state", return_value={}),
        patch.object(paper_trader, "get_trades", return_value=[]),
        patch.object(paper_trader, "get_all_trades", return_value=[]),
    ):
        canonical_api = main.cmd_portfolio()
        snapshot_api = portfolio_snapshot.get_portfolio_snapshot()

    for field in ("equity_complete", "unrealized_pnl", "unrealised_pnl"):
        assert canonical_api[field] == snapshot_api[field], field
    assert canonical_api["equity_complete"] is False
    assert canonical_api["unrealized_pnl"] is None