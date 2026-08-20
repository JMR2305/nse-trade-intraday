"""
Phase 23 Parts 2/3 — Historical Backtest Engine tests.

All tests run against the file fallback (DATABASE_URL stripped) with
synthetic candles seeded directly into the cache — no network, no DB,
and NEVER the live phase20 ledger.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, timedelta

os.environ.pop("DATABASE_URL", None)

import pandas as pd

import backtest_portfolio as bp
import historical_data_engine as hde
import backtest_runner as br
import pipeline_events as pe


def _make_candles(start_day: str, n: int, base: float = 100.0,
                  drift: float = 0.6):
    """Synthetic rising daily candles (weekdays only)."""
    out = []
    d = date.fromisoformat(start_day)
    price = base
    made = 0
    while made < n:
        if d.weekday() < 5:
            o = price
            c = price + drift
            out.append({"ts": f"{d.isoformat()}T00:00:00+00:00",
                        "open": round(o, 2), "high": round(c + 1.0, 2),
                        "low": round(o - 1.0, 2), "close": round(c, 2),
                        "volume": 500000 + made * 1000})
            price = c
            made += 1
        d += timedelta(days=1)
    return out


class BacktestEngineTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bt_test_")
        # redirect every file-fallback store into the sandbox
        self._orig = (hde._CACHE_DIR, bp._RUNS_FILE, bp._TRADES_FILE,
                      pe.FALLBACK_FILE)
        hde._CACHE_DIR = os.path.join(self.tmp, "candles")
        bp._RUNS_FILE = os.path.join(self.tmp, "runs.json")
        bp._TRADES_FILE = os.path.join(self.tmp, "trades.json")
        pe.FALLBACK_FILE = os.path.join(self.tmp, "events.json")

    def tearDown(self):
        (hde._CACHE_DIR, bp._RUNS_FILE, bp._TRADES_FILE,
         pe.FALLBACK_FILE) = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestCustomUniverseEvidence(unittest.TestCase):
    """Custom-universe provenance must be retained for result consumers."""

    def test_snapshot_backed_universe_records_immutable_evidence(self):
        cfg = {
            "universe": "custom_low_price_sector",
            "end": "2025-01-10",
        }
        historical = {
            "status": "HISTORICAL_SNAPSHOT",
            "symbols": ["INFY", "TCS"],
            "as_of_date": "2025-01-10",
            "snapshot_at": "2025-01-09T18:30:00+00:00",
        }
        with patch(
            "custom_universe_store.get_historical_universe_resolution",
            return_value=historical,
        ):
            self.assertEqual(br.resolve_universe(cfg), ["INFY", "TCS"])

        self.assertEqual(cfg["universe_evidence"], "HISTORICAL_SNAPSHOT")
        self.assertEqual(
            cfg["universe_resolution"]["source"],
            "IMMUTABLE_HISTORICAL_SNAPSHOT",
        )
        self.assertFalse(cfg["universe_resolution"]["degraded"])
        self.assertEqual(
            cfg["universe_resolution"]["snapshot_at"],
            "2025-01-09T18:30:00+00:00",
        )

    def test_missing_snapshot_records_current_list_fallback_as_degraded(self):
        cfg = {
            "universe": "custom_low_price_sector",
            "end": "2025-01-10",
            "allow_current_universe_fallback": True,
        }
        with patch(
            "custom_universe_store.get_historical_universe_resolution",
            return_value={
                "status": "HISTORICAL_SNAPSHOT_UNAVAILABLE",
                "symbols": [],
                "as_of_date": "2025-01-10",
            },
        ), patch(
            "custom_universe_store.get_active_symbols",
            return_value=["BANKBARODA", "NBCC"],
        ):
            self.assertEqual(br.resolve_universe(cfg), ["BANKBARODA", "NBCC"])

        self.assertEqual(cfg["universe_evidence"], "CURRENT_MEMBERSHIP_FALLBACK")
        self.assertEqual(
            cfg["universe_resolution"]["source"],
            "CURRENT_ACTIVE_LIST_FALLBACK",
        )
        self.assertTrue(cfg["universe_resolution"]["degraded"])


class TestCandleCache(BacktestEngineTestBase):
    def test_store_and_read_roundtrip(self):
        candles = _make_candles("2026-01-01", 10)
        hde._store_candles("TESTSYM", "1d", candles)
        out = hde.get_candles("TESTSYM", "1d", "2026-01-01", "2026-02-28")
        self.assertEqual(len(out), 10)
        self.assertEqual(out[0]["open"], candles[0]["open"])

    def test_coverage_prevents_redownload(self):
        calls = {"n": 0}
        orig = hde._download

        def counting(*a, **k):
            calls["n"] += 1
            return _make_candles("2026-01-01", 5), None

        hde._download = counting
        try:
            r1 = hde.ensure_candles("COV", "1d", "2026-01-01", "2026-01-08")
            r2 = hde.ensure_candles("COV", "1d", "2026-01-01", "2026-01-08")
            self.assertTrue(r1["ok"] and r2["ok"])
            self.assertEqual(calls["n"], 1)   # identical range → ONE download
        finally:
            hde._download = orig

    def test_10m_resample(self):
        five = [
            {"ts": "2026-01-05T09:15:00+05:30", "open": 10, "high": 12,
             "low": 9, "close": 11, "volume": 100},
            {"ts": "2026-01-05T09:20:00+05:30", "open": 11, "high": 14,
             "low": 10, "close": 13, "volume": 200},
        ]
        # 09:15 and 09:20 land in different 10-min buckets (09:10, 09:20)
        ten = hde._resample_10m(five)
        self.assertEqual(len(ten), 2)
        merged = hde._resample_10m([
            {**five[0], "ts": "2026-01-05T09:10:00+05:30"},
            {**five[1], "ts": "2026-01-05T09:15:00+05:30"},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["high"], 14)
        self.assertEqual(merged[0]["low"], 9)
        self.assertEqual(merged[0]["close"], 13)
        self.assertEqual(merged[0]["volume"], 300)

    def test_intraday_range_too_old_is_explicit_error(self):
        r = hde.ensure_candles("OLD", "5m", "2020-01-01", "2020-02-01")
        self.assertFalse(r["ok"])
        self.assertIn("not available", r["error"])


class TestNoLookahead(BacktestEngineTestBase):
    def test_asof_daily_never_includes_future(self):
        candles = _make_candles("2026-01-01", 20)
        daily = br._to_df(candles)
        mid_ts = pd.Timestamp(candles[9]["ts"])
        df = br.build_asof_df(daily, None, mid_ts, "1d")
        self.assertEqual(len(df), 10)
        self.assertTrue((df.index <= mid_ts).all())

    def test_asof_intraday_partial_day(self):
        daily = br._to_df(_make_candles("2026-01-01", 10))
        intraday = br._to_df([
            {"ts": "2026-01-20T09:15:00+00:00", "open": 100, "high": 102,
             "low": 99, "close": 101, "volume": 10},
            {"ts": "2026-01-20T09:20:00+00:00", "open": 101, "high": 105,
             "low": 100, "close": 104, "volume": 20},
            {"ts": "2026-01-20T09:25:00+00:00", "open": 104, "high": 110,
             "low": 103, "close": 109, "volume": 30},
        ])
        ts = pd.Timestamp("2026-01-20T09:20:00+00:00")
        df = br.build_asof_df(daily, intraday, ts, "5m")
        # last row = partial "today" bar from candles up to 09:20 ONLY
        last = df.iloc[-1]
        self.assertEqual(float(last["high"]), 105.0)   # not 110 (09:25 bar)
        self.assertEqual(float(last["close"]), 104.0)
        self.assertEqual(float(last["volume"]), 30.0)  # 10 + 20


class TestBacktestLedger(BacktestEngineTestBase):
    def _row(self, run_id="BT-x", symbol="AAA"):
        return {"run_id": run_id, "symbol": symbol, "strategy_id": "trend",
                "strategy_name": "TrendRider", "signal_ts": "t1",
                "fill_ts": "t1", "signal_price": 100.0, "fill_price": 100.2,
                "quantity": 10, "stop_loss": 95.0, "target": 110.0,
                "est_charges": 1.2, "slippage": 0.2, "confidence": 70.0,
                "opportunity_score": 60.0, "regime": "TRENDING"}

    def test_no_duplicate_open_positions(self):
        t1 = bp.open_trade(self._row())
        t2 = bp.open_trade(self._row())
        self.assertIsNotNone(t1)
        self.assertIsNone(t2)     # second OPEN for same run+symbol blocked

    def test_close_and_snapshot_math(self):
        rid = bp.create_run({"capital": 10000.0, "interval": "1d",
                             "start": "2026-01-01", "end": "2026-01-31"})
        tid = bp.open_trade({**self._row(run_id=rid)})
        closed = bp.close_trade(tid, "t2", 110.0, "TARGET")
        self.assertAlmostEqual(closed["realized_pnl"], 98.0)  # (110-100.2)*10
        snap = bp.portfolio_snapshot(rid)
        self.assertEqual(snap["closed_positions_count"], 1)
        self.assertEqual(snap["wins"], 1)
        self.assertEqual(snap["win_rate"], 100.0)
        self.assertAlmostEqual(snap["realized_pnl"], 98.0)
        # cash = 10000 - (100.2*10 + 1.2) + 110*10
        self.assertAlmostEqual(snap["cash"], 10000 - 1003.2 + 1100.0)
        self.assertEqual(snap["open_positions_count"], 0)

    def test_unrealized_uses_marks(self):
        rid = bp.create_run({"capital": 10000.0})
        bp.open_trade({**self._row(run_id=rid, symbol="BBB")})
        snap = bp.portfolio_snapshot(rid, {"BBB": 105.0})
        self.assertAlmostEqual(snap["unrealized_pnl"], 48.0)  # (105-100.2)*10


class TestEndToEndRun(BacktestEngineTestBase):
    def _seed_and_run(self):
        # Seed 90 daily candles ending inside the replay window so the
        # production pipeline has warmup + replay data. Uptrend → entries.
        all_candles = _make_candles("2025-09-01", 110, base=500.0, drift=4.0)
        hde._store_candles("SYNTH", "1d", all_candles)
        # mark coverage so execute_run never tries to download
        hde._record_coverage("SYNTH", "1d",
                             date(2025, 1, 1), date(2026, 12, 31))
        replay_start = all_candles[95]["ts"][:10]
        replay_end = all_candles[-1]["ts"][:10]
        rid = bp.create_run({"interval": "1d", "start": replay_start,
                             "end": replay_end, "capital": 100000.0,
                             "symbols": ["SYNTH"]})
        out = br.execute_run(rid)
        return rid, out

    def test_full_run_pipeline_and_isolation(self):
        # live phase20 ledger must be completely untouched by a backtest
        from phase20_executor import get_ledger
        live_before = len(get_ledger(limit=10000))

        rid, out = self._seed_and_run()
        self.assertTrue(out["ok"], out)
        run = bp.get_run(rid)
        self.assertEqual(run["status"], "COMPLETED")
        self.assertGreater(run["metrics"]["ticks"], 5)

        # events exist and are BACKTEST-mode only
        evs = pe.query_events(run_id=rid, mode="BACKTEST", limit=5000)
        self.assertGreater(len(evs), 20)
        self.assertTrue(all(e["mode"] == "BACKTEST" for e in evs))
        # live event queries must NOT see backtest events
        live_evs = pe.query_events(mode="LIVE", limit=5000)
        self.assertTrue(all(e.get("run_id") != rid for e in live_evs))

        # scanner events present for the production pipeline stages
        stages = {e["stage"] for e in evs}
        for s in ("SUPERVISOR", "SCANNER", "RESEARCH", "STRATEGY", "RISK",
                  "AI_DECISION"):
            self.assertIn(s, stages)

        live_after = len(get_ledger(limit=10000))
        self.assertEqual(live_before, live_after)   # HARD ISOLATION

        # no duplicate trades: at most one OPEN per symbol at all times and
        # every trade has a unique id
        trades = bp.trades(rid)
        ids = [t["trade_id"] for t in trades]
        self.assertEqual(len(ids), len(set(ids)))
        # all trades closed by end of run
        self.assertEqual(bp.open_trades(rid), [])

    def test_run_cannot_execute_twice(self):
        rid, out = self._seed_and_run()
        self.assertTrue(out["ok"], out)
        trades_before = len(bp.trades(rid))
        again = br.execute_run(rid)   # COMPLETED run — claim must refuse
        self.assertFalse(again["ok"])
        self.assertIn("refusing", again["error"])
        self.assertEqual(len(bp.trades(rid)), trades_before)

    def test_validation_replay_equals_pipeline(self):
        rid, out = self._seed_and_run()
        self.assertTrue(out["ok"], out)
        v = br.validate_run(rid, sample=10)
        self.assertTrue(v["ok"])
        self.assertGreater(v["checked"], 0)
        self.assertEqual(v["mismatches"], [],
                         "Replay must produce identical decisions")
        self.assertEqual(v["verdict"], "MATCH")

    def test_decision_tree_no_hidden_logic(self):
        rid, out = self._seed_and_run()
        tree = br.decision_tree(rid, "SYNTH")
        self.assertEqual(tree["symbol"], "SYNTH")
        self.assertGreater(tree["total_events"], 0)
        stage_names = [s["stage"] for s in tree["stages"]]
        self.assertEqual(stage_names, pe.STAGES)
        risk = next(s for s in tree["stages"] if s["stage"] == "RISK")
        for e in risk["events"]:
            if e["event_type"] == "RISK_REJECTED":
                self.assertIn("failed_gates", e["payload"])  # exact rules


class TestReplayExplorer(BacktestEngineTestBase):
    """Phase 23 Parts 4/5 — replay bundle, trade story, explain, search,
    replay integrity. The explorer layer is READ-ONLY over the canonical
    stores, so these tests build a deterministic synthetic run (events +
    ledger + candles) instead of depending on live pipeline thresholds.
    Pipeline equivalence itself is proven by validate_run above."""

    def _seed_store_run(self):
        candles = _make_candles("2026-02-02", 3, base=100.0, drift=2.0)
        hde._store_candles("SYN", "1d", candles)
        hde._store_candles("REJ", "1d",
                           _make_candles("2026-02-02", 3, base=50.0,
                                         drift=1.0))
        tl = [c["ts"] for c in candles]
        rid = bp.create_run({"interval": "1d", "start": tl[0][:10],
                             "end": tl[-1][:10], "capital": 100000.0,
                             "symbols": ["SYN", "REJ"]})
        sid = [f"{rid}-T{i:05d}" for i in range(3)]

        def ev(et, stage, i, sym=None, payload=None):
            pe.emit(et, stage, scan_id=sid[i], mode="BACKTEST", run_id=rid,
                    symbol=sym, payload=payload or {})

        # tick 0: full BUY chain for SYN + rejection for REJ
        ev("SCAN_STARTED", "SUPERVISOR", 0)
        ev("SYMBOL_SCANNED", "SCANNER", 0, "SYN",
           {"rsi": 61.0, "adx": 28.0, "volume_ratio": 1.4,
            "data_quality": "LIVE", "bars": 200})
        ev("RESEARCH_COMPLETED", "RESEARCH", 0, "SYN",
           {"win_rate": 60.0, "profit_factor": 2.0, "total_trades": 10,
            "low_evidence": False})
        ev("MARKET_INTELLIGENCE_COMPLETED", "MARKET_INTELLIGENCE", 0, "SYN",
           {"regime": "TRENDING", "sector": "IT"})
        ev("MONITORING_COMPLETED", "MONITORING", 0, "SYN",
           {"above_ema20": True, "above_ema50": True})
        ev("STRATEGY_SELECTED", "STRATEGY", 0, "SYN",
           {"strategy_id": "trend", "strategy_name": "Trend Rider",
            "technical_score": 72.0})
        ev("RISK_APPROVED", "RISK", 0, "SYN",
           {"gates": {"rr": {"passed": True, "reason": "RR 2.0 ok"}},
            "rr_ratio": 2.0})
        ev("BUY_GENERATED", "AI_DECISION", 0, "SYN",
           {"action": "BUY", "confidence": 71.0, "opportunity_score": 68.0,
            "paper_eligible": True})
        tid = bp.open_trade({
            "run_id": rid, "scan_id": sid[0], "symbol": "SYN",
            "strategy_id": "trend", "strategy_name": "Trend Rider",
            "signal_ts": tl[0], "fill_ts": tl[0], "signal_price": 100.0,
            "fill_price": 100.2, "quantity": 10, "stop_loss": 96.0,
            "target": 108.0, "est_charges": 1.2, "slippage": 0.2,
            "confidence": 71.0, "opportunity_score": 68.0,
            "regime": "TRENDING"})
        ev("ORDER_SUBMITTED", "EXECUTION", 0, "SYN",
           {"qty": 10, "signal_price": 100.0, "fill_model": "next_open"})
        ev("ORDER_EXECUTED", "EXECUTION", 0, "SYN",
           {"trade_id": tid, "fill_price": 100.2, "qty": 10,
            "charges": 1.2, "slippage": 0.2})
        ev("POSITION_OPENED", "PORTFOLIO", 0, "SYN",
           {"trade_id": tid, "stop_loss": 96.0, "target": 108.0,
            "strategy": "Trend Rider"})
        ev("SYMBOL_SCANNED", "SCANNER", 0, "REJ",
           {"rsi": 40.0, "adx": 12.0, "volume_ratio": 0.4,
            "data_quality": "LIVE", "bars": 200})
        ev("RISK_REJECTED", "RISK", 0, "REJ",
           {"failed_gates": {"volume": {"passed": False,
                                        "reason": "Volume ratio 0.4 < 0.75",
                                        "threshold": 0.75, "value": 0.4}},
            "rr_ratio": 1.1, "confidence": 44.0})
        ev("PORTFOLIO_UPDATED", "PORTFOLIO", 0, None,
           {"cash": 98996.8, "portfolio_value": 99998.8,
            "open_positions": 1, "realized_pnl": 0.0})
        # tick 1: quiet tick
        ev("SYMBOL_SCANNED", "SCANNER", 1, "SYN",
           {"rsi": 60.0, "adx": 27.0, "volume_ratio": 1.2,
            "data_quality": "LIVE", "bars": 201})
        ev("PORTFOLIO_UPDATED", "PORTFOLIO", 1, None,
           {"cash": 98996.8, "portfolio_value": 100016.8,
            "open_positions": 1, "realized_pnl": 0.0})
        # tick 2: exit
        bp.close_trade(tid, tl[2], 108.0, "TARGET")
        ev("SELL_GENERATED", "AI_DECISION", 2, "SYN",
           {"reason": "TARGET", "trade_id": tid})
        ev("POSITION_CLOSED", "PORTFOLIO", 2, "SYN",
           {"trade_id": tid, "exit_rule": "TARGET", "exit_price": 108.0,
            "realized_pnl": 76.8})
        ev("PORTFOLIO_UPDATED", "PORTFOLIO", 2, None,
           {"cash": 100076.8, "portfolio_value": 100076.8,
            "open_positions": 0, "realized_pnl": 76.8})
        bp.update_run(
            rid, status="COMPLETED",
            metrics={"ticks": 3, "symbols": 2, "cash": 100076.8,
                     "portfolio_value": 100076.8, "realized_pnl": 76.8,
                     "total_trades": 1, "wins": 1, "losses": 0},
            validation={"verdict": "MATCH", "checked": 1, "mismatches": []})
        return rid, tid

    def test_replay_bundle_synchronized(self):
        import backtest_replay as brp
        rid, tid = self._seed_store_run()
        b = brp.replay_bundle(rid)
        self.assertTrue(b["ok"], b)
        self.assertEqual(len(b["timeline"]), 3)
        self.assertEqual(b["stage_order"], pe.STAGES)
        for row in b["ticks"]:
            self.assertLess(row["tick"], len(b["timeline"]))
            self.assertEqual(row["ts"], b["timeline"][row["tick"]])
            self.assertTrue(row["stages"])
        t0 = next(r for r in b["ticks"] if r["tick"] == 0)
        self.assertEqual(len(t0["buys"]), 1)
        self.assertEqual(t0["stages"]["RISK"]["rejected"], 1)
        self.assertEqual(t0["portfolio"]["open_positions"], 1)
        t2 = next(r for r in b["ticks"] if r["tick"] == 2)
        self.assertEqual(len(t2["sells"]), 1)
        self.assertEqual(len(b["trade_markers"]), 1)
        self.assertEqual(b["trade_markers"][0]["entry_tick"], 0)
        self.assertEqual(b["trade_markers"][0]["exit_tick"], 2)

    def test_trade_story_narrative(self):
        import backtest_replay as brp
        rid, tid = self._seed_store_run()
        s = brp.trade_story(rid, tid)
        self.assertTrue(s["ok"], s)
        types = [st["event_type"] for st in s["steps"]]
        for et in ("SYMBOL_SCANNED", "STRATEGY_SELECTED", "RISK_APPROVED",
                   "BUY_GENERATED", "ORDER_EXECUTED", "POSITION_OPENED",
                   "POSITION_CLOSED"):
            self.assertIn(et, types)
        self.assertEqual(s["entry_tick"], 0)
        self.assertEqual(s["exit_tick"], 2)
        ticks = [st["tick"] for st in s["steps"]]
        self.assertEqual(ticks, sorted(ticks))
        self.assertFalse(brp.trade_story(rid, "NOPE")["ok"])

    def test_explain_buy_and_reject(self):
        import backtest_replay as brp
        rid, tid = self._seed_store_run()
        ex = brp.explain(rid, "SYN")
        self.assertTrue(ex["ok"], ex)
        self.assertEqual(ex["verdict"], "BUY")
        self.assertEqual(ex["indicators"]["rsi"], 61.0)
        self.assertEqual(ex["confidence_breakdown"]["final_confidence"], 71.0)
        self.assertEqual(ex["target"], 108.0)
        self.assertEqual(ex["stop_loss"], 96.0)
        self.assertAlmostEqual(ex["expected_reward_pct"], 7.78, places=2)
        self.assertEqual(ex["position_size_calc"]["qty"], 10)
        rej = brp.explain(rid, "REJ")
        self.assertTrue(rej["ok"], rej)
        self.assertEqual(rej["verdict"], "REJECTED")
        gate = rej["rejection"]["failed_gates"]["volume"]
        self.assertEqual(gate["threshold"], 0.75)   # exact rule preserved
        self.assertEqual(gate["value"], 0.4)
        self.assertTrue(rej["relax_analysis"]["available"])
        self.assertIn("would_relaxing_have_helped", rej["relax_analysis"])
        # unknown symbol fails loudly, never fabricates
        self.assertFalse(brp.explain(rid, "GHOST")["ok"])

    def test_search_finds_trades_and_events(self):
        import backtest_replay as brp
        rid, tid = self._seed_store_run()
        r = brp.search(rid, tid)
        self.assertEqual(len(r["trades"]), 1)
        self.assertTrue(r["events"])          # events carry the trade_id too
        r2 = brp.search(rid, "trend rider")
        self.assertTrue(r2["trades"])
        self.assertEqual(brp.search(rid, "")["trades"], [])

    def test_replay_verify_pass_and_fail(self):
        import backtest_replay as brp
        rid, tid = self._seed_store_run()
        v = brp.replay_verify(rid)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["verdict"], "PASS",
                         [c for c in v["checks"] if c["status"] != "PASS"])
        names = {c["check"] for c in v["checks"]}
        for n in ("no_duplicate_events", "ticks_within_timeline",
                  "execution_matches_ledger", "fill_prices_match_ledger",
                  "portfolio_matches_replay", "decision_matches_backtest"):
            self.assertIn(n, names)
        # tamper with the ledger copy → verification must FAIL, not mask it
        rows = bp._load(bp._TRADES_FILE)
        rows[0]["fill_price"] = float(rows[0]["fill_price"]) + 50.0
        with open(bp._TRADES_FILE, "w") as f:
            json.dump(rows, f)
        v2 = brp.replay_verify(rid)
        self.assertEqual(v2["verdict"], "FAIL")


class TestStrategyLab(BacktestEngineTestBase):
    """Phase 23 Parts 6/7 — Strategy Lab is read-only + advisory; base runs
    must remain byte-identical after every lab operation."""

    def _seed_run(self, n_trades=8):
        import strategy_lab as lab
        lab._CACHE.clear()
        candles = _make_candles("2026-01-05", 40, base=100.0, drift=1.0)
        hde._store_candles("LAB", "1d", candles)
        tl = [c["ts"] for c in candles]
        rid = bp.create_run({"interval": "1d", "start": tl[0][:10],
                             "end": tl[-1][:10], "capital": 100000.0,
                             "symbols": ["LAB"]})
        pnls = [120.0, -60.0, 200.0, -40.0, 90.0, -110.0, 150.0, 30.0]
        regimes = ["TRENDING", "RANGING"] * 4
        for i in range(n_trades):
            tid = bp.open_trade({
                "run_id": rid, "scan_id": f"{rid}-T{i * 4:05d}",
                "symbol": "LAB", "strategy_id": f"s{i % 2}",
                "strategy_name": f"Strat{i % 2}",
                "signal_ts": tl[i * 4], "fill_ts": tl[i * 4],
                "signal_price": 100.0 + i, "fill_price": 100.0 + i,
                "quantity": 10, "stop_loss": 96.0 + i, "target": 110.0 + i,
                "est_charges": 1.0, "slippage": 0.1,
                "confidence": 45.0 + i * 5, "opportunity_score": 60.0,
                "regime": regimes[i]})
            bp.close_trade(tid, tl[i * 4 + 2],
                           100.0 + i + pnls[i] / 10.0, "TARGET"
                           if pnls[i] > 0 else "STOP")
        bp.update_run(rid, status="COMPLETED",
                      metrics={"ticks": len(tl), "portfolio_value": 100380.0,
                               "cash": 100380.0,
                               "equity_curve": [{"ts": tl[-1],
                                                 "equity": 100380.0}]},
                      validation={"verdict": "MATCH"})
        return rid

    def test_run_metrics_and_compare(self):
        import strategy_lab as lab
        rid = self._seed_run()
        m = lab.run_metrics(rid)
        self.assertTrue(m["ok"], m)
        self.assertEqual(m["trades"], 8)
        self.assertGreater(m["max_exposure"], 0)
        self.assertIsNotNone(m["capital_growth_pct"])
        cmp2 = lab.compare_runs([rid, "BT-NOPE"])
        self.assertTrue(cmp2["rows"][0]["ok"])
        self.assertFalse(cmp2["rows"][1]["ok"])   # unknown run fails loudly

    def test_what_if_filters_and_immutability(self):
        import strategy_lab as lab
        rid = self._seed_run()
        before = json.dumps(bp.trades(rid), sort_keys=True, default=str)
        wf = lab.what_if(rid, {"min_confidence": 60})
        self.assertTrue(wf["ok"], wf)
        self.assertEqual(wf["trades_kept"] + wf["trades_dropped"], 8)
        self.assertTrue(all("confidence" in d["reason"]
                            for d in wf["dropped"]))
        wf2 = lab.what_if(rid, {"stop_mult": 2.0, "target_mult": 1.5})
        self.assertTrue(wf2["resimulated_exits"])
        self.assertEqual(wf2["resim_failures"], 0)
        # base ledger byte-identical — derived only
        self.assertEqual(before, json.dumps(bp.trades(rid), sort_keys=True,
                                            default=str))
        self.assertFalse(wf.get("base_run_modified"))

    def test_walk_forward_and_monte_carlo(self):
        import strategy_lab as lab
        rid = self._seed_run()
        w = lab.walk_forward(rid, folds=3)
        self.assertTrue(w["ok"])
        self.assertEqual(w["verdict"], "OK")
        self.assertTrue(w["folds"])
        self.assertIn(w["overfitting_risk"], ("LOW", "MEDIUM", "HIGH"))
        mc = lab.monte_carlo("backtest", rid, simulations=200)
        self.assertEqual(mc["verdict"], "OK")
        self.assertEqual(mc["simulations"], 200)
        self.assertTrue(0 <= mc["probability_of_profit"] <= 100)
        self.assertTrue(mc["return_histogram"])
        # deterministic (seeded) — identical on rerun
        mc2 = lab.monte_carlo("backtest", rid, simulations=200)
        self.assertEqual(mc["expected_return_range_pct"],
                         mc2["expected_return_range_pct"])

    def test_buckets_leaderboard_calibration(self):
        import strategy_lab as lab
        rid = self._seed_run()
        b = lab.bucket_analysis("backtest", rid)
        self.assertEqual(b["verdict"], "OK")
        self.assertEqual({r["bucket"] for r in b["regime"]},
                         {"TRENDING", "RANGING"})
        self.assertTrue(b["weekday"] and b["month"])
        lb = lab.leaderboard("backtest", rid)
        self.assertEqual(len(lb["rows"]), 2)     # Strat0 / Strat1
        cal = lab.calibration("backtest", rid)
        self.assertTrue(cal["reliability_curve"])
        self.assertIsNotNone(cal["brier_score"])

    def test_dashboard_recommendations_diff_export(self):
        import strategy_lab as lab
        rid = self._seed_run()
        d = lab.dashboard("backtest", rid)
        self.assertEqual(d["verdict"], "OK")
        self.assertTrue(d["drawdown_curve"] and d["monthly_returns"])
        self.assertTrue(d["risk_heatmap"])
        r = lab.recommendations("backtest", rid)
        self.assertTrue(r["ok"])
        self.assertFalse(r["auto_apply"])        # advisory-only, always
        rid2 = self._seed_run()
        diff = lab.run_diff(rid, rid2)
        self.assertTrue(diff["ok"])
        ex = lab.export_report("backtest", rid, "markdown")
        self.assertIn("Advisory only", ex["content"])
        self.assertTrue(lab.export_report("backtest", rid, "csv")["content"])
        self.assertTrue(lab.export_report("backtest", rid, "json")["content"])

    def test_insufficient_evidence_never_extrapolates(self):
        import strategy_lab as lab
        rid = bp.create_run({"interval": "1d", "start": "2026-01-05",
                             "end": "2026-01-09", "capital": 100000.0,
                             "symbols": ["LAB"]})
        bp.update_run(rid, status="COMPLETED", metrics={})
        self.assertEqual(lab.monte_carlo("backtest", rid)["verdict"],
                         "INSUFFICIENT_EVIDENCE")
        self.assertEqual(lab.recommendations("backtest", rid)["verdict"],
                         "INSUFFICIENT_EVIDENCE")
        w = lab.walk_forward(rid)
        self.assertEqual(w["verdict"], "INSUFFICIENT_EVIDENCE")


class TestMockCandleDetection(BacktestEngineTestBase):
    """Mock-sourced candles must be rejected and logged — never traded silently."""

    def _seed_real(self, symbol: str, base: float = 500.0):
        candles = _make_candles("2025-09-01", 110, base=base, drift=4.0)
        hde._store_candles(symbol, "1d", candles)
        hde._record_coverage(symbol, "1d", date(2025, 1, 1), date(2026, 12, 31))
        return candles

    def _seed_mock(self, symbol: str):
        """Store candles tagged source='mock' (simulates market_data_engine fallback)."""
        candles = _make_candles("2025-09-01", 110, base=300.0, drift=2.0)
        for c in candles:
            c["source"] = "mock"
        hde._store_candles(symbol, "1d", candles)
        hde._record_coverage(symbol, "1d", date(2025, 1, 1), date(2026, 12, 31))

    # ── Source round-trip ────────────────────────────────────────────────────

    def test_source_field_stored_and_returned(self):
        """File-fallback stores and returns the source field correctly."""
        candles = _make_candles("2026-01-01", 5)
        for c in candles:
            c["source"] = "yfinance"
        hde._store_candles("SRC_TEST", "1d", candles)
        out = hde.get_candles("SRC_TEST", "1d", "2026-01-01", "2026-12-31")
        self.assertTrue(all(c.get("source") == "yfinance" for c in out),
                        "All returned candles must carry source='yfinance'")

    def test_mock_source_field_round_trips(self):
        """Candles stored with source='mock' are returned with source='mock'."""
        candles = _make_candles("2026-01-01", 5)
        for c in candles:
            c["source"] = "mock"
        hde._store_candles("MOCK_ROUND", "1d", candles)
        out = hde.get_candles("MOCK_ROUND", "1d", "2026-01-01", "2026-12-31")
        self.assertTrue(all(c.get("source") == "mock" for c in out),
                        "Mock source must survive the file-cache round-trip")

    def test_legacy_candles_without_source_default_to_yfinance(self):
        """Older file-cache entries that lack a source field default to 'yfinance'."""
        # Write a candle dict without the source key to mimic old cache entries.
        data = hde._file_load("LEGACY", "1d")
        data.setdefault("candles", {})
        data["candles"]["2026-01-05T00:00:00+00:00"] = {
            "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 1000
        }
        hde._file_save("LEGACY", "1d", data)
        out = hde.get_candles("LEGACY", "1d", "2026-01-01", "2026-12-31")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].get("source"), "yfinance",
                         "Missing source must default to 'yfinance'")

    # ── Backtest run guards ──────────────────────────────────────────────────

    def test_mock_symbol_skipped_and_logged(self):
        """A symbol with mock candles is excluded from trading and logged."""
        real_candles = self._seed_real("REAL_A")
        self._seed_mock("FAKE_A")
        start = real_candles[95]["ts"][:10]
        end = real_candles[-1]["ts"][:10]
        rid = bp.create_run({
            "interval": "1d", "start": start, "end": end,
            "capital": 100000.0, "symbols": ["REAL_A", "FAKE_A"],
        })
        out = br.execute_run(rid)
        self.assertTrue(out["ok"], out)
        run = bp.get_run(rid)
        self.assertEqual(run["status"], "COMPLETED")

        # mock_candle_symbols must name the offending symbol
        mcs = run["metrics"].get("mock_candle_symbols", [])
        self.assertIn("FAKE_A", mcs,
                      "mock_candle_symbols must list the excluded symbol")

        # FAKE_A must appear in data_errors with a clear message
        errors = run["metrics"].get("data_errors", {})
        self.assertIn("FAKE_A", errors)
        self.assertIn("mock", errors["FAKE_A"].lower())

        # No trades must be generated for the mock symbol
        trades = bp.trades(rid)
        mock_trades = [t for t in trades
                       if str(t["symbol"]).upper() == "FAKE_A"]
        self.assertEqual(mock_trades, [],
                         "No trades allowed on mock-source data")

    def test_mock_candle_symbols_always_present_in_metrics(self):
        """mock_candle_symbols key exists even when all data is clean."""
        real_candles = self._seed_real("REAL_B")
        start = real_candles[95]["ts"][:10]
        end = real_candles[-1]["ts"][:10]
        rid = bp.create_run({
            "interval": "1d", "start": start, "end": end,
            "capital": 100000.0, "symbols": ["REAL_B"],
        })
        out = br.execute_run(rid)
        self.assertTrue(out["ok"], out)
        run = bp.get_run(rid)
        self.assertIn("mock_candle_symbols", run["metrics"],
                      "Key must always be present so the UI can rely on it")
        self.assertEqual(run["metrics"]["mock_candle_symbols"], [],
                         "Empty list when no mock data was detected")

    def test_all_mock_symbols_causes_failed_run(self):
        """When every symbol has mock candles the run must FAIL, not silently succeed."""
        self._seed_mock("ONLY_MOCK_1")
        self._seed_mock("ONLY_MOCK_2")
        all_c = _make_candles("2025-09-01", 110)
        start = all_c[95]["ts"][:10]
        end = all_c[-1]["ts"][:10]
        rid = bp.create_run({
            "interval": "1d", "start": start, "end": end,
            "capital": 100000.0, "symbols": ["ONLY_MOCK_1", "ONLY_MOCK_2"],
        })
        out = br.execute_run(rid)
        # All symbols rejected → per_symbol is empty → RuntimeError → FAILED
        self.assertFalse(out["ok"],
                         "Run must fail when every symbol has mock candles")
        run = bp.get_run(rid)
        self.assertEqual(run["status"], "FAILED")

    def test_mock_warning_event_emitted(self):
        """A MOCK_DATA_WARNING pipeline event is emitted for each rejected symbol."""
        real_candles = self._seed_real("REAL_C")
        self._seed_mock("FAKE_C")
        start = real_candles[95]["ts"][:10]
        end = real_candles[-1]["ts"][:10]
        rid = bp.create_run({
            "interval": "1d", "start": start, "end": end,
            "capital": 100000.0, "symbols": ["REAL_C", "FAKE_C"],
        })
        br.execute_run(rid)
        events = pe.query_events(run_id=rid, mode="BACKTEST",
                                 event_type="MOCK_DATA_WARNING", limit=100)
        mock_syms = [e.get("symbol") for e in events]
        self.assertIn("FAKE_C", mock_syms,
                      "MOCK_DATA_WARNING event must be emitted for FAKE_C")
        # No warning event for the real symbol
        self.assertNotIn("REAL_C", mock_syms)

    # ── 10m provenance propagation ───────────────────────────────────────────

    def test_resample_10m_propagates_mock_source(self):
        """A 10m bucket is mock if ANY constituent 5m candle is mock."""
        five = [
            {"ts": "2026-01-05T09:15:00+05:30", "open": 10, "high": 12,
             "low": 9, "close": 11, "volume": 100, "source": "yfinance"},
            {"ts": "2026-01-05T09:20:00+05:30", "open": 11, "high": 14,
             "low": 10, "close": 13, "volume": 200, "source": "mock"},
        ]
        # Both candles land in different 10-min buckets (09:10 and 09:20).
        ten = hde._resample_10m(five)
        sources = {c["ts"]: c["source"] for c in ten}
        # Bucket containing the yfinance-only candle stays yfinance.
        yf_bucket = next(k for k in sources if "09:10" in k or "09:15" in k)
        mock_bucket = next(k for k in sources if "09:20" in k)
        self.assertEqual(sources[yf_bucket], "yfinance")
        self.assertEqual(sources[mock_bucket], "mock",
                         "10m bucket must inherit 'mock' from any constituent")

    def test_resample_10m_bucket_with_mixed_sources_is_mock(self):
        """When a single 10m bucket contains both yfinance and mock 5m bars, the bucket is mock."""
        # Both candles share the same 10-min bucket (09:10–09:20).
        five = [
            {"ts": "2026-01-05T09:10:00+05:30", "open": 10, "high": 12,
             "low": 9, "close": 11, "volume": 100, "source": "yfinance"},
            {"ts": "2026-01-05T09:15:00+05:30", "open": 11, "high": 14,
             "low": 10, "close": 13, "volume": 200, "source": "mock"},
        ]
        ten = hde._resample_10m(five)
        self.assertEqual(len(ten), 1)
        self.assertEqual(ten[0]["source"], "mock",
                         "Mixed bucket must be conservatively marked mock")

    def test_resample_10m_all_yfinance_stays_yfinance(self):
        """A 10m bucket where every 5m candle is yfinance stays yfinance."""
        five = [
            {"ts": "2026-01-05T09:10:00+05:30", "open": 10, "high": 12,
             "low": 9, "close": 11, "volume": 100, "source": "yfinance"},
            {"ts": "2026-01-05T09:15:00+05:30", "open": 11, "high": 14,
             "low": 10, "close": 13, "volume": 200, "source": "yfinance"},
        ]
        ten = hde._resample_10m(five)
        self.assertEqual(len(ten), 1)
        self.assertEqual(ten[0]["source"], "yfinance")


if __name__ == "__main__":
    unittest.main()
