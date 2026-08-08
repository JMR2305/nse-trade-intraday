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


if __name__ == "__main__":
    unittest.main()
