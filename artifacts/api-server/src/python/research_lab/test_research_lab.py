"""
test_research_lab.py — Unit tests for research_lab.shared_services cache helpers.

Covers:
  - invalidate_snapshot_cache() removes the file when it exists
  - invalidate_snapshot_cache() is a no-op (and returns a clean message) when the file is absent
  - invalidate_snapshot_cache() returns a non-fatal message when os.remove raises
  - _load_snapshot_cache() returns None after invalidation
  - _save_snapshot_cache() then _load_snapshot_cache() round-trip still works
  - The post-scan pipeline includes a 'research_lab_cache_flush' module entry

PAPER / ADVISORY ONLY.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

# ── Path bootstrap ────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_ROOT = os.path.dirname(_HERE)
if _PYTHON_ROOT not in sys.path:
    sys.path.insert(0, _PYTHON_ROOT)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers to load the module under a custom cache path so tests never touch the
# real _snapshot_cache.json on disk.
# ─────────────────────────────────────────────────────────────────────────────

def _reload_with_cache_path(tmp_path: str):
    """Import shared_services with _SNAPSHOT_CACHE_FILE overridden to tmp_path."""
    import importlib
    import research_lab.shared_services as mod
    importlib.reload(mod)
    mod._SNAPSHOT_CACHE_FILE = tmp_path          # type: ignore[attr-defined]
    return mod


class TestInvalidateSnapshotCache(unittest.TestCase):
    """invalidate_snapshot_cache() behaviour."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        # Write a valid cache entry so the file genuinely exists.
        with open(self.tmp.name, "w") as f:
            json.dump({"research_score": 55, "_cached_at": time.time()}, f)
        self.mod = _reload_with_cache_path(self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    # ------------------------------------------------------------------
    def test_removes_existing_cache_file(self):
        msg = self.mod.invalidate_snapshot_cache()
        self.assertFalse(os.path.exists(self.tmp.name),
                         "Cache file should have been deleted")
        self.assertIn("cache invalidated", msg)

    def test_returns_descriptive_message_on_removal(self):
        msg = self.mod.invalidate_snapshot_cache()
        self.assertIn("removed", msg)
        # Message must mention the cache-invalidated prefix
        self.assertIn("cache invalidated", msg)

    def test_no_op_when_file_absent(self):
        os.unlink(self.tmp.name)           # pre-delete
        msg = self.mod.invalidate_snapshot_cache()
        self.assertIn("already clear", msg)

    def test_non_fatal_on_os_error(self):
        """A permission error must not propagate — must return a non-fatal string."""
        with patch("os.remove", side_effect=PermissionError("denied")):
            with patch("os.path.exists", return_value=True):
                msg = self.mod.invalidate_snapshot_cache()
        self.assertIn("non-fatal", msg)

    def test_load_returns_none_after_invalidation(self):
        """_load_snapshot_cache should return None once the file is gone."""
        self.mod.invalidate_snapshot_cache()
        result = self.mod._load_snapshot_cache()
        self.assertIsNone(result)

    def test_save_then_load_still_works(self):
        """Verify the save/load round-trip is intact after a re-save."""
        self.mod.invalidate_snapshot_cache()
        snap = {"research_score": 72, "grade": "B", "trend": "IMPROVING"}
        self.mod._save_snapshot_cache(snap)
        loaded = self.mod._load_snapshot_cache()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["research_score"], 72)
        self.assertEqual(loaded["grade"], "B")

    def test_idempotent_double_call(self):
        """Calling invalidate twice must not raise."""
        self.mod.invalidate_snapshot_cache()
        # Second call — file is already gone
        msg2 = self.mod.invalidate_snapshot_cache()
        self.assertIn("already clear", msg2)


class TestInvalidateWithoutExistingFile(unittest.TestCase):
    """invalidate_snapshot_cache() when the cache file never existed."""

    def setUp(self):
        # Point to a path that definitely does not exist
        self.phantom = os.path.join(tempfile.gettempdir(),
                                    "_phantom_research_cache_test.json")
        if os.path.exists(self.phantom):
            os.unlink(self.phantom)
        self.mod = _reload_with_cache_path(self.phantom)

    def tearDown(self):
        if os.path.exists(self.phantom):
            os.unlink(self.phantom)

    def test_no_op_returns_clear_message(self):
        msg = self.mod.invalidate_snapshot_cache()
        self.assertIn("already clear", msg)

    def test_no_file_created(self):
        self.mod.invalidate_snapshot_cache()
        self.assertFalse(os.path.exists(self.phantom))


class TestScanPipelineIncludesFlushModule(unittest.TestCase):
    """The post-scan pipeline records a 'research_lab_cache_flush' module entry."""

    def _make_minimal_snap(self) -> dict:
        import uuid
        from datetime import datetime, timezone as _tz
        return {
            "scan_id": str(uuid.uuid4()),
            "snapshot_ts": datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "recommendations": [],
            "provider_health": {},
            "safety": {},
        }

    def test_flush_module_present_in_output(self):
        """run_post_scan_pipeline must include research_lab_cache_flush in modules."""
        snap = self._make_minimal_snap()

        # Stub everything the pipeline needs so it doesn't hit DB / yfinance.
        stubs = {
            "scan_state_store": MagicMock(FALLBACK_SNAPSHOT_FILE="/tmp/_test_snap.json"),
            "intelligence": MagicMock(run_intelligence_scan=MagicMock(return_value={})),
            "phase13_intelligence": MagicMock(run_phase13_analysis=MagicMock()),
            "phase14_adjustments": MagicMock(compute_adjustments=MagicMock()),
            "copilot_engine": MagicMock(generate_alerts=MagicMock(),
                                        daily_briefing=MagicMock()),
            "phase20_gates": MagicMock(evaluate_entries=MagicMock(return_value=[])),
            "phase20_store": MagicMock(
                kv_set=MagicMock(),
                kv_get=MagicMock(return_value=None),
                get_settings=MagicMock(return_value={}),
            ),
            "phase15_sync": MagicMock(sync_derived_caches=MagicMock()),
            "phase15_consistency": MagicMock(run_consistency_check=MagicMock(
                return_value={"verdict": "PASS", "checks_performed": 1,
                              "hard_mismatch_count": 0, "stale_source_count": 0})),
            "signals_store": MagicMock(load_watchlist=MagicMock(return_value=["RELIANCE"])),
            "paper_trader": MagicMock(get_portfolio=MagicMock(return_value=MagicMock(cash=5000.0))),
        }
        # Stub the research_lab flush so it doesn't need yfinance
        rl_ss = MagicMock()
        rl_ss.invalidate_snapshot_cache = MagicMock(return_value="cache invalidated: removed")
        stubs["research_lab.shared_services"] = rl_ss

        import importlib
        import scan_pipeline as sp
        importlib.reload(sp)

        with patch.dict("sys.modules", stubs):
            # patch store directly on the reloaded module
            sp.store = stubs["phase20_store"]  # type: ignore[attr-defined]
            result = sp.run_post_scan_pipeline(snap, trigger="TEST")

        module_names = [m["module"] for m in result.get("modules", [])]
        self.assertIn("research_lab_cache_flush", module_names,
                      f"Expected 'research_lab_cache_flush' in modules, got: {module_names}")

    def test_flush_module_not_in_required_modules(self):
        """research_lab_cache_flush must NOT be in REQUIRED_MODULES."""
        import scan_pipeline as sp
        self.assertNotIn("research_lab_cache_flush", sp.REQUIRED_MODULES)


# ══════════════════════════════════════════════════════════════════════════════
# _as_str coercion on grade and trend in get_research_lab_snapshot()
# ══════════════════════════════════════════════════════════════════════════════

class TestStringKpiCoercion(unittest.TestCase):
    """
    Guard: grade and trend in get_research_lab_snapshot() must always be plain
    strings, never a dict/None/list, even when the upstream get_summary()
    returns unexpected types for these fields.
    """

    # ── _as_str helper unit tests ─────────────────────────────────────────────

    def test_as_str_none_returns_fallback(self):
        from research_lab.shared_services import _as_str
        self.assertEqual(_as_str(None), "N/A")

    def test_as_str_dict_returns_fallback(self):
        from research_lab.shared_services import _as_str
        self.assertEqual(_as_str({"grade": "A"}), "N/A")

    def test_as_str_list_returns_fallback(self):
        from research_lab.shared_services import _as_str
        self.assertEqual(_as_str(["A", "B"]), "N/A")

    def test_as_str_empty_string_returns_fallback(self):
        from research_lab.shared_services import _as_str
        self.assertEqual(_as_str(""), "N/A")

    def test_as_str_valid_string_passes_through(self):
        from research_lab.shared_services import _as_str
        self.assertEqual(_as_str("IMPROVING"), "IMPROVING")

    def test_as_str_custom_fallback(self):
        from research_lab.shared_services import _as_str
        self.assertEqual(_as_str(None, fallback="STABLE"), "STABLE")

    # ── grade coercion guards ─────────────────────────────────────────────────

    def test_grade_coerced_when_dict(self):
        """If get_summary() returns grade as a dict, _as_str must coerce it."""
        from research_lab.shared_services import _as_str
        upstream_grade = {"letter": "A", "score": 85}
        coerced = _as_str(upstream_grade, fallback="N/A")
        self.assertEqual(coerced, "N/A")
        self.assertIsInstance(coerced, str)

    def test_grade_coerced_when_none(self):
        from research_lab.shared_services import _as_str
        coerced = _as_str(None, fallback="N/A")
        self.assertEqual(coerced, "N/A")
        self.assertIsInstance(coerced, str)

    def test_grade_valid_string_survives_coercion(self):
        from research_lab.shared_services import _as_str
        self.assertEqual(_as_str("A"), "A")

    # ── trend coercion guards ─────────────────────────────────────────────────

    def test_trend_coerced_when_dict(self):
        """If get_summary() returns trend as a dict, _as_str must coerce it."""
        from research_lab.shared_services import _as_str
        upstream_trend = {"direction": "up", "delta": 5}
        coerced = _as_str(upstream_trend, fallback="STABLE")
        self.assertEqual(coerced, "STABLE")
        self.assertIsInstance(coerced, str)

    def test_trend_coerced_when_none(self):
        from research_lab.shared_services import _as_str
        coerced = _as_str(None, fallback="STABLE")
        self.assertEqual(coerced, "STABLE")
        self.assertIsInstance(coerced, str)

    def test_trend_valid_strings_survive_coercion(self):
        from research_lab.shared_services import _as_str
        for val in ("IMPROVING", "WEAKENING", "STABLE"):
            self.assertEqual(_as_str(val), val)

    # ── cached snapshot field types ───────────────────────────────────────────

    def test_cached_snapshot_grade_and_trend_are_str(self):
        """Snapshot loaded from file cache must have grade/trend as strings."""
        import tempfile
        import time
        import json
        import importlib

        import research_lab.shared_services as mod
        importlib.reload(mod)

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump({
                "status": "ENABLED",
                "research_score": 72,
                "grade": "B",
                "trend": "IMPROVING",
                "_cached_at": time.time(),
            }, f)
            tmp_path = f.name

        try:
            mod._SNAPSHOT_CACHE_FILE = tmp_path
            snap = mod.get_research_lab_snapshot()
            self.assertIsInstance(snap.get("grade"), str,
                f"grade from cache type={type(snap.get('grade')).__name__!r}")
            self.assertIsInstance(snap.get("trend"), str,
                f"trend from cache type={type(snap.get('trend')).__name__!r}")
        finally:
            import os
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
