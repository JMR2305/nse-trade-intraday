"""
test_paper_sell_no_position.py — Regression suite for Task #659.

Verifies that a paper-mode SELL whose underlying position no longer exists
emits a visible terminal pipeline event (EXECUTION_SKIPPED_WITH_REASON)
instead of silently disappearing, and that:
  - the paper portfolio is unchanged when the SELL is skipped
  - no live broker call is made at any point
  - a SELL with an open position still executes normally
  - the _retry_pending path also emits the event on failure

All storage is mocked — no real files or DB connections are touched.
"""

from __future__ import annotations

import contextlib
import unittest
from unittest import mock
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _fake_open_trade(
    trade_id: str = "T001",
    symbol: str = "RELIANCE",
    qty: int = 5,
    stop: float = 2400.0,
    target: float = 2700.0,
    fill_price: float = 2550.0,
    status: str = "OPEN",
    exit_rule: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "quantity": qty,
        "stop_loss": stop,
        "target": target,
        "fill_price": fill_price,
        "fill_ts": "2026-08-10T10:00:00+00:00",
        "status": status,
        "exit_rule": exit_rule,
        "sector": "OIL",
    }


def _fake_scan_ctx(
    symbol: str = "RELIANCE",
    price: float = 2650.0,
    scan_id: str = "scan_abc123",
    action: str = "HOLD",
) -> Dict[str, Any]:
    return {
        "available": True,
        "stale": False,
        "scan_id": scan_id,
        "symbols": {
            symbol: {
                "entry_price": price,
                "data_quality": "LIVE",
                "final_action": action,
                "error": None,
            }
        },
    }


def _fake_portfolio(positions: Optional[List] = None) -> Dict[str, Any]:
    return {
        "total_value": 50000.0,
        "cash": 40000.0,
        "positions": positions or [],
    }


def _fake_paper_state(
    has_position: bool = True,
    symbol: str = "RELIANCE",
    qty: int = 5,
    avg: float = 2550.0,
) -> Dict[str, Any]:
    state: Dict[str, Any] = {"cash": 40000.0, "positions": {}, "trades": []}
    if has_position:
        state["positions"][symbol] = {"quantity": qty, "avg_price": avg}
    return state


# ---------------------------------------------------------------------------
# 1. execute_sell directly — no position → returns (False, "No position …")
# ---------------------------------------------------------------------------

class TestExecuteSellNoPosition(unittest.TestCase):
    """execute_sell() must return (False, msg) when the symbol is absent from
    the paper portfolio; it must not raise, fabricate a fill, or call any
    live broker endpoint."""

    def _run_sell(
        self,
        has_position: bool,
        symbol: str = "RELIANCE",
        qty: int = 5,
        price: float = 2650.0,
    ):
        """Run execute_sell with mocked state layer.

        Patches for trade_intelligence and market_scanner are added only when
        has_position=True because execute_sell returns before reaching those
        imports when no position exists.
        """
        from paper_trader import execute_sell
        state = _fake_paper_state(has_position=has_position, symbol=symbol)
        mock_save = mock.MagicMock()

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch("paper_trader._load_state", return_value=state))
            stack.enter_context(
                mock.patch("paper_trader._save_state", mock_save))
            stack.enter_context(
                mock.patch("paper_trader._append_pnl_snapshot"))
            if has_position:
                # These imports only execute after execute_sell confirms a
                # position exists, so only needed for the success path.
                stack.enter_context(
                    mock.patch("paper_trader.estimate_broker_charges",
                               return_value=0.0))
                stack.enter_context(
                    mock.patch("paper_trader.estimate_slippage",
                               return_value=0.0))
                stack.enter_context(
                    mock.patch("trade_intelligence.record_paper_trade"))
                stack.enter_context(
                    mock.patch("trade_intelligence.find_buy_trade",
                               return_value=None))
                stack.enter_context(
                    mock.patch("market_scanner._sector_of",
                               return_value="OIL"))
            ok, msg = execute_sell(symbol, qty, price)

        return ok, msg, mock_save

    # ------------------------------------------------------------------

    def test_no_position_returns_false(self):
        """SELL with no open paper position must return ok=False."""
        ok, msg, _save = self._run_sell(has_position=False)
        self.assertFalse(ok)
        self.assertIn("No position", msg)

    def test_no_position_does_not_save_state(self):
        """Portfolio must be unchanged — _save_state must NOT be called."""
        _ok, _msg, mock_save = self._run_sell(has_position=False)
        mock_save.assert_not_called()

    def test_with_open_position_returns_true(self):
        """SELL with a valid open position must succeed."""
        ok, _msg, _save = self._run_sell(has_position=True)
        self.assertTrue(ok)

    def test_no_live_broker_call(self):
        """No kiteconnect or broker client must be instantiated during execute_sell."""
        fake_kite = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"kiteconnect": fake_kite}):
            ok, _msg, _ = self._run_sell(has_position=False)
        fake_kite.KiteConnect.assert_not_called()
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# 2. manage_open_positions — no portfolio position emits terminal event
# ---------------------------------------------------------------------------

class TestManageOpenPositionsNoPosition(unittest.TestCase):
    """manage_open_positions() must emit EXECUTION_SKIPPED_WITH_REASON and
    add an operator notification when execute_sell fails."""

    def _run_manage(
        self,
        execute_sell_ok: bool = False,
        execute_sell_msg: str = "No position in RELIANCE",
        action: str = "EXIT",
        scan_id: str = "scan_test01",
    ) -> tuple:
        """Run manage_open_positions() with all storage mocked.

        Returns (result, emitted_events, notifications).
        RECOMMENDATION_EXIT rule is triggered by final_action="EXIT" in the
        scan context when the price is between stop and target.
        """
        from phase20_exits import manage_open_positions

        # Trade is OPEN per the ledger; price between stop (2400) and
        # target (2700) so STOP_LOSS_HIT and TARGET_HIT don't fire.
        # RECOMMENDATION_EXIT fires because final_action="EXIT".
        open_trade = _fake_open_trade(symbol="RELIANCE", qty=5)
        ctx = _fake_scan_ctx(
            symbol="RELIANCE", price=2550.0, scan_id=scan_id, action=action)
        portfolio = _fake_portfolio()
        state = _fake_paper_state(has_position=False)   # paper portfolio diverged
        settings = {
            "daily_loss_limit_pct": 5.0,
            "sector_exposure_cap_pct": 40.0,
            "max_holding_days": 10,
            "square_off_before_close": False,
        }

        emitted: list = []
        notifications: list = []

        # phase20_exits.py has TOP-LEVEL imports:
        #   from phase20_executor import get_open_trades, record_exit
        # Those names are bound in the phase20_exits module at import time,
        # so we must patch phase20_exits.<name> (not phase20_executor.<name>).
        # Functions imported INSIDE manage_open_positions() (execute_sell,
        # get_portfolio, _load_state, build_scan_context, market_status) are
        # fetched fresh each call, so patching the source module works there.
        with (
            mock.patch("phase20_exits.get_open_trades",
                       return_value=[open_trade]),
            mock.patch("phase15_scan_context.build_scan_context",
                       return_value=ctx),
            mock.patch("paper_trader.get_portfolio", return_value=portfolio),
            mock.patch("paper_trader._load_state", return_value=state),
            mock.patch("market_hours.market_status",
                       return_value={"state": "CLOSED"}),
            mock.patch("paper_trader.execute_sell",
                       return_value=(execute_sell_ok, execute_sell_msg)),
            mock.patch("phase20_exits.record_exit"),
            mock.patch("phase20_store.add_notification",
                       side_effect=lambda kind, title, body, **kw:
                           notifications.append({"kind": kind, "title": title})),
            mock.patch("pipeline_events.emit",
                       side_effect=lambda *a, **kw: emitted.append((a, kw))),
        ):
            result = manage_open_positions(settings)

        return result, emitted, notifications

    # ------------------------------------------------------------------

    def test_no_position_emits_execution_skipped_event(self):
        """SELL failure must produce an EXECUTION_SKIPPED_WITH_REASON event."""
        _result, emitted, _notifs = self._run_manage(execute_sell_ok=False)
        event_types = [ev[0][0] for ev in emitted]
        self.assertIn(
            "EXECUTION_SKIPPED_WITH_REASON", event_types,
            "Expected EXECUTION_SKIPPED_WITH_REASON pipeline event was not emitted",
        )

    def test_no_position_event_carries_required_fields(self):
        """The emitted event payload must include symbol, source, and reason."""
        _result, emitted, _notifs = self._run_manage(execute_sell_ok=False)
        skipped = [ev for ev in emitted
                   if ev[0][0] == "EXECUTION_SKIPPED_WITH_REASON"]
        self.assertTrue(skipped, "No EXECUTION_SKIPPED_WITH_REASON event found")
        payload = skipped[0][1].get("payload", {})
        self.assertEqual(payload.get("source"), "paper_mode_sell_validation")
        self.assertIn("reason", payload)
        self.assertIn("position_count", payload)

    def test_no_position_adds_operator_notification(self):
        """A SELL_SKIPPED_NO_POSITION notification must be raised for operators."""
        _result, _emitted, notifications = self._run_manage(execute_sell_ok=False)
        kinds = [n["kind"] for n in notifications]
        self.assertIn("SELL_SKIPPED_NO_POSITION", kinds)

    def test_no_position_does_not_silently_disappear(self):
        """The failed trade must appear in the 'pending' list, never discarded."""
        result, _emitted, _notifs = self._run_manage(execute_sell_ok=False)
        pending_symbols = [p["symbol"] for p in result.get("pending", [])]
        self.assertIn(
            "RELIANCE", pending_symbols,
            "A failed SELL must surface in the pending list — "
            "it must not silently disappear",
        )

    def test_successful_sell_does_not_emit_skipped_event(self):
        """A SELL with a valid open position must NOT emit EXECUTION_SKIPPED_WITH_REASON."""
        _result, emitted, _notifs = self._run_manage(execute_sell_ok=True)
        skipped = [ev for ev in emitted
                   if ev[0][0] == "EXECUTION_SKIPPED_WITH_REASON"]
        self.assertEqual(
            skipped, [],
            "A successful SELL must not emit EXECUTION_SKIPPED_WITH_REASON",
        )

    def test_portfolio_unchanged_when_sell_skipped(self):
        """record_exit must not be called when execute_sell fails."""
        called: list = []
        # patch the binding inside phase20_exits (top-level import)
        with mock.patch("phase20_exits.record_exit",
                        side_effect=lambda *a, **kw: called.append((a, kw))):
            self._run_manage(execute_sell_ok=False)
        self.assertEqual(
            called, [],
            "record_exit must not be called when execute_sell fails — "
            "the ledger must remain unchanged",
        )

    def test_no_live_broker_order_on_sell_skip(self):
        """No live broker endpoint may be contacted during a paper SELL failure."""
        fake_kite = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"kiteconnect": fake_kite}):
            self._run_manage(execute_sell_ok=False)
        fake_kite.KiteConnect.assert_not_called()


# ---------------------------------------------------------------------------
# 3. _retry_pending — also emits terminal event on failure
# ---------------------------------------------------------------------------

class TestRetryPendingNoPosition(unittest.TestCase):
    """_retry_pending() must also emit EXECUTION_SKIPPED_WITH_REASON when
    execute_sell fails for an EXIT_PENDING trade."""

    def test_retry_pending_emits_event_on_sell_failure(self):
        from phase20_exits import _retry_pending

        pending_trade = _fake_open_trade(
            trade_id="T002", symbol="TCS", qty=3,
            status="EXIT_PENDING", exit_rule="STOP_LOSS_HIT",
        )
        ctx = _fake_scan_ctx(symbol="TCS", price=4200.0,
                             scan_id="scan_retry01")
        emitted: list = []

        with (
            mock.patch("phase20_executor.get_ledger",
                       return_value=[pending_trade]),
            mock.patch("paper_trader.execute_sell",
                       return_value=(False, "No position in TCS")),
            mock.patch("phase20_executor.record_exit"),
            mock.patch("phase20_store.add_notification"),
            mock.patch("pipeline_events.emit",
                       side_effect=lambda *a, **kw: emitted.append((a, kw))),
        ):
            _retry_pending(ctx["symbols"], scan_ok=True, stale=False,
                           exit_scan_id="scan_retry01")

        event_types = [ev[0][0] for ev in emitted]
        self.assertIn(
            "EXECUTION_SKIPPED_WITH_REASON", event_types,
            "_retry_pending must emit EXECUTION_SKIPPED_WITH_REASON on sell failure",
        )
        payload = emitted[0][1].get("payload", {})
        self.assertEqual(payload.get("source"), "paper_mode_sell_validation")


if __name__ == "__main__":
    unittest.main()
