"""Phase 27B: avg per-symbol stage processing time in stage_summary().

Definition: the time attributed to a stage is the gap between a symbol's
event in that stage and the SAME symbol's previous pipeline event in the
same scan. Uses the file fallback (DATABASE_URL removed) so tests are
hermetic; the SQL path implements the identical definition with LAG().
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pipeline_events as pe                                   # noqa: E402


class TestStageTiming(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_file = pe.FALLBACK_FILE
        self._old_db = os.environ.pop("DATABASE_URL", None)
        pe.FALLBACK_FILE = os.path.join(self.tmp.name, "events.json")

    def tearDown(self):
        pe.FALLBACK_FILE = self._old_file
        if self._old_db is not None:
            os.environ["DATABASE_URL"] = self._old_db
        self.tmp.cleanup()

    @staticmethod
    def _write(rows):
        import json
        with open(pe.FALLBACK_FILE, "w") as f:
            json.dump(rows, f)

    def _row(self, i, ts, stage, symbol, scan="S1", et="SYMBOL_ENTERED"):
        return {"id": i, "ts": ts, "mode": "LIVE", "run_id": None,
                "scan_id": scan, "event_type": et, "stage": stage,
                "symbol": symbol, "payload": {}}

    def test_avg_symbol_ms_from_inter_stage_gaps(self):
        self._write([
            self._row(1, "2026-08-09T10:00:00+00:00", "SCANNER", "TCS"),
            self._row(2, "2026-08-09T10:00:02+00:00", "RESEARCH", "TCS"),
            self._row(3, "2026-08-09T10:00:00+00:00", "SCANNER", "INFY"),
            self._row(4, "2026-08-09T10:00:04+00:00", "RESEARCH", "INFY"),
        ])
        s = pe.stage_summary(scan_id="S1")
        by = {x["stage"]: x for x in s["stages"]}
        # RESEARCH gaps: 2000ms (TCS) + 4000ms (INFY) → avg 3000ms
        self.assertEqual(by["RESEARCH"]["avg_symbol_ms"], 3000.0)
        # SCANNER events have no prior event for the symbol → None
        self.assertIsNone(by["SCANNER"]["avg_symbol_ms"])

    def test_gaps_never_cross_scans(self):
        self._write([
            self._row(1, "2026-08-09T10:00:00+00:00", "RESEARCH", "TCS", scan="S1"),
            # 1 hour later in a DIFFERENT scan: must not contribute a gap
            self._row(2, "2026-08-09T11:00:00+00:00", "RESEARCH", "TCS", scan="S2"),
        ])
        for scan in ("S1", "S2"):
            s = pe.stage_summary(scan_id=scan)
            by = {x["stage"]: x for x in s["stages"]}
            self.assertIsNone(by["RESEARCH"]["avg_symbol_ms"])

    def test_equal_timestamps_ordered_by_id_like_sql(self):
        # Two events share a timestamp; ordering must fall back to id
        # (ORDER BY ts, id) so the gap is 0ms for the later id, matching SQL.
        self._write([
            self._row(2, "2026-08-09T10:00:00+00:00", "RESEARCH", "TCS"),
            self._row(1, "2026-08-09T10:00:00+00:00", "SCANNER", "TCS"),
        ])
        s = pe.stage_summary(scan_id="S1")
        by = {x["stage"]: x for x in s["stages"]}
        self.assertEqual(by["RESEARCH"]["avg_symbol_ms"], 0.0)
        self.assertIsNone(by["SCANNER"]["avg_symbol_ms"])

    def test_field_always_present(self):
        self._write([])
        s = pe.stage_summary()
        for st in s["stages"]:
            self.assertIn("avg_symbol_ms", st)
            self.assertIsNone(st["avg_symbol_ms"])


if __name__ == "__main__":
    unittest.main()
