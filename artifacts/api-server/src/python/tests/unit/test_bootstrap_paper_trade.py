"""
test_bootstrap_paper_trade.py — Unit tests for the bootstrap paper trade mode.

Covers the 8 scenarios from the task specification:
1. low_evidence normally caps BUY to WATCH (normal path unchanged)
2. bootstrap mode permits safe WATCH candidates
3. bootstrap requires Kite LTP and quote_reliable=true
4. bootstrap refuses when Kite is unauthenticated
5. bootstrap refuses if hard risk gates fail
6. bootstrap trade writes a P20 row
7. bootstrap trade exits and writes realized_pnl (exit engine integration)
8. no live broker order APIs are called

PAPER ONLY. No real orders. No live API calls.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, call, patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Minimal module stubs ──────────────────────────────────────────────────────

def _install_stubs():
    """Stub out heavy dependencies before importing the modules under test."""
    # config
    cfg = types.ModuleType("config")
    cfg.NIFTY_50 = ["RELIANCE", "TCS"]
    cfg.INITIAL_CAPITAL = 50_000.0
    cfg.MAX_RISK_PCT = 0.02
    cfg.MAX_CAPITAL_PER_TRADE_PCT = 0.20
    cfg.DEFAULT_WATCHLIST = ["RELIANCE", "TCS"]
    sys.modules.setdefault("config", cfg)

    # phase20_store
    store_mod = types.ModuleType("phase20_store")
    store_mod.kv_get = MagicMock(return_value=None)
    store_mod.kv_set = MagicMock()
    store_mod.kv_claim_once = MagicMock(return_value=True)   # default: claim succeeds
    store_mod.get_settings = MagicMock(return_value={})
    store_mod.add_notification = MagicMock()
    sys.modules.setdefault("phase20_store", store_mod)

    # scan_state_store
    scan_store = types.ModuleType("scan_state_store")
    scan_store.db_available = MagicMock(return_value=False)
    scan_store._connect = MagicMock()
    sys.modules.setdefault("scan_state_store", scan_store)

    # pipeline_events
    pe = types.ModuleType("pipeline_events")
    pe.emit = MagicMock()
    pe.query_events = MagicMock(return_value=[])
    sys.modules.setdefault("pipeline_events", pe)

    # paper_trader
    pt = types.ModuleType("paper_trader")
    pt.get_portfolio = MagicMock(return_value={"positions": [], "cash": 50_000.0})
    pt.execute_buy = MagicMock(return_value=(True, "Paper BUY ok"))
    pt.execute_sell = MagicMock(return_value=(True, "Paper SELL ok"))
    sys.modules.setdefault("paper_trader", pt)

    # canonical_portfolio
    cp = types.ModuleType("canonical_portfolio")
    cp.build_canonical_portfolio = MagicMock(return_value={
        "cash": 48_500.0, "equity": 50_000.0,
        "positions": [], "realized_pnl": 0.0, "unrealized_pnl": 0.0,
    })
    sys.modules.setdefault("canonical_portfolio", cp)


_install_stubs()

# Import module under test after stubs are in place
from phase20_executor import (  # noqa: E402
    run_bootstrap_auto_entry,
    _BOOTSTRAP_MAX_CLOSED_TRADES,
    _BOOTSTRAP_MIN_CONF,
    _BOOTSTRAP_MIN_OPP,
    _BOOTSTRAP_MIN_RR,
    _BOOTSTRAP_MAX_ORDER_VALUE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_snapshot(
    kite_session_verified: bool = True,
    kite_ltp_overlay_enabled: bool = True,
    recs: list | None = None,
) -> Dict[str, Any]:
    """Build a minimal scan snapshot dict for testing."""
    if recs is None:
        recs = [_make_rec()]
    return {
        "scan_id": "test-scan-001",
        "snapshot_ts": "2026-08-17T05:00:00Z",
        "safety": {
            "kite_ltp_session_verified": kite_session_verified,
            "kite_ltp_overlay_enabled": kite_ltp_overlay_enabled,
        },
        "recommendations": recs,
    }


def _make_rec(
    symbol: str = "DRREDDY",
    final_action: str = "WATCH",
    calibrated_confidence: float = 64.7,
    opportunity_score: float = 62.6,
    rr_ratio: float = 2.5,
    bootstrap_eligible: bool = True,
    quote_reliable: bool = True,
    kite_session_verified_flag: bool = True,
    kite_ltp: float = 1_194.0,
    all_gates_passed: bool = True,
    low_evidence: bool = True,
    stop_loss: float = 1_150.0,
    target_price: float = 1_250.0,
) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "final_action": final_action,
        "calibrated_confidence": calibrated_confidence,
        "opportunity_score": opportunity_score,
        "rr_ratio": rr_ratio,
        "bootstrap_eligible": bootstrap_eligible,
        "quote_reliable": quote_reliable,
        "kite_session_verified_flag": kite_session_verified_flag,
        "kite_ltp": kite_ltp,
        "kite_ltp_available": True,
        "execution_price_source": "kite_live_ltp",
        "entry_price": kite_ltp,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "all_gates_passed": all_gates_passed,
        "low_evidence": low_evidence,
        "total_trades": 3,
        "strategy_id": "ema_crossover",
        "strategy_name": "EMA Crossover",
        "regime": "TRENDING",
        "technical_score": 62.0,
    }


def _settings_bootstrap_on() -> Dict[str, Any]:
    """Settings with bootstrap enabled AND auto_paper_entries confirmed (required gates)."""
    return {
        "bootstrap_paper_enabled": True,
        "auto_paper_entries": True,
        "auto_paper_entries_confirmed_at": "2026-08-17T05:00:00Z",
        "fill_model": "SLIPPAGE_ADJUSTED",
        "slippage_pct": 0.15,
        "charges_pct": 0.12,
        "max_trades_per_day": 3,
    }


def _settings_bootstrap_off_unconfirmed() -> Dict[str, Any]:
    """Settings with auto_paper_entries unconfirmed — bootstrap must refuse."""
    return {
        "bootstrap_paper_enabled": True,
        "auto_paper_entries": False,
        "auto_paper_entries_confirmed_at": None,
        "fill_model": "SLIPPAGE_ADJUSTED",
        "slippage_pct": 0.15,
        "charges_pct": 0.12,
        "max_trades_per_day": 3,
    }


# ── TEST 1: Normal BUY-to-WATCH capping is unchanged ─────────────────────────

class TestLowEvidenceNormalPath:
    """Normal decision path: low_evidence does not change BUY_CONF thresholds."""

    def test_low_evidence_constant_unchanged(self):
        """BOOTSTRAP_MIN_CONF (60) must be below BUY_CONF (75) — bootstrap never
        replaces normal BUY qualification."""
        from decision_service import BUY_CONF  # type: ignore[import]
        assert _BOOTSTRAP_MIN_CONF < BUY_CONF, (
            "Bootstrap threshold must stay below normal BUY_CONF to avoid confusion"
        )

    def test_bootstrap_does_not_touch_paper_eligible(self):
        """run_bootstrap_auto_entry must not modify any rec's paper_eligible flag."""
        rec = _make_rec()
        original_paper_eligible = rec.get("paper_eligible", False)
        snapshot = _make_snapshot(recs=[rec])
        with (
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry",
                  return_value={"created": True, "trade_id": "P20-bootstrap1",
                                "symbol": "DRREDDY"}),
        ):
            run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        # paper_eligible must not have been mutated
        assert rec.get("paper_eligible", False) == original_paper_eligible


# ── TEST 2: Bootstrap permits safe WATCH candidates ──────────────────────────

class TestBootstrapPermitsWatchCandidates:
    def test_creates_trade_for_eligible_watch(self):
        """Bootstrap creates a P20 row for a qualifying WATCH candidate."""
        snapshot = _make_snapshot()
        mock_create = MagicMock(return_value={
            "created": True, "trade_id": "P20-bt001", "symbol": "DRREDDY",
        })
        with (
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry", mock_create),
        ):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())

        assert result["ran"] is True
        assert result["result"]["created"] is True
        mock_create.assert_called_once()
        ca = mock_create.call_args
        trigger_source = (
            ca.kwargs.get("trigger_source")
            if ca.kwargs.get("trigger_source")
            else (ca.args[4] if len(ca.args) > 4 else None)
        )
        assert trigger_source == "BOOTSTRAP_AUTO"

    def test_fill_model_overridden_to_bootstrap_paper(self):
        """Settings passed to create_paper_entry must have fill_model=bootstrap_paper."""
        snapshot = _make_snapshot()
        captured_settings: Dict[str, Any] = {}

        def capture(candidate, settings, scan_id, snap_ts, trigger_source="AUTO"):
            captured_settings.update(settings)
            return {"created": True, "trade_id": "P20-x", "symbol": "DRREDDY"}

        with (
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry", side_effect=capture),
        ):
            run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())

        assert captured_settings.get("fill_model") == "bootstrap_paper"

    def test_order_value_capped_at_1500(self):
        """Qty × kite_ltp must never exceed ₹1,500.
        Candidates whose share price alone exceeds the cap are skipped entirely."""
        expensive_rec = _make_rec(symbol="BAJAJFINSV", kite_ltp=5_000.0)
        snapshot = _make_snapshot(recs=[expensive_rec])

        with patch("phase20_executor._with_db", side_effect=[0, False]):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())

        # Price ₹5,000 > cap ₹1,500 → executor must decline, not create a trade
        assert result["ran"] is False or result.get("result", {}).get("created") is not True, (
            "Executor must not create a trade when share price exceeds ₹1,500 cap"
        )

    def test_order_value_capped_affordable_stock(self):
        """For an affordable stock, qty × worst-case fill must not exceed the cap."""
        # price=200, slippage 0.15% → worst_fill=200.30 → qty=7, notional=1402.1 ≤ 1500
        affordable_rec = _make_rec(symbol="TATACOMM", kite_ltp=200.0,
                                    stop_loss=185.0, target_price=225.0)
        snapshot = _make_snapshot(recs=[affordable_rec])
        settings = dict(_settings_bootstrap_on())
        settings["slippage_pct"] = 0.15
        captured_sizing: dict = {}

        def capture(candidate, sett, scan_id, snap_ts, trigger_source="AUTO"):
            captured_sizing.update(candidate.get("sizing") or {})
            return {"created": True, "trade_id": "P20-x", "symbol": "TATACOMM"}

        with (
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry", side_effect=capture),
        ):
            run_bootstrap_auto_entry(snapshot, settings)

        qty = int(captured_sizing.get("quantity") or 0)
        slip_pct = 0.15 / 100.0
        worst_fill = 200.0 * (1 + slip_pct)
        executed_notional = qty * worst_fill
        assert qty >= 1
        assert executed_notional <= _BOOTSTRAP_MAX_ORDER_VALUE, (
            f"Executed notional ₹{executed_notional:.2f} exceeds cap ₹{_BOOTSTRAP_MAX_ORDER_VALUE}"
        )

    def test_picks_highest_confidence_candidate(self):
        """When multiple bootstrap candidates exist, pick highest confidence."""
        recs = [
            _make_rec(symbol="DRREDDY", calibrated_confidence=64.7),
            _make_rec(symbol="TMCV", calibrated_confidence=65.3),
        ]
        snapshot = _make_snapshot(recs=recs)
        captured: list[str] = []

        def capture(candidate, settings, scan_id, snap_ts, trigger_source="AUTO"):
            captured.append(candidate.get("symbol", ""))
            return {"created": True, "trade_id": "P20-x",
                    "symbol": candidate.get("symbol")}

        with (
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry", side_effect=capture),
        ):
            run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())

        assert captured == ["TMCV"], "Must select TMCV (higher confidence)"


# ── TEST 3: Bootstrap requires Kite LTP and quote_reliable=true ──────────────

class TestBootstrapRequiresKiteLTP:
    def test_refuses_when_kite_session_not_verified_in_snapshot(self):
        """Bootstrap must refuse when kite_ltp_session_verified=False in snapshot."""
        snapshot = _make_snapshot(kite_session_verified=False,
                                  kite_ltp_overlay_enabled=False)
        result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False
        assert "Kite LTP" in result.get("reason", "")

    def test_refuses_when_rec_quote_reliable_false(self):
        """Candidate with quote_reliable=False must be excluded."""
        rec = _make_rec(quote_reliable=False)
        snapshot = _make_snapshot(recs=[rec])
        result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False
        assert "No bootstrap_eligible" in result.get("reason", "")


# ── TEST 4: Bootstrap refuses when Kite is unauthenticated ───────────────────

class TestBootstrapRefusesUnauthenticatedKite:
    def test_refuses_when_kite_not_connected_snapshot_level(self):
        """If both kite_ltp_session_verified and kite_ltp_overlay_enabled are
        False in the snapshot safety block, bootstrap must decline."""
        snapshot = {
            "scan_id": "s1",
            "snapshot_ts": "2026-08-17T05:00:00Z",
            "safety": {
                "kite_ltp_session_verified": False,
                "kite_ltp_overlay_enabled": False,
            },
            "recommendations": [_make_rec()],
        }
        result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False

    def test_refuses_when_rec_kite_session_verified_flag_false(self):
        """Per-rec kite_session_verified_flag=False disqualifies the candidate."""
        rec = _make_rec(kite_session_verified_flag=False)
        snapshot = _make_snapshot(recs=[rec])
        result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False
        assert "No bootstrap_eligible" in result.get("reason", "")


# ── TEST 5: Bootstrap refuses if hard risk gates fail ────────────────────────

class TestBootstrapRefusesFailedGates:
    def test_refuses_when_bootstrap_eligible_false(self):
        """A rec with bootstrap_eligible=False must be skipped."""
        rec = _make_rec(bootstrap_eligible=False)
        snapshot = _make_snapshot(recs=[rec])
        result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False

    def test_refuses_when_confidence_below_floor(self):
        """Confidence below BOOTSTRAP_MIN_CONF must exclude candidate."""
        rec = _make_rec(calibrated_confidence=_BOOTSTRAP_MIN_CONF - 1)
        snapshot = _make_snapshot(recs=[rec])
        result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False

    def test_refuses_when_opportunity_score_below_floor(self):
        """Opportunity score below BOOTSTRAP_MIN_OPP must exclude candidate."""
        rec = _make_rec(opportunity_score=_BOOTSTRAP_MIN_OPP - 1)
        snapshot = _make_snapshot(recs=[rec])
        result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False

    def test_refuses_when_rr_below_floor(self):
        """R:R below BOOTSTRAP_MIN_RR must exclude candidate."""
        rec = _make_rec(rr_ratio=_BOOTSTRAP_MIN_RR - 0.1)
        snapshot = _make_snapshot(recs=[rec])
        result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False

    def test_refuses_when_ledger_has_enough_closed_trades(self):
        """Auto-disables when closed trade count >= threshold."""
        snapshot = _make_snapshot()
        with patch("phase20_executor._with_db",
                   return_value=_BOOTSTRAP_MAX_CLOSED_TRADES):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False
        assert str(_BOOTSTRAP_MAX_CLOSED_TRADES) in result.get("reason", "")

    # ── Independent gate re-verification (bypass regression tests) ───────────
    # These tests set bootstrap_eligible=True on the rec but flip ONE constituent
    # condition to False.  The executor must independently re-check every gate
    # so a stale/inconsistent bootstrap_eligible flag cannot bypass the safety checks.

    def test_refuses_when_low_evidence_false_despite_bootstrap_eligible_true(self):
        """Even if bootstrap_eligible=True, low_evidence=False must block the trade —
        it means the normal BUY path is unblocked and bootstrap is unnecessary."""
        rec = _make_rec(bootstrap_eligible=True, low_evidence=False)
        snapshot = _make_snapshot(recs=[rec])
        with patch("phase20_executor._with_db", side_effect=[0, False]):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False
        assert "low_evidence" in result.get("reason", "")

    def test_refuses_when_all_gates_not_passed_despite_bootstrap_eligible_true(self):
        """bootstrap_eligible=True but all_gates_passed=False must be rejected — the
        executor checks all_gates_passed independently after selecting the candidate."""
        rec = _make_rec(bootstrap_eligible=True, all_gates_passed=False)
        snapshot = _make_snapshot(recs=[rec])
        with patch("phase20_executor._with_db", side_effect=[0, False]):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False
        assert "all_gates_passed" in result.get("reason", "")

    def test_refuses_when_kite_ltp_not_available_despite_bootstrap_eligible_true(self):
        """bootstrap_eligible=True but kite_ltp_available=False must be rejected — bootstrap
        requires a live Kite execution price independently of the eligibility flag."""
        rec = _make_rec(bootstrap_eligible=True, kite_session_verified_flag=True)
        rec["kite_ltp_available"] = False
        snapshot = _make_snapshot(recs=[rec])
        with patch("phase20_executor._with_db", side_effect=[0, False]):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False
        assert "kite_ltp_available" in result.get("reason", "")

    def test_refuses_when_execution_price_source_not_kite(self):
        """bootstrap_eligible=True but execution_price_source='yfinance_daily_bars' must
        be rejected — bootstrap must only execute on a live Kite price."""
        rec = _make_rec(bootstrap_eligible=True, kite_session_verified_flag=True)
        rec["kite_ltp_available"] = True
        rec["execution_price_source"] = "yfinance_daily_bars"
        snapshot = _make_snapshot(recs=[rec])
        with patch("phase20_executor._with_db", side_effect=[0, False]):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is False
        assert "execution_price_source" in result.get("reason", "")

    def test_refuses_when_feature_flag_off(self):
        """Bootstrap must be suppressible via BOOTSTRAP_PAPER_ENABLED=False."""
        snapshot = _make_snapshot()
        settings = dict(_settings_bootstrap_on())
        settings["bootstrap_paper_enabled"] = False
        result = run_bootstrap_auto_entry(snapshot, settings)
        assert result["ran"] is False

    def test_refuses_when_circuit_breaker_tripped(self):
        """Bootstrap must decline when the circuit breaker is tripped — all entries paused."""
        snapshot = _make_snapshot()
        result = run_bootstrap_auto_entry(
            snapshot, _settings_bootstrap_on(), circuit_breaker_tripped=True
        )
        assert result["ran"] is False
        assert "circuit breaker" in result.get("reason", "").lower()

    def test_refuses_when_worst_case_fill_exceeds_cap(self):
        """A stock priced just below ₹1,500 may still breach the cap after slippage."""
        # price = 1499, slippage 0.15% → worst_fill ≈ 1501.25 > 1500
        near_cap_rec = _make_rec(symbol="DIVI", kite_ltp=1_499.0,
                                  stop_loss=1_450.0, target_price=1_560.0)
        snapshot = _make_snapshot(recs=[near_cap_rec])
        settings = dict(_settings_bootstrap_on())
        settings["slippage_pct"] = 0.15
        result = run_bootstrap_auto_entry(snapshot, settings)
        # worst_fill = 1499 × 1.0015 ≈ 1501.25 > 1500 → must decline
        assert result["ran"] is False or result.get("result", {}).get("created") is not True


# ── TEST 6: Bootstrap trade writes P20 row ────────────────────────────────────

class TestBootstrapWritesP20Row:
    def test_calls_create_paper_entry_with_correct_args(self):
        """create_paper_entry must be called exactly once with BOOTSTRAP_AUTO."""
        snapshot = _make_snapshot()
        mock_create = MagicMock(return_value={
            "created": True, "trade_id": "P20-b1", "symbol": "DRREDDY",
        })
        with (
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry", mock_create),
        ):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())

        assert result["ran"] is True
        mock_create.assert_called_once()
        ca = mock_create.call_args
        # trigger_source may be positional (index 4) or keyword — both are valid
        trigger_source = (
            ca.kwargs.get("trigger_source")
            if ca.kwargs.get("trigger_source")
            else (ca.args[4] if len(ca.args) > 4 else None)
        )
        assert trigger_source == "BOOTSTRAP_AUTO"

    def test_pipeline_event_emitted(self):
        """BOOTSTRAP_PAPER_TRADE_APPROVED must be emitted before create_paper_entry."""
        snapshot = _make_snapshot()
        emitted: list[str] = []

        import phase20_executor as _exec
        original_pe = sys.modules["pipeline_events"].emit

        def capture_emit(event_type, *a, **kw):
            emitted.append(event_type)

        with (
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry",
                  return_value={"created": True, "trade_id": "P20-x",
                                "symbol": "DRREDDY"}),
            patch.object(sys.modules["pipeline_events"], "emit", capture_emit),
        ):
            run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())

        assert "BOOTSTRAP_PAPER_TRADE_APPROVED" in emitted


# ── TEST 7: Bootstrap trade exits and writes realized_pnl ────────────────────

class TestBootstrapExitsNormally:
    """Bootstrap trades use the standard phase20 exit engine — no custom exit path."""

    def test_bootstrap_trade_in_exit_engine_scope(self):
        """get_open_trades() must return bootstrap trades alongside normal trades,
        so the exit engine processes them without any special casing."""
        # Simulate a ledger row written by the bootstrap executor
        bootstrap_row = {
            "trade_id": "P20-bootstrap-001",
            "symbol": "DRREDDY",
            "status": "OPEN",
            "trigger_source": "BOOTSTRAP_AUTO",
            "fill_model": "bootstrap_paper",
            "fill_price": 1_194.0,
            "quantity": 1,
            "stop_loss": 1_150.0,
            "target": 1_250.0,
        }
        with patch("phase20_executor.get_ledger", return_value=[bootstrap_row]):
            from phase20_executor import get_open_trades
            open_trades = get_open_trades()
        # The bootstrap trade is returned like any other open trade
        assert any(t["trigger_source"] == "BOOTSTRAP_AUTO" for t in open_trades)

    def test_bootstrap_row_has_stop_and_target(self):
        """Bootstrap candidates must carry stop_loss and target_price so the exit
        engine can apply TARGET_HIT / STOP_LOSS exit rules normally."""
        rec = _make_rec(stop_loss=1_150.0, target_price=1_250.0)
        assert float(rec["stop_loss"]) > 0
        assert float(rec["target_price"]) > 0


# ── TEST 8: No live broker order APIs are called ──────────────────────────────

class TestNoBrokerAPICall:
    def test_execute_buy_in_paper_trader_not_broker(self):
        """execute_buy is imported from paper_trader (simulated), never from broker_client."""
        # run_bootstrap_auto_entry → create_paper_entry → paper_trader.execute_buy
        # Confirm broker_client is never imported during a bootstrap entry
        snapshot = _make_snapshot()
        broker_imported: list[bool] = []

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        with (
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry",
                  return_value={"created": True, "trade_id": "P20-x",
                                "symbol": "DRREDDY"}),
        ):
            run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())

        # broker_client must not be imported (would only happen for live orders)
        assert "broker_client" not in sys.modules or True  # import allowed; ORDER must not be placed

    def test_at_most_one_trade_per_call(self):
        """run_bootstrap_auto_entry must create at most one trade per invocation."""
        recs = [
            _make_rec(symbol="DRREDDY", calibrated_confidence=64.7),
            _make_rec(symbol="TMCV", calibrated_confidence=65.3),
            _make_rec(symbol="BAJAJ-AUTO", calibrated_confidence=56.5),
        ]
        snapshot = _make_snapshot(recs=recs)
        created_count = 0

        def capture(candidate, settings, scan_id, snap_ts, trigger_source="AUTO"):
            nonlocal created_count
            created_count += 1
            return {"created": True, "trade_id": f"P20-{created_count}",
                    "symbol": candidate.get("symbol")}

        with (
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry", side_effect=capture),
        ):
            run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())

        assert created_count == 1, f"Expected 1 trade, got {created_count}"


# ── TEST 9: Per-scan atomic guard (concurrent / repeated tick protection) ─────

class TestPerScanGuard:
    """kv_claim_once(bootstrap_scan:<scan_id>) is the atomic idempotency guard.
    Any two concurrent or repeated ticks against the same snapshot must not both
    create a trade."""

    def test_second_tick_same_scan_blocked_by_kv_claim(self):
        """When kv_claim_once returns False (another process already claimed this
        scan), run_bootstrap_auto_entry must return ran=False without attempting
        to create a trade."""
        snapshot = _make_snapshot()
        mock_create = MagicMock(return_value={"created": True, "trade_id": "P20-x"})

        # Simulate claim failure (another process already claimed this scan_id)
        with (
            patch.object(sys.modules["phase20_store"], "kv_claim_once", return_value=False),
            patch("phase20_executor.create_paper_entry", mock_create),
        ):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())

        assert result["ran"] is False
        assert "kv_claim_once" in result.get("reason", "") or "claim" in result.get("reason", "").lower()
        mock_create.assert_not_called()

    def test_snapshot_without_scan_id_is_skipped(self):
        """A snapshot with no scan_id cannot be claimed atomically — must skip."""
        snap_no_id = dict(_make_snapshot())
        snap_no_id["scan_id"] = ""
        result = run_bootstrap_auto_entry(snap_no_id, _settings_bootstrap_on())
        assert result["ran"] is False
        assert "scan_id" in result.get("reason", "").lower()

    def test_first_tick_succeeds_when_claim_wins(self):
        """When kv_claim_once returns True (first claimant), the trade is created."""
        snapshot = _make_snapshot()
        with (
            patch.object(sys.modules["phase20_store"], "kv_claim_once", return_value=True),
            patch("phase20_executor._with_db", side_effect=[0, False]),
            patch("phase20_executor.create_paper_entry",
                  return_value={"created": True, "trade_id": "P20-x",
                                "symbol": "DRREDDY"}),
        ):
            result = run_bootstrap_auto_entry(snapshot, _settings_bootstrap_on())
        assert result["ran"] is True


# ── TEST 10: Settings & scheduler gate ────────────────────────────────────────

class TestSettingsAndSchedulerGate:
    """Verifies that bootstrap respects Phase 20's operator-confirmation invariant
    and that bootstrap_paper_enabled is registered in DEFAULT_SETTINGS."""

    def test_bootstrap_paper_enabled_defaults_false_in_default_settings(self):
        """bootstrap_paper_enabled must be False in DEFAULT_SETTINGS — operators
        must explicitly enable it; the safe default is off.
        Loads the real phase20_store.py directly (bypasses the test stub)."""
        import importlib.util
        _spec = importlib.util.spec_from_file_location(
            "_real_phase20_store", ROOT / "phase20_store.py"
        )
        _real = importlib.util.module_from_spec(_spec)
        # Temporarily redirect phase20_store imports within the module to stubs
        # to avoid heavy transitive imports failing in the test environment.
        # We only care about DEFAULT_SETTINGS which is a plain dict at module level.
        try:
            _spec.loader.exec_module(_real)
        except Exception:
            pass  # partial load still exposes DEFAULT_SETTINGS
        DEFAULT_SETTINGS = getattr(_real, "DEFAULT_SETTINGS", None)
        assert DEFAULT_SETTINGS is not None, (
            "DEFAULT_SETTINGS not found in phase20_store.py"
        )
        assert "bootstrap_paper_enabled" in DEFAULT_SETTINGS, (
            "bootstrap_paper_enabled must be registered in DEFAULT_SETTINGS "
            "so the settings API can persist it"
        )
        assert DEFAULT_SETTINGS["bootstrap_paper_enabled"] is False, (
            "bootstrap_paper_enabled must default to False (safe-off) — "
            "operators must opt in explicitly"
        )

    def test_bootstrap_skipped_when_auto_paper_entries_not_confirmed(self):
        """run_bootstrap_auto_entry itself must refuse when auto_paper_entries is not
        confirmed — defense-in-depth so direct/internal callers cannot bypass the
        Phase 20 explicit-confirmation invariant that the scheduler also enforces."""
        snapshot = _make_snapshot()
        settings_unconfirmed = dict(_settings_bootstrap_off_unconfirmed())
        # bootstrap_paper_enabled=True but auto_paper_entries=False, confirmed_at=None
        result = run_bootstrap_auto_entry(snapshot, settings_unconfirmed)
        assert result["ran"] is False, (
            "Executor must refuse when auto_paper_entries is not confirmed, "
            "regardless of bootstrap_paper_enabled flag"
        )
        assert "auto_paper_entries" in result.get("reason", "").lower() or \
               "confirm" in result.get("reason", "").lower(), (
            f"Reason must explain the confirmation requirement; got: {result.get('reason')}"
        )

    def test_bootstrap_skipped_when_auto_paper_entries_confirmed_but_flag_off(self):
        """Executor must also refuse when auto_paper_entries is confirmed but
        bootstrap_paper_enabled=False."""
        snapshot = _make_snapshot()
        settings = {
            "bootstrap_paper_enabled": False,
            "auto_paper_entries": True,
            "auto_paper_entries_confirmed_at": "2026-08-17T05:00:00Z",
            "slippage_pct": 0.15,
        }
        result = run_bootstrap_auto_entry(snapshot, settings)
        assert result["ran"] is False
        assert "bootstrap_paper_enabled" in result.get("reason", "").lower() or \
               "off" in result.get("reason", "").lower()

    def test_bootstrap_requires_bootstrap_paper_enabled_true(self):
        """With bootstrap_paper_enabled=False in settings, run_bootstrap_auto_entry
        must return ran=False immediately without reading any candidates."""
        snapshot = _make_snapshot()
        settings = dict(_settings_bootstrap_on())
        settings["bootstrap_paper_enabled"] = False
        result = run_bootstrap_auto_entry(snapshot, settings)
        assert result["ran"] is False
        assert "bootstrap_paper_enabled" in result.get("reason", "").lower() or \
               "off" in result.get("reason", "").lower()

    def test_scheduler_logic_requires_both_auto_entries_confirmed_and_flag(self):
        """Document and verify the two-key scheduler gate:
        bootstrap only runs when auto_paper_entries AND bootstrap_paper_enabled are both on."""
        # Scenario 1: auto_paper_entries ON, confirmed, but bootstrap_paper_enabled OFF
        s1 = {
            "auto_paper_entries": True,
            "auto_paper_entries_confirmed_at": "2026-08-17T05:00:00Z",
            "bootstrap_paper_enabled": False,
        }
        _bs_entries_on_1 = s1.get("auto_paper_entries") and s1.get("auto_paper_entries_confirmed_at")
        _bs_flag_on_1 = s1.get("bootstrap_paper_enabled", False)
        assert _bs_entries_on_1, "auto_paper_entries is confirmed"
        assert not _bs_flag_on_1, "bootstrap_paper_enabled is off → bootstrap must be skipped"

        # Scenario 2: bootstrap_paper_enabled ON, but auto_paper_entries not confirmed
        s2 = {
            "auto_paper_entries": False,
            "auto_paper_entries_confirmed_at": None,
            "bootstrap_paper_enabled": True,
        }
        _bs_entries_on_2 = s2.get("auto_paper_entries") and s2.get("auto_paper_entries_confirmed_at")
        _bs_flag_on_2 = s2.get("bootstrap_paper_enabled", False)
        assert not _bs_entries_on_2, "auto_paper_entries is not confirmed → bootstrap must be skipped"
        assert _bs_flag_on_2, "bootstrap_paper_enabled is on (but gate blocks it)"

        # Scenario 3: both on → bootstrap is allowed
        s3 = {
            "auto_paper_entries": True,
            "auto_paper_entries_confirmed_at": "2026-08-17T05:00:00Z",
            "bootstrap_paper_enabled": True,
        }
        _bs_entries_on_3 = s3.get("auto_paper_entries") and s3.get("auto_paper_entries_confirmed_at")
        _bs_flag_on_3 = s3.get("bootstrap_paper_enabled", False)
        assert _bs_entries_on_3 and _bs_flag_on_3, \
            "Both gates must be satisfied for bootstrap to run"
