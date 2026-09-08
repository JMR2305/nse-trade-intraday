"""
test_force_close_stale_exits.py — Unit tests for the EXIT_PENDING force-close
safeguards introduced in Task 807.

Covers:
  1. _resolve_timeout_exit_pending: created_at fallback rescues trades where
     both exit_ts and fill_ts are NULL (the bug that stranded the Aug 4-7 trades).
  2. Normal exit_ts path still closes old trades.
  3. fill_ts fallback path still closes old trades.
  4. No force-close when position is too young.
  5. Uses yfinance daily close when available in scan context.
  6. Falls back to fill_price when no scan data at all.
  7. Force-closes even when execute_sell fails (portfolio desync).
  8. Kite LTP preferred over yfinance close.
  9. max_holding_days=0 immediately closes all EXIT_PENDING (force-close cmd).
 10. OPEN / CLOSED rows are silently skipped.
 11. _retry_pending: _ep_pending_hours computed via created_at when both
     exit_ts and fill_ts are NULL (tier-2 gate now fires correctly).
 12. _retry_pending: tier-2 does NOT fire for a trade pending < 24 h.
 13. _retry_pending: stale/unavailable scan → no retries.
 14. _retry_pending: tier-1 LIVE quote resolves immediately (no age gate).
 15. _retry_pending: Kite LTP counts as tier-1.

ISOLATION GUARANTEE
-------------------
This file installs NO module-level stubs and imports NO application modules at
module scope.  All stubs are installed inside setUpClass() and removed in
tearDownClass(), so the sys.modules state is completely restored after each test
class.  This prevents the "import pollution" that was breaking other test files.

Patch targets (local imports inside the functions under test):
  - phase20_executor.get_exit_pending_trades  (replaces get_ledger(500) in both fns)
  - phase20_executor.record_exit             (from phase20_executor import record_exit)
  - paper_trader.execute_sell               (from paper_trader import execute_sell)
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# IMPORTANT: no module-level imports of application modules, and no stubs
# installed here.  Everything happens inside setUpClass / tearDownClass.


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _days_ago(n: float) -> datetime:
    return _utc_now() - timedelta(days=n)


def _hours_ago(h: float) -> datetime:
    return _utc_now() - timedelta(hours=h)


# ── Stub factory (creates a FRESH, COMPLETE set of stubs each time) ───────────

def _build_stubs() -> Dict[str, types.ModuleType]:
    """
    Return a complete set of stub modules for phase20_exits / phase20_executor.

    Every function that any test in this session might call on these stubs is
    included so that if these stubs accidentally end up visible to another test
    (e.g. collection-order edge case), they do not raise AttributeError.
    """
    # config
    cfg = types.ModuleType("config")
    cfg.NIFTY_50 = ["RELIANCE", "TCS"]
    cfg.INITIAL_CAPITAL = 50_000.0
    cfg.DEFAULT_WATCHLIST = ["RELIANCE", "TCS"]
    cfg.MAX_RISK_PCT = 0.02
    cfg.MAX_CAPITAL_PER_TRADE_PCT = 0.20

    # phase20_store
    store = types.ModuleType("phase20_store")
    store.kv_get = MagicMock(return_value=None)
    store.kv_set = MagicMock()
    store.kv_claim_once = MagicMock(return_value=True)
    store.add_notification = MagicMock()
    store.get_settings = MagicMock(return_value={})

    # scan_state_store — include ALL public functions so no AttributeError in
    # other tests if this stub is ever visible outside its intended scope.
    sss = types.ModuleType("scan_state_store")
    sss.db_available = MagicMock(return_value=False)
    sss._connect = MagicMock()
    sss._ensure_schema = MagicMock()
    sss.save_successful_scan = MagicMock()
    sss.record_failed_scan = MagicMock()
    sss.load_latest_snapshot = MagicMock(return_value=None)
    sss.load_latest_meta = MagicMock(return_value=None)
    sss.acquire_scan_lock = MagicMock(return_value=("lock-id", True))
    sss.renew_scan_lock = MagicMock(return_value=True)
    sss.release_scan_lock = MagicMock()
    sss.count_scans_today_ist = MagicMock(return_value=0)
    sss.build_scan_status_response = MagicMock(return_value={})
    sss.build_scan_history_response = MagicMock(return_value={"scans": []})

    # pipeline_events
    pe = types.ModuleType("pipeline_events")
    pe.emit = MagicMock()
    pe.query_events = MagicMock(return_value=[])

    # paper_trader
    pt = types.ModuleType("paper_trader")
    pt.get_portfolio = MagicMock(return_value={
        "positions": [], "cash": 50_000.0, "total_value": 50_000.0,
    })
    pt.execute_buy = MagicMock(return_value=(True, "ok"))
    pt.execute_sell = MagicMock(return_value=(True, "ok"))
    pt._load_state = MagicMock(return_value={"trades": []})

    # canonical_portfolio
    cp = types.ModuleType("canonical_portfolio")
    cp.build_canonical_portfolio = MagicMock(return_value={
        "cash": 50_000.0, "equity": 50_000.0,
        "positions": [], "realized_pnl": 0.0, "unrealized_pnl": 0.0,
    })

    # market_hours
    mh = types.ModuleType("market_hours")
    mh.market_status = MagicMock(return_value={"state": "CLOSED"})
    mh.now_ist = MagicMock(
        return_value=datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc))
    mh.MARKET_CLOSE = datetime(2026, 8, 18, 15, 30, tzinfo=timezone.utc)

    # phase15_scan_context
    ctx = types.ModuleType("phase15_scan_context")
    ctx.build_scan_context = MagicMock(return_value={
        "available": True, "stale": False,
        "scan_id": "scan-test-001", "symbols": {},
    })

    # market_scanner
    ms = types.ModuleType("market_scanner")
    ms._sector_of = MagicMock(return_value="Finance")

    # phase3f_logging (imported by phase20_executor at module level)
    log_mod = types.ModuleType("phase3f_logging")
    log_mod.get_logger = MagicMock(return_value=MagicMock())

    return {
        "config": cfg,
        "phase20_store": store,
        "scan_state_store": sss,
        "pipeline_events": pe,
        "paper_trader": pt,
        "canonical_portfolio": cp,
        "market_hours": mh,
        "phase15_scan_context": ctx,
        "market_scanner": ms,
        "phase3f_logging": log_mod,
    }


# ── Sentinel for "not in sys.modules" ────────────────────────────────────────
_MISSING = object()

# Modules imported by the modules under test (plus the modules under test
# themselves).  We save and restore ALL of these in setUpClass/tearDownClass.
_MANAGED_MODULES = [
    "config", "phase20_store", "scan_state_store", "pipeline_events",
    "paper_trader", "canonical_portfolio", "market_hours",
    "phase15_scan_context", "market_scanner", "phase3f_logging",
    # modules under test
    "phase20_executor", "phase20_exits",
]


def _save_and_install(stubs: Dict[str, types.ModuleType]) -> Dict[str, Any]:
    """
    Save the current sys.modules state for all managed modules, then install
    stubs and clear the modules under test so they reimport with fresh stubs.
    Returns the saved state for later restoration.
    """
    saved: Dict[str, Any] = {}
    for key in _MANAGED_MODULES:
        saved[key] = sys.modules.pop(key, _MISSING)

    # Install stubs (modules under test are not in stubs — they'll reimport)
    sys.modules.update(stubs)
    return saved


def _restore(saved: Dict[str, Any]) -> None:
    """
    Remove all managed modules from sys.modules, then put back only those that
    existed before _save_and_install() was called.
    """
    for key in _MANAGED_MODULES:
        sys.modules.pop(key, None)
    for key, val in saved.items():
        if val is not _MISSING:
            sys.modules[key] = val


# ── Trade-row builder ─────────────────────────────────────────────────────────

def _make_pending_trade(
    trade_id: str = "P20-aaa111",
    symbol: str = "TRENT",
    fill_price: float = 5_500.0,
    quantity: int = 1,
    exit_rule: str = "STALE_DATA_SAFETY",
    exit_ts: Optional[str] = None,
    fill_ts: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "status": "EXIT_PENDING",
        "fill_price": fill_price,
        "quantity": quantity,
        "exit_rule": exit_rule,
        "exit_ts": exit_ts,
        "fill_ts": fill_ts,
        "created_at": created_at,
    }


def _settings(max_holding_days: float = 10,
               exit_on_stale_after_days: int = 5) -> Dict[str, Any]:
    return {
        "max_holding_days": max_holding_days,
        "exit_on_stale_after_days": exit_on_stale_after_days,
        "daily_loss_limit_pct": 2.0,
        "sector_exposure_cap_pct": 25.0,
        "square_off_before_close": False,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Tests for _resolve_timeout_exit_pending
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveTimeoutExitPending(unittest.TestCase):
    """
    Covers the force-close path for EXIT_PENDING positions that are stuck
    because Kite LTP never came back online.

    All stubs are scoped to this class (setUpClass / tearDownClass).
    """

    _saved: Dict[str, Any] = {}

    @classmethod
    def setUpClass(cls) -> None:
        stubs = _build_stubs()
        cls._saved = _save_and_install(stubs)
        # Import modules under test — they now use our stubs
        import phase20_executor as em
        import phase20_exits as xm
        cls._exec_mod = em
        cls._exits_mod = xm
        # Wrap with staticmethod so self is NOT auto-bound when accessed via
        # self._resolve_timeout() — without this, Python's descriptor protocol
        # would prepend self as the first argument, causing a TypeError.
        cls._resolve_timeout = staticmethod(xm._resolve_timeout_exit_pending)

    @classmethod
    def tearDownClass(cls) -> None:
        _restore(cls._saved)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _run(
        self,
        trades: List[Dict[str, Any]],
        settings: Optional[Dict[str, Any]] = None,
        symbols_ctx: Optional[Dict[str, Any]] = None,
        exit_scan_id: str = "scan-001",
        sell_ok: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Run _resolve_timeout_exit_pending with mocked ledger and execute_sell.
        Patches phase20_executor.get_ledger, phase20_executor.record_exit,
        and paper_trader.execute_sell (all three are locally imported inside
        the function under test).
        """
        pt = sys.modules["paper_trader"]
        s = settings or _settings()
        with (
            patch.object(self._exec_mod, "get_exit_pending_trades",
                         return_value=trades),
            patch.object(self._exec_mod, "record_exit") as mock_rec,
            patch.object(pt, "execute_sell",
                         return_value=(sell_ok,
                                       "ok" if sell_ok else "No open position")),
        ):
            result = self._resolve_timeout(s, symbols_ctx or {}, exit_scan_id)
        return result

    # ── Test 1: core regression — created_at fallback rescues stranded trade ──

    def test_created_at_fallback_rescues_stranded_trade(self) -> None:
        """
        A trade with both exit_ts=NULL and fill_ts=NULL must be force-closed
        using created_at as the age timestamp.  This is the exact bug that
        permanently stranded the Aug 4-7 TRENT/DIVISLAB/GRASIM/BAJFINANCE trades.
        """
        trade = _make_pending_trade(
            trade_id="P20-trent001", symbol="TRENT", fill_price=5_500.0,
            exit_ts=None, fill_ts=None,
            created_at=_iso(_days_ago(14)),   # 14 days > max_holding_days=10
        )
        result = self._run([trade])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "TRENT")
        self.assertEqual(result[0]["exit_rule"], "TIMEOUT_EXIT_PENDING")
        self.assertGreater(result[0]["exit_price"], 0)

    def test_all_four_stuck_aug_trades_resolved(self) -> None:
        """All 4 Aug 4-7 stuck trades are resolved in one call."""
        stuck = [
            _make_pending_trade("P20-trent",  "TRENT",     5_500.0,
                                created_at=_iso(_days_ago(14))),
            _make_pending_trade("P20-divlab", "DIVISLAB",  4_800.0,
                                created_at=_iso(_days_ago(13))),
            _make_pending_trade("P20-grasim", "GRASIM",    2_600.0,
                                created_at=_iso(_days_ago(12))),
            _make_pending_trade("P20-bajfin", "BAJFINANCE", 6_900.0,
                                created_at=_iso(_days_ago(11))),
        ]
        result = self._run(stuck)
        self.assertEqual(len(result), 4)
        closed_syms = {r["symbol"] for r in result}
        self.assertEqual(closed_syms, {"TRENT", "DIVISLAB", "GRASIM", "BAJFINANCE"})

    # ── Test 2: exit_ts (primary) still works ─────────────────────────────────

    def test_exit_ts_primary_path(self) -> None:
        trade = _make_pending_trade(
            symbol="RELIANCE",
            exit_ts=_iso(_days_ago(11)),
            fill_ts=None, created_at=None,
        )
        result = self._run([trade])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "RELIANCE")

    # ── Test 3: fill_ts fallback still works ──────────────────────────────────

    def test_fill_ts_fallback_path(self) -> None:
        trade = _make_pending_trade(
            symbol="TCS",
            exit_ts=None, fill_ts=_iso(_days_ago(12)),
            created_at=_iso(_days_ago(12)),
        )
        result = self._run([trade])
        self.assertEqual(len(result), 1)

    # ── Test 4: too young — skip ──────────────────────────────────────────────

    def test_young_trade_not_force_closed(self) -> None:
        trade = _make_pending_trade(
            symbol="HDFCBANK",
            exit_ts=None, fill_ts=None,
            created_at=_iso(_days_ago(2)),
        )
        result = self._run([trade])
        self.assertEqual(len(result), 0)

    def test_all_timestamps_null_not_closed(self) -> None:
        """All three timestamps NULL → pending_dt is None → skip safely."""
        trade = _make_pending_trade(
            symbol="WIPRO",
            exit_ts=None, fill_ts=None, created_at=None,
        )
        result = self._run([trade])
        self.assertEqual(len(result), 0)

    # ── Test 5: prefers yfinance daily close from scan ────────────────────────

    def test_uses_yfinance_price_from_scan(self) -> None:
        trade = _make_pending_trade(
            symbol="INFY", fill_price=1_700.0,
            created_at=_iso(_days_ago(11)),
        )
        symbols_ctx = {"INFY": {
            "entry_price": 1_850.0,
            "data_quality": "ACCEPTABLE",
            "kite_ltp": None,
            "kite_ltp_available": False,
            "quote_reliable": False,
            "error": None,
        }}
        result = self._run([trade], symbols_ctx=symbols_ctx)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["exit_price"], 1_850.0)
        self.assertEqual(result[0]["price_source"], "yfinance_daily_close")

    # ── Test 6: fill_price fallback when no scan data ─────────────────────────

    def test_fallback_to_fill_price_when_no_scan_data(self) -> None:
        trade = _make_pending_trade(
            symbol="WIPRO", fill_price=2_200.0,
            created_at=_iso(_days_ago(11)),
        )
        result = self._run([trade], symbols_ctx={})
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["exit_price"], 2_200.0)
        self.assertEqual(result[0]["price_source"], "fill_price_fallback")

    # ── Test 7: force-closes even when execute_sell fails (desync) ────────────

    def test_force_close_even_when_sell_fails(self) -> None:
        """
        Portfolio desync: execute_sell returns False but record_exit must still
        be called to stamp the ledger CLOSED so the trade is not stranded.
        """
        trade = _make_pending_trade(
            symbol="GRASIM", fill_price=2_600.0,
            created_at=_iso(_days_ago(12)),
        )
        pt = sys.modules["paper_trader"]
        with (
            patch.object(self._exec_mod, "get_exit_pending_trades",
                         return_value=[trade]),
            patch.object(self._exec_mod, "record_exit") as mock_rec,
            patch.object(pt, "execute_sell",
                         return_value=(False, "No open paper position")),
        ):
            result = self._resolve_timeout(_settings(), {}, "scan-001")

        self.assertEqual(len(result), 1)
        mock_rec.assert_called_once()
        _, kw = mock_rec.call_args
        self.assertEqual(kw.get("status"), "CLOSED")

    # ── Regression: trade older than 500 newer ledger rows is still resolved ──

    def test_exit_pending_older_than_500_newer_rows_is_resolved(self) -> None:
        """
        Regression for the get_ledger(500) pagination bug.

        Before the fix:
          • _resolve_timeout_exit_pending called get_ledger(500) → missed old rows
          • record_exit called get_trade → called get_ledger(500) → returned None
            → skipped _update_row → row stayed EXIT_PENDING forever

        After the fix:
          • get_exit_pending_trades() queries status='EXIT_PENDING' directly (no limit)
          • get_trade() queries by trade_id directly (no 500-row window)
          • _update_row() is called with status='CLOSED'

        This test lets record_exit run WITHOUT mocking it, then verifies that
        _update_row is called with the correct trade_id and status='CLOSED',
        proving that the persistence chain completes end-to-end for a trade that
        would have been invisible to get_ledger(500).
        """
        stuck_trade = _make_pending_trade(
            trade_id="P20-ancient", symbol="TRENT", fill_price=5_500.0,
            exit_ts=None, fill_ts=None,
            created_at=_iso(_days_ago(14)),
        )
        pt = sys.modules["paper_trader"]
        with (
            # Discovery: use the new unlimited query
            patch.object(self._exec_mod, "get_exit_pending_trades",
                         return_value=[stuck_trade]),
            # Persistence: get_trade is now a direct lookup; simulate it finding
            # the trade (proves the non-paginated path works)
            patch.object(self._exec_mod, "get_trade",
                         return_value=stuck_trade),
            # Capture the DB UPDATE to verify it fires with status=CLOSED
            patch.object(self._exec_mod, "_update_row") as mock_update,
            patch.object(pt, "execute_sell", return_value=(True, "ok")),
        ):
            result = self._resolve_timeout(_settings(), {}, "scan-001")

        # The function must report the trade as force-closed
        self.assertEqual(len(result), 1,
                         "Stuck trade older than 500 newer rows must be reported as force-closed")
        self.assertEqual(result[0]["symbol"], "TRENT")
        self.assertEqual(result[0]["exit_rule"], "TIMEOUT_EXIT_PENDING")

        # _update_row must have been called — this is the DB persistence step.
        # Without this call the row stays EXIT_PENDING in the database forever.
        mock_update.assert_called_once()
        update_trade_id, update_fields = mock_update.call_args[0]
        self.assertEqual(update_trade_id, "P20-ancient")
        self.assertEqual(update_fields.get("status"), "CLOSED",
                         "_update_row must stamp status='CLOSED', not leave it EXIT_PENDING")

    # ── Test 8: Kite LTP preferred over yfinance ──────────────────────────────

    def test_kite_ltp_preferred_over_yfinance(self) -> None:
        trade = _make_pending_trade(
            symbol="BAJFINANCE", fill_price=6_900.0,
            created_at=_iso(_days_ago(13)),
        )
        symbols_ctx = {"BAJFINANCE": {
            "entry_price": 7_100.0,
            "kite_ltp": 7_050.50,
            "kite_ltp_available": True,
            "quote_reliable": True,
            "data_quality": "LIVE",
            "error": None,
        }}
        result = self._run([trade], symbols_ctx=symbols_ctx)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["exit_price"], 7_050.50)
        self.assertEqual(result[0]["price_source"], "kite_ltp")

    # ── OPEN / CLOSED rows are skipped ────────────────────────────────────────

    def test_open_trade_ignored(self) -> None:
        trade = {"trade_id": "P20-o1", "symbol": "HDFCBANK", "status": "OPEN",
                 "fill_price": 1_800.0, "quantity": 2,
                 "created_at": _iso(_days_ago(15))}
        self.assertEqual(len(self._run([trade])), 0)

    def test_closed_trade_ignored(self) -> None:
        trade = {"trade_id": "P20-c1", "symbol": "RELIANCE", "status": "CLOSED",
                 "fill_price": 2_800.0, "quantity": 1,
                 "created_at": _iso(_days_ago(15))}
        self.assertEqual(len(self._run([trade])), 0)

    # ── Test 9: max_holding_days=0 → force-close everything ──────────────────

    def test_max_holding_days_zero_closes_all(self) -> None:
        """
        max_holding_days=0 means every EXIT_PENDING trade is immediately
        eligible — this is the phase20_force_close_stale command path.
        """
        trades = [
            _make_pending_trade("P20-n1", "SBIN",
                                created_at=_iso(_hours_ago(1))),
            _make_pending_trade("P20-n2", "KOTAKBANK",
                                created_at=_iso(_hours_ago(2))),
        ]
        result = self._run(trades, settings=_settings(max_holding_days=0))
        self.assertEqual(len(result), 2)

    def test_max_holding_days_zero_null_timestamps_still_skips(self) -> None:
        """
        max_holding_days=0 with ALL timestamps NULL: pending_dt is None so the
        age guard `not (pending_dt and ...)` skips the trade.
        """
        trade = _make_pending_trade(
            symbol="ONGC",
            exit_ts=None, fill_ts=None, created_at=None,
        )
        result = self._run([trade], settings=_settings(max_holding_days=0))
        self.assertEqual(len(result), 0)

    def test_exit_ts_takes_precedence_over_fill_ts_and_created_at(self) -> None:
        """exit_ts is used when all three timestamps are populated."""
        # exit_ts=11d (eligible); fill_ts=1d + created_at=2d (would be ineligible)
        trade = _make_pending_trade(
            symbol="SBIN",
            exit_ts=_iso(_days_ago(11)),
            fill_ts=_iso(_days_ago(1)),
            created_at=_iso(_days_ago(2)),
        )
        result = self._run([trade])
        self.assertEqual(len(result), 1)

    def test_fill_ts_used_when_exit_ts_null(self) -> None:
        """fill_ts is the second fallback when exit_ts is NULL."""
        trade = _make_pending_trade(
            symbol="NTPC",
            exit_ts=None,
            fill_ts=_iso(_days_ago(11)),
            created_at=_iso(_days_ago(1)),
        )
        result = self._run([trade])
        self.assertEqual(len(result), 1)


# ══════════════════════════════════════════════════════════════════════════════
# Tests for _retry_pending (tier-2 gate with created_at fallback)
# ══════════════════════════════════════════════════════════════════════════════

class TestRetryPending(unittest.TestCase):
    """
    Tests for _retry_pending's _ep_pending_hours calculation.
    Stubs are scoped to this class via setUpClass / tearDownClass.
    """

    _saved: Dict[str, Any] = {}

    @classmethod
    def setUpClass(cls) -> None:
        stubs = _build_stubs()
        cls._saved = _save_and_install(stubs)
        import phase20_executor as em
        import phase20_exits as xm
        cls._exec_mod = em
        # staticmethod prevents Python's descriptor protocol from binding self
        # as the first argument when the function is accessed via self._retry_pending().
        cls._retry_pending = staticmethod(xm._retry_pending)

    @classmethod
    def tearDownClass(cls) -> None:
        _restore(cls._saved)

    def _run(
        self,
        trades: List[Dict[str, Any]],
        symbols_ctx: Optional[Dict[str, Any]] = None,
        scan_ok: bool = True,
        stale: bool = False,
        sell_ok: bool = True,
    ) -> List[Dict[str, Any]]:
        pt = sys.modules["paper_trader"]
        with (
            patch.object(self._exec_mod, "get_exit_pending_trades",
                         return_value=trades),
            patch.object(self._exec_mod, "record_exit") as _mock_rec,
            patch.object(pt, "execute_sell",
                         return_value=(sell_ok,
                                       "ok" if sell_ok else "No open position")),
        ):
            return self._retry_pending(symbols_ctx or {}, scan_ok, stale, "scan-r01")

    # ── Test 11: created_at fallback enables tier-2 gate ─────────────────────

    def test_created_at_fallback_enables_tier2_gate(self) -> None:
        """
        Trade with NULL exit_ts + NULL fill_ts, but created_at=3d ago.
        Before the fix: _ep_pending_hours=0 → tier-2 never fires.
        After the fix: hours ≈ 72 > 24 → tier-2 resolves the trade.
        """
        trade = _make_pending_trade(
            symbol="DIVISLAB", fill_price=4_800.0,
            exit_ts=None, fill_ts=None,
            created_at=_iso(_days_ago(3)),   # 72 h > MIN_PENDING_HOURS_FOR_FALLBACK=24
        )
        symbols_ctx = {"DIVISLAB": {
            "entry_price": 4_950.0,
            "data_quality": "ACCEPTABLE",
            "kite_ltp": None,
            "kite_ltp_available": False,
            "quote_reliable": False,
            "error": None,
        }}
        result = self._run([trade], symbols_ctx=symbols_ctx)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "DIVISLAB")
        self.assertAlmostEqual(result[0]["exit_price"], 4_950.0)

    # ── Test 12: tier-2 does NOT fire for fresh EXIT_PENDING ─────────────────

    def test_tier2_does_not_fire_for_fresh_pending(self) -> None:
        """A trade just entered EXIT_PENDING (30 min ago) must NOT be retried."""
        trade = _make_pending_trade(
            symbol="SBIN", fill_price=800.0,
            exit_ts=None, fill_ts=None,
            created_at=_iso(_hours_ago(0.5)),
        )
        symbols_ctx = {"SBIN": {
            "entry_price": 810.0,
            "data_quality": "ACCEPTABLE",
            "kite_ltp": None,
            "kite_ltp_available": False,
            "quote_reliable": False,
            "error": None,
        }}
        result = self._run([trade], symbols_ctx=symbols_ctx)
        self.assertEqual(len(result), 0)

    # ── Test 13: stale/unavailable scan → skip ───────────────────────────────

    def test_stale_scan_skips_retry(self) -> None:
        trade = _make_pending_trade(symbol="AXISBANK",
                                    created_at=_iso(_days_ago(3)))
        self.assertEqual(len(self._run([trade], scan_ok=True, stale=True)), 0)

    def test_scan_unavailable_skips_retry(self) -> None:
        trade = _make_pending_trade(symbol="AXISBANK",
                                    created_at=_iso(_days_ago(3)))
        self.assertEqual(len(self._run([trade], scan_ok=False)), 0)

    # ── Test 14: tier-1 (LIVE) resolves immediately regardless of age ─────────

    def test_tier1_resolves_immediately_with_live_quote(self) -> None:
        """LIVE quality resolves without any 24-hour age gate."""
        trade = _make_pending_trade(
            symbol="KOTAKBANK", fill_price=1_800.0,
            exit_ts=None, fill_ts=None,
            created_at=_iso(_hours_ago(1)),   # only 1 hour old
        )
        symbols_ctx = {"KOTAKBANK": {
            "entry_price": 1_820.0,
            "data_quality": "LIVE",
            "kite_ltp": None,
            "kite_ltp_available": False,
            "quote_reliable": False,
            "error": None,
        }}
        result = self._run([trade], symbols_ctx=symbols_ctx)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["exit_price"], 1_820.0)

    # ── Test 15: Kite LTP counts as tier-1 ───────────────────────────────────

    def test_kite_ltp_tier1_resolves_immediately(self) -> None:
        """Kite LTP with quote_reliable=True resolves without 24-hour wait."""
        trade = _make_pending_trade(
            symbol="HDFCBANK", fill_price=1_700.0,
            exit_ts=None, fill_ts=None,
            created_at=_iso(_hours_ago(0.5)),
        )
        symbols_ctx = {"HDFCBANK": {
            "entry_price": 1_710.0,
            "kite_ltp": 1_715.75,
            "kite_ltp_available": True,
            "quote_reliable": True,
            "data_quality": "ACCEPTABLE",
            "error": None,
        }}
        result = self._run([trade], symbols_ctx=symbols_ctx)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["exit_price"], 1_715.75)

    def test_non_exit_pending_rows_skipped(self) -> None:
        """_retry_pending only processes EXIT_PENDING rows."""
        trades = [
            {**_make_pending_trade("P20-open",   "ONGC"), "status": "OPEN"},
            {**_make_pending_trade("P20-closed", "NTPC"), "status": "CLOSED"},
        ]
        self.assertEqual(len(self._run(trades)), 0)


if __name__ == "__main__":
    unittest.main()
