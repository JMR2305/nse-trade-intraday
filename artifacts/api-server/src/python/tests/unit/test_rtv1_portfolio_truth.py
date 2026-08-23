"""Focused RTV-1 regressions for portfolio accounting and entry atomicity."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import phase20_executor as executor
import portfolio_bridge
import portfolio_snapshot


def test_canonical_equity_never_uses_legacy_peak_for_drawdown() -> None:
    """A legacy ₹200k peak must not turn a canonical ₹100k book into -50%."""
    import paper_trader

    canonical = {
        "source": "phase20_ledger",
        "cash": 100_000.0,
        "invested_value": 0.0,
        "unrealized_pnl": 0.0,
        "initial_capital": 100_000.0,
        "positions": [],
    }
    legacy_state = {
        "initial_capital": 100_000.0,
        "pnl_history": [{"timestamp": "old", "value": 200_000.0}],
    }
    with (
        patch("canonical_portfolio.build_canonical_portfolio",
              return_value=canonical),
        patch.object(paper_trader, "_load_state", return_value=legacy_state),
        patch.object(paper_trader, "get_trades", return_value=[]),
        patch.object(paper_trader, "get_all_trades", return_value=[]),
    ):
        snap = portfolio_snapshot.get_portfolio_snapshot()

    assert snap["equity"] == 100_000.0
    assert snap["peak_equity"] == 100_000.0
    assert snap["drawdown_pct"] == 0.0
    assert snap["pnl_history"] == []


def test_bridge_build_service_reads_active_capital_accessor() -> None:
    """The bridge config must use Phase-20's runtime capital, not its constant."""
    import portfolio_store

    with patch.object(portfolio_store, "get_initial_capital", return_value=175_000.0):
        service, _repo = portfolio_bridge._build_service()
    assert float(service.config.initial_capital) == 175_000.0


def test_analytics_capital_accessor_is_runtime_authority() -> None:
    from portfolio_performance.performance_engine import _initial_capital
    import portfolio_store

    with patch.object(portfolio_store, "get_initial_capital", return_value=175_000.0):
        assert _initial_capital() == 175_000.0


def test_legacy_portfolio_route_exposes_canonical_contract_aliases() -> None:
    """The legacy route must expose the same canonical financial truth."""
    import main
    canonical = {
        "source": "phase20_ledger",
        "scan_id": "scan-1",
        "portfolio_version": "1:now",
        "initial_capital": 100_000.0,
        "cash": 89_000.0,
        "invested_value": 10_000.0,
        "equity": 101_000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 1_000.0,
        "open_position_count": 1,
        "sector_exposure": {"IT": 11_000.0},
        "positions": [{"symbol": "INFY", "market_value": 11_000.0}],
    }
    with (
        patch("canonical_portfolio.build_canonical_portfolio", return_value=canonical),
        patch("paper_trader._load_state", return_value={}),
    ):
        result = main.cmd_portfolio()

    assert result["equity"] == result["total_value"] == 101_000.0
    assert result["current_market_value"] == 11_000.0
    assert result["utilization_pct"] == round(11_000 / 101_000 * 100, 2)
    assert result["largest_position_pct"] == round(11_000 / 101_000 * 100, 2)
    assert result["source"] == "phase20_ledger"
    assert result["calculated_at"]


def test_exit_pending_symbol_rejected_at_locked_admission_and_rolls_back() -> None:
    """EXIT_PENDING is still economically open; do not admit/re-spend it."""
    class Cursor:
        def __init__(self):
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, statement, *_args):
            self.statements.append(statement)

        def fetchone(self):
            statement = self.statements[-1]
            if "phase20_settings" in statement:
                return ({"auto_paper_entries": True,
                         "auto_paper_entries_confirmed_at": "yes"},)
            if "UPPER(symbol)" in statement:
                return ("existing-exit-pending",)
            return None

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.rolled_back = False
            self.committed = False

        def cursor(self):
            return self.cursor_instance

        def rollback(self):
            self.rolled_back = True

        def commit(self):
            self.committed = True

        def close(self):
            return None

    conn = Connection()
    with (
        patch.object(executor, "_market_entry_status", return_value={"allowed": True}),
        patch.object(executor, "db_available", return_value=True),
        patch.object(executor, "_connect", return_value=conn),
        patch.object(executor, "_ensure_schema"),
        patch.object(executor.store, "_ensure_schema"),
    ):
        with pytest.raises(executor.DuplicateOpenTrade):
            executor._insert_row({"status": "OPEN", "symbol": "RELIANCE"})

    assert conn.rolled_back is True
    assert conn.committed is False
    assert not any(
        statement.lstrip().startswith("INSERT INTO phase20_paper_trades")
        for statement in conn.cursor_instance.statements
    )