"""Unit tests for phase27_operator_analytics (Phase 27E).

Tests are hermetic: canonical sources (replay, pipeline events, snapshot,
sessions) are patched — no DB, no network, no live scan required.
"""
import unittest
from unittest.mock import patch

import phase27_operator_analytics as opan


def ev(event_type, symbol=None, stage="SCANNER", scan_id="scanA",
       ts="2026-08-09T04:00:00+00:00", payload=None, _id=1):
    return {"id": _id, "event_type": event_type, "stage": stage,
            "scan_id": scan_id, "symbol": symbol, "ts": ts,
            "payload": payload or {}}


class TestRejectionReasons(unittest.TestCase):
    def test_symbol_rejected_uses_payload_error(self):
        e = ev("SYMBOL_REJECTED", "X", payload={"error": "Data fetch failed"})
        self.assertEqual(opan._rejection_reasons(e), ["Data fetch failed"])

    def test_risk_rejected_uses_failed_gate_keys(self):
        e = ev("RISK_REJECTED", "X",
               payload={"failed_gates": {"min_rr": {}, "max_exposure": {}}})
        self.assertEqual(sorted(opan._rejection_reasons(e)),
                         ["max_exposure", "min_rr"])

    def test_precheck_rejected_uses_reasons_list(self):
        e = ev("PRECHECK_REJECTED", "X",
               payload={"reasons": ["MAX_POSITIONS", "DAILY_LOSS_LIMIT"]})
        self.assertEqual(opan._rejection_reasons(e),
                         ["MAX_POSITIONS", "DAILY_LOSS_LIMIT"])

    def test_unknown_payload_falls_back_to_event_type(self):
        e = ev("ORDER_REJECTED", "X", payload={})
        self.assertEqual(opan._rejection_reasons(e), ["ORDER_REJECTED"])


class TestAggregateRejections(unittest.TestCase):
    def test_counts_pct_symbols_and_raw_codes_preserved(self):
        events = [
            ev("SYMBOL_REJECTED", "A", payload={"error": "no data"}, _id=1),
            ev("SYMBOL_REJECTED", "B", payload={"error": "no data"}, _id=2),
            ev("RISK_REJECTED", "C", payload={"failed_gates": {"min_rr": {}}}, _id=3),
            ev("BUY_GENERATED", "D", _id=4),  # not a rejection
        ]
        out = opan._aggregate_rejections(events)
        self.assertEqual(out["rejected_events"], 3)
        self.assertEqual(out["reason_occurrences"], 3)
        top = out["reasons"][0]
        self.assertEqual(top["reason_code"], "no data")   # raw, verbatim
        self.assertEqual(top["count"], 2)
        self.assertEqual(top["symbols"], ["A", "B"])
        self.assertAlmostEqual(top["pct_of_occurrences"], 66.7)
        codes = {r["reason_code"] for r in out["reasons"]}
        self.assertIn("min_rr", codes)

    def test_empty_events_gives_zero_not_error(self):
        out = opan._aggregate_rejections([])
        self.assertEqual(out["rejected_events"], 0)
        self.assertEqual(out["reason_occurrences"], 0)
        self.assertEqual(out["reasons"], [])
        self.assertEqual(out["evidence"], "VERIFIED_EMPTY")

    def test_multi_gate_event_counts_once_as_event(self):
        events = [ev("RISK_REJECTED", "X",
                     payload={"failed_gates": {"a": {}, "b": {}}})]
        out = opan._aggregate_rejections(events)
        self.assertEqual(out["rejected_events"], 1)
        self.assertEqual(out["reason_occurrences"], 2)

    def test_truncated_fetch_marks_partial_evidence(self):
        events = [ev("SYMBOL_REJECTED", "A", payload={"error": "x"})]
        out = opan._aggregate_rejections(
            events, {"available": True, "truncated": True})
        self.assertEqual(out["evidence"], "PARTIAL")

    def test_unavailable_source_never_reported_as_empty(self):
        out = opan._aggregate_rejections(
            [], {"available": False, "error": "db down", "truncated": False})
        self.assertEqual(out["evidence"], "SOURCE_UNAVAILABLE")


class TestDecisionDistribution(unittest.TestCase):
    def test_event_counts_and_snapshot_normalisation(self):
        events = [ev("BUY_GENERATED", "A"), ev("WATCH_GENERATED", "B"),
                  ev("WATCH_GENERATED", "C"), ev("IGNORE_GENERATED", "D")]
        rows = [{"final_action": "STRONG_BUY", "sector": "IT"},
                {"final_action": "STRONG BUY", "sector": "IT"},
                {"final_action": "watch", "sector": "Auto"}]
        out = opan._decision_distribution(events, rows, "scanA", "scanA")
        self.assertEqual(out["event_decisions"]["counts"],
                         {"BUY": 1, "WATCH": 2, "IGNORE": 1})
        self.assertTrue(out["snapshot_distribution"]["available"])
        actions = {a["action"]: a["count"]
                   for a in out["snapshot_distribution"]["actions"]}
        # STRONG_BUY and "STRONG BUY" normalise to one bucket
        self.assertEqual(actions["STRONG BUY"], 2)
        self.assertEqual(actions["WATCH"], 1)

    def test_snapshot_from_different_scan_is_omitted_not_mixed(self):
        rows = [{"final_action": "BUY"}]
        out = opan._decision_distribution([], rows, "oldScan", "scanA")
        self.assertFalse(out["snapshot_distribution"]["available"])
        self.assertEqual(out["snapshot_distribution"]["actions"], [])
        self.assertIn("different scan", out["snapshot_distribution"]["note"])


class TestRiskInterventions(unittest.TestCase):
    def test_approved_blocked_and_reasons(self):
        events = [
            ev("RISK_APPROVED", "A", _id=1), ev("RISK_APPROVED", "B", _id=2),
            ev("RISK_REJECTED", "C",
               payload={"failed_gates": {"min_rr": {}}}, _id=3),
            ev("PRECHECK_REJECTED", "D",
               payload={"reasons": ["MAX_POSITIONS"]}, _id=4),
        ]
        out = opan._risk_interventions(events)
        risk = out["risk"]
        self.assertEqual((risk["candidates"], risk["approved"], risk["blocked"]),
                         (3, 2, 1))
        self.assertAlmostEqual(risk["block_rate_pct"], 33.3)
        self.assertEqual(risk["reasons"][0]["reason_code"], "min_rr")
        pre = out["portfolio_precheck"]
        self.assertEqual((pre["candidates"], pre["approved"], pre["blocked"]),
                         (1, 0, 1))
        self.assertEqual(pre["reasons"][0]["reason_code"], "MAX_POSITIONS")

    def test_no_events_marks_no_evidence_never_fabricates(self):
        out = opan._risk_interventions([])
        self.assertEqual(out["risk"]["evidence"], "VERIFIED_EMPTY")
        unavailable = opan._risk_interventions(
            [], {"available": False, "error": "boom", "truncated": False})
        self.assertEqual(unavailable["risk"]["evidence"], "SOURCE_UNAVAILABLE")
        self.assertIsNone(out["risk"]["block_rate_pct"])


class TestStageTiming(unittest.TestCase):
    def _seq(self, symbol, times_stages):
        out = []
        for i, (ts, stage) in enumerate(times_stages):
            out.append(ev("SYMBOL_PROCESSED", symbol, stage=stage,
                          ts=ts, _id=i + 1))
        return out

    def test_insufficient_samples_flagged_never_inferred(self):
        events = self._seq("A", [("2026-08-09T04:00:00+00:00", "SCANNER"),
                                 ("2026-08-09T04:00:01+00:00", "RESEARCH")])
        out = opan._stage_timing(events)
        self.assertTrue(out["RESEARCH"]["insufficient_telemetry"])
        self.assertEqual(out["RESEARCH"]["samples"], 1)
        self.assertNotIn("avg_ms", out["RESEARCH"])

    def test_avg_median_p95_computed_with_enough_samples(self):
        events = []
        base = "2026-08-09T04:00:0{}+00:00"
        for i, sym in enumerate(["A", "B", "C", "D"]):
            events += self._seq(sym, [
                (base.format(0), "SCANNER"),
                (f"2026-08-09T04:00:0{i + 1}+00:00", "RESEARCH")])
        out = opan._stage_timing(events)
        r = out["RESEARCH"]
        self.assertFalse(r["insufficient_telemetry"])
        self.assertEqual(r["samples"], 4)
        # gaps: 1s,2s,3s,4s
        self.assertAlmostEqual(r["avg_ms"], 2500.0)
        self.assertAlmostEqual(r["median_ms"], 2500.0)
        self.assertAlmostEqual(r["p95_ms"], 4000.0)

    def test_unparseable_timestamps_are_skipped(self):
        events = self._seq("A", [("garbage", "SCANNER"),
                                 ("also-garbage", "RESEARCH")])
        self.assertEqual(opan._stage_timing(events), {})


class TestFunnel(unittest.TestCase):
    def test_conversion_pct_and_timing_overlay(self):
        replay = {"stages": [
            {"id": "market_data", "label": "Scanner", "order": 1,
             "stocks_in": 50, "stocks_out": 48, "rejected": 2, "pending": 0},
            {"id": "risk", "label": "Risk", "order": 2,
             "stocks_in": 0, "stocks_out": 0, "rejected": 0, "pending": 0},
        ]}
        out = opan._funnel(replay, [])
        s0, s1 = out["stages"]
        self.assertEqual(s0["conversion_pct"], 96.0)
        self.assertIsNone(s1["conversion_pct"])  # 0 in → no fabricated %
        self.assertTrue(s0["timing"]["insufficient_telemetry"])


class TestTrends(unittest.TestCase):
    def test_per_scan_points_bounded_and_current_marked(self):
        sessions = [{"scan_id": "scanA", "snapshot_ts": "t1"},
                    {"scan_id": "scanB", "snapshot_ts": "t2"}]
        events_by_scan = {
            "scanA": [ev("SYMBOL_REJECTED", "X", scan_id="scanA",
                         payload={"error": "no data"}),
                      ev("BUY_GENERATED", "Y", scan_id="scanA")],
            "scanB": [],
        }
        with patch.object(opan, "_scan_events",
                          side_effect=lambda sid, limit=1000:
                          (events_by_scan.get(sid, []),
                           {"available": True, "error": None,
                            "truncated": False, "limit": limit})):
            out = opan._trends("scanA", sessions)
        self.assertEqual(len(out["points"]), 2)
        p0 = out["points"][0]
        self.assertTrue(p0["is_current"])
        self.assertEqual(p0["rejected_events"], 1)
        self.assertEqual(p0["decisions"], {"BUY": 1})
        self.assertEqual(out["points"][1]["rejected_events"], 0)
        self.assertEqual(out["points"][1]["evidence"], "VERIFIED_EMPTY")


class TestReportEndToEnd(unittest.TestCase):
    def test_full_report_hermetic(self):
        replay = {"scan_id": "scanA", "stages": [
            {"id": "market_data", "label": "Scanner", "order": 1,
             "stocks_in": 2, "stocks_out": 2, "rejected": 0, "pending": 0}]}
        events = [ev("RISK_APPROVED", "A", scan_id="scanA"),
                  ev("BUY_GENERATED", "A", scan_id="scanA", _id=2)]
        rows = [{"final_action": "BUY", "sector": "IT"}]
        ok_state = {"available": True, "error": None,
                    "truncated": False, "limit": 2000}
        with patch.object(opan, "_replay", return_value=replay), \
             patch.object(opan, "_scan_events",
                          return_value=(events, ok_state)), \
             patch.object(opan, "_snapshot_rows",
                          return_value=(rows, "scanA", "2026-08-09T04:00:00",
                                        {"available": True, "error": None})), \
             patch.object(opan, "_sessions", return_value=(
                 [{"scan_id": "scanA", "snapshot_ts": "t"}],
                 {"available": True, "error": None, "demo_excluded": 0})):
            out = opan.operator_analytics_report()
        self.assertTrue(out["ok"])
        self.assertTrue(out["advisory_only"] and out["read_only"])
        self.assertEqual(out["scan_id"], "scanA")
        self.assertEqual(out["event_count"], 2)
        self.assertEqual(out["risk_interventions"]["risk"]["approved"], 1)
        self.assertTrue(out["decisions"]["snapshot_distribution"]["available"])
        self.assertEqual(len(out["funnel"]["stages"]), 1)

    def test_report_survives_replay_failure(self):
        with patch.object(opan, "_replay", side_effect=RuntimeError("boom")), \
             patch.object(opan, "_scan_events", return_value=(
                 [], {"available": False, "error": "no events",
                      "truncated": False, "limit": 2000})), \
             patch.object(opan, "_snapshot_rows",
                          return_value=([], "scanA", None,
                                        {"available": True, "error": None})), \
             patch.object(opan, "_sessions", return_value=(
                 [], {"available": True, "error": None, "demo_excluded": 0})):
            out = opan.operator_analytics_report()
        self.assertTrue(out["ok"])
        # replay failure is surfaced, never hidden as empty data
        self.assertFalse(out["sources"]["replay"]["available"])
        self.assertIn("boom", out["sources"]["replay"]["error"])
        self.assertFalse(out["sources"]["pipeline_events"]["available"])
        self.assertEqual(out["funnel"]["stages"], [])
        self.assertEqual(out["rejections"]["rejected_events"], 0)
        self.assertEqual(out["rejections"]["evidence"], "SOURCE_UNAVAILABLE")

    def test_deterministic_for_same_inputs(self):
        events = [ev("SYMBOL_REJECTED", "B", payload={"error": "x"}, _id=1),
                  ev("SYMBOL_REJECTED", "A", payload={"error": "x"}, _id=2)]
        a = opan._aggregate_rejections(events)
        b = opan._aggregate_rejections(list(reversed(events)))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
