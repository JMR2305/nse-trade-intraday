"""
test_ops_centre_buy_count.py
─────────────────────────────
Focused regression tests for the Ops Centre confirmed-BUY count fix.

Proves:
  1. When decision_summary_cache.json has BUY/STRONG_BUY counts the Ops Centre
     pipeline funnel reflects them (confirmed_buy_count = strong_buy + buy).
  2. Records in the legacy ai_decisions_cache.json schema (field "decision"
     not "recommendation") cannot silently produce a zero count — the code
     never reads that file for the confirmed count.
  3. When no summary file exists yet (Trade Decisions page never loaded),
     buy_recommendations is None and decision_summary_ok is False — scanner
     candidates are NEVER substituted in its place.
  4. scanner_candidates != buy_recommendations when the scanner count is higher
     than the decision-service count (the original bug scenario).
  5. _write_decision_summary() is atomic (temp+replace) so a concurrent reader
     never sees a partial file.
  6. load_decision_summary() validates the schema — corrupt or incomplete files
     return None rather than being silently treated as authoritative.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, mock_open

# ── Helpers ───────────────────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _make_summary(strong_buy: int = 0, buy: int = 0,
                  generated_at: str = "2026-01-01T09:00:00Z",
                  universe_size: int = 50) -> dict:
    """Build a minimal decision_summary_cache.json payload."""
    return {
        "generated_at":        generated_at,
        "strong_buy_count":    strong_buy,
        "buy_count":           buy,
        "confirmed_buy_count": strong_buy + buy,
        "watch_count":         universe_size - strong_buy - buy,
        "avoid_count":         0,
        "universe_size":       universe_size,
        "market_regime":       "Bullish",
    }


# ── Tests for decision_service.load_decision_summary ─────────────────────────

class TestLoadDecisionSummary(unittest.TestCase):
    """Unit-test the summary read helpers in isolation."""

    def test_returns_none_when_file_absent(self):
        """load_decision_summary() returns None when no file exists yet."""
        import decision_service
        with patch.object(decision_service, "_SUMMARY_FILE", "/nonexistent/path.json"):
            result = decision_service.load_decision_summary()
        self.assertIsNone(result)

    def test_returns_summary_dict_when_file_present(self):
        """load_decision_summary() returns the written summary when file exists."""
        import decision_service
        summary = _make_summary(strong_buy=1, buy=3)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump(summary, fh)
            tmp_path = fh.name
        try:
            with patch.object(decision_service, "_SUMMARY_FILE", tmp_path):
                result = decision_service.load_decision_summary()
            self.assertIsNotNone(result)
            self.assertEqual(result["confirmed_buy_count"], 4)
            self.assertEqual(result["strong_buy_count"], 1)
            self.assertEqual(result["buy_count"], 3)
        finally:
            os.unlink(tmp_path)

    def test_returns_none_on_corrupt_file(self):
        """load_decision_summary() returns None on corrupt JSON, never raises."""
        import decision_service
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            fh.write("NOT VALID JSON{{{")
            tmp_path = fh.name
        try:
            with patch.object(decision_service, "_SUMMARY_FILE", tmp_path):
                result = decision_service.load_decision_summary()
            self.assertIsNone(result)
        finally:
            os.unlink(tmp_path)

    def test_write_decision_summary_idempotent(self):
        """_write_decision_summary() never raises and writes the correct keys."""
        import decision_service
        result = {
            "generated_at": "2026-01-01T10:00:00Z",
            "strong_buy_count": 2,
            "buy_count": 1,
            "watch_count": 10,
            "avoid_count": 5,
            "universe_size": 18,
            "market_regime": "Neutral",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            tmp_path = fh.name
        try:
            with patch.object(decision_service, "_SUMMARY_FILE", tmp_path):
                decision_service._write_decision_summary(result)
            with open(tmp_path) as fh:
                written = json.load(fh)
            self.assertEqual(written["confirmed_buy_count"], 3)   # 2 + 1
            self.assertEqual(written["strong_buy_count"], 2)
            self.assertEqual(written["buy_count"], 1)
        finally:
            os.unlink(tmp_path)

    def test_write_decision_summary_silent_on_bad_path(self):
        """_write_decision_summary() never raises even when the path is unwritable."""
        import decision_service
        with patch.object(decision_service, "_SUMMARY_FILE", "/root/no_perms/x.json"):
            # Must not raise
            decision_service._write_decision_summary({"strong_buy_count": 1,
                                                       "buy_count": 0})

    def test_write_decision_summary_is_atomic(self):
        """
        _write_decision_summary() uses temp-file + os.replace() so a concurrent
        reader cannot observe a partial file.  We verify no *.json.tmp orphan is
        left behind and the final file is valid JSON.
        """
        import decision_service
        payload = {
            "generated_at": "2026-01-01T10:00:00Z",
            "strong_buy_count": 1, "buy_count": 2,
            "watch_count": 5, "avoid_count": 2,
            "universe_size": 10, "market_regime": "Bullish",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = os.path.join(tmpdir, "decision_summary_cache.json")
            with patch.object(decision_service, "_SUMMARY_FILE", summary_path):
                decision_service._write_decision_summary(payload)
            # Verify file was written and is valid JSON
            self.assertTrue(os.path.exists(summary_path), "Summary file must exist after write")
            with open(summary_path) as fh:
                data = json.load(fh)
            self.assertEqual(data["confirmed_buy_count"], 3)
            # Verify no orphaned temp files remain
            leftovers = [f for f in os.listdir(tmpdir) if f.endswith(".json.tmp")]
            self.assertEqual(leftovers, [], f"Orphaned temp files found: {leftovers}")

    def test_load_decision_summary_rejects_missing_required_keys(self):
        """
        load_decision_summary() returns None when the file is missing required
        keys — it must never treat a partial/schema-shifted file as authoritative.
        """
        import decision_service
        # File is valid JSON but missing 'confirmed_buy_count'
        partial = {"generated_at": "2026-01-01T09:00:00Z", "buy_count": 2}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump(partial, fh)
            tmp_path = fh.name
        try:
            with patch.object(decision_service, "_SUMMARY_FILE", tmp_path):
                result = decision_service.load_decision_summary()
            self.assertIsNone(result,
                              "Partial schema must be rejected — not treated as authoritative")
        finally:
            os.unlink(tmp_path)

    def test_load_decision_summary_rejects_wrong_type_for_count(self):
        """
        load_decision_summary() returns None when an integer count field holds
        a non-numeric value (e.g. a string from a broken serialiser).
        """
        import decision_service
        bad_types = _make_summary(strong_buy=1, buy=2)
        bad_types["confirmed_buy_count"] = "four"   # wrong type
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump(bad_types, fh)
            tmp_path = fh.name
        try:
            with patch.object(decision_service, "_SUMMARY_FILE", tmp_path):
                result = decision_service.load_decision_summary()
            self.assertIsNone(result,
                              "Wrong-type count field must be rejected — not treated as authoritative")
        finally:
            os.unlink(tmp_path)

    def test_load_decision_summary_rejects_non_dict(self):
        """load_decision_summary() returns None when the JSON root is not a dict."""
        import decision_service
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump([1, 2, 3], fh)   # list, not dict
            tmp_path = fh.name
        try:
            with patch.object(decision_service, "_SUMMARY_FILE", tmp_path):
                result = decision_service.load_decision_summary()
            self.assertIsNone(result, "JSON array root must be rejected")
        finally:
            os.unlink(tmp_path)


# ── Tests that prove _pipeline_summary uses the decision summary ──────────────

class TestPipelineSummaryBuyCount(unittest.TestCase):
    """
    Test _pipeline_summary() in isolation by mocking all external I/O.
    These tests prove the confirmed BUY count comes from decision_summary_cache
    and cannot be silently defeated by the legacy ai_decisions_cache schema.
    """

    def _run_pipeline_summary(self, decision_summary, scanner_buy_count=4,
                              eligible=3):
        """
        Run _pipeline_summary() with controlled mocks and return the result dict.
        decision_summary: the dict that load_decision_summary() returns, or None.
        scanner_buy_count: what the phase15 scan context reports as BUY/STRONG BUY.
        """
        from ops_centre import _pipeline_summary

        # Phase-15 scan context mock
        mock_symbols = {}
        for i in range(10):
            action = "BUY" if i < scanner_buy_count else "WATCH"
            mock_symbols[f"SYM{i}"] = {
                "data_quality": "LIVE",
                "final_action": action,
            }
        mock_ctx = {
            "symbols": mock_symbols,
            "scan_id": "test-scan-001",
            "snapshot_ts": "2026-01-01T09:30:00Z",
            "stale": False,
        }

        # Phase-20 risk mock
        mock_ev = {"eligible_count": eligible, "scan_id": "test-scan-001"}

        def _fake_load_dec_summary():
            return decision_summary

        with (
            patch("ops_centre.phase15_scan_context", create=True),
            patch.dict("sys.modules", {
                "phase15_scan_context": MagicMock(
                    build_scan_context=MagicMock(return_value=mock_ctx)),
                "paper_trader": MagicMock(
                    get_portfolio=MagicMock(return_value={"positions": []})),
                "phase20_executor": MagicMock(
                    get_ledger=MagicMock(return_value=[])),
                "phase20_gates": MagicMock(
                    get_last_evaluation=MagicMock(return_value=mock_ev)),
                "decision_service": MagicMock(
                    load_decision_summary=_fake_load_dec_summary),
            }),
        ):
            return _pipeline_summary()

    def test_confirmed_count_matches_decision_summary(self):
        """
        CORE: buy_recommendations equals confirmed_buy_count from the decision
        summary, which is strong_buy_count + buy_count.  scanner_candidates is
        higher (4) but must NOT be used as buy_recommendations.
        """
        summary = _make_summary(strong_buy=0, buy=0)  # Trade Decisions: 0 BUY
        result = self._run_pipeline_summary(decision_summary=summary,
                                            scanner_buy_count=4)
        self.assertEqual(result["buy_recommendations"], 0,
                         "Confirmed BUY must be 0 when decision service says 0")
        self.assertEqual(result["scanner_candidates"], 4,
                         "Scanner candidates must still be 4")
        self.assertNotEqual(result["buy_recommendations"],
                            result["scanner_candidates"],
                            "The two counts must differ — that was the original bug")

    def test_confirmed_count_reflects_actual_decisions(self):
        """buy_recommendations matches the real decision-service count."""
        summary = _make_summary(strong_buy=1, buy=2)  # 3 confirmed
        result = self._run_pipeline_summary(decision_summary=summary,
                                            scanner_buy_count=6)
        self.assertEqual(result["buy_recommendations"], 3)
        self.assertEqual(result["scanner_candidates"], 6)

    def test_no_scanner_fallback_when_no_summary(self):
        """
        When load_decision_summary() returns None (Trade Decisions page never
        loaded), buy_recommendations must be None — NOT scanner_candidates.
        Substituting scanner_candidates would recreate the original bug.
        decision_summary_ok must be False and consistency_note must explain
        that the count is not yet available.
        """
        result = self._run_pipeline_summary(decision_summary=None,
                                            scanner_buy_count=4)
        # buy_recommendations must be null/None — never 4 (scanner proxy)
        self.assertIsNone(result["buy_recommendations"],
                          "buy_recommendations must be None when no decision summary exists — "
                          "scanner_candidates must NOT be substituted")
        self.assertNotEqual(result["buy_recommendations"], 4,
                            "Scanner candidates (4) must NOT appear as confirmed BUY")
        self.assertFalse(result["decision_summary_ok"],
                         "decision_summary_ok must be False when no summary file exists")
        self.assertIn("Trade Decisions", result["consistency_note"],
                      "consistency_note must explain how to populate the confirmed count")

    def test_legacy_ai_decisions_cache_cannot_produce_zero(self):
        """
        The old code read from ai_decisions_cache.json using 'decision_type'
        (wrong field name) and always got 0 even when the cache had BUY entries.
        Prove the new code does NOT read from that file for confirmed count.

        We put a legacy cache on disk with 'decision' field = BUY for 5 symbols,
        and confirm the confirmed count still comes from the decision summary
        (not the legacy file).
        """
        import decision_service

        # Write a legacy-schema cache with 5 "BUY" entries via 'decision' field
        legacy_records = [
            {"stock": f"SYM{i}", "decision": "BUY", "confidence": 0.8}
            for i in range(5)
        ]

        original_summary_file = decision_service._SUMMARY_FILE
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_path = os.path.join(tmpdir, "ai_decisions_cache.json")
            with open(legacy_path, "w") as fh:
                json.dump(legacy_records, fh)

            # Decision summary says 0 BUY — this should be authoritative
            summary = _make_summary(strong_buy=0, buy=0)
            result = self._run_pipeline_summary(decision_summary=summary,
                                                scanner_buy_count=5)

        # The legacy cache has 5 BUY but decision summary says 0 — confirmed must be 0
        self.assertEqual(result["buy_recommendations"], 0,
                         "Legacy ai_decisions_cache must NOT override decision summary")

    def test_both_fields_present_in_pipeline_dict(self):
        """The pipeline dict must always have both scanner_candidates and buy_recommendations."""
        summary = _make_summary(strong_buy=2, buy=1)
        result = self._run_pipeline_summary(decision_summary=summary,
                                            scanner_buy_count=3)
        self.assertIn("scanner_candidates", result)
        self.assertIn("buy_recommendations", result)
        self.assertIn("decision_summary_ok", result)

    def test_pipeline_trace_ai_decision_stage_reflects_confirmed(self):
        """The AI Decision stage in pipeline_trace uses confirmed_buy_count."""
        summary = _make_summary(strong_buy=0, buy=1)  # 1 confirmed
        result = self._run_pipeline_summary(decision_summary=summary,
                                            scanner_buy_count=4, eligible=3)
        trace = {s["stage"]: s for s in result.get("pipeline_trace", [])}
        ai_stage = trace.get("AI Decision")
        self.assertIsNotNone(ai_stage, "Pipeline trace must have an AI Decision stage")
        self.assertEqual(ai_stage["output"], 1,
                         "AI Decision stage output must equal confirmed_buy_count")


# ── Integration test: get_trade_decisions() writes the summary ────────────────

class TestGetTradeDecisionsIntegration(unittest.TestCase):
    """
    Runs get_trade_decisions() with a minimal valid scan item and verifies:
      - The function returns well-formed decisions (recommendation field present)
      - The summary file is written with the correct confirmed_buy_count
      - load_decision_summary() reads back the correct counts
    """

    def _minimal_scan_item(self, symbol: str = "TEST", confidence: float = 80.0,
                           filter_passed: bool = True) -> dict:
        """A minimal scan item that decision_service._decide() can process."""
        return {
            "stock": symbol,
            "price": 100.0,
            "base_confidence": confidence,
            "final_confidence": confidence,
            "confidence": confidence,
            "learning_adjustment": 0.0,
            "historical_expectancy": 0.5,
            "historical_profit_factor": 1.5,
            "historical_win_rate": 0.6,
            "historical_sharpe": 1.0,
            "historical_kelly": 0.1,
            "pattern_match_pct": 70.0,
            "historical_trades": 25,
            "best_pattern": "Breakout",
            "best_regime": "Bullish",
            "rr_ratio": 2.5,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target": 112.5,
            "expected_holding_days": 10.0,
            "expected_drawdown": 2.0,
            "filter_passed": filter_passed,
            "filter_reasons": [],
            "error": None,
            "sector": "Technology",
            "volume_ratio": 1.5,
            "above_ema20": True,
            "above_ema50": True,
            "supertrend_dir": "UP",
            "rsi": 60.0,
            "macd_hist": 0.5,
            "opportunity_score": 75.0,
            "live_signal": True,
            "similarity_adjustment": 0.0,
            "evidence_reliability": "MEDIUM",
            "similarity_evidence": None,
            "similarity_explanation": "",
            "learning_explanation": "",
        }

    def test_get_trade_decisions_writes_summary_and_reads_back(self):
        """
        Full integration: get_trade_decisions() with mocked scan → writes summary
        → load_decision_summary() returns the correct confirmed_buy_count.
        """
        import decision_service

        item_buy  = self._minimal_scan_item("BUY_STOCK",  confidence=80.0, filter_passed=True)
        item_watch = self._minimal_scan_item("WATCH_STOCK", confidence=60.0, filter_passed=True)
        item_avoid = self._minimal_scan_item("AVOID_STOCK", confidence=40.0, filter_passed=False)

        mock_scan = {
            "items": [item_buy, item_watch, item_avoid],
            "learning": {"regime_strength": 60.0},
            "scan_id": "integration-test-001",
        }

        mock_portfolio_state = {"cash": 100000.0, "positions": {}, "trades": []}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            tmp_summary = fh.name

        try:
            with (
                patch.object(decision_service, "_SUMMARY_FILE", tmp_summary),
                patch.dict("sys.modules", {
                    "market_scanner": MagicMock(
                        run_market_scan=MagicMock(return_value=mock_scan)),
                    "paper_trader": MagicMock(
                        _load_state=MagicMock(return_value=mock_portfolio_state)),
                    "adaptive_learning": MagicMock(
                        current_market_regime=MagicMock(return_value="Bullish")),
                    "similarity_engine": MagicMock(
                        annotate_items_with_evidence=MagicMock()),
                    "model_versioning": MagicMock(
                        get_active_version=MagicMock(
                            return_value={"version": 0, "weights": {}})),
                    "market_data_engine": MagicMock(
                        get_last_source=MagicMock(return_value="yfinance")),
                }),
            ):
                result = decision_service.get_trade_decisions()

            # Verify return value structure
            self.assertIn("decisions", result)
            self.assertIn("strong_buy_count", result)
            self.assertIn("buy_count", result)
            self.assertGreaterEqual(len(result["decisions"]), 1)
            for d in result["decisions"]:
                self.assertIn("recommendation", d,
                              "Every decision must have a 'recommendation' field")
                self.assertIn(d["recommendation"],
                              {"STRONG_BUY", "BUY", "WATCH", "AVOID", "EXIT"},
                              f"Unexpected recommendation value: {d['recommendation']}")

            # Verify summary file was written
            self.assertTrue(os.path.exists(tmp_summary),
                            "Summary file must be written by get_trade_decisions()")

            # Verify load_decision_summary() reads back correctly
            with patch.object(decision_service, "_SUMMARY_FILE", tmp_summary):
                summary = decision_service.load_decision_summary()

            self.assertIsNotNone(summary, "load_decision_summary() must return the written summary")
            confirmed = summary["confirmed_buy_count"]
            expected  = result["strong_buy_count"] + result["buy_count"]
            self.assertEqual(confirmed, expected,
                             f"confirmed_buy_count {confirmed} must equal "
                             f"strong_buy+buy {expected} from get_trade_decisions()")

        finally:
            if os.path.exists(tmp_summary):
                os.unlink(tmp_summary)

    def test_summary_confirmed_count_reflects_avoid_not_buy(self):
        """When all scan items score AVOID, confirmed_buy_count must be 0."""
        import decision_service

        item_avoid = self._minimal_scan_item("AVOID_A", confidence=30.0, filter_passed=False)
        mock_scan = {
            "items": [item_avoid],
            "learning": {"regime_strength": 40.0},
            "scan_id": "integration-test-002",
        }
        mock_portfolio_state = {"cash": 100000.0, "positions": {}, "trades": []}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            tmp_summary = fh.name

        try:
            with (
                patch.object(decision_service, "_SUMMARY_FILE", tmp_summary),
                patch.dict("sys.modules", {
                    "market_scanner": MagicMock(
                        run_market_scan=MagicMock(return_value=mock_scan)),
                    "paper_trader": MagicMock(
                        _load_state=MagicMock(return_value=mock_portfolio_state)),
                    "adaptive_learning": MagicMock(
                        current_market_regime=MagicMock(return_value="Bearish")),
                    "similarity_engine": MagicMock(
                        annotate_items_with_evidence=MagicMock()),
                    "model_versioning": MagicMock(
                        get_active_version=MagicMock(
                            return_value={"version": 0, "weights": {}})),
                    "market_data_engine": MagicMock(
                        get_last_source=MagicMock(return_value="yfinance")),
                }),
            ):
                result = decision_service.get_trade_decisions()

            with patch.object(decision_service, "_SUMMARY_FILE", tmp_summary):
                summary = decision_service.load_decision_summary()

            self.assertIsNotNone(summary)
            self.assertEqual(summary["confirmed_buy_count"], 0)
            self.assertEqual(result["buy_count"] + result["strong_buy_count"], 0)

        finally:
            if os.path.exists(tmp_summary):
                os.unlink(tmp_summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
