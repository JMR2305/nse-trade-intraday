"""
test_phase20.py — Phase 20 tests: settings, confirmation flow, fill models,
gates, exits safety (no fabricated fills), replay determinism, validation.

All tests are pure-unit: no network, no scan runs, no DB writes to canonical
scan state. PAPER TRADING / RESEARCH ONLY.
"""

import unittest
from unittest.mock import patch

import phase20_store as store
from phase20_store import DEFAULT_SETTINGS, CONFIRMATION_TEXT, config_hash
from phase20_executor import compute_fill, compute_charges


class TestSettingsDefaults(unittest.TestCase):
    def test_auto_paper_entries_default_off(self):
        self.assertFalse(DEFAULT_SETTINGS["auto_paper_entries"])
        self.assertIsNone(DEFAULT_SETTINGS["auto_paper_entries_confirmed_at"])

    def test_interval_default_and_allowed(self):
        self.assertEqual(DEFAULT_SETTINGS["scan_interval_minutes"], 5)

    def test_fill_model_default_conservative(self):
        self.assertEqual(DEFAULT_SETTINGS["fill_model"], "SLIPPAGE_ADJUSTED")

    def test_config_hash_stable(self):
        a = config_hash(dict(DEFAULT_SETTINGS))
        b = config_hash(dict(DEFAULT_SETTINGS))
        self.assertEqual(a, b)
        changed = dict(DEFAULT_SETTINGS)
        changed["min_confidence"] = 99.0
        self.assertNotEqual(a, config_hash(changed))


class TestSettingsValidation(unittest.TestCase):
    """Validation rules in update_settings (mocked persistence)."""

    def _update(self, patch_dict, confirmation=None, current=None):
        cur = dict(DEFAULT_SETTINGS)
        if current:
            cur.update(current)
        with patch.object(store, "get_settings", return_value=cur), \
             patch.object(store, "_persist_settings", lambda s: s):
            return store.update_settings(patch_dict, confirmation_text=confirmation)

    def test_invalid_interval_rejected(self):
        with self.assertRaises(ValueError):
            self._update({"scan_interval_minutes": 2})

    def test_valid_intervals_accepted(self):
        for m in (1, 3, 5, 10, 15):
            s = self._update({"scan_interval_minutes": m})
            self.assertEqual(s["scan_interval_minutes"], m)

    def test_enabling_auto_entries_requires_exact_confirmation(self):
        with self.assertRaises(ValueError):
            self._update({"auto_paper_entries": True})
        with self.assertRaises(ValueError):
            self._update({"auto_paper_entries": True},
                         confirmation="yes please")
        s = self._update({"auto_paper_entries": True},
                         confirmation=CONFIRMATION_TEXT)
        self.assertTrue(s["auto_paper_entries"])
        self.assertIsNotNone(s["auto_paper_entries_confirmed_at"])

    def test_disabling_auto_entries_needs_no_confirmation(self):
        s = self._update({"auto_paper_entries": False},
                         current={"auto_paper_entries": True,
                                  "auto_paper_entries_confirmed_at": "x"})
        self.assertFalse(s["auto_paper_entries"])
        self.assertIsNone(s["auto_paper_entries_confirmed_at"])

    def test_unknown_keys_rejected(self):
        with self.assertRaises(ValueError):
            self._update({"live_trading": True})

    def test_invalid_fill_model_rejected(self):
        with self.assertRaises(ValueError):
            self._update({"fill_model": "FUTURE_PRICE"})


class TestFillModels(unittest.TestCase):
    SETTINGS = {"fill_model": "SLIPPAGE_ADJUSTED", "slippage_pct": 0.2,
                "charges_pct": 0.12}

    def test_ltp_no_slippage(self):
        f = compute_fill(100.0, {**self.SETTINGS, "fill_model": "LAST_TRADED_PRICE"})
        self.assertEqual(f["fill_price"], 100.0)
        self.assertEqual(f["slippage"], 0.0)

    def test_slippage_adjusted_moves_against_buy(self):
        f = compute_fill(100.0, self.SETTINGS, side="BUY")
        self.assertEqual(f["fill_price"], 100.2)

    def test_next_quote_half_slippage(self):
        f = compute_fill(100.0, {**self.SETTINGS, "fill_model": "NEXT_QUOTE"})
        self.assertEqual(f["fill_price"], 100.1)

    def test_sell_slippage_moves_down(self):
        f = compute_fill(100.0, self.SETTINGS, side="SELL")
        self.assertEqual(f["fill_price"], 99.8)

    def test_deterministic(self):
        self.assertEqual(compute_fill(543.21, self.SETTINGS),
                         compute_fill(543.21, self.SETTINGS))

    def test_charges(self):
        self.assertEqual(compute_charges(10000.0, self.SETTINGS), 12.0)


class TestGates(unittest.TestCase):
    def _ctx(self, **overrides):
        sym = {
            "symbol": "TCS", "sector": "IT", "final_action": "BUY",
            "entry_price": 100.0, "stop_loss": 95.0, "target_price": 112.0,
            "rr_ratio": 2.4, "confidence": 80.0, "opportunity_score": 75.0,
            "technical_score": 70.0, "data_quality": "LIVE",
            "all_gates_passed": True, "strategy_id": "s1",
            "strategy_name": "Trend", "regime": "Bullish", "error": None,
            "expected_holding_days": 5,
        }
        sym.update(overrides.pop("symbol_overrides", {}))
        ctx = {"available": True, "scan_id": "abc123", "snapshot_ts": "t",
               "stale": False, "scan_age_seconds": 60,
               "stale_after_seconds": 5400, "symbols": {"TCS": sym}}
        ctx.update(overrides)
        return ctx

    def _evaluate(self, ctx=None, market_state="OPEN", provider="Zerodha Kite Connect",
                  settings_overrides=None, portfolio=None, state=None):
        import phase20_gates as g
        ctx = ctx or self._ctx()
        settings = dict(DEFAULT_SETTINGS)
        settings["config_hash"] = "h"
        settings.update(settings_overrides or {})
        pf = portfolio or {"cash": 5000.0, "total_value": 5000.0,
                           "invested_value": 0.0, "positions": []}
        st = state or {"trades": [], "positions": {}}
        with patch.object(g.store, "get_settings", return_value=settings), \
             patch.object(g.store, "kv_set", lambda *a, **k: None), \
             patch.object(g.store, "kv_get", return_value={}), \
             patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch("market_hours.market_status",
                   return_value={"state": market_state}), \
             patch("scan_state_store.load_latest_meta",
                   return_value={"scan_id": ctx.get("scan_id"),
                                 "provider": provider}), \
             patch("scan_state_store.load_latest_snapshot",
                   return_value={"scan_id": ctx.get("scan_id"),
                                 "safety": {
                                     "kite_connected":
                                         "zerodha" in provider.lower()
                                         and "fallback" not in provider.lower()
                                         and "mock" not in provider.lower(),
                                     "data_provider": provider}}), \
             patch("paper_trader._load_state", return_value=st), \
             patch("paper_trader.get_portfolio", return_value=pf), \
             patch("phase20_executor.get_ledger", return_value=[]):
            return g.evaluate_entries()

    def test_all_gates_pass_for_clean_candidate(self):
        ev = self._evaluate()
        self.assertEqual(ev["eligible_count"], 1)
        self.assertEqual(ev["candidates"][0]["failed_gates"], [])
        self.assertGreaterEqual(ev["candidates"][0]["sizing"]["quantity"], 1)

    def test_stale_scan_blocks(self):
        ev = self._evaluate(ctx=self._ctx(stale=True))
        self.assertIn("scan_fresh", ev["candidates"][0]["failed_gates"])

    def test_market_closed_blocks(self):
        ev = self._evaluate(market_state="CLOSED")
        self.assertIn("market_open", ev["candidates"][0]["failed_gates"])

    def test_yahoo_fallback_provider_blocks(self):
        ev = self._evaluate(
            provider="Yahoo Finance (History) — Kite Connect not configured")
        failed = ev["candidates"][0]["failed_gates"]
        self.assertIn("provider_zerodha", failed)

    def test_low_confidence_blocks(self):
        ev = self._evaluate(ctx=self._ctx(
            symbol_overrides={"confidence": 50.0}))
        self.assertIn("min_confidence", ev["candidates"][0]["failed_gates"])

    def test_bad_rr_blocks(self):
        ev = self._evaluate(ctx=self._ctx(symbol_overrides={"rr_ratio": 1.0}))
        self.assertIn("min_risk_reward", ev["candidates"][0]["failed_gates"])

    def test_invalid_stop_blocks(self):
        ev = self._evaluate(ctx=self._ctx(
            symbol_overrides={"stop_loss": 150.0}))
        self.assertIn("valid_stop_loss", ev["candidates"][0]["failed_gates"])

    def test_insufficient_cash_blocks(self):
        ev = self._evaluate(portfolio={"cash": 50.0, "total_value": 5000.0,
                                       "invested_value": 4950.0,
                                       "positions": []})
        failed = ev["candidates"][0]["failed_gates"]
        self.assertTrue({"position_size", "sufficient_cash"} & set(failed))

    def test_duplicate_position_blocks(self):
        pf = {"cash": 5000.0, "total_value": 6000.0, "invested_value": 1000.0,
              "positions": [{"symbol": "TCS", "quantity": 10,
                             "current_price": 100.0}]}
        ev = self._evaluate(portfolio=pf)
        self.assertIn("no_open_duplicate", ev["candidates"][0]["failed_gates"])

    def test_daily_loss_limit_blocks(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        st = {"positions": {}, "trades": [
            {"action": "SELL", "pnl": -500.0, "timestamp": f"{today}T10:00:00Z"}]}
        ev = self._evaluate(state=st)
        self.assertIn("daily_loss_limit", ev["candidates"][0]["failed_gates"])


class TestAutoEntriesSafety(unittest.TestCase):
    def test_off_by_default_never_runs(self):
        from phase20_executor import run_auto_entries
        res = run_auto_entries(dict(DEFAULT_SETTINGS))
        self.assertFalse(res["ran"])

    def test_enabled_but_unconfirmed_never_runs(self):
        from phase20_executor import run_auto_entries
        s = dict(DEFAULT_SETTINGS)
        s["auto_paper_entries"] = True  # confirmed_at still None
        res = run_auto_entries(s)
        self.assertFalse(res["ran"])


class TestExitsSafety(unittest.TestCase):
    def _trade(self, **over):
        t = {"trade_id": "P20-x", "symbol": "TCS", "quantity": 5,
             "fill_price": 100.0, "stop_loss": 95.0, "target": 112.0,
             "fill_ts": "2026-07-25T04:00:00Z", "status": "OPEN",
             "sector": "IT"}
        t.update(over)
        return t

    def _run(self, trade, rec, stale=False, market_state="OPEN"):
        import phase20_exits as x
        ctx = {"available": True, "scan_id": "s2", "stale": stale,
               "symbols": ({"TCS": rec} if rec else {})}
        pf = {"cash": 0.0, "total_value": 5000.0, "invested_value": 500.0,
              "positions": [{"symbol": "TCS", "quantity": 5,
                             "current_price": rec.get("entry_price", 100.0)
                             if rec else 100.0}]}
        recorded = []
        sells = []
        settings = dict(DEFAULT_SETTINGS)
        with patch.object(x, "get_open_trades", return_value=[trade]), \
             patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch("market_hours.market_status",
                   return_value={"state": market_state}), \
             patch("paper_trader._load_state",
                   return_value={"trades": [], "positions": {}}), \
             patch("paper_trader.get_portfolio", return_value=pf), \
             patch("paper_trader.execute_sell",
                   side_effect=lambda *a, **k: (sells.append((a, k)) or (True, "ok"))), \
             patch.object(x, "record_exit",
                          side_effect=lambda *a, **k: recorded.append((a, k))), \
             patch.object(x.store, "add_notification", lambda *a, **k: None), \
             patch("phase20_executor.get_ledger", return_value=[]):
            result = x.manage_open_positions(settings)
        return result, recorded, sells

    def test_stop_hit_closes(self):
        rec = {"entry_price": 94.0, "data_quality": "LIVE", "final_action": "WATCH"}
        result, recorded, sells = self._run(self._trade(), rec)
        self.assertEqual(len(result["exits"]), 1)
        self.assertEqual(result["exits"][0]["rule"], "STOP_LOSS_HIT")
        self.assertEqual(len(sells), 1)

    def test_target_hit_closes(self):
        rec = {"entry_price": 115.0, "data_quality": "LIVE", "final_action": "WATCH"}
        result, _, _ = self._run(self._trade(), rec)
        self.assertEqual(result["exits"][0]["rule"], "TARGET_HIT")

    def test_recommendation_exit(self):
        rec = {"entry_price": 105.0, "data_quality": "LIVE", "final_action": "EXIT"}
        result, _, _ = self._run(self._trade(), rec)
        self.assertEqual(result["exits"][0]["rule"], "RECOMMENDATION_EXIT")

    def test_stale_data_never_fabricates_fill(self):
        # Stop would be hit, but data is STALE → PENDING, no sell.
        rec = {"entry_price": 90.0, "data_quality": "LIVE", "final_action": "WATCH"}
        trade = self._trade(fill_ts="2026-06-01T04:00:00Z")  # also time-exit due
        result, recorded, sells = self._run(trade, rec, stale=True)
        self.assertEqual(len(sells), 0, "No fill may be fabricated from stale data")
        self.assertEqual(len(result["pending"]), 1)
        # record_exit called with EXIT_PENDING status
        self.assertTrue(any(k.get("status") == "EXIT_PENDING" or
                            (len(a) >= 5 and a[4] == "EXIT_PENDING")
                            for a, k in recorded))

    def test_time_exit_after_max_holding(self):
        rec = {"entry_price": 101.0, "data_quality": "LIVE", "final_action": "WATCH"}
        trade = self._trade(fill_ts="2026-06-01T04:00:00Z")
        result, _, _ = self._run(trade, rec)
        self.assertEqual(result["exits"][0]["rule"], "TIME_EXIT")

    def test_trailing_stop_triggers_after_peak_then_pullback(self):
        import phase20_exits as x
        peaks = {}
        with patch.object(x.store, "kv_get",
                          side_effect=lambda k, d=None: peaks.get(k, d)), \
             patch.object(x.store, "kv_set",
                          side_effect=lambda k, v: peaks.__setitem__(k, v)):
            # 1R = 5. Peak reaches 110 (= fill + 2R) → armed.
            rec = {"entry_price": 110.0, "data_quality": "LIVE",
                   "final_action": "WATCH"}
            result, _, _ = self._run(self._trade(target=0), rec)
            self.assertEqual(result["exits"], [], "No exit at the peak itself")
            # Pullback to 104 (<= fill + 1R = 105) → TRAILING_STOP.
            rec = {"entry_price": 104.0, "data_quality": "LIVE",
                   "final_action": "WATCH"}
            result, _, sells = self._run(self._trade(target=0), rec)
            self.assertEqual(result["exits"][0]["rule"], "TRAILING_STOP")
            self.assertEqual(len(sells), 1)

    def test_trailing_stop_not_armed_without_peak(self):
        import phase20_exits as x
        peaks = {}
        with patch.object(x.store, "kv_get",
                          side_effect=lambda k, d=None: peaks.get(k, d)), \
             patch.object(x.store, "kv_set",
                          side_effect=lambda k, v: peaks.__setitem__(k, v)):
            # Price never reached 2R; pullback to 104 must NOT exit.
            rec = {"entry_price": 104.0, "data_quality": "LIVE",
                   "final_action": "WATCH"}
            result, _, sells = self._run(self._trade(target=0), rec)
            self.assertEqual(result["exits"], [])
            self.assertEqual(len(sells), 0)

    def test_no_exit_keeps_position_open(self):
        rec = {"entry_price": 101.0, "data_quality": "LIVE", "final_action": "BUY"}
        result, recorded, sells = self._run(self._trade(), rec)
        self.assertEqual(result["exits"], [])
        self.assertEqual(result["pending"], [])
        self.assertEqual(len(sells), 0)


class TestReplayDeterminism(unittest.TestCase):
    def test_replay_matches_original(self):
        import phase20_executor as ex
        trade = {
            "trade_id": "P20-repro", "scan_id": "abc", "snapshot_ts": "t0",
            "decision_ts": "t1", "side": "BUY", "signal_price": 100.0,
            "fill_price": 100.15, "quantity": 5, "slippage": 0.15,
            "fill_model": "SLIPPAGE_ADJUSTED", "status": "OPEN",
            "config_hash": "h", "rule_version": "phase20-v1",
            "model_version": "1",
            "evidence": {"gates": [{"gate": "x", "passed": True}],
                         "sizing": {"quantity": 5}},
        }
        with patch.object(ex, "get_trade", return_value=trade), \
             patch.object(ex.store, "get_settings",
                          return_value={"config_hash": "h"}):
            rep = ex.replay_trade("P20-repro")
        self.assertTrue(rep["found"])
        self.assertTrue(rep["deterministic_match"])
        self.assertEqual(rep["label"], "RECOMPUTED")
        self.assertFalse(rep["config_changed_since"])


class TestValidationStatus(unittest.TestCase):
    def test_returns_status_and_checks(self):
        from phase20_validation import get_validation_status
        v = get_validation_status()
        self.assertIn(v["overall_status"],
                      ("NOT_READY", "PAPER_READY", "DEGRADED"))
        names = {c["check"] for c in v["checks"]}
        self.assertIn("live_orders_disabled", names)
        self.assertIn("no_look_ahead", names)
        self.assertIn("reproducibility", names)
        live = next(c for c in v["checks"] if c["check"] == "live_orders_disabled")
        self.assertTrue(live["passed"], "Live orders must be disabled")


if __name__ == "__main__":
    unittest.main()
