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

    def test_quality_allocation_defaults_preserve_requested_safety_caps(self):
        self.assertTrue(DEFAULT_SETTINGS["quality_allocation_override_enabled"])
        self.assertEqual(
            DEFAULT_SETTINGS["quality_allocation_2x_risk_budget_pct"], 1.5)
        self.assertEqual(
            DEFAULT_SETTINGS["quality_allocation_3x_risk_budget_pct"], 2.0)
        self.assertFalse(
            DEFAULT_SETTINGS[
                "quality_allocation_3x_sector_override_enabled"])
        self.assertLessEqual(
            DEFAULT_SETTINGS[
                "quality_allocation_3x_sector_override_cap_pct"], 50.0)

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
        # 1, 2, 7 are no longer valid; only 3,4,5,6,10,15 are allowed
        for bad in (1, 2, 7):
            with self.assertRaises(ValueError):
                self._update({"scan_interval_minutes": bad})

    def test_valid_intervals_accepted(self):
        for m in (3, 4, 5, 6, 10, 15):
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

    def test_quality_thresholds_and_caps_are_validated(self):
        for patch_dict in (
            {"quality_allocation_2x_min_confidence": 101},
            {"quality_allocation_3x_min_risk_reward": 0.5},
            {"quality_allocation_2x_risk_budget_pct": 2.1},
            {"quality_allocation_3x_risk_budget_pct": 2.1},
            {"quality_allocation_3x_max_atr_pct": 0},
            {"quality_allocation_3x_max_stop_distance_pct": 11},
            {"quality_allocation_absolute_cap": 999},
            {"quality_allocation_3x_sector_override_cap_pct": 51},
        ):
            with self.assertRaises(ValueError):
                self._update(patch_dict)

    def test_3x_thresholds_cannot_be_looser_than_2x(self):
        with self.assertRaises(ValueError):
            self._update({
                "quality_allocation_2x_min_confidence": 90,
                "quality_allocation_3x_min_confidence": 89,
            })


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

    def test_quality_allocation_preview_uses_kite_and_cache_evidence(self):
        ctx = self._ctx(symbol_overrides={
            "confidence": 86.0,
            "opportunity_score": 82.0,
            "technical_score": 82.0,
            "rr_ratio": 2.6,
            "kite_ltp": 100.0,
            "kite_ltp_available": True,
            "kite_session_verified_flag": True,
            "kite_ltp_overlay_enabled": True,
            "execution_price_source": "kite_live_ltp",
            "quote_reliable": True,
            "ohlcv_source": "yfinance_daily_bars",
        })
        with patch("ohlcv_cache_store.get_cache_status", return_value={
            "TCS": {
                "cached": True,
                "data_quality": "LIVE",
                "missing_required": False,
                "latest_date": "2026-08-19",
                "age_days": 0,
            }
        }), patch("ohlcv_cache_store.read_symbol_from_cache",
                  return_value=None):
            ev = self._evaluate(ctx=ctx)
        candidate = ev["candidates"][0]
        self.assertEqual(
            candidate["allocation_override_preview"]["tier"],
            "HIGH_QUALITY_2X",
        )
        self.assertEqual(
            candidate["allocation_context"]["ohlcv_cache_data_quality"],
            "LIVE",
        )
        self.assertEqual(
            candidate["execution_price_source"], "kite_live_ltp")

    def test_research_fail_open_passes_when_halted(self):
        # fail_open (default) — gate must PASS even when research mode is
        # PIPELINE_HALTED so that the pipeline continues on market-only data.
        import phase20_gates as g

        def _kv_get(key, *args, **kwargs):
            if key == "research_agent_mode":
                return {"mode": "PIPELINE_HALTED"}
            return {}

        ctx = self._ctx()
        settings = dict(DEFAULT_SETTINGS)
        settings["config_hash"] = "h"
        settings["research_failure_mode"] = "fail_open"
        pf = {"cash": 5000.0, "total_value": 5000.0,
              "invested_value": 0.0, "positions": []}
        st = {"trades": [], "positions": {}}
        with patch.object(g.store, "get_settings", return_value=settings), \
             patch.object(g.store, "kv_set", lambda *a, **k: None), \
             patch.object(g.store, "kv_get", side_effect=_kv_get), \
             patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch("market_hours.market_status", return_value={"state": "OPEN"}), \
             patch("scan_state_store.load_latest_meta",
                   return_value={"scan_id": ctx["scan_id"],
                                 "provider": "Zerodha Kite Connect"}), \
             patch("scan_state_store.load_latest_snapshot",
                   return_value={"scan_id": ctx["scan_id"],
                                 "safety": {"kite_connected": True,
                                            "data_provider": "Zerodha Kite Connect"}}), \
             patch("paper_trader._load_state", return_value=st), \
             patch("paper_trader.get_portfolio", return_value=pf), \
             patch("phase20_executor.get_ledger", return_value=[]):
            ev = g.evaluate_entries()

        global_gate_ids = {gg["gate"]: gg for gg in ev["global_gates"]}
        self.assertIn("research_available", global_gate_ids,
                      "research_available must be present in global_gates")
        self.assertTrue(global_gate_ids["research_available"]["passed"],
                        "fail_open: gate must PASS even when PIPELINE_HALTED")
        self.assertNotIn("research_available", ev["candidates"][0]["failed_gates"])

    def test_research_fail_closed_blocks_when_halted(self):
        # fail_closed — gate must FAIL when research mode is PIPELINE_HALTED,
        # blocking every BUY candidate until research recovers.
        import phase20_gates as g

        def _kv_get(key, *args, **kwargs):
            if key == "research_agent_mode":
                return {"mode": "PIPELINE_HALTED"}
            return {}

        ctx = self._ctx()
        settings = dict(DEFAULT_SETTINGS)
        settings["config_hash"] = "h"
        settings["research_failure_mode"] = "fail_closed"
        pf = {"cash": 5000.0, "total_value": 5000.0,
              "invested_value": 0.0, "positions": []}
        st = {"trades": [], "positions": {}}
        with patch.object(g.store, "get_settings", return_value=settings), \
             patch.object(g.store, "kv_set", lambda *a, **k: None), \
             patch.object(g.store, "kv_get", side_effect=_kv_get), \
             patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch("market_hours.market_status", return_value={"state": "OPEN"}), \
             patch("scan_state_store.load_latest_meta",
                   return_value={"scan_id": ctx["scan_id"],
                                 "provider": "Zerodha Kite Connect"}), \
             patch("scan_state_store.load_latest_snapshot",
                   return_value={"scan_id": ctx["scan_id"],
                                 "safety": {"kite_connected": True,
                                            "data_provider": "Zerodha Kite Connect"}}), \
             patch("paper_trader._load_state", return_value=st), \
             patch("paper_trader.get_portfolio", return_value=pf), \
             patch("phase20_executor.get_ledger", return_value=[]):
            ev = g.evaluate_entries()

        global_gate_ids = {gg["gate"]: gg for gg in ev["global_gates"]}
        self.assertIn("research_available", global_gate_ids,
                      "research_available must be present in global_gates")
        self.assertFalse(global_gate_ids["research_available"]["passed"],
                         "fail_closed: gate must FAIL when PIPELINE_HALTED")
        self.assertIn("research_available", ev["candidates"][0]["failed_gates"],
                      "fail_closed: candidate must be blocked by research_available")
        self.assertEqual(ev["eligible_count"], 0,
                         "fail_closed: no candidates should be eligible when halted")


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
        # fill_ts must stay well inside max_holding_days (default 10) or
        # TIME_EXIT fires and masks the rule under test — use a dynamic
        # recent timestamp instead of a hardcoded date that goes stale.
        from datetime import datetime, timedelta, timezone
        recent = (datetime.now(timezone.utc) - timedelta(days=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        t = {"trade_id": "P20-x", "symbol": "TCS", "quantity": 5,
             "fill_price": 100.0, "stop_loss": 95.0, "target": 112.0,
             "fill_ts": recent, "status": "OPEN",
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
        # TIME_EXIT fires (3 days held, max_holding_days=2), data is STALE, but
        # held days (3) < exit_on_stale_after_days (5, default) → EXIT_PENDING.
        # Verifies that the new stale-exit feature doesn't fire below its threshold.
        from datetime import datetime, timedelta, timezone
        recent_3d = (datetime.now(timezone.utc) - timedelta(days=3)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        rec = {"entry_price": 90.0, "data_quality": "LIVE", "final_action": "WATCH"}
        trade = self._trade(fill_ts=recent_3d)
        # max_holding_days=2 → TIME_EXIT fires; exit_on_stale_after_days=5 → not met
        result, recorded, sells = self._run_with_settings(
            trade, rec, stale=True,
            settings_override={"max_holding_days": 2, "exit_on_stale_after_days": 5})
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

    # ── Task 791: exit_on_stale_after_days tests ──────────────────────────────

    def _run_with_settings(self, trade, rec, stale=False, settings_override=None):
        """Like _run but accepts a full settings dict override."""
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
        if settings_override:
            settings.update(settings_override)
        with patch.object(x, "get_open_trades", return_value=[trade]), \
             patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch("market_hours.market_status",
                   return_value={"state": "OPEN"}), \
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

    def _old_trade(self, days_held=6):
        """Trade held for `days_held` days (default exceeds exit_on_stale_after_days=5)."""
        from datetime import datetime, timedelta, timezone
        old_ts = (datetime.now(timezone.utc) - timedelta(days=days_held)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        return self._trade(fill_ts=old_ts)

    def test_stale_exit_after_n_days_closes_immediately(self):
        """Stale scan + TIME_EXIT + held >= exit_on_stale_after_days + yfinance quote
        → CLOSED immediately, no EXIT_PENDING.
        (max_holding_days=2 makes TIME_EXIT fire; 6 days >= threshold of 5.)"""
        rec = {"entry_price": 90.0, "data_quality": "LIVE", "final_action": "WATCH"}
        trade = self._old_trade(days_held=6)
        result, recorded, sells = self._run_with_settings(
            trade, rec, stale=True,
            settings_override={"max_holding_days": 2, "exit_on_stale_after_days": 5})
        self.assertEqual(len(sells), 1, "execute_sell must be called for stale-after-N-days exit")
        self.assertEqual(result["pending"], [], "Position must not enter EXIT_PENDING")
        self.assertEqual(len(result["exits"]), 1)
        self.assertEqual(result["exits"][0].get("price_source"), "yfinance_daily_close_stale")
        # record_exit must be called with CLOSED, not EXIT_PENDING
        self.assertTrue(any(k.get("status") == "CLOSED" or
                            (len(a) >= 5 and a[4] == "CLOSED")
                            for a, k in recorded),
                        "record_exit must be called with status=CLOSED")

    def test_stale_exit_below_threshold_defers_to_pending(self):
        """Stale scan + TIME_EXIT fires but held days < exit_on_stale_after_days
        → EXIT_PENDING (no sell).
        (max_holding_days=2 fires TIME_EXIT; 3 days < threshold of 5.)"""
        rec = {"entry_price": 90.0, "data_quality": "LIVE", "final_action": "WATCH"}
        trade = self._old_trade(days_held=3)
        result, recorded, sells = self._run_with_settings(
            trade, rec, stale=True,
            settings_override={"max_holding_days": 2, "exit_on_stale_after_days": 5})
        self.assertEqual(len(sells), 0, "No fill when held days < threshold")
        self.assertEqual(len(result["pending"]), 1)
        self.assertTrue(any(k.get("status") == "EXIT_PENDING" or
                            (len(a) >= 5 and a[4] == "EXIT_PENDING")
                            for a, k in recorded))

    def test_stale_exit_disabled_when_flag_zero(self):
        """exit_on_stale_after_days=0 disables the feature → EXIT_PENDING regardless
        of how long the trade has been held."""
        rec = {"entry_price": 90.0, "data_quality": "LIVE", "final_action": "WATCH"}
        trade = self._old_trade(days_held=30)  # well past any threshold
        result, recorded, sells = self._run_with_settings(
            trade, rec, stale=True,
            settings_override={"exit_on_stale_after_days": 0})
        self.assertEqual(len(sells), 0, "Feature is disabled — no fill must occur")
        self.assertEqual(len(result["pending"]), 1)
        self.assertTrue(any(k.get("status") == "EXIT_PENDING" or
                            (len(a) >= 5 and a[4] == "EXIT_PENDING")
                            for a, k in recorded))

    def test_stale_exit_no_yfinance_quote_defers_to_pending(self):
        """Stale scan + held >= threshold but no yfinance quote (entry_price=0)
        → EXIT_PENDING even though the stale-exit gate is open.
        (max_holding_days=2 fires TIME_EXIT; 6 days >= threshold of 5.)"""
        rec = {"entry_price": 0, "data_quality": "LIVE", "final_action": "WATCH"}
        trade = self._old_trade(days_held=6)
        result, recorded, sells = self._run_with_settings(
            trade, rec, stale=True,
            settings_override={"max_holding_days": 2, "exit_on_stale_after_days": 5})
        self.assertEqual(len(sells), 0, "No fill when yfinance quote is unavailable")
        self.assertEqual(len(result["pending"]), 1)

    def test_stale_exit_custom_threshold(self):
        """Custom exit_on_stale_after_days=10: trade held 8 days → still EXIT_PENDING;
        trade held 11 days → CLOSED via yfinance.
        (max_holding_days=2 makes TIME_EXIT fire for both.)"""
        rec = {"entry_price": 90.0, "data_quality": "LIVE", "final_action": "WATCH"}
        settings_ov = {"max_holding_days": 2, "exit_on_stale_after_days": 10}

        # 8 days held — below custom 10-day threshold → EXIT_PENDING
        trade_8 = self._old_trade(days_held=8)
        result8, _, sells8 = self._run_with_settings(
            trade_8, rec, stale=True, settings_override=settings_ov)
        self.assertEqual(len(sells8), 0, "8 days < 10 threshold — must not close")
        self.assertEqual(len(result8["pending"]), 1)

        # 11 days held — above custom 10-day threshold → CLOSED
        trade_11 = self._old_trade(days_held=11)
        result11, _, sells11 = self._run_with_settings(
            trade_11, rec, stale=True, settings_override=settings_ov)
        self.assertEqual(len(sells11), 1, "11 days >= 10 threshold — must close")
        self.assertEqual(result11["pending"], [])


class TestTimeoutExitPending(unittest.TestCase):
    """Tests for TIMEOUT_EXIT_PENDING force-close and yfinance fallback retry."""

    def _exit_pending_trade(self, pending_days=12, fill_days_ago=15, **over):
        """A trade in EXIT_PENDING state.

        pending_days — how long ago the trade transitioned to EXIT_PENDING
                       (stored in exit_ts).
        fill_days_ago — how long ago the trade was opened (stored in fill_ts).
                        Default older than pending_days to simulate a realistic
                        hold-then-stuck scenario.

        The critical distinction: timeout gating uses exit_ts (time in
        EXIT_PENDING), NOT fill_ts (total holding time).
        """
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        fill_ts = (now - timedelta(days=fill_days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        exit_ts = (now - timedelta(days=pending_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        t = {
            "trade_id": "P20-ep1", "symbol": "BAJFINANCE",
            "quantity": 3, "fill_price": 6500.0,
            "stop_loss": 6200.0, "target": 7000.0,
            "fill_ts": fill_ts, "exit_ts": exit_ts,
            "status": "EXIT_PENDING",
            "exit_rule": "TIME_EXIT",
            "sector": "Finance",
        }
        t.update(over)
        return t

    def _run_manage(self, trade, rec, stale=False, ledger_extra=None):
        import phase20_exits as x
        ctx = {"available": True, "scan_id": "s-ep", "stale": stale,
               "symbols": ({"BAJFINANCE": rec} if rec else {})}
        pf = {"cash": 10_000.0, "total_value": 15_000.0,
              "invested_value": 5_000.0,
              "positions": [{"symbol": "BAJFINANCE", "quantity": 3,
                             "current_price": rec.get("entry_price", 6500.0) if rec else 6500.0}]}
        recorded = []
        sells = []
        settings = dict(DEFAULT_SETTINGS)
        # Ledger includes the EXIT_PENDING trade so _retry_pending and
        # _resolve_timeout_exit_pending can see it.
        ledger = [trade] + (ledger_extra or [])
        with patch.object(x, "get_open_trades", return_value=[]), \
             patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch("market_hours.market_status",
                   return_value={"state": "OPEN"}), \
             patch("paper_trader._load_state",
                   return_value={"trades": [], "positions": {}}), \
             patch("paper_trader.get_portfolio", return_value=pf), \
             patch("paper_trader.execute_sell",
                   side_effect=lambda *a, **k: (sells.append((a, k)) or (True, "ok"))), \
             patch.object(x, "record_exit",
                          side_effect=lambda *a, **k: recorded.append((a, k))), \
             patch.object(x.store, "add_notification", lambda *a, **k: None), \
             patch("phase20_executor.get_ledger", return_value=ledger):
            result = x.manage_open_positions(settings)
        return result, recorded, sells

    def test_timeout_exit_pending_force_closes_with_yfinance_price(self):
        """A trade EXIT_PENDING for > max_holding_days must be force-closed."""
        rec = {"entry_price": 6450.0, "data_quality": "DAILY",
               "final_action": "WATCH"}
        # exit_ts = 12 days ago (>10 day threshold); fill_ts = 15 days ago
        trade = self._exit_pending_trade(pending_days=12, fill_days_ago=15)
        result, recorded, sells = self._run_manage(trade, rec)
        timeout_closed = result.get("timeout_closed", [])
        self.assertEqual(len(timeout_closed), 1,
                         "Trade stuck in EXIT_PENDING >max_holding_days must be force-closed")
        self.assertEqual(timeout_closed[0]["exit_rule"], "TIMEOUT_EXIT_PENDING")
        self.assertEqual(timeout_closed[0]["symbol"], "BAJFINANCE")
        self.assertEqual(timeout_closed[0]["exit_price"], 6450.0)
        self.assertEqual(timeout_closed[0]["price_source"], "yfinance_daily_close")

    def test_timeout_exit_pending_uses_kite_ltp_when_available(self):
        """Kite LTP is preferred over yfinance daily close in timeout force-close."""
        rec = {"entry_price": 6450.0, "data_quality": "DAILY",
               "final_action": "WATCH",
               "kite_ltp": 6460.0, "kite_ltp_available": True,
               "quote_reliable": True}
        trade = self._exit_pending_trade(pending_days=12)
        result, _, _ = self._run_manage(trade, rec)
        tc = result.get("timeout_closed", [])
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0]["price_source"], "kite_ltp")
        self.assertAlmostEqual(tc[0]["exit_price"], 6460.0)

    def test_timeout_exit_pending_falls_back_to_fill_price_when_no_quote(self):
        """When even yfinance has no price, fill_price is used as exit price."""
        trade = self._exit_pending_trade(pending_days=12)
        result, recorded, _ = self._run_manage(trade, rec={})
        tc = result.get("timeout_closed", [])
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0]["price_source"], "fill_price_fallback")
        self.assertAlmostEqual(tc[0]["exit_price"], 6500.0)

    def test_timeout_uses_exit_ts_not_fill_ts(self):
        """Timeout gate must measure time-in-EXIT_PENDING (exit_ts), not total
        holding time (fill_ts).  A trade held for 15 days that only just entered
        EXIT_PENDING (exit_ts 3 days ago) must NOT be force-closed."""
        rec = {"entry_price": 6450.0, "data_quality": "DAILY",
               "final_action": "WATCH"}
        # fill_ts = 15 days ago (would trip fill_ts-based gate),
        # exit_ts =  3 days ago (within max_holding_days=10 → must NOT close)
        trade = self._exit_pending_trade(pending_days=3, fill_days_ago=15)
        result, _, _ = self._run_manage(trade, rec)
        self.assertEqual(result.get("timeout_closed", []), [],
                         "Must not force-close: exit_ts is only 3 days old "
                         "(even though fill_ts is 15 days old)")

    def test_timeout_exit_not_triggered_for_recent_exit_pending(self):
        """EXIT_PENDING trade within max_holding_days (by exit_ts) must NOT fire."""
        rec = {"entry_price": 6450.0, "data_quality": "DAILY",
               "final_action": "WATCH"}
        trade = self._exit_pending_trade(pending_days=3)  # 3 days < 10 threshold
        result, _, _ = self._run_manage(trade, rec)
        self.assertEqual(result.get("timeout_closed", []), [],
                         "Should not force-close a recently-pending trade")

    def _pending_trade_for_retry(self, pending_hours=48, **over):
        """An EXIT_PENDING trade with exit_ts `pending_hours` ago."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        exit_ts = (now - timedelta(hours=pending_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        fill_ts = (now - timedelta(days=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        t = {
            "trade_id": "P20-ep-retry", "symbol": "BAJFINANCE",
            "quantity": 3, "fill_price": 6500.0,
            "fill_ts": fill_ts, "exit_ts": exit_ts,
            "status": "EXIT_PENDING", "exit_rule": "TIME_EXIT",
        }
        t.update(over)
        return t

    def test_retry_pending_accepts_yfinance_fallback_after_24h(self):
        """_retry_pending resolves EXIT_PENDING via yfinance daily close when
        the trade has been pending for ≥ 24 hours (Kite LTP offline scenario)."""
        import phase20_exits as x
        trade = self._pending_trade_for_retry(pending_hours=48)  # 2 days stuck
        rec = {"entry_price": 6430.0, "data_quality": "DAILY",
               "final_action": "WATCH"}
        sells = []
        recorded = []
        with patch("paper_trader.execute_sell",
                   side_effect=lambda *a, **k: (sells.append((a, k)) or (True, "ok"))), \
             patch("phase20_executor.get_ledger", return_value=[trade]), \
             patch.object(x, "record_exit",
                          side_effect=lambda *a, **k: recorded.append((a, k))), \
             patch.object(x.store, "add_notification", lambda *a, **k: None):
            out = x._retry_pending({"BAJFINANCE": rec}, scan_ok=True, stale=False,
                                   exit_scan_id="s-retry")
        self.assertEqual(len(out), 1,
                         "yfinance daily close must resolve EXIT_PENDING after 24 h")
        self.assertEqual(out[0]["symbol"], "BAJFINANCE")

    def test_retry_pending_rejects_yfinance_fallback_for_new_pending(self):
        """_retry_pending must NOT resolve via yfinance fallback when the trade
        just entered EXIT_PENDING (< 24 h ago).  New pending positions must
        wait for a reliable LIVE/NEAR_LIVE quote, not settle for daily close."""
        import phase20_exits as x
        trade = self._pending_trade_for_retry(pending_hours=2)  # just entered pending
        rec = {"entry_price": 6430.0, "data_quality": "DAILY",
               "final_action": "WATCH"}
        sells = []
        with patch("paper_trader.execute_sell",
                   side_effect=lambda *a, **k: (sells.append((a, k)) or (True, "ok"))), \
             patch("phase20_executor.get_ledger", return_value=[trade]), \
             patch.object(x, "record_exit", lambda *a, **k: None), \
             patch.object(x.store, "add_notification", lambda *a, **k: None):
            out = x._retry_pending({"BAJFINANCE": rec}, scan_ok=True, stale=False,
                                   exit_scan_id="s-retry")
        self.assertEqual(out, [],
                         "New pending position must wait for reliable quote, "
                         "not be immediately resolved via yfinance daily close")

    def test_retry_pending_skips_error_quotes(self):
        """_retry_pending must not resolve from a symbol marked with an error."""
        import phase20_exits as x
        trade = self._pending_trade_for_retry(pending_hours=48)
        rec = {"entry_price": 6430.0, "data_quality": "DAILY", "error": "timeout"}
        sells = []
        with patch("paper_trader.execute_sell",
                   side_effect=lambda *a, **k: (sells.append((a, k)) or (True, "ok"))), \
             patch("phase20_executor.get_ledger", return_value=[trade]), \
             patch.object(x, "record_exit", lambda *a, **k: None), \
             patch.object(x.store, "add_notification", lambda *a, **k: None):
            out = x._retry_pending({"BAJFINANCE": rec}, scan_ok=True, stale=False,
                                   exit_scan_id="s-retry")
        self.assertEqual(out, [],
                         "Error quote must not be used to resolve EXIT_PENDING")


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
