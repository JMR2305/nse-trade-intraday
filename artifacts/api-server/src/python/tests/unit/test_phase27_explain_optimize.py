"""Unit tests for Phase 27C/27D read-only aggregators."""
import unittest
from unittest.mock import patch

import phase27_explainability as pe
import phase27_strategy_optimization as po


REC = {
    "symbol": "ABC", "final_action": "STRONG BUY", "regime": "TRENDING",
    "rsi": 61.0, "adx": 27.0, "above_ema20": True, "above_ema50": True,
    "volume_ratio": 1.8, "sector": "IT", "entry_price": 100.0,
    "stop_loss": 96.0, "target_price": 110.0, "rr_ratio": 2.5, "heat": 3.1,
    "technical_score": 7.2, "calibrated_confidence": 64.0,
    "opportunity_score": 8.0, "historical_evidence_adjustment": -1.0,
    "low_evidence": False, "total_trades": 12, "win_rate": 58.0,
    "profit_factor": 1.4, "strategy_name": "Trend Rider",
    "gate_price": {"passed": True, "reason": "ok"},
    "gate_rr": {"passed": True, "reason": "ok"},
    "gate_volume": {"passed": True, "reason": "ok"},
    "gate_data_quality": {"passed": True, "reason": "ok"},
    "data_quality": "GOOD", "paper_eligible": True,
    "paper_order_id": None, "paper_order_note": None,
}


class TestExplainSymbol(unittest.TestCase):
    def _explain(self, rec, journey=None, position=None):
        with patch.object(pe, "_canonical_row", return_value=rec), \
             patch.object(pe, "_open_position", return_value=position), \
             patch("ops_centre.get_stock_journey",
                   return_value=journey or {"found": True, "stages": []}):
            return pe.explain_symbol("ABC")

    def test_strong_buy_maps_to_buy(self):
        d = self._explain(dict(REC))
        self.assertEqual(d["decision"], "BUY")
        self.assertEqual(d["confidence"], 64.0)
        self.assertTrue(d["advisory_only"] and d["read_only"])

    def test_open_position_maps_to_hold(self):
        d = self._explain(dict(REC), position={"symbol": "ABC", "quantity": 5})
        self.assertEqual(d["decision"], "HOLD")

    def test_ignore_maps_to_rejected_and_watch(self):
        d = self._explain({**REC, "final_action": "IGNORE"})
        self.assertEqual(d["decision"], "REJECTED")
        d = self._explain({**REC, "final_action": "WATCH"})
        self.assertEqual(d["decision"], "WATCH")

    def test_not_scanned_is_honest(self):
        d = self._explain(None)
        self.assertEqual(d["decision"], "NOT_SCANNED")
        self.assertFalse(d["scanned"])
        self.assertEqual(d["factors"], [])
        self.assertIn("not part of the latest canonical scan", d["note"])

    def test_unevaluated_factors_marked_never_fabricated(self):
        d = self._explain(dict(REC))
        by = {f["name"]: f for f in d["factors"]}
        for name in ("VWAP", "MACD", "ATR", "News impact", "Corporate actions"):
            self.assertFalse(by[name]["evaluated"])
            self.assertIsNone(by[name]["value"])
        self.assertTrue(by["Momentum (RSI)"]["evaluated"])
        self.assertEqual(by["Momentum (RSI)"]["value"], 61.0)

    def test_rejection_maps_spec_labels(self):
        journey = {"found": True, "stages": [], "why_not": {
            "rejected_by": "Risk Agent", "reason": "RR too low",
            "alternative": "Wait for better entry",
            "failing_criteria": [{"field": "rr_ratio", "threshold": 2.0,
                                  "current": 1.4}]}}
        rec = {**REC, "gate_rr": {"passed": False, "reason": "RR 1.4 below min 2.0"}, "final_action": "IGNORE"}
        d = self._explain(rec, journey=journey)
        rej = d["rejection"]["rejections"]
        first = rej[0]
        self.assertEqual(first["rejected_by"], "Risk Agent")
        self.assertEqual(first["rule"], "rr_ratio")
        self.assertEqual(first["threshold"], 2.0)
        self.assertEqual(first["actual"], 1.4)
        self.assertEqual(first["recommendation"], "Wait for better entry")
        # gate-derived rejection also present
        self.assertTrue(any(r["rule"] == "Risk/Reward gate" for r in rej))


def _trade(strategy="Trend Rider", pnl=100.0, pnl_pct=1.0, ts="2026-08-03T10:00:00",
           hold=45.0, entry=100.0, qty=10, conf=70.0, risk=3.0,
           sector="IT", regime="TRENDING"):
    return {"strategy": strategy, "pnl": pnl, "pnl_pct": pnl_pct,
            "timestamp": ts, "holding_time_minutes": hold,
            "entry_price": entry, "quantity": qty, "ai_confidence": conf,
            "risk_score": risk, "sector": sector, "market_regime": regime}


class TestStrategyOptimization(unittest.TestCase):
    def test_strategy_metric_contract(self):
        rows = [_trade(pnl=100, pnl_pct=1.0), _trade(pnl=-50, pnl_pct=-0.5),
                _trade(pnl=200, pnl_pct=2.0), _trade(pnl=-20, pnl_pct=-0.2),
                _trade(pnl=80, pnl_pct=0.8)]
        with patch.object(po, "_initial_capital", return_value=100000.0):
            m = po._strategy_metrics(rows)[0]
        self.assertEqual(m["trades"], 5)
        self.assertEqual(m["wins"], 3)
        self.assertEqual(m["losses"], 2)
        self.assertEqual(m["win_pct"], 60.0)
        self.assertAlmostEqual(m["avg_profit"], (100 + 200 + 80) / 3, places=2)
        self.assertAlmostEqual(m["avg_loss"], (-50 - 20) / 2, places=2)
        self.assertAlmostEqual(m["profit_factor"], 380 / 70, places=2)
        self.assertEqual(m["max_drawdown"], 50.0)
        self.assertIsNotNone(m["sharpe"])
        self.assertEqual(m["avg_hold_minutes"], 45.0)
        self.assertEqual(m["capital_utilisation_pct"], 1.0)  # 1000/100000
        self.assertFalse(m["low_evidence"])

    def test_low_evidence_flag(self):
        with patch.object(po, "_initial_capital", return_value=100000.0):
            m = po._strategy_metrics([_trade()])[0]
        self.assertTrue(m["low_evidence"])

    def test_filter_analysis_insufficient_evidence_and_duplicates(self):
        P = {"passed": True, "reason": "ok"}
        F = {"passed": False, "reason": "fail"}
        scan = [
            {"symbol": "A", "gate_price": P, "gate_rr": F,
             "gate_volume": F, "gate_data_quality": P},
            {"symbol": "B", "gate_price": P, "gate_rr": F,
             "gate_volume": F, "gate_data_quality": P},
            {"symbol": "C", "gate_price": P, "gate_rr": P,
             "gate_volume": P, "gate_data_quality": P},
        ]
        with patch.object(po, "_missed_opps", return_value=[]):
            fa = po._filter_analysis(scan)
        by = {f["filter"]: f for f in fa["filters"]}
        self.assertEqual(by["Risk/Reward gate"]["times_triggered"], 2)
        self.assertIsNone(by["Risk/Reward gate"]["good_rejections"])
        self.assertEqual(by["Risk/Reward gate"]["outcome_evidence"],
                         "INSUFFICIENT_EVIDENCE")
        # rr and volume reject identical sets → flagged duplicates
        self.assertEqual(by["Risk/Reward gate"]["classification"],
                         "DUPLICATE_REJECTION_SET")
        self.assertIn("Volume gate", by["Risk/Reward gate"]["duplicate_of"])
        self.assertEqual(by["Price gate"]["classification"],
                         "UNUSED_ON_LATEST_SCAN")

    def test_period_heatmap_distributions(self):
        rows = [_trade(ts="2026-08-03T10:00:00"), _trade(ts="2026-08-04T10:00:00", pnl=-30),
                _trade(ts="2026-07-15T10:00:00", strategy="Breakout", sector="AUTO")]
        pp = po._period_perf(rows)
        self.assertEqual(len(pp["monthly"]), 2)
        self.assertEqual(len(pp["daily"]), 3)
        hm = po._heatmaps(rows)
        self.assertTrue(hm["strategy_x_regime"])
        self.assertTrue(hm["weekday_x_strategy"])
        dist = po._distributions(rows)
        self.assertEqual(sum(b["trades"] for b in dist["confidence"]), 3)
        self.assertEqual(sum(b["trades"] for b in dist["risk_score"]), 3)

    def test_report_read_only_flags_and_empty_honesty(self):
        with patch.object(po, "_records", return_value=[]), \
             patch.object(po, "_scan_rows", return_value=[]), \
             patch.object(po, "_missed_opps", return_value=[]), \
             patch.object(po, "_recommendations", return_value=[]):
            d = po.strategy_optimization_report()
        self.assertTrue(d["ok"] and d["advisory_only"] and d["read_only"])
        self.assertFalse(d["evidence"]["sufficient"])
        self.assertEqual(d["strategies"], [])
        self.assertEqual(d["distributions"]["confidence"], [])


if __name__ == "__main__":
    unittest.main()
