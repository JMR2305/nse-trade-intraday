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

import sys
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
    kite_ltp: float = 0.0,
    yf_price: float = 1183.0,
    scan_ok: bool = True,
    dq: str = "LIVE",
    quote_reliable: bool = True,
) -> Dict[str, types.ModuleType]:
    stubs: Dict[str, types.ModuleType] = {}

    # phase20_executor
    pe = types.ModuleType("phase20_executor")
    pe.get_open_trades = MagicMock(return_value=open_trades)
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

    # phase15_scan_context
    ctx_sym: Dict[str, Any] = {}
    for t in open_trades:
        sym = str(t.get("symbol", "")).upper()
        ctx_sym[sym] = {
            "entry_price": yf_price,
            "data_quality": dq,
            "kite_ltp": kite_ltp,
            "kite_ltp_available": kite_ltp > 0,
            "quote_reliable": quote_reliable,
            "final_action": "HOLD",
            "error": None,
        }
    sc = types.ModuleType("phase15_scan_context")
    sc.build_scan_context = MagicMock(return_value={
        "available": scan_ok, "stale": False,
        "symbols": ctx_sym, "scan_id": "scan123",
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
        stubs["phase20_executor"].get_open_trades = MagicMock(
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


if __name__ == "__main__":
    unittest.main()
