"""
Unit tests for ExecutionEngine PAPER_TRADING submit path.

Confirms that paper-mode orders route through paper_trader.execute_buy
(not the removed create_paper_order) and succeed without ImportError.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Minimal stubs required before importing execution_engine ──────────────────

def _make_config_module():
    m = types.ModuleType("config")
    m.NIFTY_50 = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
    m.INITIAL_CAPITAL = 50_000.0
    m.MAX_RISK_PCT = 0.02
    m.MAX_CAPITAL_PER_TRADE_PCT = 0.20
    return m


def _install_stubs():
    sys.modules.setdefault("config", _make_config_module())


_install_stubs()

from execution_engine import (  # noqa: E402 — must come after stub install
    ExecutionEngine, ExecutionMode, OrderStatus,
    set_execution_mode, get_execution_mode,
    CONFIG_FILE, AUDIT_FILE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _engine() -> ExecutionEngine:
    return ExecutionEngine(broker_client=None)


def _build_passing_preview(engine: ExecutionEngine, symbol: str = "RELIANCE"):
    """
    Build a preview that would pass all validation when mocked correctly.
    We bypass the real validator by patching PreTradeValidator.run to return
    (True, []) so we can focus the test on the submission path only.
    """
    with (
        patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
        patch("execution_engine.get_safety_controls") as mock_ctrl,
        patch("execution_engine.PreTradeValidator.run", return_value=(True, [])),
        patch("execution_engine.get_daily_order_count", return_value=0),
        patch("execution_engine.get_last_failed_order_ts", return_value=None),
        patch("execution_engine._append_audit"),
        patch("execution_engine._load_config", return_value={}),
        patch("execution_engine._save_config"),
    ):
        from execution_engine import SafetyControls
        ctrl = SafetyControls(kill_switch=False)
        mock_ctrl.return_value = ctrl

        preview = engine.build_preview(
            symbol=symbol, side="BUY", quantity=1,
            entry_price=100.0, stop_loss=95.0, target=110.0,
            strategy="test_strategy", confidence=80.0,
            data_quality="LIVE", available_cash=50_000.0,
            total_capital=50_000.0, broker_connected=True,
        )
    return preview


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestExecutionEnginePaperMode:
    """Confirm paper-mode orders call execute_buy, not the removed create_paper_order."""

    def test_paper_order_uses_execute_buy_not_create_paper_order(self):
        """
        execute_buy must be importable and called; create_paper_order must NOT
        be referenced (it was removed from paper_trader.py).
        """
        import paper_trader
        assert not hasattr(paper_trader, "create_paper_order"), (
            "create_paper_order still exists in paper_trader — clean it up"
        )
        assert hasattr(paper_trader, "execute_buy"), (
            "execute_buy must exist in paper_trader"
        )

    def test_paper_submit_succeeds_without_import_error(self):
        """
        A full step1 → step2 confirm cycle in PAPER_TRADING mode must
        complete without raising ImportError for create_paper_order.
        """
        engine = _engine()
        preview = _build_passing_preview(engine)

        # Promote to PENDING_STEP2 via step1
        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            r1 = engine.step1_confirm(preview.preview_id, preview.confirm_token_step1)

        assert r1["success"], f"step1 failed: {r1}"

        # step2: patch execute_buy to succeed and confirm no ImportError path
        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
            patch("paper_trader.execute_buy", return_value=(True, "Bought 1 × RELIANCE")) as mock_buy,
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            r2 = engine.step2_submit(preview.preview_id, preview.confirm_token_step2)

        assert r2["success"], f"step2 failed: {r2}"
        assert r2["status"] == OrderStatus.SUBMITTED
        assert "paper" in r2.get("message", "").lower()
        mock_buy.assert_called_once()

    def test_paper_submit_propagates_execute_buy_failure(self):
        """
        When execute_buy returns (False, reason), step2_submit must return
        success=False with the reason — not swallow it silently.
        """
        engine = _engine()
        preview = _build_passing_preview(engine)

        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            engine.step1_confirm(preview.preview_id, preview.confirm_token_step1)

        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
            patch("paper_trader.execute_buy", return_value=(False, "Insufficient cash")) as mock_buy,
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            r2 = engine.step2_submit(preview.preview_id, preview.confirm_token_step2)

        assert not r2["success"]
        assert "Insufficient cash" in r2.get("error", "")
        mock_buy.assert_called_once()

    def test_paper_sell_calls_execute_sell_not_execute_buy(self):
        """
        A SELL preview in PAPER_TRADING mode must route to execute_sell,
        never execute_buy — calling execute_buy for a SELL would debit cash
        and open a position instead of closing one.
        """
        engine = _engine()

        # Build a SELL preview (bypass validation the same way)
        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine.PreTradeValidator.run", return_value=(True, [])),
            patch("execution_engine.get_daily_order_count", return_value=0),
            patch("execution_engine.get_last_failed_order_ts", return_value=None),
            patch("execution_engine._append_audit"),
            patch("execution_engine._load_config", return_value={}),
            patch("execution_engine._save_config"),
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            preview = engine.build_preview(
                symbol="RELIANCE", side="SELL", quantity=1,
                entry_price=100.0, stop_loss=105.0, target=90.0,
                strategy="exit_signal", confidence=75.0,
                data_quality="LIVE", available_cash=50_000.0,
                total_capital=50_000.0, broker_connected=True,
            )

        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            engine.step1_confirm(preview.preview_id, preview.confirm_token_step1)

        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
            patch("paper_trader.execute_sell", return_value=(True, "Sold 1 × RELIANCE")) as mock_sell,
            patch("paper_trader.execute_buy") as mock_buy,
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            r2 = engine.step2_submit(preview.preview_id, preview.confirm_token_step2)

        assert r2["success"], f"SELL step2 failed: {r2}"
        mock_sell.assert_called_once()
        mock_buy.assert_not_called()

    def test_paper_sell_propagates_no_position_failure(self):
        """
        When execute_sell returns (False, 'No position in X'), step2_submit
        must surface the error and not report success.
        """
        engine = _engine()

        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine.PreTradeValidator.run", return_value=(True, [])),
            patch("execution_engine.get_daily_order_count", return_value=0),
            patch("execution_engine.get_last_failed_order_ts", return_value=None),
            patch("execution_engine._append_audit"),
            patch("execution_engine._load_config", return_value={}),
            patch("execution_engine._save_config"),
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            preview = engine.build_preview(
                symbol="TCS", side="SELL", quantity=1,
                entry_price=100.0, stop_loss=105.0, target=90.0,
                data_quality="LIVE", available_cash=50_000.0,
                total_capital=50_000.0, broker_connected=True,
            )

        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            engine.step1_confirm(preview.preview_id, preview.confirm_token_step1)

        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
            patch("paper_trader.execute_sell", return_value=(False, "No position in TCS")),
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            r2 = engine.step2_submit(preview.preview_id, preview.confirm_token_step2)

        assert not r2["success"]
        assert "No position in TCS" in r2.get("error", "")

    def test_paper_submit_passes_correct_params_to_execute_buy(self):
        """
        execute_buy must be called with symbol, quantity, price, stop_loss_price,
        and target matching the preview ticket.
        """
        engine = _engine()
        preview = _build_passing_preview(engine, symbol="RELIANCE")

        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            engine.step1_confirm(preview.preview_id, preview.confirm_token_step1)

        with (
            patch("execution_engine.get_execution_mode", return_value=ExecutionMode.PAPER_TRADING),
            patch("execution_engine.get_safety_controls") as mock_ctrl,
            patch("execution_engine._append_audit"),
            patch("paper_trader.execute_buy", return_value=(True, "ok")) as mock_buy,
        ):
            from execution_engine import SafetyControls
            mock_ctrl.return_value = SafetyControls(kill_switch=False)
            engine.step2_submit(preview.preview_id, preview.confirm_token_step2)

        call_kwargs = mock_buy.call_args
        # Called with keyword args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        args = call_kwargs.args if call_kwargs.args else ()

        # Collect all params (positional + keyword)
        all_params = dict(zip(
            ["symbol", "quantity", "price", "reason", "signal_confidence",
             "stop_loss_price", "target", "scan_id"],
            args,
        ))
        all_params.update(kwargs)

        assert all_params.get("symbol") == "RELIANCE"
        assert all_params.get("quantity") == 1
        assert all_params.get("price") == 100.0
        assert all_params.get("stop_loss_price") == 95.0
        assert all_params.get("target") == 110.0
