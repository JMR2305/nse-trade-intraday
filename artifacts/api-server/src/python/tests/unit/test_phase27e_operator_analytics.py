"""Unit tests for Phase 27E Operator Analytics (read-only aggregators).

Covers: funnel calculation, rejection aggregation (events vs occurrences),
decision distribution (events + snapshot splits), risk interventions,
evidence states (SOURCE_UNAVAILABLE / PARTIAL / VERIFIED_EMPTY / OK),
demo-session exclusion, deterministic aggregation, and the
operator_analytics_report() entry point contract.
"""
import copy
import sys
import types
import unittest
from unittest.mock import patch

import phase27_operator_analytics as oa


def _ev(event_type, symbol=None, payload=None, ts=None, eid=None, stage=None):
    return {"event_type": event_type, "symbol": symbol,
            "payload": payload or {}, "ts": ts, "id": eid, "stage": stage}


OK_STATE = {"available": True, "error": None, "truncated": False, "limit": 2000}
TRUNC_STATE = {"available": True, "error": None, "truncated": True, "limit": 2000}
DOWN_STATE = {"available": False, "error": "db down", "truncated": False,
              "limit": 2000}


REJECTION_EVENTS = [
    _ev("RISK_REJECTED", "AAA",
        {"failed_gates": {"max_positions": True, "max_exposure": True}}, eid=1),
    _ev("RISK_REJECTED", "BBB", {"failed_gates": ["max_positions"]}, eid=2),
    _ev("PRECHECK_REJECTED", "CCC", {"reasons": ["insufficient_cash"]}, eid=3),
    _ev("SYMBOL_REJECTED", "DDD", {"error": "no candles"}, eid=4),
    _ev("BUY_GENERATED", "EEE", eid=5),  # not a rejection
]


class TestAggregateRejections(unittest.TestCase):
    def test_events_vs_occurrences_distinction(self):
        d = oa._aggregate_rejections(list(REJECTION_EVENTS), OK_STATE)
        # 4 rejected events; the first carries TWO failed gates → 5 occurrences
        self.assertEqual(d["rejected_events"], 4)
        self.assertEqual(d["reason_occurrences"], 5)
        by = {(r["event_type"], r["reason_code"]): r for r in d["reasons"]}
        self.assertEqual(by[("RISK_REJECTED", "max_positions")]["count"], 2)
        self.assertEqual(by[("RISK_REJECTED", "max_exposure")]["count"], 1)
        self.assertEqual(by[("PRECHECK_REJECTED", "insufficient_cash")]["count"], 1)
        self.assertEqual(by[("SYMBOL_REJECTED", "no candles")]["count"], 1)

    def test_pct_is_share_of_occurrences_not_events(self):
        d = oa._aggregate_rejections(list(REJECTION_EVENTS), OK_STATE)
        row = next(r for r in d["reasons"]
                   if r["reason_code"] == "max_positions")
        self.assertEqual(row["pct_of_occurrences"], round(2 / 5 * 100, 1))
        self.assertIn("share of", d["source"])

    def test_group_labels_and_symbols(self):
        d = oa._aggregate_rejections(list(REJECTION_EVENTS), OK_STATE)
        row = next(r for r in d["reasons"] if r["reason_code"] == "no candles")
        self.assertEqual(row["group"], "Scanner / market data")
        self.assertEqual(row["symbols"], ["DDD"])
        self.assertEqual(row["event_ids"], [4])

    def test_evidence_states(self):
        self.assertEqual(
            oa._aggregate_rejections(list(REJECTION_EVENTS), OK_STATE)["evidence"],
            "OK")
        self.assertEqual(
            oa._aggregate_rejections([], OK_STATE)["evidence"], "VERIFIED_EMPTY")
        self.assertEqual(
            oa._aggregate_rejections(list(REJECTION_EVENTS), TRUNC_STATE)["evidence"],
            "PARTIAL")
        self.assertEqual(
            oa._aggregate_rejections([], DOWN_STATE)["evidence"],
            "SOURCE_UNAVAILABLE")

    def test_deterministic_same_input_same_output(self):
        a = oa._aggregate_rejections(copy.deepcopy(REJECTION_EVENTS), OK_STATE)
        b = oa._aggregate_rejections(copy.deepcopy(REJECTION_EVENTS), OK_STATE)
        self.assertEqual(a, b)


class TestRejectionReasons(unittest.TestCase):
    def test_precheck_blocking_limit_fallback(self):
        ev = _ev("PRECHECK_REJECTED", "AAA", {"blocking_limit": "max_daily_loss"})
        self.assertEqual(oa._rejection_reasons(ev), ["max_daily_loss"])

    def test_unknown_payload_falls_back_to_event_type(self):
        ev = _ev("ORDER_REJECTED", "AAA", {})
        self.assertEqual(oa._rejection_reasons(ev), ["ORDER_REJECTED"])


class TestDecisionDistribution(unittest.TestCase):
    EVENTS = [_ev("BUY_GENERATED"), _ev("BUY_GENERATED"),
              _ev("WATCH_GENERATED"), _ev("IGNORE_GENERATED"),
              _ev("RISK_REJECTED")]
    SNAP = [
        {"final_action": "STRONG BUY", "sector": "IT", "market_regime": "TRENDING"},
        {"final_action": "BUY", "sector": "IT"},
        {"final_action": "IGNORE", "sector": "AUTO"},
        {"final_action": "watch", "sector": None},
    ]

    def test_event_counts_and_pct(self):
        d = oa._decision_distribution(self.EVENTS, [], None, "s1", OK_STATE)
        ev = d["event_decisions"]
        self.assertEqual(ev["counts"], {"BUY": 2, "WATCH": 1, "IGNORE": 1})
        self.assertEqual(ev["total"], 4)
        self.assertEqual(ev["pct"]["BUY"], 50.0)
        self.assertEqual(ev["evidence"], "OK")

    def test_snapshot_splits_when_scan_matches(self):
        d = oa._decision_distribution(self.EVENTS, self.SNAP, "s1", "s1", OK_STATE)
        snap = d["snapshot_distribution"]
        self.assertTrue(snap["available"])
        acts = {a["action"]: a for a in snap["actions"]}
        # actions normalised (upper, "_"→" ")
        self.assertIn("STRONG BUY", acts)
        self.assertIn("WATCH", acts)
        self.assertEqual(acts["STRONG BUY"]["count"], 1)
        self.assertEqual(acts["STRONG BUY"]["pct"], 25.0)
        sectors = {s["sector"]: s["actions"] for s in snap["by_sector"]}
        self.assertEqual(sectors["IT"]["STRONG BUY"], 1)
        self.assertIn("Unknown", sectors)
        self.assertEqual(snap["regime"], "TRENDING")

    def test_snapshot_splits_omitted_on_scan_mismatch(self):
        d = oa._decision_distribution(self.EVENTS, self.SNAP, "other", "s1",
                                      OK_STATE)
        snap = d["snapshot_distribution"]
        self.assertFalse(snap["available"])
        self.assertIn("different scan", snap["note"])
        self.assertEqual(snap["actions"], [])

    def test_empty_events_verified_empty(self):
        d = oa._decision_distribution([], [], None, "s1", OK_STATE)
        self.assertEqual(d["event_decisions"]["evidence"], "VERIFIED_EMPTY")
        self.assertEqual(d["event_decisions"]["pct"], {})

    def test_source_unavailable(self):
        d = oa._decision_distribution([], [], None, "s1", DOWN_STATE)
        self.assertEqual(d["event_decisions"]["evidence"], "SOURCE_UNAVAILABLE")


class TestRiskInterventions(unittest.TestCase):
    EVENTS = [
        _ev("RISK_APPROVED", "AAA"), _ev("RISK_APPROVED", "BBB"),
        _ev("RISK_REJECTED", "CCC", {"failed_gates": {"max_exposure": 1}}, eid=9),
        _ev("PRECHECK_APPROVED", "AAA"),
        _ev("PRECHECK_REJECTED", "DDD", {"reasons": ["insufficient_cash",
                                                     "max_positions"]}, eid=10),
    ]

    def test_risk_and_precheck_aggregation(self):
        d = oa._risk_interventions(self.EVENTS, OK_STATE)
        risk = d["risk"]
        self.assertEqual(risk["candidates"], 3)
        self.assertEqual(risk["approved"], 2)
        self.assertEqual(risk["blocked"], 1)
        self.assertEqual(risk["block_rate_pct"], 33.3)
        self.assertEqual(risk["reasons"][0]["reason_code"], "max_exposure")
        self.assertEqual(risk["reasons"][0]["symbols"], ["CCC"])
        pre = d["portfolio_precheck"]
        self.assertEqual(pre["candidates"], 2)
        self.assertEqual(pre["blocked"], 1)
        codes = {r["reason_code"] for r in pre["reasons"]}
        self.assertEqual(codes, {"insufficient_cash", "max_positions"})
        self.assertEqual(risk["evidence"], "OK")

    def test_no_candidates_block_rate_none_verified_empty(self):
        d = oa._risk_interventions([], OK_STATE)
        for key in ("risk", "portfolio_precheck"):
            self.assertEqual(d[key]["candidates"], 0)
            self.assertIsNone(d[key]["block_rate_pct"])
            self.assertEqual(d[key]["evidence"], "VERIFIED_EMPTY")

    def test_source_unavailable_propagates(self):
        d = oa._risk_interventions([], DOWN_STATE)
        self.assertEqual(d["risk"]["evidence"], "SOURCE_UNAVAILABLE")


class TestStageTiming(unittest.TestCase):
    def _events(self, n_gaps, stage="RISK"):
        evs = []
        for i in range(n_gaps + 1):
            evs.append(_ev("X", "AAA", ts=f"2026-08-14T10:00:{i:02d}+00:00",
                           eid=i, stage="SCANNER" if i == 0 else stage))
        return evs

    def test_insufficient_telemetry_below_min_samples(self):
        t = oa._stage_timing(self._events(oa.MIN_TIMING_SAMPLES - 1))
        self.assertTrue(t["RISK"]["insufficient_telemetry"])
        self.assertEqual(t["RISK"]["samples"], oa.MIN_TIMING_SAMPLES - 1)

    def test_stats_with_enough_samples(self):
        t = oa._stage_timing(self._events(4))["RISK"]
        self.assertFalse(t["insufficient_telemetry"])
        self.assertEqual(t["samples"], 4)
        self.assertEqual(t["avg_ms"], 1000.0)
        self.assertEqual(t["median_ms"], 1000.0)
        self.assertEqual(t["p95_ms"], 1000.0)

    def test_events_without_symbol_or_ts_ignored(self):
        self.assertEqual(oa._stage_timing([_ev("X"), _ev("X", "A")]), {})


class TestFunnel(unittest.TestCase):
    REPLAY = {"stages": [
        {"id": "market_data", "label": "Scanner", "order": 1,
         "stocks_in": 50, "stocks_out": 40, "rejected": 10, "pending": 0,
         "cancelled": 0},
        {"id": "risk", "label": "Risk", "order": 2,
         "stocks_in": 0, "stocks_out": 0, "rejected": 0, "pending": 0,
         "cancelled": 0},
    ]}

    def test_funnel_counts_and_conversion(self):
        d = oa._funnel(self.REPLAY, [])
        s0, s1 = d["stages"]
        self.assertEqual((s0["stocks_in"], s0["stocks_out"]), (50, 40))
        self.assertEqual(s0["conversion_pct"], 80.0)
        # zero-in stage: conversion is None, never a divide-by-zero
        self.assertIsNone(s1["conversion_pct"])
        self.assertTrue(s0["timing"]["insufficient_telemetry"])
        self.assertIn("replay snapshot", d["source"])

    def test_empty_replay_yields_empty_stages(self):
        self.assertEqual(oa._funnel({}, [])["stages"], [])

    def test_deterministic(self):
        self.assertEqual(oa._funnel(copy.deepcopy(self.REPLAY), []),
                         oa._funnel(copy.deepcopy(self.REPLAY), []))


class TestSessionsDemoExclusion(unittest.TestCase):
    def _with_fake_replay_engine(self, sessions):
        mod = types.ModuleType("replay_engine")
        mod.get_replay_sessions = lambda: {"sessions": sessions}
        return patch.dict(sys.modules, {"replay_engine": mod})

    def test_demo_sessions_excluded(self):
        raw = [{"scan_id": "s1", "source": "scan"},
               {"scan_id": "demo", "source": "scan"},
               {"scan_id": "s2", "source": "demo"}]
        with self._with_fake_replay_engine(raw):
            real, state = oa._sessions()
        self.assertEqual([s["scan_id"] for s in real], ["s1"])
        self.assertTrue(state["available"])
        self.assertEqual(state["demo_excluded"], 2)

    def test_sessions_failure_reports_unavailable(self):
        mod = types.ModuleType("replay_engine")
        def boom():
            raise RuntimeError("no db")
        mod.get_replay_sessions = boom
        with patch.dict(sys.modules, {"replay_engine": mod}):
            real, state = oa._sessions()
        self.assertEqual(real, [])
        self.assertFalse(state["available"])
        self.assertIn("no db", state["error"])


class TestTrends(unittest.TestCase):
    SESSIONS = [{"scan_id": "s3", "snapshot_ts": "2026-08-14T10:00:00Z"},
                {"scan_id": "s2", "snapshot_ts": "2026-08-13T10:00:00Z"}]

    def test_trend_points_scan_isolated(self):
        per_scan = {
            "s3": ([_ev("RISK_REJECTED", "AAA",
                        {"failed_gates": ["max_positions"]}),
                    _ev("BUY_GENERATED", "BBB")], dict(OK_STATE)),
            "s2": ([], dict(OK_STATE)),
        }
        with patch.object(oa, "_scan_events",
                          side_effect=lambda sid, limit=0: per_scan[sid]):
            d = oa._trends("s3", list(self.SESSIONS))
        self.assertEqual(len(d["points"]), 2)
        p3, p2 = d["points"]
        self.assertTrue(p3["is_current"])
        self.assertEqual(p3["rejected_events"], 1)
        self.assertEqual(p3["rejections_by_reason"], {"max_positions": 1})
        self.assertEqual(p3["decisions"], {"BUY": 1})
        self.assertEqual(p3["evidence"], "OK")
        # s2 events never leak into s3's point
        self.assertEqual(p2["rejected_events"], 0)
        self.assertEqual(p2["evidence"], "VERIFIED_EMPTY")
        self.assertIsNone(d["note"])

    def test_single_point_flags_insufficient_data(self):
        with patch.object(oa, "_scan_events",
                          return_value=([], dict(OK_STATE))):
            d = oa._trends("s3", self.SESSIONS[:1])
        self.assertEqual(d["note"], "INSUFFICIENT DATA")

    def test_window_bounded(self):
        many = [{"scan_id": f"s{i}"} for i in range(10)]
        with patch.object(oa, "_scan_events",
                          return_value=([], dict(OK_STATE))):
            d = oa._trends("s0", many)
        self.assertEqual(len(d["points"]), oa.TREND_SCAN_WINDOW)


class TestOperatorAnalyticsReport(unittest.TestCase):
    REPLAY = {"scan_id": "s1", "stages": [
        {"id": "market_data", "label": "Scanner", "order": 1,
         "stocks_in": 10, "stocks_out": 8, "rejected": 2, "pending": 0,
         "cancelled": 0}]}
    SNAP_ROWS = [{"final_action": "BUY", "sector": "IT"}]

    def _report(self, replay=None, events=None, events_state=None,
                snap=None, sessions_state=None):
        snap = snap or (self.SNAP_ROWS, "s1", "2026-08-14T10:00:00Z",
                        {"available": True, "error": None})
        with patch.object(oa, "_snapshot_rows", return_value=snap), \
             patch.object(oa, "_replay",
                          return_value=replay if replay is not None
                          else dict(self.REPLAY)), \
             patch.object(oa, "_scan_events",
                          return_value=(events or [],
                                        events_state or dict(OK_STATE))), \
             patch.object(oa, "_sessions",
                          return_value=([], sessions_state or
                                        {"available": True, "error": None,
                                         "demo_excluded": 0})):
            return oa.operator_analytics_report()

    def test_ok_true_with_all_required_keys(self):
        d = self._report(events=list(REJECTION_EVENTS))
        self.assertTrue(d["ok"])
        self.assertTrue(d["advisory_only"] and d["read_only"])
        for key in ("generated_at", "note", "scan_id", "snapshot_ts",
                    "event_count", "sources", "session_summary", "funnel",
                    "rejections", "decisions", "risk_interventions",
                    "trends", "performance_note"):
            self.assertIn(key, d)
        self.assertEqual(d["scan_id"], "s1")
        self.assertEqual(d["event_count"], len(REJECTION_EVENTS))
        for src in ("replay", "pipeline_events", "snapshot", "sessions"):
            self.assertIn(src, d["sources"])

    def test_snapshot_ts_nulled_on_scan_mismatch(self):
        snap = (self.SNAP_ROWS, "other", "2026-08-14T10:00:00Z",
                {"available": True, "error": None})
        d = self._report(snap=snap)
        self.assertIsNone(d["snapshot_ts"])
        self.assertFalse(d["decisions"]["snapshot_distribution"]["available"])

    def test_replay_error_reported_not_fatal(self):
        d = self._report(replay={"error": "no session"})
        self.assertTrue(d["ok"])
        self.assertFalse(d["sources"]["replay"]["available"])
        self.assertIn("no session", d["sources"]["replay"]["error"])
        self.assertEqual(d["funnel"]["stages"], [])

    def test_events_source_down_surfaces_unavailable(self):
        d = self._report(events_state=dict(DOWN_STATE))
        self.assertTrue(d["ok"])
        self.assertFalse(d["sources"]["pipeline_events"]["available"])
        self.assertEqual(d["rejections"]["evidence"], "SOURCE_UNAVAILABLE")
        self.assertEqual(
            d["risk_interventions"]["risk"]["evidence"], "SOURCE_UNAVAILABLE")

    def test_partial_fetch_flagged(self):
        d = self._report(events=list(REJECTION_EVENTS),
                         events_state=dict(TRUNC_STATE))
        self.assertEqual(d["rejections"]["evidence"], "PARTIAL")
        self.assertTrue(d["sources"]["pipeline_events"]["truncated"])


if __name__ == "__main__":
    unittest.main()
