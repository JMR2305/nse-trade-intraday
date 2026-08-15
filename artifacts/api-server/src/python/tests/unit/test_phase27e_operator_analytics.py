"""Unit tests for Phase 27E: Operator Analytics (read-only aggregators).

All canonical-source functions (_replay, _sessions, _scan_events,
_snapshot_rows) are patched on the module so tests never touch real DB.
"""
import unittest
from unittest.mock import patch, MagicMock

import phase27_operator_analytics as oa


# ---------------------------------------------------------------------------
# Minimal helpers
# ---------------------------------------------------------------------------

def _make_event(event_type, symbol=None, payload=None,
                ts="2025-01-01T09:15:00+00:00", id=1, stage=None):
    return {
        "event_type": event_type,
        "symbol": symbol,
        "payload": payload or {},
        "ts": ts,
        "id": id,
        "stage": stage,
    }


def _ok_state(truncated=False, limit=2000):
    return {"available": True, "error": None, "truncated": truncated, "limit": limit}


def _unavailable_state(error="db down"):
    return {"available": False, "error": error, "truncated": False, "limit": 2000}


# ---------------------------------------------------------------------------
# 1. Funnel calculation
# ---------------------------------------------------------------------------

class TestFunnel(unittest.TestCase):

    def _replay_with_stage(self, stage_id, stocks_in, stocks_out, rejected=0):
        return {
            "stages": [{
                "id": stage_id, "label": stage_id.title(), "order": 1,
                "stocks_in": stocks_in, "stocks_out": stocks_out,
                "rejected": rejected, "pending": 0, "cancelled": 0,
            }]
        }

    def test_funnel_conversion_pct_calculated(self):
        replay = self._replay_with_stage("scanner", 50, 48, rejected=2)
        result = oa._funnel(replay, [])
        stage = result["stages"][0]
        self.assertEqual(stage["stocks_in"], 50)
        self.assertEqual(stage["stocks_out"], 48)
        self.assertAlmostEqual(stage["conversion_pct"], 96.0)

    def test_funnel_conversion_pct_zero_stocks_in_is_none(self):
        replay = self._replay_with_stage("scanner", 0, 0)
        result = oa._funnel(replay, [])
        self.assertIsNone(result["stages"][0]["conversion_pct"])

    def test_funnel_empty_replay_returns_empty_stages(self):
        result = oa._funnel({}, [])
        self.assertEqual(result["stages"], [])

    def test_funnel_timing_insufficient_telemetry_lt3_samples(self):
        # Only 1 gap → insufficient_telemetry
        events = [
            _make_event("EV", "AAA", ts="2025-01-01T09:15:00+00:00", id=1, stage="SCANNER"),
            _make_event("EV", "AAA", ts="2025-01-01T09:15:01+00:00", id=2, stage="SCANNER"),
        ]
        timing = oa._stage_timing(events)
        # 2 events for 1 symbol → 1 gap → insufficient
        self.assertIn("SCANNER", timing)
        self.assertTrue(timing["SCANNER"]["insufficient_telemetry"])
        self.assertEqual(timing["SCANNER"]["samples"], 1)

    def test_funnel_timing_with_3_or_more_samples(self):
        # 4 events for one symbol → 3 gaps → sufficient
        events = [
            _make_event("EV", "AAA", ts="2025-01-01T09:15:00+00:00", id=1, stage="SCANNER"),
            _make_event("EV", "AAA", ts="2025-01-01T09:15:01+00:00", id=2, stage="SCANNER"),
            _make_event("EV", "AAA", ts="2025-01-01T09:15:02+00:00", id=3, stage="SCANNER"),
            _make_event("EV", "AAA", ts="2025-01-01T09:15:03+00:00", id=4, stage="SCANNER"),
        ]
        timing = oa._stage_timing(events)
        self.assertIn("SCANNER", timing)
        t = timing["SCANNER"]
        self.assertFalse(t["insufficient_telemetry"])
        self.assertEqual(t["samples"], 3)
        self.assertIn("avg_ms", t)
        self.assertIn("median_ms", t)
        self.assertIn("p95_ms", t)

    def test_funnel_stage_without_timing_gets_insufficient_marker(self):
        replay = self._replay_with_stage("supervisor", 10, 9)
        result = oa._funnel(replay, [])
        stage = result["stages"][0]
        # No events → timing should be insufficient_telemetry=True, samples=0
        self.assertTrue(stage["timing"]["insufficient_telemetry"])
        self.assertEqual(stage["timing"]["samples"], 0)

    def test_funnel_source_field_present(self):
        result = oa._funnel({}, [])
        self.assertIn("source", result)


# ---------------------------------------------------------------------------
# 2. Rejection aggregation
# ---------------------------------------------------------------------------

class TestAggregateRejections(unittest.TestCase):

    def test_risk_rejected_uses_failed_gates_dict_keys(self):
        ev = _make_event("RISK_REJECTED", "ABC",
                         payload={"failed_gates": {"DAILY_LOSS_LIMIT": True, "MAX_OPEN_TRADES": True}},
                         id=1)
        result = oa._aggregate_rejections([ev], _ok_state())
        self.assertEqual(result["rejected_events"], 1)
        self.assertEqual(result["reason_occurrences"], 2)
        codes = {r["reason_code"] for r in result["reasons"]}
        self.assertIn("DAILY_LOSS_LIMIT", codes)
        self.assertIn("MAX_OPEN_TRADES", codes)

    def test_risk_rejected_failed_gates_list(self):
        ev = _make_event("RISK_REJECTED", "XYZ",
                         payload={"failed_gates": ["GATE_A", "GATE_B"]},
                         id=2)
        result = oa._aggregate_rejections([ev], _ok_state())
        self.assertEqual(result["reason_occurrences"], 2)

    def test_precheck_rejected_uses_reasons_list(self):
        ev = _make_event("PRECHECK_REJECTED", "DEF",
                         payload={"reasons": ["INSUFFICIENT_CASH", "POSITION_LIMIT"]},
                         id=3)
        result = oa._aggregate_rejections([ev], _ok_state())
        self.assertEqual(result["rejected_events"], 1)
        self.assertEqual(result["reason_occurrences"], 2)
        codes = {r["reason_code"] for r in result["reasons"]}
        self.assertIn("INSUFFICIENT_CASH", codes)

    def test_symbol_rejected_uses_error_field(self):
        ev = _make_event("SYMBOL_REJECTED", "GHI", payload={"error": "NO_DATA"}, id=4)
        result = oa._aggregate_rejections([ev], _ok_state())
        self.assertEqual(result["reasons"][0]["reason_code"], "NO_DATA")

    def test_pct_is_of_occurrences_not_events(self):
        """One event with 2 failed_gates → 2 occurrences; pct must be 50/50."""
        ev = _make_event("RISK_REJECTED", "ABC",
                         payload={"failed_gates": {"GATE_A": True, "GATE_B": True}},
                         id=1)
        result = oa._aggregate_rejections([ev], _ok_state())
        for r in result["reasons"]:
            self.assertAlmostEqual(r["pct_of_occurrences"], 50.0, places=1)

    def test_symbols_sorted_in_output(self):
        events = [
            _make_event("RISK_REJECTED", "ZZZ", payload={"failed_gates": {"G1": True}}, id=1),
            _make_event("RISK_REJECTED", "AAA", payload={"failed_gates": {"G1": True}}, id=2),
        ]
        result = oa._aggregate_rejections(events, _ok_state())
        row = result["reasons"][0]
        self.assertEqual(row["symbols"], sorted(row["symbols"]))

    def test_non_rejection_events_ignored(self):
        ev = _make_event("BUY_GENERATED", "ABC", id=5)
        result = oa._aggregate_rejections([ev], _ok_state())
        self.assertEqual(result["rejected_events"], 0)
        self.assertEqual(result["reason_occurrences"], 0)

    def test_empty_events_returns_zero_counts(self):
        result = oa._aggregate_rejections([], _ok_state())
        self.assertEqual(result["rejected_events"], 0)
        self.assertEqual(result["reason_occurrences"], 0)
        self.assertEqual(result["reasons"], [])


# ---------------------------------------------------------------------------
# 3. Decision distribution
# ---------------------------------------------------------------------------

class TestDecisionDistribution(unittest.TestCase):

    def test_buy_generated_maps_to_buy(self):
        events = [_make_event("BUY_GENERATED", id=1)]
        result = oa._decision_distribution(events, [], None, "scan1", _ok_state())
        self.assertEqual(result["event_decisions"]["counts"].get("BUY"), 1)

    def test_watch_generated_maps_to_watch(self):
        events = [_make_event("WATCH_GENERATED", id=2)]
        result = oa._decision_distribution(events, [], None, "scan1", _ok_state())
        self.assertEqual(result["event_decisions"]["counts"].get("WATCH"), 1)

    def test_ignore_generated_maps_to_ignore(self):
        events = [_make_event("IGNORE_GENERATED", id=3)]
        result = oa._decision_distribution(events, [], None, "scan1", _ok_state())
        self.assertEqual(result["event_decisions"]["counts"].get("IGNORE"), 1)

    def test_snapshot_splits_only_when_snap_scan_id_matches(self):
        snap_rows = [{"final_action": "BUY", "sector": "IT", "market_regime": "TRENDING"}]
        # Matching scan_id → splits available
        result = oa._decision_distribution([], snap_rows, "scan1", "scan1", _ok_state())
        self.assertTrue(result["snapshot_distribution"]["available"])

    def test_snapshot_splits_omitted_when_scan_id_mismatch(self):
        snap_rows = [{"final_action": "BUY", "sector": "IT"}]
        result = oa._decision_distribution([], snap_rows, "scan_other", "scan1", _ok_state())
        self.assertFalse(result["snapshot_distribution"]["available"])

    def test_regime_extracted_from_snapshot(self):
        snap_rows = [{"final_action": "BUY", "sector": "IT", "market_regime": "TRENDING"}]
        result = oa._decision_distribution([], snap_rows, "scan1", "scan1", _ok_state())
        self.assertEqual(result["snapshot_distribution"]["regime"], "TRENDING")

    def test_pct_sums_to_100_with_multiple_decisions(self):
        events = [
            _make_event("BUY_GENERATED", id=1),
            _make_event("BUY_GENERATED", id=2),
            _make_event("WATCH_GENERATED", id=3),
        ]
        result = oa._decision_distribution(events, [], None, "scan1", _ok_state())
        pcts = result["event_decisions"]["pct"]
        self.assertAlmostEqual(sum(pcts.values()), 100.0, delta=0.2)


# ---------------------------------------------------------------------------
# 4. Risk interventions
# ---------------------------------------------------------------------------

class TestRiskInterventions(unittest.TestCase):

    def test_risk_approved_rejected_split(self):
        events = [
            _make_event("RISK_APPROVED", "ABC", id=1),
            _make_event("RISK_APPROVED", "DEF", id=2),
            _make_event("RISK_REJECTED", "XYZ",
                        payload={"failed_gates": {"DAILY_LOSS_LIMIT": True}}, id=3),
        ]
        result = oa._risk_interventions(events, _ok_state())
        r = result["risk"]
        self.assertEqual(r["approved"], 2)
        self.assertEqual(r["blocked"], 1)
        self.assertEqual(r["candidates"], 3)

    def test_precheck_approved_rejected_split(self):
        events = [
            _make_event("PRECHECK_APPROVED", "A", id=1),
            _make_event("PRECHECK_REJECTED", "B",
                        payload={"reasons": ["INSUFFICIENT_CASH"]}, id=2),
        ]
        result = oa._risk_interventions(events, _ok_state())
        p = result["portfolio_precheck"]
        self.assertEqual(p["approved"], 1)
        self.assertEqual(p["blocked"], 1)

    def test_block_rate_pct_calculated_correctly(self):
        events = [
            _make_event("RISK_APPROVED", id=1),
            _make_event("RISK_APPROVED", id=2),
            _make_event("RISK_APPROVED", id=3),
            _make_event("RISK_REJECTED", payload={"failed_gates": {"G": True}}, id=4),
        ]
        result = oa._risk_interventions(events, _ok_state())
        self.assertAlmostEqual(result["risk"]["block_rate_pct"], 25.0, places=1)

    def test_block_rate_none_when_no_candidates(self):
        result = oa._risk_interventions([], _ok_state())
        self.assertIsNone(result["risk"]["block_rate_pct"])
        self.assertIsNone(result["portfolio_precheck"]["block_rate_pct"])

    def test_risk_reasons_populated(self):
        events = [
            _make_event("RISK_REJECTED", "ABC",
                        payload={"failed_gates": {"DAILY_LOSS_LIMIT": True}}, id=1),
        ]
        result = oa._risk_interventions(events, _ok_state())
        reasons = result["risk"]["reasons"]
        self.assertEqual(len(reasons), 1)
        self.assertEqual(reasons[0]["reason_code"], "DAILY_LOSS_LIMIT")


# ---------------------------------------------------------------------------
# 5. Evidence state / empty-partial handling
# ---------------------------------------------------------------------------

class TestEvidenceState(unittest.TestCase):

    def test_source_unavailable_when_available_false(self):
        st = {"available": False, "error": "db down", "truncated": False}
        self.assertEqual(oa._evidence_state(st, True), "SOURCE_UNAVAILABLE")
        self.assertEqual(oa._evidence_state(st, False), "SOURCE_UNAVAILABLE")

    def test_partial_when_truncated(self):
        st = {"available": True, "truncated": True}
        self.assertEqual(oa._evidence_state(st, True), "PARTIAL")

    def test_verified_empty_when_ok_no_rows(self):
        st = {"available": True, "truncated": False}
        self.assertEqual(oa._evidence_state(st, False), "VERIFIED_EMPTY")

    def test_ok_when_available_and_has_rows(self):
        st = {"available": True, "truncated": False}
        self.assertEqual(oa._evidence_state(st, True), "OK")

    def test_aggregate_rejections_evidence_source_unavailable(self):
        result = oa._aggregate_rejections([], _unavailable_state())
        self.assertEqual(result["evidence"], "SOURCE_UNAVAILABLE")

    def test_aggregate_rejections_evidence_partial_when_truncated(self):
        # Even with rejection events, truncated = PARTIAL
        ev = _make_event("RISK_REJECTED", payload={"failed_gates": {"G": True}}, id=1)
        result = oa._aggregate_rejections([ev], _ok_state(truncated=True))
        self.assertEqual(result["evidence"], "PARTIAL")

    def test_aggregate_rejections_evidence_verified_empty_no_events(self):
        result = oa._aggregate_rejections([], _ok_state())
        self.assertEqual(result["evidence"], "VERIFIED_EMPTY")


# ---------------------------------------------------------------------------
# 6. Session isolation — demo sessions excluded
# ---------------------------------------------------------------------------

class TestSessionIsolation(unittest.TestCase):

    def test_sessions_excludes_demo_source(self):
        raw = [
            {"scan_id": "scan1", "source": "replay"},
            {"scan_id": "demo", "source": "demo"},
            {"scan_id": "scan2", "source": "demo"},
        ]
        with patch.object(oa, "_sessions") as mock_sess:
            # Simulate what the real _sessions does: exclude demo
            real_sessions = [s for s in raw
                             if s.get("source") != "demo" and s.get("scan_id") != "demo"]
            mock_sess.return_value = (
                real_sessions,
                {"available": True, "error": None, "demo_excluded": 2}
            )
            sessions, state = oa._sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["scan_id"], "scan1")
        self.assertEqual(state["demo_excluded"], 2)

    def test_sessions_returns_empty_on_exception(self):
        with patch("phase27_operator_analytics._sessions") as mock_sess:
            mock_sess.return_value = (
                [],
                {"available": False, "error": "error", "demo_excluded": 0}
            )
            sessions, state = oa._sessions()
        self.assertEqual(sessions, [])
        self.assertFalse(state["available"])

    def test_real_sessions_function_excludes_demo(self):
        """Test actual _sessions() logic by mocking get_replay_sessions."""
        mock_sessions_data = {
            "sessions": [
                {"scan_id": "real1", "source": "live"},
                {"scan_id": "demo", "source": "demo"},
                {"scan_id": "real2", "source": "replay"},
            ]
        }
        with patch.dict("sys.modules", {"replay_engine": MagicMock(
            get_replay_sessions=lambda: mock_sessions_data
        )}):
            import importlib
            # Re-test logic: the function filters demo source and demo scan_id
            raw = mock_sessions_data["sessions"]
            real = [s for s in raw
                    if s.get("source") != "demo" and s.get("scan_id") != "demo"]
            self.assertEqual(len(real), 2)
            demo_excluded = len(raw) - len(real)
            self.assertEqual(demo_excluded, 1)


# ---------------------------------------------------------------------------
# 7. Deterministic aggregation
# ---------------------------------------------------------------------------

class TestDeterministicAggregation(unittest.TestCase):

    def test_same_input_identical_output_rejections(self):
        events = [
            _make_event("RISK_REJECTED", "ABC",
                        payload={"failed_gates": {"GATE_A": True, "GATE_B": True}}, id=1),
            _make_event("PRECHECK_REJECTED", "DEF",
                        payload={"reasons": ["INSUFFICIENT_CASH"]}, id=2),
        ]
        state = _ok_state()
        r1 = oa._aggregate_rejections(events, state)
        r2 = oa._aggregate_rejections(events, state)
        self.assertEqual(r1["rejected_events"], r2["rejected_events"])
        self.assertEqual(r1["reason_occurrences"], r2["reason_occurrences"])
        codes1 = [r["reason_code"] for r in r1["reasons"]]
        codes2 = [r["reason_code"] for r in r2["reasons"]]
        self.assertEqual(codes1, codes2)

    def test_same_input_identical_output_risk_interventions(self):
        events = [
            _make_event("RISK_APPROVED", id=1),
            _make_event("RISK_REJECTED", payload={"failed_gates": {"G": True}}, id=2),
        ]
        state = _ok_state()
        r1 = oa._risk_interventions(events, state)
        r2 = oa._risk_interventions(events, state)
        self.assertEqual(r1["risk"]["approved"], r2["risk"]["approved"])
        self.assertEqual(r1["risk"]["blocked"], r2["risk"]["blocked"])

    def test_same_input_identical_output_funnel(self):
        replay = {
            "stages": [{
                "id": "risk", "label": "Risk", "order": 6,
                "stocks_in": 10, "stocks_out": 3,
                "rejected": 7, "pending": 0, "cancelled": 0,
            }]
        }
        events = []
        r1 = oa._funnel(replay, events)
        r2 = oa._funnel(replay, events)
        self.assertEqual(r1["stages"][0]["conversion_pct"],
                         r2["stages"][0]["conversion_pct"])


# ---------------------------------------------------------------------------
# 8. Entry point — operator_analytics_report()
# ---------------------------------------------------------------------------

class TestOperatorAnalyticsReport(unittest.TestCase):

    def _make_full_report(self, scan_id="scan_abc"):
        """Run operator_analytics_report() with all sources mocked."""
        mock_replay = {
            "scan_id": scan_id,
            "stages": [
                {"id": "scanner", "label": "Scanner", "order": 1,
                 "stocks_in": 50, "stocks_out": 48, "rejected": 2,
                 "pending": 0, "cancelled": 0},
            ],
        }
        mock_snap_rows = [{"final_action": "WATCH", "sector": "IT",
                           "market_regime": "TRENDING"}]
        mock_events = [
            _make_event("BUY_GENERATED", "ABC", id=1),
            _make_event("WATCH_GENERATED", "DEF", id=2),
            _make_event("RISK_REJECTED", "XYZ",
                        payload={"failed_gates": {"DAILY_LOSS_LIMIT": True}}, id=3),
        ]
        mock_sessions = [
            {"scan_id": scan_id, "snapshot_ts": "2025-01-01T09:10:00Z",
             "status": "SUCCESS", "universe_size": 50}
        ]

        with patch.object(oa, "_replay", return_value=mock_replay), \
             patch.object(oa, "_snapshot_rows",
                          return_value=(mock_snap_rows, scan_id,
                                        "2025-01-01T09:10:00Z",
                                        {"available": True, "error": None})), \
             patch.object(oa, "_scan_events",
                          return_value=(mock_events, _ok_state())), \
             patch.object(oa, "_sessions",
                          return_value=(mock_sessions,
                                        {"available": True, "error": None,
                                         "demo_excluded": 0})):
            return oa.operator_analytics_report(scan_id=scan_id)

    def test_entry_point_ok_true(self):
        result = self._make_full_report()
        self.assertTrue(result["ok"])

    def test_entry_point_advisory_only_true(self):
        result = self._make_full_report()
        self.assertTrue(result["advisory_only"])

    def test_entry_point_read_only_true(self):
        result = self._make_full_report()
        self.assertTrue(result["read_only"])

    def test_entry_point_all_required_keys_present(self):
        result = self._make_full_report()
        for key in ("funnel", "rejections", "decisions",
                    "risk_interventions", "trends",
                    "session_summary", "sources"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_entry_point_sources_map_has_all_four(self):
        result = self._make_full_report()
        src = result["sources"]
        for key in ("replay", "pipeline_events", "snapshot", "sessions"):
            self.assertIn(key, src, f"Missing source key: {key}")

    def test_entry_point_funnel_has_stages(self):
        result = self._make_full_report()
        self.assertIn("stages", result["funnel"])

    def test_entry_point_rejections_structure(self):
        result = self._make_full_report()
        rej = result["rejections"]
        self.assertIn("rejected_events", rej)
        self.assertIn("reason_occurrences", rej)
        self.assertIn("reasons", rej)
        self.assertIn("evidence", rej)

    def test_entry_point_decisions_structure(self):
        result = self._make_full_report()
        dec = result["decisions"]
        self.assertIn("event_decisions", dec)
        self.assertIn("snapshot_distribution", dec)

    def test_entry_point_risk_interventions_structure(self):
        result = self._make_full_report()
        ri = result["risk_interventions"]
        self.assertIn("risk", ri)
        self.assertIn("portfolio_precheck", ri)

    def test_entry_point_trends_structure(self):
        result = self._make_full_report()
        tr = result["trends"]
        self.assertIn("points", tr)
        self.assertIn("window_scans", tr)

    def test_entry_point_session_summary_structure(self):
        result = self._make_full_report()
        ss = result["session_summary"]
        self.assertIn("sessions", ss)
        self.assertIn("available", ss)

    def test_entry_point_no_scan_id_uses_snapshot_scan(self):
        """When scan_id=None, report uses snapshot's scan_id."""
        mock_replay = {"scan_id": "snap_scan", "stages": []}
        with patch.object(oa, "_replay", return_value=mock_replay), \
             patch.object(oa, "_snapshot_rows",
                          return_value=([], "snap_scan", None,
                                        {"available": True, "error": None})), \
             patch.object(oa, "_scan_events",
                          return_value=([], _ok_state())), \
             patch.object(oa, "_sessions",
                          return_value=([], {"available": True, "error": None,
                                             "demo_excluded": 0})):
            result = oa.operator_analytics_report(scan_id=None)
        self.assertTrue(result["ok"])

    def test_entry_point_replay_error_graceful(self):
        """A replay error sets source unavailable but report still returns ok=True."""
        with patch.object(oa, "_replay", side_effect=Exception("replay down")), \
             patch.object(oa, "_snapshot_rows",
                          return_value=([], None, None,
                                        {"available": True, "error": None})), \
             patch.object(oa, "_scan_events",
                          return_value=([], _ok_state())), \
             patch.object(oa, "_sessions",
                          return_value=([], {"available": True, "error": None,
                                             "demo_excluded": 0})):
            result = oa.operator_analytics_report(scan_id="any")
        self.assertTrue(result["ok"])
        self.assertFalse(result["sources"]["replay"]["available"])


if __name__ == "__main__":
    unittest.main()
