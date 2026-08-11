"""
Capital Deployment Fix — safety tests.

Proves (per the directive):
  * No scale-in when disabled (default behaviour preserved — regression).
  * Scale-in respects symbol/total exposure caps, cash, stop validity,
    count limit, confidence, RR and unrealized-P&L floor.
  * Every scale-in attempt records events with exact reasons.
  * Volume time-normalization only affects intraday mode; daily unchanged;
    insufficient volume-curve evidence falls back safely (never fabricated).
  * Sizing is settings-driven with behaviour-preserving defaults.
  * PAPER/RESEARCH ONLY: everything runs against the isolated backtest
    ledger file fallback — the live phase20 ledger is never touched.
"""

import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

os.environ.pop("DATABASE_URL", None)

import pandas as pd

import backtest_portfolio as bp
import backtest_runner as br
import pipeline_events as pe


def _rec(symbol="GLAND", entry=100.0, stop=94.0, target=112.0,
         confidence=75.0, rr=2.0):
    return SimpleNamespace(
        symbol=symbol, entry_price=entry, stop_loss=stop, target_price=target,
        strategy_id="s1", strategy_name="Test", calibrated_confidence=confidence,
        opportunity_score=70.0, regime="TRENDING", rr_ratio=rr)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bt_scalein_")
        self._orig = (bp._RUNS_FILE, bp._TRADES_FILE, pe.FALLBACK_FILE)
        bp._RUNS_FILE = os.path.join(self.tmp, "runs.json")
        bp._TRADES_FILE = os.path.join(self.tmp, "trades.json")
        pe.FALLBACK_FILE = os.path.join(self.tmp, "events.json")
        self.run_id = bp.create_run({"interval": "5m", "capital": 100000})

    def tearDown(self):
        (bp._RUNS_FILE, bp._TRADES_FILE, pe.FALLBACK_FILE) = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def events(self, etype=None):
        try:
            with open(pe.FALLBACK_FILE) as f:
                evs = json.load(f)
        except Exception:
            evs = []
        return [e for e in evs if etype is None or e["event_type"] == etype]

    def sizing(self, **over):
        s = dict(br.DEFAULT_SIZING)
        s.update(over)
        return s

    def enter(self, cash, sizing=None, mark=None, **rec_kw):
        return br._try_enter(self.run_id, "S1", _rec(**rec_kw), cash,
                             "2026-08-10T05:00:00+00:00",
                             sizing=sizing, mark=mark)


class TestDefaultsPreserved(Base):
    def test_default_sizing_matches_historical_constants(self):
        s = br.resolve_sizing({})
        self.assertEqual(s["risk_per_trade_pct"], 1.0)
        self.assertEqual(s["max_position_cap_pct"], 25.0)
        self.assertFalse(s["scale_in_enabled"])

    def test_second_entry_blocked_when_scale_in_disabled(self):
        cash, tid = self.enter(100000.0)
        self.assertIsNotNone(tid)
        cash2, tid2 = self.enter(cash)
        self.assertIsNone(tid2)
        self.assertEqual(cash2, cash)  # no cash consumed
        cancels = self.events("ORDER_CANCELLED")
        self.assertEqual(len(cancels), 1)
        self.assertIn("already exists", cancels[0]["payload"]["reason"])
        self.assertFalse(self.events("SCALE_IN_APPROVED"))
        self.assertFalse(self.events("SCALE_IN_EXECUTED"))
        self.assertEqual(len(bp.open_trades(self.run_id)), 1)

    def test_default_qty_identical_to_historical_formula(self):
        cash, tid = self.enter(100000.0)
        t = bp.open_trades(self.run_id)[0]
        # 1% risk of 100000 = 1000; per-share risk 6 → 166 shares,
        # capped at 25% of cash / 100 = 250 → 166.
        self.assertEqual(int(t["quantity"]), 166)
        self.assertEqual(int(t.get("tranche") or 0), 0)

    def test_sizing_is_settings_driven(self):
        s = self.sizing(risk_per_trade_pct=1.5)
        self.enter(100000.0, sizing=s)
        t = bp.open_trades(self.run_id)[0]
        self.assertEqual(int(t["quantity"]), 250)  # 1500 / 6


class TestScaleIn(Base):
    def setUp(self):
        super().setUp()
        self.s = self.sizing(scale_in_enabled=True, max_scale_in_count=2,
                             max_symbol_exposure_pct=60.0,
                             max_total_exposure_pct=80.0)
        self.cash, self.tid = self.enter(100000.0, sizing=self.s)
        self.assertIsNotNone(self.tid)

    def test_scale_in_executes_with_events(self):
        cash2, tid2 = self.enter(self.cash, sizing=self.s, mark=101.0)
        self.assertIsNotNone(tid2)
        self.assertEqual(len(self.events("SCALE_IN_APPROVED")), 1)
        self.assertEqual(len(self.events("SCALE_IN_EXECUTED")), 1)
        opens = bp.open_trades(self.run_id)
        self.assertEqual(len(opens), 2)
        self.assertEqual(sorted(int(t["tranche"]) for t in opens), [0, 1])
        self.assertLess(cash2, self.cash)

    def test_count_limit(self):
        s = dict(self.s, max_scale_in_count=1)
        _, t2 = self.enter(self.cash, sizing=s, mark=101.0)
        self.assertIsNotNone(t2)
        _, t3 = self.enter(50000.0, sizing=s, mark=101.0)
        self.assertIsNone(t3)
        rej = self.events("SCALE_IN_REJECTED")
        self.assertTrue(any("count" in e["payload"]["reason"].lower() for e in rej))

    def test_confidence_and_rr_thresholds(self):
        _, t2 = self.enter(self.cash, sizing=self.s, mark=101.0, confidence=50.0)
        self.assertIsNone(t2)
        _, t3 = self.enter(self.cash, sizing=self.s, mark=101.0, rr=1.0)
        self.assertIsNone(t3)
        reasons = [e["payload"]["reason"] for e in self.events("SCALE_IN_REJECTED")]
        self.assertTrue(any("Confidence" in r for r in reasons))
        self.assertTrue(any("Risk/reward" in r for r in reasons))

    def test_unrealized_floor(self):
        _, t2 = self.enter(self.cash, sizing=self.s, mark=90.0)  # ~-10%
        self.assertIsNone(t2)
        reasons = [e["payload"]["reason"] for e in self.events("SCALE_IN_REJECTED")]
        self.assertTrue(any("unrealized" in r for r in reasons))

    def test_invalid_stop_rejected(self):
        _, t2 = self.enter(self.cash, sizing=self.s, mark=101.0,
                           stop=110.0)  # stop above entry
        self.assertIsNone(t2)
        reasons = [e["payload"]["reason"] for e in self.events("SCALE_IN_REJECTED")]
        self.assertTrue(any("Invalid stop" in r for r in reasons))

    def test_symbol_exposure_cap(self):
        s = dict(self.s, max_symbol_exposure_pct=20.0)
        _, t2 = self.enter(self.cash, sizing=s, mark=101.0)
        self.assertIsNone(t2)
        reasons = [e["payload"]["reason"] for e in self.events("SCALE_IN_REJECTED")]
        self.assertTrue(any("Symbol exposure" in r for r in reasons))

    def test_total_exposure_cap(self):
        s = dict(self.s, max_total_exposure_pct=18.0)
        _, t2 = self.enter(self.cash, sizing=s, mark=101.0)
        self.assertIsNone(t2)
        reasons = [e["payload"]["reason"] for e in self.events("SCALE_IN_REJECTED")]
        self.assertTrue(any("Total exposure" in r for r in reasons))

    def test_insufficient_cash(self):
        _, t2 = self.enter(50.0, sizing=self.s, mark=101.0)
        self.assertIsNone(t2)
        rej = self.events("SCALE_IN_REJECTED")
        self.assertTrue(rej)

    def test_live_ledger_untouched(self):
        # All state lives in the sandboxed backtest files; the live phase20
        # paper ledger module is never imported by _try_enter.
        import backtest_runner as m
        import inspect
        src = inspect.getsource(m._try_enter) + inspect.getsource(m._scale_in_guards)
        self.assertNotIn("paper_trader", src)
        self.assertNotIn("portfolio_store", src)


class TestSizingValidation(unittest.TestCase):
    def test_malformed_values_fall_back_to_defaults(self):
        s = br.resolve_sizing({"sizing": {
            "risk_per_trade_pct": float("nan"),
            "max_position_cap_pct": float("inf"),
            "max_symbol_exposure_pct": -5,
            "max_total_exposure_pct": "80",
            "scale_in_enabled": "false",       # string, not JSON bool
            "max_scale_in_count": float("nan"),
            "scale_in_min_confidence": None,
        }})
        self.assertEqual(s, br.DEFAULT_SIZING)

    def test_non_dict_sizing_ignored(self):
        self.assertEqual(br.resolve_sizing({"sizing": "yes"}), br.DEFAULT_SIZING)

    def test_valid_values_accepted(self):
        s = br.resolve_sizing({"sizing": {"scale_in_enabled": True,
                                          "risk_per_trade_pct": 1.5,
                                          "max_scale_in_count": 2}})
        self.assertTrue(s["scale_in_enabled"])
        self.assertEqual(s["risk_per_trade_pct"], 1.5)
        self.assertEqual(s["max_scale_in_count"], 2)


class TestVolumeNormalization(unittest.TestCase):
    def _intraday(self, days, bars_per_day=6, vol=1000.0):
        rows = []
        for d in range(days):
            day = pd.Timestamp("2026-08-03", tz="UTC") + pd.Timedelta(days=d)
            for b in range(bars_per_day):
                rows.append({"ts": day + pd.Timedelta(minutes=5 * b),
                             "open": 100.0, "high": 101.0, "low": 99.0,
                             "close": 100.5, "volume": vol})
        df = pd.DataFrame(rows).set_index("ts").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    def _daily(self):
        idx = pd.date_range("2026-07-01", "2026-08-08", freq="D", tz="UTC")
        return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                             "close": 100.5, "volume": 6000.0}, index=idx)

    def test_normalized_ratio_attached_intraday(self):
        intraday = self._intraday(7)
        ts = pd.Timestamp("2026-08-09 00:10:00", tz="UTC")
        df = br.build_asof_df(self._daily(), intraday, ts, "5m",
                              vol_normalize=True)
        norm = df.attrs.get("intraday_vol_norm")
        self.assertTrue(norm and norm["ok"])
        self.assertAlmostEqual(norm["ratio"], 1.0, places=3)  # identical days

    def test_daily_mode_never_normalized(self):
        ts = pd.Timestamp("2026-08-08", tz="UTC")
        df = br.build_asof_df(self._daily(), None, ts, "1d", vol_normalize=True)
        self.assertNotIn("intraday_vol_norm", df.attrs)

    def test_disabled_by_default(self):
        intraday = self._intraday(7)
        ts = pd.Timestamp("2026-08-09 00:10:00", tz="UTC")
        df = br.build_asof_df(self._daily(), intraday, ts, "5m")
        self.assertNotIn("intraday_vol_norm", df.attrs)

    def test_insufficient_evidence_falls_back(self):
        intraday = self._intraday(3)  # < VOL_CURVE_MIN_DAYS prior sessions
        ts = pd.Timestamp("2026-08-05 00:10:00", tz="UTC")
        df = br.build_asof_df(self._daily(), intraday, ts, "5m",
                              vol_normalize=True)
        norm = df.attrs.get("intraday_vol_norm")
        self.assertIsNotNone(norm)
        self.assertFalse(norm["ok"])
        self.assertIn("insufficient", norm["reason"])


if __name__ == "__main__":
    unittest.main()
