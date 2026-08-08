"""Unit tests — durable operator overrides for PortfolioConfig limits."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_PY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

import portfolio_config_overrides as pco  # noqa: E402


class TestOverridesFileFallback(unittest.TestCase):
    """Hermetic: force the file fallback so tests never touch the dev DB."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.patches = [
            patch.object(pco, "_db_available", return_value=False),
            patch.object(pco, "_FALLBACK_FILE", self.tmp.name),
        ]
        for p in self.patches:
            p.start()
        # Other suites set the hermetic kill-switch at collection time;
        # these tests exercise the store itself, so lift it here.
        self._prev_disabled = os.environ.pop("PORTFOLIO_OVERRIDES_DISABLED", None)

    def tearDown(self):
        if self._prev_disabled is not None:
            os.environ["PORTFOLIO_OVERRIDES_DISABLED"] = self._prev_disabled
        for p in self.patches:
            p.stop()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_set_get_roundtrip_and_merge(self):
        pco.set_overrides({"max_open_positions": 15})
        pco.set_overrides({"cash_reserve_pct": 0.08})
        self.assertEqual(
            pco.get_overrides(),
            {"max_open_positions": 15, "cash_reserve_pct": 0.08},
        )

    def test_merged_config_applies_overrides(self):
        pco.set_overrides({"max_open_positions": 15})
        cfg = pco.merged_config()
        self.assertEqual(cfg.max_open_positions, 15)

    def test_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            pco.set_overrides({"paper_mode": False})
        with self.assertRaises(ValueError):
            pco.set_overrides({"initial_capital": 1})

    def test_invalid_combination_rejected_by_config_validators(self):
        # min >= max order value must be rejected before persisting
        with self.assertRaises(Exception):
            pco.set_overrides({"min_order_value": 60000,
                               "max_order_value": 50000})
        self.assertEqual(pco.get_overrides(), {})

    def test_out_of_range_pct_rejected(self):
        with self.assertRaises(Exception):
            pco.set_overrides({"max_drawdown_pct": 1.5})

    def test_corrupt_store_fails_open_to_env(self):
        with open(self.tmp.name, "w") as f:
            f.write("{not json")
        self.assertEqual(pco.get_overrides(), {})
        cfg = pco.merged_config()  # env defaults, no raise
        self.assertEqual(cfg.max_open_positions, 10)

    def test_poisoned_persisted_overrides_fail_open(self):
        # Value bypasses set-time validation (e.g. written by an older
        # build) — merged_config must fall back to env config, not raise.
        with open(self.tmp.name, "w") as f:
            json.dump({"max_drawdown_pct": 9.9}, f)
        cfg = pco.merged_config()
        self.assertEqual(float(cfg.max_drawdown_pct), 0.10)

    def test_clear(self):
        pco.set_overrides({"max_open_positions": 12})
        pco.clear_overrides()
        self.assertEqual(pco.get_overrides(), {})

    def test_effective_overrides_hides_invalid_persisted_state(self):
        # A poisoned store must not be reported as active: the bridge
        # fail-opens to env config, so reads must match (no false claims).
        with open(self.tmp.name, "w") as f:
            json.dump({"max_drawdown_pct": 9.9}, f)
        self.assertEqual(pco.effective_overrides(), {})
        pco.clear_overrides()
        pco.set_overrides({"max_open_positions": 12})
        self.assertEqual(pco.effective_overrides(), {"max_open_positions": 12})

    def test_clear_raises_on_db_failure_no_false_success(self):
        with patch.object(pco, "_db_available", return_value=True), \
                patch.object(pco, "_connect", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                pco.clear_overrides()

    def test_set_rolls_back_when_merged_db_state_is_invalid(self):
        """Concurrent individually-valid PATCHes may merge into an invalid
        config; the transaction must roll back, never commit it."""
        from unittest.mock import MagicMock
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        # Simulated RETURNING row: merged state where min >= max order value
        cur.fetchone.return_value = ({"min_order_value": 60000,
                                      "max_order_value": 50000},)
        with patch.object(pco, "_db_available", return_value=True), \
                patch.object(pco, "_connect", return_value=conn), \
                patch.object(pco, "_SCHEMA_READY", True):
            with self.assertRaises(Exception):
                pco.set_overrides({"min_order_value": 60000})
            conn.rollback.assert_called_once()
            conn.commit.assert_not_called()

    def test_stamp_changes_on_write(self):
        self.assertIsNone(pco.get_overrides_stamp())
        pco.set_overrides({"max_open_positions": 12})
        self.assertIsNotNone(pco.get_overrides_stamp())


class TestLongLivedHotReload(unittest.TestCase):
    """A PATCH must take effect inside an already-running process (bridge
    service already built) on the next decision cycle, without a restart."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.patches = [
            patch.object(pco, "_db_available", return_value=False),
            patch.object(pco, "_FALLBACK_FILE", self.tmp.name),
        ]
        for p in self.patches:
            p.start()
        self._prev_disabled = os.environ.pop("PORTFOLIO_OVERRIDES_DISABLED", None)

    def tearDown(self):
        if self._prev_disabled is not None:
            os.environ["PORTFOLIO_OVERRIDES_DISABLED"] = self._prev_disabled
        for p in self.patches:
            p.stop()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_refresh_swaps_config_on_service_and_all_collaborators(self):
        import portfolio_bridge as pb
        from src.portfolio.service import PortfolioService

        service = PortfolioService(config=pco.merged_config())

        with patch.object(pb, "_service", service), \
                patch.object(pb, "_overrides_stamp", None):
            pco.set_overrides({"max_open_positions": 15})
            pb._refresh_config_if_stale()
            self.assertEqual(service.config.max_open_positions, 15)
            for attr in ("_state_manager", "_limits_engine",
                         "_exposure_engine", "_capital_allocator",
                         "_position_sizer", "_health_monitor",
                         "_reconciliation_engine"):
                self.assertEqual(
                    getattr(service, attr).config.max_open_positions, 15,
                    f"{attr} still holds a stale config")
            # unchanged stamp → no rebuild churn
            stamp_before = pb._overrides_stamp
            pb._refresh_config_if_stale()
            self.assertEqual(pb._overrides_stamp, stamp_before)

    def test_apply_config_covers_every_config_holding_collaborator(self):
        """Guard: any new collaborator constructed with a config must be
        swapped by apply_config(), or running strategies enforce stale
        limits after an operator edit."""
        from src.portfolio.service import PortfolioService
        service = PortfolioService(config=pco.merged_config())
        new_cfg = pco.build_config({"max_open_positions": 12})
        service.apply_config(new_cfg)
        stale = [
            name for name, obj in vars(service).items()
            if hasattr(obj, "config") and getattr(obj, "config") is not new_cfg
        ]
        self.assertEqual(stale, [], f"collaborators with stale config: {stale}")


if __name__ == "__main__":
    unittest.main()
