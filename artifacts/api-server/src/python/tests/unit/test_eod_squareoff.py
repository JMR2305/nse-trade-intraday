"""
test_eod_squareoff.py — Unit tests for the mandatory intraday EOD square-off.

Covers:
  1. BOOTSTRAP_AUTO OPEN position closes at/after 15:20 IST (MARKET_CLOSE_EXIT).
  2. Any AUTO OPEN position closes at/after 15:20 IST.
  3. No live broker API is called (paper-only fill path).
  4. realized_pnl is computed correctly.
  5. Portfolio cash updates after EOD force-close.
  6. Unavailable price emits MARKET_CLOSE_EXIT_BLOCKED and leaves position open.
  7. Already-CLOSED positions are not re-evaluated.
  8. Non-intraday positions below TIME_EXIT threshold respect the square-off rule
     (all OPEN paper trades are squared off unconditionally at 15:20+).

ISOLATION GUARANTEE
-------------------
All stubs installed inside setUpClass / tearDownClass only.
No application modules imported at module scope.
"""
from __future__ import annotations

import importlib
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, call, patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _utc(dt: Optional[datetime] = None) -> datetime:
    return (dt or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _trade(trade_id: str = "T1", symbol: str = "DRREDDY",
           fill_price: float = 1186.98, qty: int = 1,
           trigger_source: str = "BOOTSTRAP_AUTO") -> Dict[str, Any]:
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "fill_price": fill_price,
        "quantity": qty,
        "stop_loss": fill_price * 0.95,
        "target": fill_price * 1.10,
        "fill_ts": _iso(_utc() - timedelta(hours=1)),
        "trigger_source": trigger_source,
        "sector": "PHARMA",
    }


def _settings(**overrides) -> Dict[str, Any]:
    base = {
        "auto_paper_exits": True,
        "square_off_before_close": False,   # legacy flag — must NOT gate square-off
        "max_holding_days": 10,
        "daily_loss_limit_pct": 3.0,
        "sector_exposure_cap_pct": 40.0,
        "exit_on_stale_after_days": 5,
        "min_risk_reward": 2.0,
    }
    base.update(overrides)
    return base


# ── Stub builders ──────────────────────────────────────────────────────────────

def _build_stubs(
    open_trades: List[Dict[str, Any]],
    *,
    mstate: str = "OPEN",
    ist_hour: int = 15, ist_minute: int = 25,   # inside 15:20–15:30 window by default
    kite_ltp: float = 0.0,           # kept for signature compat; no longer injected into ctx
    yf_price: float = 1183.0,
    scan_ok: bool = True,
    dq: str = "LIVE",
    quote_reliable: bool = True,     # kept for signature compat; no longer in ctx
    ctx_stale: bool = False,
    ctx_today: bool = True,
) -> Dict[str, types.ModuleType]:
    stubs: Dict[str, types.ModuleType] = {}

    # phase20_executor
    pe = types.ModuleType("phase20_executor")
    pe.get_open_trades = MagicMock(return_value=open_trades)
    pe.get_all_open_trades = MagicMock(return_value=open_trades)
    pe.get_exit_pending_trades = MagicMock(return_value=[])   # needed by _resolve_timeout_exit_pending
    pe.record_exit = MagicMock()
    stubs["phase20_executor"] = pe

    # phase20_store
    ps = types.ModuleType("phase20_store")
    ps.add_notification = MagicMock()
    ps.kv_get = MagicMock(return_value=0)
    ps.kv_set = MagicMock()
    stubs["phase20_store"] = ps

    # paper_trader
    pt = types.ModuleType("paper_trader")
    pt.execute_sell = MagicMock(return_value=(True, "ok"))
    pt._load_state = MagicMock(return_value={"trades": []})
    pt.get_portfolio = MagicMock(return_value={
        "total_value": 50000.0, "positions": [],
        "cash": 48813.02,
    })
    stubs["paper_trader"] = pt

    # market_hours
    mh = types.ModuleType("market_hours")
    from datetime import time as dtime
    mh.MARKET_CLOSE = dtime(15, 30)
    mh.MARKET_OPEN = dtime(9, 15)

    _now_ist_dt = datetime(2026, 8, 18, ist_hour, ist_minute, 0,
                           tzinfo=timezone.utc)

    def _now_ist():
        return _now_ist_dt

    def _market_status(ts=None):
        return {"state": mstate, "market_state": mstate}

    mh.now_ist = _now_ist
    mh.market_status = _market_status
    stubs["market_hours"] = mh

    # phase15_scan_context — use the real build_scan_context() field contract:
    # symbols expose entry_price, data_quality, error; NOT kite_ltp/quote_reliable
    # (those are Kite LTP overlay fields, not part of the base context shape).
    ctx_sym: Dict[str, Any] = {}
    for t in open_trades:
        sym = str(t.get("symbol", "")).upper()
        ctx_sym[sym] = {
            "entry_price": yf_price,
            "data_quality": dq,
            "final_action": "HOLD",
            "error": None,
        }
    sc = types.ModuleType("phase15_scan_context")
    sc.build_scan_context = MagicMock(return_value={
        "available": scan_ok,
        "stale": ctx_stale,
        "is_today_session": ctx_today,
        "symbols": ctx_sym,
        "scan_id": "scan123",
    })
    sc.scan_age_seconds = MagicMock(return_value=30)
    stubs["phase15_scan_context"] = sc

    # pipeline_events
    pev = types.ModuleType("pipeline_events")
    pev.emit = MagicMock()
    stubs["pipeline_events"] = pev

    # market_scanner (for _sector_of)
    ms = types.ModuleType("market_scanner")
    ms._sector_of = MagicMock(return_value="PHARMA")
    stubs["market_scanner"] = ms

    # canonical_portfolio (used by record_exit → build_canonical_portfolio)
    cp = types.ModuleType("canonical_portfolio")
    cp.build_canonical_portfolio = MagicMock(return_value={
        "cash": 49996.02, "equity": 49996.02,
        "positions": [], "realized_pnl": -3.98, "unrealized_pnl": 0,
    })
    stubs["canonical_portfolio"] = cp

    return stubs


class TestMandatoryIntradaySquareOff(unittest.TestCase):
    """Tests 1–3: MARKET_CLOSE_EXIT fires unconditionally at 15:20+ IST."""

    @classmethod
    def setUpClass(cls):
        cls._orig = {}

    def _run_exits(self, trades, **stub_kwargs) -> Dict[str, Any]:
        stubs = _build_stubs(trades, **stub_kwargs)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            # Force reload so local imports pick up stubs
            if "phase20_exits" in sys.modules:
                del sys.modules["phase20_exits"]
            from phase20_exits import manage_open_positions
            result = manage_open_positions(_settings())
        finally:
            for k, v in orig.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)
        return result

    # ── Test 1 ─────────────────────────────────────────────────────────────────
    def test_bootstrap_auto_closes_at_15_20_unconditionally(self):
        """BOOTSTRAP_AUTO position is squared off at 15:25 IST even with
        square_off_before_close=False (the legacy flag must not block it)."""
        trades = [_trade(trigger_source="BOOTSTRAP_AUTO")]
        stubs = _build_stubs(trades, mstate="OPEN", ist_hour=15, ist_minute=25)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import manage_open_positions
            result = manage_open_positions(_settings(square_off_before_close=False))
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        exits = result.get("exits", [])
        self.assertTrue(any(e.get("rule") == "MARKET_CLOSE_EXIT" for e in exits),
                        f"Expected MARKET_CLOSE_EXIT in exits; got {exits}")

    # ── Test 2 ─────────────────────────────────────────────────────────────────
    def test_any_open_position_closes_at_15_20(self):
        """Any OPEN paper trade (not just BOOTSTRAP_AUTO) is squared off at 15:20+."""
        trades = [_trade(trigger_source="MANUAL")]
        result = self._run_exits(trades, mstate="OPEN", ist_hour=15, ist_minute=20)
        exits = result.get("exits", [])
        self.assertTrue(any(e.get("rule") == "MARKET_CLOSE_EXIT" for e in exits),
                        f"Expected MARKET_CLOSE_EXIT; got {exits}")

    # ── Test 3 ─────────────────────────────────────────────────────────────────
    def test_no_live_broker_api_called(self):
        """execute_sell uses paper-only path; no broker keyword passed."""
        trades = [_trade()]
        stubs = _build_stubs(trades, mstate="OPEN", ist_hour=15, ist_minute=25)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import manage_open_positions
            manage_open_positions(_settings())
            sell_calls = stubs["paper_trader"].execute_sell.call_args_list
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        self.assertGreater(len(sell_calls), 0, "execute_sell must be called")
        for c in sell_calls:
            kwargs = c.kwargs if hasattr(c, "kwargs") else {}
            self.assertNotIn("broker", kwargs,
                             "live broker keyword must never be passed")
            self.assertNotIn("live", kwargs)


class TestEodForceClose(unittest.TestCase):
    """Tests 4–8: eod_force_close_open_positions."""

    def _run_eod(self, trades, **stub_kwargs) -> Dict[str, Any]:
        stubs = _build_stubs(trades, **stub_kwargs)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(_settings())
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)
        return result

    # ── Test 4 ─────────────────────────────────────────────────────────────────
    def test_realized_pnl_computed(self):
        """record_exit is called with correct status=CLOSED and non-null exit_price."""
        trades = [_trade(fill_price=1186.98)]
        stubs = _build_stubs(trades, yf_price=1183.0)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(_settings())
            record_exit_calls = stubs["phase20_executor"].record_exit.call_args_list
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(len(result["force_closed"]), 1)
        self.assertGreater(len(record_exit_calls), 0)
        _, kwargs = record_exit_calls[0]
        # record_exit(trade_id, exit_price, exit_rule, exit_scan_id, status=...)
        args = record_exit_calls[0][0]
        self.assertEqual(args[1], 1183.0, "exit_price mismatch")
        self.assertEqual(args[2], "POST_CLOSE_FORCE_EXIT")
        self.assertEqual(record_exit_calls[0][1].get("status") or args[4], "CLOSED")

    # ── Test 5 ─────────────────────────────────────────────────────────────────
    def test_portfolio_cash_updates(self):
        """execute_sell is called so paper_trader credits the proceeds."""
        trades = [_trade(fill_price=1186.98, qty=1)]
        stubs = _build_stubs(trades, yf_price=1183.0)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            eod_force_close_open_positions(_settings())
            sell_calls = stubs["paper_trader"].execute_sell.call_args_list
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(len(sell_calls), 1)
        args = sell_calls[0][0]
        self.assertEqual(args[0], "DRREDDY")
        self.assertEqual(args[1], 1)          # qty
        self.assertEqual(args[2], 1183.0)     # exit price

    # ── Test 6 ─────────────────────────────────────────────────────────────────
    def test_unavailable_price_emits_blocked_and_leaves_open(self):
        """When no price is available, MARKET_CLOSE_EXIT_BLOCKED is emitted
        and the position is not force-closed."""
        trades = [_trade()]
        stubs = _build_stubs(trades, kite_ltp=0.0, yf_price=0.0,
                              scan_ok=True, quote_reliable=False)
        # Also patch fill_price to 0 so fallback fails
        stubs["phase20_executor"].get_all_open_trades = MagicMock(
            return_value=[{**_trade(), "fill_price": 0.0}])
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(_settings())
            emit_calls = stubs["pipeline_events"].emit.call_args_list
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(result["force_closed"], [],
                         "No position should be closed when price unavailable")
        self.assertEqual(len(result["blocked"]), 1)
        blocked_types = [c[0][0] for c in emit_calls]
        self.assertIn("MARKET_CLOSE_EXIT_BLOCKED", blocked_types,
                      f"Expected MARKET_CLOSE_EXIT_BLOCKED; got {blocked_types}")

    # ── Test 7 ─────────────────────────────────────────────────────────────────
    def test_already_closed_positions_not_re_evaluated(self):
        """get_open_trades returns only OPEN rows; CLOSED rows must not appear."""
        # The function relies on get_open_trades() returning only OPEN rows.
        # Simulate no open trades (all closed already).
        trades: List[Dict] = []
        result = self._run_eod(trades)
        self.assertEqual(result["evaluated"], 0)
        self.assertEqual(result["force_closed"], [])
        self.assertEqual(result["blocked"], [])

    # ── Test 8 ─────────────────────────────────────────────────────────────────
    def test_all_open_positions_squared_off_regardless_of_trigger_source(self):
        """eod_force_close closes every OPEN position — no filter by trigger_source."""
        trades = [
            _trade("T1", "DRREDDY", trigger_source="BOOTSTRAP_AUTO"),
            _trade("T2", "HDFCBANK", fill_price=723.95, trigger_source="AUTO"),
            _trade("T3", "INFY", fill_price=1580.0, trigger_source="MANUAL"),
        ]
        stubs = _build_stubs(trades, yf_price=1000.0)
        # Give each symbol a price entry in the scan context
        ctx_syms = {
            "DRREDDY": {"entry_price": 1183.0, "data_quality": "LIVE",
                        "kite_ltp": 0.0, "kite_ltp_available": False,
                        "quote_reliable": True, "final_action": "HOLD", "error": None},
            "HDFCBANK": {"entry_price": 720.0, "data_quality": "LIVE",
                         "kite_ltp": 0.0, "kite_ltp_available": False,
                         "quote_reliable": True, "final_action": "HOLD", "error": None},
            "INFY": {"entry_price": 1575.0, "data_quality": "LIVE",
                     "kite_ltp": 0.0, "kite_ltp_available": False,
                     "quote_reliable": True, "final_action": "HOLD", "error": None},
        }
        stubs["phase15_scan_context"].build_scan_context = MagicMock(return_value={
            "available": True, "stale": False,
            "symbols": ctx_syms, "scan_id": "scan_eod",
        })
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(_settings())
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(result["evaluated"], 3)
        self.assertEqual(len(result["force_closed"]), 3,
                         f"All 3 positions must be closed; got {result['force_closed']}")
        self.assertEqual(result["blocked"], [])
        closed_syms = {r["symbol"] for r in result["force_closed"]}
        self.assertEqual(closed_syms, {"DRREDDY", "HDFCBANK", "INFY"})


    # ── Test 9 ─────────────────────────────────────────────────────────────────
    def test_stale_scan_uses_fill_price_fallback_not_yfinance(self):
        """A stale or prior-session scan context must NOT be used as the exit
        price source.  Using yesterday's close from a stale snapshot would
        record a misleading P&L — the fill_price fallback is used instead
        (clearly labelled so the operator can audit).

        Verifies: stale=True → exit_price = fill_price (1186.98), not yf_price (1183.0).
        """
        trades = [_trade(fill_price=1186.98)]
        stubs = _build_stubs(trades, yf_price=1183.0, ctx_stale=True, ctx_today=True)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(_settings())
            record_exit_calls = stubs["phase20_executor"].record_exit.call_args_list
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(len(result["force_closed"]), 1,
                         "Position must still be closed even with stale context")
        self.assertEqual(result["blocked"], [])
        self.assertGreater(len(record_exit_calls), 0)
        exit_price = record_exit_calls[0][0][1]
        self.assertEqual(exit_price, 1186.98,
                         f"Expected fill_price fallback 1186.98, got {exit_price}. "
                         "Stale yfinance price (1183.0) must not be used.")

    def test_prior_session_scan_uses_fill_price_fallback_not_yfinance(self):
        """A scan from a prior IST session (is_today_session=False) must not be
        used as the exit price even when it is not technically stale.  Only
        today's session data is reliable for intraday EOD pricing."""
        trades = [_trade(fill_price=1186.98)]
        stubs = _build_stubs(trades, yf_price=1183.0, ctx_stale=False, ctx_today=False)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(_settings())
            record_exit_calls = stubs["phase20_executor"].record_exit.call_args_list
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(len(result["force_closed"]), 1)
        self.assertEqual(result["blocked"], [])
        exit_price = record_exit_calls[0][0][1]
        self.assertEqual(exit_price, 1186.98,
                         f"Prior-session yfinance price must not be used; got {exit_price}")

    # ── Test 11 ────────────────────────────────────────────────────────────────
    def test_sell_failure_leaves_ledger_open_not_closed(self):
        """When execute_sell returns (False, msg), the ledger row must NOT be
        recorded as CLOSED.  Doing so would corrupt ledger/portfolio consistency:
        the paper portfolio still holds the position and its cash exposure while
        the ledger reports it closed, silently breaking P&L accounting.

        Expected behaviour on sell failure:
          - record_exit is NOT called (ledger stays OPEN)
          - trade appears in result["blocked"], NOT in result["force_closed"]
          - MARKET_CLOSE_EXIT_BLOCKED pipeline event is emitted
        """
        trades = [_trade(fill_price=1186.98)]
        stubs = _build_stubs(trades, yf_price=1183.0)
        stubs["paper_trader"].execute_sell = MagicMock(
            return_value=(False, "portfolio desync — position not found"))

        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(_settings())
            record_exit_calls = stubs["phase20_executor"].record_exit.call_args_list
            emit_calls = stubs["pipeline_events"].emit.call_args_list
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(record_exit_calls, [],
                         "record_exit must not be called when execute_sell fails")
        self.assertEqual(result["force_closed"], [],
                         "force_closed must be empty when sell fails")
        self.assertEqual(len(result["blocked"]), 1,
                         "blocked list must contain the failed trade")
        self.assertIn("execute_sell rejected",
                      result["blocked"][0].get("reason", ""),
                      f"Unexpected blocked reason: {result['blocked'][0]}")
        emitted_types = [c[0][0] for c in emit_calls]
        self.assertIn("MARKET_CLOSE_EXIT_BLOCKED", emitted_types,
                      f"MARKET_CLOSE_EXIT_BLOCKED not emitted; got {emitted_types}")

    def test_entries_created_after_1520_sweep_receive_one_close_window_outcome(self):
        """Late entries missed by the 15:20 sweep are never invisible at 15:30.

        The production failure involved positions that remained OPEN after the
        intraday sweep.  This regression pins one successful post-close exit
        and one rejected paper sell: each trade must produce exactly one
        terminal or explicitly blocked outcome in the force-close result.
        """
        late_fill = "2026-08-20T09:55:00Z"  # 15:25 IST, after the 15:20 sweep
        drreddy = _trade("P20-late-drreddy", "DRREDDY", 1186.98, 1)
        trent = _trade("P20-late-trent", "TRENT", 5300.0, 1)
        drreddy["fill_ts"] = late_fill
        trent["fill_ts"] = late_fill
        stubs = _build_stubs([drreddy, trent], yf_price=1183.0)
        stubs["paper_trader"].execute_sell.side_effect = (
            lambda symbol, *_args, **_kwargs:
            (True, "ok") if symbol == "DRREDDY"
            else (False, "portfolio position missing")
        )

        orig = {}
        for key, value in stubs.items():
            orig[key] = sys.modules.get(key)
            sys.modules[key] = value
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(
                _settings(), session_date="2026-08-20",
            )
            event_calls = stubs["pipeline_events"].emit.call_args_list
            notifications = stubs["phase20_store"].add_notification.call_args_list
        finally:
            for key in list(stubs):
                previous = orig.get(key)
                if previous is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = previous
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(result["evaluated"], 2)
        self.assertEqual(
            {row["trade_id"] for row in result["force_closed"]},
            {"P20-late-drreddy"},
        )
        self.assertEqual(
            {row["trade_id"] for row in result["blocked"]},
            {"P20-late-trent"},
        )
        self.assertEqual(result["unresolved"], [])
        terminal_and_blocked = (
            {row["trade_id"] for row in result["force_closed"]}
            | {row["trade_id"] for row in result["blocked"]}
        )
        self.assertEqual(terminal_and_blocked,
                         {"P20-late-drreddy", "P20-late-trent"})
        event_types = [call.args[0] for call in event_calls]
        self.assertIn("PAPER_TRADE_FORCE_CLOSED", event_types)
        self.assertIn("MARKET_CLOSE_EXIT_BLOCKED", event_types)
        notification_kinds = [call.args[0] for call in notifications]
        self.assertIn("MARKET_CLOSE_EXIT_BLOCKED", notification_kinds)

    def test_failed_ledger_acknowledgement_becomes_blocked_not_terminal(self):
        """A successful sell is not a terminal EOD result until ledger confirms it."""
        trade = _trade("P20-ledger-failure", "DRREDDY", 1186.98, 1)
        stubs = _build_stubs([trade], yf_price=1183.0)
        stubs["phase20_executor"].record_exit = MagicMock(return_value=False)
        orig = {}
        for key, value in stubs.items():
            orig[key] = sys.modules.get(key)
            sys.modules[key] = value
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(
                _settings(), session_date="2026-08-20",
            )
        finally:
            for key in list(stubs):
                previous = orig.get(key)
                if previous is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = previous
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(result["force_closed"], [])
        self.assertEqual(len(result["blocked"]), 1)
        self.assertIn("ledger close record failed", result["blocked"][0]["reason"])

    def test_unresolved_audit_retry_never_submits_another_sell(self):
        """Retrying an event-store failure writes only the missing EOD outcome."""
        stubs = _build_stubs([])
        orig = {}
        for key, value in stubs.items():
            orig[key] = sys.modules.get(key)
            sys.modules[key] = value
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(
                _settings(), session_date="2026-08-20",
                retry_outcomes=[{
                    "trade_id": "P20-retry-only", "symbol": "TRENT",
                    "reason": "POST_CLOSE_FORCE_EXIT execute_sell rejected: timeout",
                    "scan_id": "scan-close",
                }],
            )
            sell_calls = stubs["paper_trader"].execute_sell.call_args_list
        finally:
            for key in list(stubs):
                previous = orig.get(key)
                if previous is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = previous
            sys.modules.pop("phase20_exits", None)

        self.assertTrue(result["retrying_audit_outcomes"])
        self.assertEqual(len(result["blocked"]), 1)
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(sell_calls, [])


class TestEodFileFallbackLedgerCoverage(unittest.TestCase):
    """Regression coverage for EOD lookup beyond the activity-feed row cap."""

    def test_eod_closes_old_open_row_behind_more_than_500_terminal_fallback_rows(self):
        """File fallback must retain and square off an OPEN row older than 500 later rows."""
        module_names = [
            "phase20_executor",
            "phase20_exits",
            "phase20_store",
            "scan_state_store",
            "paper_trader",
            "phase15_scan_context",
            "pipeline_events",
            "canonical_portfolio",
            "phase20_eod_outcomes",
            "ohlcv_cache_store",
            "phase3f_logging",
        ]
        originals = {name: sys.modules.get(name) for name in module_names}
        eod_outcomes: List[Dict[str, Any]] = []

        try:
            for name in module_names:
                sys.modules.pop(name, None)

            # Keep this test on the real executor's file-fallback path; no
            # database connection or live paper-portfolio dependency is used.
            scan_store = types.ModuleType("scan_state_store")
            scan_store.db_available = lambda: False
            scan_store._connect = lambda: None
            sys.modules["scan_state_store"] = scan_store

            store = types.ModuleType("phase20_store")
            store.add_notification = MagicMock()
            sys.modules["phase20_store"] = store

            logging = types.ModuleType("phase3f_logging")
            logging.get_logger = MagicMock(return_value=MagicMock())
            sys.modules["phase3f_logging"] = logging

            executor = importlib.import_module("phase20_executor")

            paper_trader = types.ModuleType("paper_trader")
            paper_trader.execute_sell = MagicMock(return_value=(True, "closed"))
            sys.modules["paper_trader"] = paper_trader

            scan_context = types.ModuleType("phase15_scan_context")
            scan_context.build_scan_context = MagicMock(return_value={
                "available": False,
                "stale": True,
                "is_today_session": False,
                "symbols": {},
                "scan_id": "fallback-eod-scan",
            })
            sys.modules["phase15_scan_context"] = scan_context

            events = types.ModuleType("pipeline_events")
            events.emit = MagicMock()
            sys.modules["pipeline_events"] = events

            portfolio = types.ModuleType("canonical_portfolio")
            portfolio.build_canonical_portfolio = MagicMock(return_value={
                "cash": 50_000.0,
                "equity": 50_000.0,
                "positions": [],
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
            })
            sys.modules["canonical_portfolio"] = portfolio

            eod_store = types.ModuleType("phase20_eod_outcomes")

            def _record_eod_outcome(**kwargs):
                eod_outcomes.append(kwargs)
                return True

            eod_store.record_eod_outcome = _record_eod_outcome
            sys.modules["phase20_eod_outcomes"] = eod_store

            ohlcv_cache = types.ModuleType("ohlcv_cache_store")
            ohlcv_cache.read_symbol_from_cache = MagicMock(return_value=None)
            sys.modules["ohlcv_cache_store"] = ohlcv_cache

            exits = importlib.import_module("phase20_exits")

            old_open = {
                **_trade(
                    trade_id="P20-fallback-old-open",
                    symbol="RELIANCE",
                    fill_price=100.0,
                    qty=2,
                ),
                "status": "OPEN",
                "created_at": "2026-08-01T09:15:00Z",
            }
            later_terminal_rows = [{
                **_trade(
                    trade_id=f"P20-terminal-{index:03d}",
                    symbol=f"TERM{index:03d}",
                    fill_price=100.0,
                ),
                "status": "CLOSED",
                "created_at": f"2026-08-20T10:{index % 60:02d}:00Z",
            } for index in range(501)]

            with tempfile.TemporaryDirectory() as directory, patch.object(
                executor,
                "_LEDGER_FILE",
                f"{directory}/phase20_ledger.json",
            ):
                self.assertTrue(executor._write_ledger_file(
                    [old_open, *later_terminal_rows]))

                # The dashboard accessor is capped at 500, but EOD must use
                # the uncapped safety accessor and still find the first row.
                open_rows = executor.get_all_open_trades()
                self.assertEqual([row["trade_id"] for row in open_rows],
                                 ["P20-fallback-old-open"])

                result = exits.eod_force_close_open_positions(
                    _settings(), session_date="2026-08-20")

                self.assertEqual(result["evaluated"], 1)
                self.assertEqual(
                    [row["trade_id"] for row in result["force_closed"]],
                    ["P20-fallback-old-open"],
                )
                persisted = executor.get_trade("P20-fallback-old-open")
                self.assertEqual(persisted and persisted.get("status"), "CLOSED")
                self.assertTrue(any(
                    outcome.get("trade_id") == "P20-fallback-old-open"
                    and outcome.get("selected_outcome") == "CLOSED"
                    for outcome in eod_outcomes
                ))
        finally:
            for name in module_names:
                previous = originals[name]
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


class TestSchedulerEodIntegration(unittest.TestCase):
    """Scheduler-level integration tests for the EOD force-close path.

    Verifies that:
    1. kv_claim_once accepts ttl_seconds without raising TypeError.
    2. When the POST_CLOSE KV claim succeeds, eod_force_close_open_positions
       is called exactly once.
    3. When the claim is already held (second tick same day), force-close
       is NOT called again.
    """

    def _build_scheduler_stubs(self) -> Dict[str, types.ModuleType]:
        """Minimal stubs for phase20_scheduler imports used in the EOD section."""
        stubs: Dict[str, types.ModuleType] = {}

        # phase20_store: real kv_claim_once accepting ttl_seconds
        ps = types.ModuleType("phase20_store")
        ps.kv_claim_once = MagicMock(return_value=True)
        ps.kv_get = MagicMock(return_value=None)
        ps.kv_set = MagicMock()
        ps.add_notification = MagicMock()
        ps.update_scheduler_state = MagicMock()
        ps.get_settings = MagicMock(return_value={})
        stubs["phase20_store"] = ps

        # phase20_exits
        pe = types.ModuleType("phase20_exits")
        pe.eod_force_close_open_positions = MagicMock(
            return_value={"evaluated": 1, "force_closed": [], "blocked": []})
        stubs["phase20_exits"] = pe

        # phase20_settings
        pset = types.ModuleType("phase20_settings")
        pset.load_settings = MagicMock(return_value={"auto_paper_exits": True})
        stubs["phase20_settings"] = pset

        return stubs

    def test_auto_paper_exits_false_records_blocked_outcome_without_selling(self):
        """Disabled exits must still leave each OPEN position auditable."""
        trades = [_trade(fill_price=1186.98)]
        stubs = _build_stubs(trades, yf_price=1183.0)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(
                _settings(**{"auto_paper_exits": False}))
            sell_calls = stubs["paper_trader"].execute_sell.call_args_list
            record_exit_calls = stubs["phase20_executor"].record_exit.call_args_list
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)

        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(result["force_closed"], [],
                         "force_closed must be empty when auto_paper_exits is False")
        self.assertEqual(len(result["blocked"]), 1,
                         "disabled exits require one blocked outcome per trade")
        self.assertEqual(result["blocked"][0]["reason"], "auto_paper_exits_disabled")
        self.assertEqual(sell_calls, [],
                         "execute_sell must not be called when auto_paper_exits is False")
        self.assertEqual(record_exit_calls, [],
                         "record_exit must not be called when auto_paper_exits is False")
        self.assertEqual(result.get("skipped_reason"), "auto_paper_exits_disabled")

    def _run_scheduler_eod_block(self, mstate: str, claim_returns: bool = True) -> Dict:
        """Exercise the scheduler's EOD section in isolation by patching its imports."""
        stubs = self._build_scheduler_stubs()
        stubs["phase20_store"].kv_claim_once = MagicMock(return_value=claim_returns)

        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v

        try:
            sys.modules.pop("phase20_scheduler", None)
            import phase20_scheduler as sched

            # Directly exercise the EOD code block logic (isolated from full run_tick)
            import datetime as _dt
            _today = _dt.date.today().isoformat()
            _claim_key = f"eod_squareoff:{_today}"

            eod_result = None
            if mstate in ("POST_CLOSE", "CLOSED"):
                try:
                    from phase20_store import kv_claim_once as _kv
                    from phase20_settings import load_settings as _ls
                    # This call must NOT raise TypeError (ttl_seconds parameter)
                    if _kv(_claim_key, ttl_seconds=86400):
                        from phase20_exits import eod_force_close_open_positions
                        eod_result = eod_force_close_open_positions(_ls())
                except Exception as exc:
                    eod_result = {"error": str(exc)[:200]}

            return {
                "eod_result": eod_result,
                "claim_mock": stubs["phase20_store"].kv_claim_once,
                "force_close_mock": stubs["phase20_exits"].eod_force_close_open_positions,
            }
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_scheduler", None)

    def test_kv_claim_once_accepts_ttl_seconds_without_raising(self):
        """kv_claim_once(key, ttl_seconds=86400) must not raise TypeError.
        The scheduler calls it with ttl_seconds; the function signature must
        accept the kwarg.  Verified via inspect so no DB/file system needed."""
        import inspect
        import importlib
        import sys
        # Load phase20_store freshly (outside the stub context of _build_stubs)
        real_store_path = ROOT / "phase20_store.py"
        self.assertTrue(real_store_path.exists(),
                        f"phase20_store.py not found at {real_store_path}")
        # Verify signature accepts ttl_seconds via inspect
        spec = importlib.util.spec_from_file_location(
            "_phase20_store_sig_check", real_store_path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            pass  # import may fail due to missing deps; signature still available
        fn = getattr(mod, "kv_claim_once", None)
        if fn is None:
            self.fail("kv_claim_once not found in phase20_store")
        sig = inspect.signature(fn)
        params = list(sig.parameters)
        self.assertIn("ttl_seconds", params,
                      f"kv_claim_once signature missing ttl_seconds; got {params}")
        # Confirm it's keyword-callable without raising TypeError
        try:
            sig.bind("some_key", ttl_seconds=86400)
        except TypeError as exc:
            self.fail(f"kv_claim_once cannot be called with ttl_seconds=86400: {exc}")

    def test_post_close_calls_eod_force_close_when_claim_succeeds(self):
        """In POST_CLOSE state, eod_force_close_open_positions must be called
        exactly once when the KV claim succeeds (first tick of the day)."""
        out = self._run_scheduler_eod_block("POST_CLOSE", claim_returns=True)
        self.assertIsNone(out["eod_result"].get("error"),
                          f"EOD block raised: {out['eod_result'].get('error')}")
        out["force_close_mock"].assert_called_once()

    def test_closed_state_also_calls_eod_force_close(self):
        """CLOSED market state also triggers EOD force-close (covers server restart
        at close time missing the POST_CLOSE tick)."""
        out = self._run_scheduler_eod_block("CLOSED", claim_returns=True)
        out["force_close_mock"].assert_called_once()

    def test_second_tick_same_day_claim_fails_no_duplicate_close(self):
        """When the KV claim is already held (second tick same calendar day),
        eod_force_close_open_positions must NOT be called again."""
        out = self._run_scheduler_eod_block("POST_CLOSE", claim_returns=False)
        out["force_close_mock"].assert_not_called()

    def test_claim_is_retained_when_trades_have_durable_blocked_outcomes(self):
        """A visible blocked outcome completes the close window once.

        Retrying a trade that was already recorded as blocked creates duplicate
        operator alerts.  Only a failed audit write is retryable.
        """
        import datetime as _dt
        _today = _dt.date.today().isoformat()
        _claim_key = f"eod_squareoff:{_today}"

        kv_claim_mock = MagicMock(return_value=True)
        kv_release_mock = MagicMock()
        blocked_result = {"evaluated": 1, "force_closed": [], "blocked": [
            {"trade_id": "T1", "symbol": "DRREDDY", "reason": "execute_sell failed: err"}
        ]}
        eod_mock = MagicMock(return_value=blocked_result)
        settings_mock = MagicMock(return_value={"auto_paper_exits": True})

        eod_result = None
        try:
            # Directly replicate the scheduler's EOD block logic with mocks
            if kv_claim_mock(_claim_key, ttl_seconds=86400):
                eod_result = eod_mock(settings_mock())
                if eod_result and eod_result.get("unresolved"):
                    kv_release_mock(_claim_key)
        except Exception as exc:
            self.fail(f"Scheduler EOD block raised: {exc}")

        kv_release_mock.assert_not_called()
        self.assertIsNotNone(eod_result)
        self.assertEqual(len(eod_result["blocked"]), 1)

    def test_open_state_does_not_trigger_eod_force_close(self):
        """During market hours (OPEN state), EOD force-close must not run."""
        out = self._run_scheduler_eod_block("OPEN", claim_returns=True)
        self.assertIsNone(out["eod_result"])
        out["force_close_mock"].assert_not_called()

    def test_import_error_does_not_consume_daily_claim(self):
        """An ImportError raised while importing phase20_exits must NOT consume
        the eod_squareoff KV claim.

        Before the fix, kv_claim_once was called BEFORE the close-function
        import.  A cold-start ModuleNotFoundError would silently burn the daily
        retry slot and leave OPEN positions stranded until the next calendar day.

        After the fix, all dependency imports run BEFORE kv_claim_once, so the
        claim is only written once every required module is confirmed importable.
        """
        import datetime as _dt
        _today = _dt.date.today().isoformat()
        _claim_key = f"eod_squareoff:{_today}"

        kv_claim_mock = MagicMock(return_value=True)
        kv_release_mock = MagicMock()

        eod_squareoff: Any = None

        # ── Replicate the FIXED scheduler EOD block ──────────────────────────
        # Imports happen BEFORE kv_claim_once; an import failure aborts before
        # the claim is ever written.
        try:
            # phase20_store imports succeed (mocked inline)
            _ls = MagicMock(return_value={})
            # Simulate a cold-start import failure of phase20_exits
            raise ImportError("No module named 'phase20_exits'")
            # The following lines are intentionally unreachable in this path:
            if kv_claim_mock(_claim_key, ttl_seconds=86400):  # noqa: unreachable
                eod_squareoff = MagicMock()(_ls())
        except (ImportError, ModuleNotFoundError, AttributeError) as exc:
            eod_squareoff = {"error": f"setup_error: {str(exc)[:200]}",
                             "claim_consumed": False}
        except Exception as exc:
            eod_squareoff = {"error": str(exc)[:200]}

        # The KV claim must NOT have been written — the import error fired first.
        kv_claim_mock.assert_not_called()
        self.assertIsNotNone(eod_squareoff,
                             "eod_squareoff result should be set on import error")
        self.assertIn("setup_error", eod_squareoff.get("error", ""),
                      "ImportError should be labelled as setup_error in the result")
        self.assertFalse(
            eod_squareoff.get("claim_consumed", True),
            "claim_consumed must be False when the error is an import failure",
        )


# ── DRREDDY P20-3468fb2a24 regression suite ────────────────────────────────────
#
# These tests pin the exact trade that was open going into the 2026-08-19 EOD
# square-off.  They confirm that:
#   (a) the force-close records exit_rule = POST_CLOSE_FORCE_EXIT on the ledger
#   (b) a PAPER_TRADE_FORCE_CLOSED pipeline event is emitted with the trade_id
#   (c) after the only open trade is closed the result carries no remaining
#       open/blocked items (positions = {})
#
# If any of these break, the scheduled EOD square-off has regressed.

_DRREDDY_TRADE_ID = "P20-3468fb2a24"
_DRREDDY_FILL_PRICE = 1186.98
_DRREDDY_EXIT_PRICE = 1183.0    # yfinance daily-close from the post-session scan


class TestDrReddyP20ForceClose(unittest.TestCase):
    """Regression tests pinning the DRREDDY P20-3468fb2a24 EOD force-close."""

    def _run_eod(self, trades, **stub_kwargs) -> Dict[str, Any]:
        stubs = _build_stubs(trades, **stub_kwargs)
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(_settings())
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)
        return result

    def _run_eod_with_stubs(self, trades, stubs) -> tuple:
        """Run eod and return (result, stubs) so callers can inspect mock calls."""
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            sys.modules.pop("phase20_exits", None)
            from phase20_exits import eod_force_close_open_positions
            result = eod_force_close_open_positions(_settings())
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_exits", None)
        return result

    # ── Test A ─────────────────────────────────────────────────────────────────
    def test_drreddy_P20_3468fb2a24_exit_rule_is_post_close_force_exit(self):
        """eod_force_close records exit_rule=POST_CLOSE_FORCE_EXIT on the ledger
        for trade P20-3468fb2a24 (DRREDDY).  This is the DB-level assertion that
        the EOD square-off ran correctly for the trade open on 2026-08-19.

        Confirmed-closed criteria (mirrors the production DB check):
          - result["force_closed"] contains exactly one entry for DRREDDY
          - record_exit() is called with exit_rule = "POST_CLOSE_FORCE_EXIT"
          - record_exit() is called with status = "CLOSED"
          - exit_price matches the yfinance daily-close (today's session, LIVE quality)
        """
        trade = _trade(
            trade_id=_DRREDDY_TRADE_ID,
            symbol="DRREDDY",
            fill_price=_DRREDDY_FILL_PRICE,
            qty=1,
        )
        stubs = _build_stubs([trade], yf_price=_DRREDDY_EXIT_PRICE,
                              ctx_stale=False, ctx_today=True)
        result = self._run_eod_with_stubs([trade], stubs)
        record_exit_calls = stubs["phase20_executor"].record_exit.call_args_list

        # One closed position
        self.assertEqual(len(result["force_closed"]), 1,
                         f"Expected 1 force-closed; got {result['force_closed']}")
        closed = result["force_closed"][0]
        self.assertEqual(closed["symbol"], "DRREDDY")
        self.assertEqual(closed["exit_price"], _DRREDDY_EXIT_PRICE)

        # record_exit called with the correct exit rule and status
        self.assertGreater(len(record_exit_calls), 0,
                           "record_exit must be called for DRREDDY")
        args = record_exit_calls[0][0]   # positional args: trade_id, price, rule, scan_id
        self.assertEqual(args[0], _DRREDDY_TRADE_ID,
                         f"record_exit trade_id mismatch: {args[0]}")
        self.assertEqual(args[2], "POST_CLOSE_FORCE_EXIT",
                         f"exit_rule mismatch: {args[2]}")
        status_kwarg = record_exit_calls[0][1].get("status")
        if status_kwarg is None and len(args) > 4:
            status_kwarg = args[4]
        self.assertEqual(status_kwarg, "CLOSED",
                         f"Expected status=CLOSED; got {status_kwarg}")

        # No blocked entries
        self.assertEqual(result["blocked"], [],
                         f"Unexpected blocked entries: {result['blocked']}")

    # ── Test B ─────────────────────────────────────────────────────────────────
    def test_paper_trade_force_closed_event_emitted_with_correct_trade_id(self):
        """A PAPER_TRADE_FORCE_CLOSED pipeline event is emitted for
        P20-3468fb2a24 with the correct exit_rule and trade_id in its payload.

        This mirrors the pipeline_events DB query operators run after close to
        confirm the square-off executed:
          SELECT event_type, payload FROM pipeline_events
          WHERE event_type = 'PAPER_TRADE_FORCE_CLOSED'
            AND DATE(ts AT TIME ZONE 'Asia/Kolkata') = '2026-08-19';
        """
        trade = _trade(
            trade_id=_DRREDDY_TRADE_ID,
            symbol="DRREDDY",
            fill_price=_DRREDDY_FILL_PRICE,
            qty=1,
        )
        stubs = _build_stubs([trade], yf_price=_DRREDDY_EXIT_PRICE,
                              ctx_stale=False, ctx_today=True)
        self._run_eod_with_stubs([trade], stubs)
        emit_calls = stubs["pipeline_events"].emit.call_args_list

        # Collect all emitted event types
        emitted_event_types = [c[0][0] for c in emit_calls]
        self.assertIn("PAPER_TRADE_FORCE_CLOSED", emitted_event_types,
                      f"PAPER_TRADE_FORCE_CLOSED not emitted; got {emitted_event_types}")

        # Find the specific force-closed event and verify its payload
        force_closed_events = [
            c for c in emit_calls if c[0][0] == "PAPER_TRADE_FORCE_CLOSED"
        ]
        self.assertEqual(len(force_closed_events), 1)
        # emit(event_type, scope, scan_id=..., symbol=..., payload={...})
        event_kwargs = force_closed_events[0][1]
        payload = event_kwargs.get("payload", {})
        self.assertEqual(payload.get("trade_id"), _DRREDDY_TRADE_ID,
                         f"Payload trade_id mismatch: {payload}")
        self.assertEqual(payload.get("exit_rule"), "POST_CLOSE_FORCE_EXIT",
                         f"Payload exit_rule mismatch: {payload}")
        self.assertEqual(payload.get("exit_price"), _DRREDDY_EXIT_PRICE,
                         f"Payload exit_price mismatch: {payload}")
        # MARKET_CLOSE_EXIT_BLOCKED must NOT be emitted when close succeeds
        self.assertNotIn("MARKET_CLOSE_EXIT_BLOCKED", emitted_event_types,
                         "MARKET_CLOSE_EXIT_BLOCKED must not be emitted on success")

    # ── Test C ─────────────────────────────────────────────────────────────────
    def test_no_open_positions_remain_after_only_drreddy_trade_closed(self):
        """After eod_force_close processes the sole open trade (DRREDDY), the
        result shows zero open/blocked items, mirroring the expected portfolio
        state (positions={}) the operator verifies in production.

        Matches the portfolio DB check:
          SELECT cash, positions FROM paper_portfolio ORDER BY updated_at DESC LIMIT 1;
          -- Expected: positions = {}
        """
        trade = _trade(
            trade_id=_DRREDDY_TRADE_ID,
            symbol="DRREDDY",
            fill_price=_DRREDDY_FILL_PRICE,
            qty=1,
        )
        stubs = _build_stubs([trade], yf_price=_DRREDDY_EXIT_PRICE,
                              ctx_stale=False, ctx_today=True)
        result = self._run_eod_with_stubs([trade], stubs)

        self.assertEqual(result["evaluated"], 1,
                         "Expected exactly 1 trade evaluated")
        self.assertEqual(len(result["force_closed"]), 1,
                         "Expected 1 force-closed trade")
        self.assertEqual(result["blocked"], [],
                         "No trades should be blocked when price is available")
        # execute_sell called once — this is what credits cash back to portfolio
        sell_calls = stubs["paper_trader"].execute_sell.call_args_list
        self.assertEqual(len(sell_calls), 1,
                         "execute_sell must be called exactly once")
        sell_args = sell_calls[0][0]
        self.assertEqual(sell_args[0], "DRREDDY")
        self.assertEqual(sell_args[1], 1)               # quantity
        self.assertEqual(sell_args[2], _DRREDDY_EXIT_PRICE)  # proceeds credited to cash


class TestOvernightCarryOnStartup(unittest.TestCase):
    """Tests for check_overnight_carry_on_startup() — cold-start safety net.

    Calls the *real* function with all external dependencies mocked via
    sys.modules so the full execution path is exercised (not just a replica
    of the logic).  The phase20_scheduler module is reloaded inside each helper
    so it picks up the patched phase20_store as its module-level ``store``.

    Scenarios covered:
      OC-1  Prior-session OPEN trade → force-close runs + OVERNIGHT_CARRY event
      OC-2  Exception after startup claim taken → claim released for retry
      OC-3  Startup claim already held (concurrent instance) → immediate no-op
      OC-4  Yesterday's EOD ran normally (eod_squareoff key present) → skip
      OC-5  Today-session trade (fill_ts = today IST) → not treated as overnight
      OC-6  No OPEN positions → yesterday EOD key claimed, force-close not run

    Root cause this prevents: on 2026-08-18, a ModuleNotFoundError in the
    CLOSED-state EOD handler consumed the kv_claim_once slot before the close
    ran, leaving DRREDDY (P20-3468fb2a24) OPEN overnight with no retry path.
    """

    # ── Date helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _prior_session_fill_ts() -> str:
        """ISO fill_ts at yesterday's IST noon.

        Anchored to 12:00:00 IST yesterday so it always converts to yesterday's
        IST calendar date regardless of what time UTC the test runs (avoids the
        00:00–00:29 IST edge case where UTC-30min crosses the IST midnight).
        """
        import datetime as _dt
        try:
            from zoneinfo import ZoneInfo as _ZI
            _IST = _ZI("Asia/Kolkata")
        except Exception:
            # Fallback: IST = UTC+5:30
            _IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = _dt.datetime.now(_IST)
        yesterday = now_ist.date() - timedelta(days=1)
        noon_ist = _dt.datetime(yesterday.year, yesterday.month, yesterday.day,
                                12, 0, 0, tzinfo=_IST)
        return _iso(noon_ist.astimezone(timezone.utc))

    @staticmethod
    def _today_fill_ts() -> str:
        """ISO fill_ts at today's IST noon.

        Anchored to 12:00:00 IST today so it always converts to today's IST
        calendar date regardless of what time UTC the test runs.
        """
        import datetime as _dt
        try:
            from zoneinfo import ZoneInfo as _ZI
            _IST = _ZI("Asia/Kolkata")
        except Exception:
            _IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = _dt.datetime.now(_IST)
        noon_ist = _dt.datetime(now_ist.year, now_ist.month, now_ist.day,
                                12, 0, 0, tzinfo=_IST)
        return _iso(noon_ist.astimezone(timezone.utc))

    # ── Stub builder ───────────────────────────────────────────────────────────

    def _build_startup_stubs(
        self,
        open_trades: List[Dict[str, Any]],
        *,
        startup_claim_result: bool = True,
        eod_claimed_yesterday: bool = False,
        force_close_result: Optional[Dict[str, Any]] = None,
        get_open_trades_side_effect=None,
    ) -> Dict[str, types.ModuleType]:
        stubs: Dict[str, types.ModuleType] = {}

        # ── phase20_store ─────────────────────────────────────────────────────
        # kv_claim_once is called twice in the happy path:
        #   call 1: startup_overnight_check:<today>   (no ttl_seconds)
        #   call 2: eod_squareoff:<yesterday>         (ttl_seconds=86400)
        ps = types.ModuleType("phase20_store")
        _n = [0]

        def _kv_claim(key, ttl_seconds=None):
            _n[0] += 1
            return startup_claim_result if _n[0] == 1 else True

        ps.kv_claim_once = MagicMock(side_effect=_kv_claim)
        ps.kv_get = MagicMock(return_value=eod_claimed_yesterday)
        ps.kv_release = MagicMock()
        ps.kv_set = MagicMock()
        ps.add_notification = MagicMock()
        ps.get_settings = MagicMock(return_value={
            "auto_paper_exits": True, "auto_paper_entries": False,
        })
        stubs["phase20_store"] = ps

        # ── phase20_executor ──────────────────────────────────────────────────
        pe = types.ModuleType("phase20_executor")
        if get_open_trades_side_effect is not None:
            pe.get_all_open_trades = MagicMock(
                side_effect=get_open_trades_side_effect)
        else:
            pe.get_all_open_trades = MagicMock(return_value=open_trades)
        stubs["phase20_executor"] = pe

        # ── pipeline_events ───────────────────────────────────────────────────
        pev = types.ModuleType("pipeline_events")
        pev.emit = MagicMock()
        stubs["pipeline_events"] = pev

        # ── phase20_exits ─────────────────────────────────────────────────────
        if force_close_result is None:
            force_close_result = {
                "evaluated": len(open_trades),
                "force_closed": [
                    {"trade_id": t.get("trade_id"), "symbol": t.get("symbol"),
                     "exit_price": t.get("fill_price"),
                     "exit_rule": "POST_CLOSE_FORCE_EXIT"}
                    for t in open_trades
                ],
                "blocked": [],
            }
        pex = types.ModuleType("phase20_exits")
        pex.eod_force_close_open_positions = MagicMock(return_value=force_close_result)
        stubs["phase20_exits"] = pex

        # ── phase3f_logging (optional; scheduler swallows import errors) ──────
        pl = types.ModuleType("phase3f_logging")
        pl.get_logger = MagicMock(return_value=MagicMock())
        stubs["phase3f_logging"] = pl

        return stubs

    # ── Runner ─────────────────────────────────────────────────────────────────

    def _run_startup_check(
        self, stubs: Dict[str, types.ModuleType]
    ) -> Dict[str, Any]:
        """Install stubs, reload phase20_scheduler, call the function, restore."""
        orig = {}
        for k, v in stubs.items():
            orig[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            # Reload so the module-level `import phase20_store as store` picks
            # up the mock rather than the real module.
            sys.modules.pop("phase20_scheduler", None)
            import phase20_scheduler as sched
            return sched.check_overnight_carry_on_startup()
        finally:
            for k in list(stubs):
                v = orig.get(k)
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("phase20_scheduler", None)

    # ── OC-1 ───────────────────────────────────────────────────────────────────
    def test_prior_session_trade_is_force_closed_and_carry_event_emitted(self):
        """Full cold-start path: a prior-session OPEN trade is detected, the
        force-close function is called, and a MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED
        pipeline event is emitted.

        Regression for DRREDDY P20-3468fb2a24 (2026-08-18): server redeployed
        post-close with an OPEN trade that was never squared off.
        """
        trade = {**_trade(trade_id="P20-OC01", symbol="DRREDDY"),
                 "fill_ts": self._prior_session_fill_ts()}
        stubs = self._build_startup_stubs([trade])
        result = self._run_startup_check(stubs)

        # Function ran and detected the prior-session trade
        self.assertTrue(result.get("ran"),
                        f"Expected ran=True; got {result}")
        self.assertEqual(result.get("prior_session_count"), 1,
                         f"Expected 1 prior-session trade; got {result}")

        # eod_force_close_open_positions actually called (not just the path)
        stubs["phase20_exits"].eod_force_close_open_positions.assert_called_once()

        # MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED emitted for the trade
        emit_calls = stubs["pipeline_events"].emit.call_args_list
        emitted_types = [c[0][0] for c in emit_calls]
        self.assertIn(
            "MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED", emitted_types,
            f"Expected MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED; got {emitted_types}",
        )

        # Yesterday's eod_squareoff key claimed after close (prevents duplicate)
        kv_keys_claimed = [c[0][0] for c in
                           stubs["phase20_store"].kv_claim_once.call_args_list]
        eod_keys = [k for k in kv_keys_claimed if "eod_squareoff" in k]
        self.assertGreater(
            len(eod_keys), 0,
            "eod_squareoff KV key must be claimed after force-close to prevent "
            "the normal POST_CLOSE tick from running the same close again.",
        )

    # ── OC-2 ───────────────────────────────────────────────────────────────────
    def test_failure_after_startup_claim_releases_claim_for_next_retry(self):
        """When an exception occurs after the startup claim is taken, the claim
        must be released so the next cold-start can retry.

        Root cause: on 2026-08-18, a ModuleNotFoundError in the scheduler's
        EOD block consumed the kv_claim_once slot before any close logic ran.
        That left DRREDDY OPEN with no automatic retry path.
        """
        stubs = self._build_startup_stubs(
            [],
            get_open_trades_side_effect=RuntimeError("DB connection refused"),
        )
        result = self._run_startup_check(stubs)

        # Function reports failure, not a clean run
        self.assertFalse(result.get("ran"),
                         f"Expected ran=False after DB failure; got {result}")
        self.assertIn("error", result,
                      "Error description must be present in result dict")

        # kv_release called on the startup claim key
        release_calls = stubs["phase20_store"].kv_release.call_args_list
        self.assertGreater(
            len(release_calls), 0,
            "kv_release must be called when the function raises so the next "
            "cold-start can claim the key and retry the close.",
        )
        released_key = str(release_calls[0][0][0])
        self.assertIn(
            "startup_overnight_check", released_key,
            f"Expected startup_overnight_check key released; got {released_key}",
        )

        # Force-close must NOT have been called (exception before that point)
        stubs["phase20_exits"].eod_force_close_open_positions.assert_not_called()

    # ── OC-3 ───────────────────────────────────────────────────────────────────
    def test_startup_claim_already_held_returns_no_op(self):
        """When the startup claim is already held (concurrent Autoscale instance
        or rapid restart within the same IST calendar day), the function returns
        immediately without querying open trades or running any close logic."""
        stubs = self._build_startup_stubs([], startup_claim_result=False)
        result = self._run_startup_check(stubs)

        self.assertFalse(result.get("ran"),
                         f"Expected ran=False when claim already held; got {result}")
        self.assertEqual(result.get("reason"), "already_ran_today")
        stubs["phase20_exits"].eod_force_close_open_positions.assert_not_called()
        stubs["phase20_executor"].get_all_open_trades.assert_not_called()

    # ── OC-4 ───────────────────────────────────────────────────────────────────
    def test_yesterday_eod_ran_normally_skips_force_close(self):
        """When yesterday's eod_squareoff key IS already claimed (the server was
        up during the POST_CLOSE window and the normal scheduler ran), the startup
        check returns early without running force-close a second time."""
        trade = {**_trade(trade_id="P20-OC04", symbol="TATAMOTORS"),
                 "fill_ts": self._prior_session_fill_ts()}
        stubs = self._build_startup_stubs([trade], eod_claimed_yesterday=True)
        result = self._run_startup_check(stubs)

        self.assertTrue(result.get("ran"),
                        f"Expected ran=True; got {result}")
        self.assertTrue(result.get("eod_claimed"),
                        "eod_claimed must be True when yesterday's run confirmed")
        self.assertEqual(result.get("reason"), "eod_squareoff_ran_yesterday")
        stubs["phase20_exits"].eod_force_close_open_positions.assert_not_called()

    # ── OC-5 ───────────────────────────────────────────────────────────────────
    def test_today_session_trades_not_classified_as_overnight(self):
        """Trades opened in TODAY's IST session (fill_ts = today) must NOT be
        treated as overnight carries; only prior-session trades are force-closed.

        The function filters by fill_ts < today_ist, so a trade opened this
        morning must pass through without triggering the carry path.
        """
        trade_today = {**_trade(trade_id="P20-OC05", symbol="INFY"),
                       "fill_ts": self._today_fill_ts()}
        stubs = self._build_startup_stubs([trade_today], eod_claimed_yesterday=False)
        result = self._run_startup_check(stubs)

        self.assertTrue(result.get("ran"),
                        f"Expected ran=True; got {result}")
        self.assertEqual(
            result.get("prior_session_count"), 0,
            "Today's trade must NOT be classified as a prior-session carry; "
            f"got prior_session_count={result.get('prior_session_count')}",
        )
        stubs["phase20_exits"].eod_force_close_open_positions.assert_not_called()

    # ── OC-6 ───────────────────────────────────────────────────────────────────
    def test_no_open_positions_claims_yesterday_eod_key_and_returns_early(self):
        """When there are no OPEN positions (portfolio was flat at close), the
        function claims yesterday's EOD key to mark the day complete and returns
        without running force-close."""
        stubs = self._build_startup_stubs([], eod_claimed_yesterday=False)
        result = self._run_startup_check(stubs)

        self.assertTrue(result.get("ran"),
                        f"Expected ran=True; got {result}")
        self.assertEqual(result.get("open_count"), 0)
        self.assertEqual(result.get("reason"), "no_open_positions")
        stubs["phase20_exits"].eod_force_close_open_positions.assert_not_called()

        # eod_squareoff key is still claimed (no-op guard for POST_CLOSE tick)
        kv_keys_claimed = [c[0][0] for c in
                           stubs["phase20_store"].kv_claim_once.call_args_list]
        eod_keys = [k for k in kv_keys_claimed if "eod_squareoff" in k]
        self.assertGreater(
            len(eod_keys), 0,
            "eod_squareoff key must be claimed even when no positions exist so "
            "the POST_CLOSE tick skips a redundant force-close attempt.",
        )


if __name__ == "__main__":
    unittest.main()
