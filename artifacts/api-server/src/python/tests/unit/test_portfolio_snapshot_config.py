"""Unit tests for portfolio_snapshot.py — PortfolioConfig import resolution.

Confirms that:
  1. The import path used in portfolio_snapshot.py (src.portfolio.config.PortfolioConfig)
     resolves correctly in the api-server Python environment.
  2. get_portfolio_snapshot() returns limits_from_config=True when PortfolioConfig
     is available (i.e. the import succeeds and values are read from it).
  3. get_portfolio_snapshot() returns limits_from_config=False and falls back to
     hardcoded defaults when PortfolioConfig cannot be imported.
"""
from __future__ import annotations

import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


class TestPortfolioConfigImportPath:
    """Confirm the exact import path used by portfolio_snapshot.py resolves."""

    def test_import_path_resolves(self):
        """from src.portfolio.config import PortfolioConfig must succeed."""
        from src.portfolio.config import PortfolioConfig  # noqa: F401 — import-path probe

        cfg = PortfolioConfig()
        assert cfg.paper_mode is True

    def test_default_instrument_limit_is_20_pct(self):
        """Default max_instrument_exposure_pct is 0.20 (20 %)."""
        from src.portfolio.config import PortfolioConfig

        cfg = PortfolioConfig()
        assert float(cfg.max_instrument_exposure_pct) == pytest.approx(0.20)

    def test_default_sector_limit_is_35_pct(self):
        """Default max_sector_exposure_pct is 0.35 (35 %)."""
        from src.portfolio.config import PortfolioConfig

        cfg = PortfolioConfig()
        assert float(cfg.max_sector_exposure_pct) == pytest.approx(0.35)


class TestPortfolioSnapshotLimitsFromConfig:
    """get_portfolio_snapshot() must set limits_from_config correctly."""

    def _get_snapshot_with_mocked_deps(self, block_portfolio_config: bool = False):
        """
        Import and call get_portfolio_snapshot() while mocking out all
        heavy dependencies so the test stays fast and self-contained.
        """
        # Modules that get_portfolio_snapshot() imports at call-time.
        _mock_phase20 = MagicMock()
        _mock_phase20.get_open_positions_view.return_value = []

        _mock_paper_trader = MagicMock()
        _mock_paper_trader._load_state.return_value = {
            "cash": 100_000.0,
            "initial_capital": 100_000.0,
            "positions": {},
        }
        _mock_paper_trader.get_portfolio.return_value = {}
        _mock_paper_trader.INITIAL_CAPITAL = 100_000.0
        _mock_paper_trader.get_trades.return_value = []

        _mock_phase22_act = MagicMock()
        _mock_phase22_act.get_activation_status.return_value = {"paper_automation_active": False}

        _mock_phase22_paper = MagicMock()
        _mock_phase22_paper.get_daily_pnl_today.return_value = 0.0

        extra_mocks = {
            "phase20_executor": _mock_phase20,
            "paper_trader": _mock_paper_trader,
            "phase22_activation": _mock_phase22_act,
            "phase22_auto_paper": _mock_phase22_paper,
        }

        if block_portfolio_config:
            # Simulate ImportError for src.portfolio.config
            broken_src = types.ModuleType("src")
            broken_portfolio = types.ModuleType("src.portfolio")
            broken_config = types.ModuleType("src.portfolio.config")

            def _raise(*a, **kw):
                raise ImportError("simulated PortfolioConfig unavailable")

            broken_config.PortfolioConfig = property(_raise)  # type: ignore[assignment]

            # Patch by making the import raise directly
            def _import_side_effect(name, *args, **kwargs):
                if name == "src.portfolio.config":
                    raise ImportError("simulated PortfolioConfig unavailable")
                return orig_import(name, *args, **kwargs)

            orig_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__  # type: ignore[union-attr]

            with patch("builtins.__import__", side_effect=_import_side_effect):
                with patch.dict(sys.modules, extra_mocks):
                    import importlib
                    import portfolio_snapshot as _ps
                    importlib.reload(_ps)
                    result = _ps.get_portfolio_snapshot()

            # Reload without the patch so we don't pollute other tests
            import importlib as _il
            import portfolio_snapshot as _ps2
            _il.reload(_ps2)
            return result
        else:
            with patch.dict(sys.modules, extra_mocks):
                import portfolio_snapshot as _ps
                return _ps.get_portfolio_snapshot()

    def test_limits_from_config_present_in_response(self):
        """Snapshot response must contain the limits_from_config key."""
        import portfolio_snapshot as _ps
        with patch.dict(sys.modules, {
            "phase20_executor": MagicMock(get_open_positions_view=lambda: []),
            "paper_trader": MagicMock(
                _load_state=lambda: {"cash": 100_000.0, "initial_capital": 100_000.0, "positions": {}},
                get_trades=lambda: [],
                INITIAL_CAPITAL=100_000.0,
            ),
            "phase22_activation": MagicMock(get_activation_status=lambda: {"paper_automation_active": False}),
            "phase22_auto_paper": MagicMock(get_daily_pnl_today=lambda: 0.0),
        }):
            snap = _ps.get_portfolio_snapshot()

        assert "limits_from_config" in snap, "limits_from_config key must be present"

    def test_limits_from_config_true_when_portfolio_config_available(self):
        """limits_from_config must be True when PortfolioConfig import succeeds."""
        import portfolio_snapshot as _ps
        with patch.dict(sys.modules, {
            "phase20_executor": MagicMock(get_open_positions_view=lambda: []),
            "paper_trader": MagicMock(
                _load_state=lambda: {"cash": 100_000.0, "initial_capital": 100_000.0, "positions": {}},
                get_trades=lambda: [],
                INITIAL_CAPITAL=100_000.0,
            ),
            "phase22_activation": MagicMock(get_activation_status=lambda: {"paper_automation_active": False}),
            "phase22_auto_paper": MagicMock(get_daily_pnl_today=lambda: 0.0),
        }):
            snap = _ps.get_portfolio_snapshot()

        # src.portfolio.config is available in this env, so limits_from_config must be True
        assert snap["limits_from_config"] is True

    def test_limits_from_config_false_uses_hardcoded_defaults(self):
        """When PortfolioConfig raises, limits fall back to 20%/35% and limits_from_config=False."""
        import portfolio_snapshot as _ps

        mock_cfg_module = MagicMock()
        mock_cfg_module.PortfolioConfig.side_effect = ImportError("blocked for test")

        with patch.dict(sys.modules, {
            "phase20_executor": MagicMock(get_open_positions_view=lambda: []),
            "paper_trader": MagicMock(
                _load_state=lambda: {"cash": 100_000.0, "initial_capital": 100_000.0, "positions": {}},
                get_trades=lambda: [],
                INITIAL_CAPITAL=100_000.0,
            ),
            "phase22_activation": MagicMock(get_activation_status=lambda: {"paper_automation_active": False}),
            "phase22_auto_paper": MagicMock(get_daily_pnl_today=lambda: 0.0),
            "src.portfolio.config": mock_cfg_module,
        }):
            snap = _ps.get_portfolio_snapshot()

        assert snap["limits_from_config"] is False
        assert snap["instrument_limit_pct"] == pytest.approx(20.0)
        assert snap["sector_limit_pct"] == pytest.approx(35.0)


# ── get_portfolio_health() ────────────────────────────────────────────────────


class TestPortfolioHealthDegradedOnMissingConfig:
    """get_portfolio_health() must return DEGRADED when PortfolioConfig cannot be imported."""

    # Shared helpers for mocking heavy dependencies --------------------------

    @staticmethod
    def _make_phase22_activation(active: bool = False) -> MagicMock:
        m = MagicMock()
        m.get_activation_status.return_value = {"paper_automation_active": active}
        return m

    @staticmethod
    def _make_paper_trader(has_state: bool = True) -> MagicMock:
        m = MagicMock()
        if has_state:
            m._load_state.return_value = {
                "cash": 100_000.0,
                "initial_capital": 100_000.0,
                "positions": {},
                "last_updated": "2024-01-01T00:00:00+00:00",
            }
        else:
            m._load_state.return_value = {}
        return m

    @staticmethod
    def _make_eod_reconciliation(unresolved: int = 0) -> MagicMock:
        m = MagicMock()
        m.get_reconciliation_status.return_value = {"unresolved_count": unresolved}
        return m

    @staticmethod
    def _make_phase20_store() -> MagicMock:
        """Stub phase20_store so the notification emit inside health does not raise."""
        m = MagicMock()
        m.kv_get.return_value = None  # force alert emit path but swallow it
        m.kv_set.return_value = None
        m.add_notification.return_value = None
        return m

    # ── 1. Status is DEGRADED when PortfolioConfig import fails --------------

    def test_health_status_degraded_when_config_missing(self):
        """health status must be DEGRADED (not HEALTHY) when PortfolioConfig raises."""
        import portfolio_snapshot as _ps

        mock_cfg = MagicMock()
        mock_cfg.PortfolioConfig.side_effect = ImportError("no module src.portfolio.config")

        with patch.dict(sys.modules, {
            "phase22_activation": self._make_phase22_activation(),
            "paper_trader": self._make_paper_trader(has_state=True),
            "eod_reconciliation": self._make_eod_reconciliation(unresolved=0),
            "src.portfolio.config": mock_cfg,
            "phase20_store": self._make_phase20_store(),
        }):
            result = _ps.get_portfolio_health()

        assert result["status"] == "DEGRADED", (
            f"Expected DEGRADED but got {result['status']!r}; "
            f"degraded_reasons={result.get('degraded_reasons')}"
        )

    # ── 2. limits_from_config is False when PortfolioConfig import fails -----

    def test_limits_from_config_false_when_config_missing(self):
        """limits_from_config must be False in the health response when import fails."""
        import portfolio_snapshot as _ps

        mock_cfg = MagicMock()
        mock_cfg.PortfolioConfig.side_effect = ImportError("blocked")

        with patch.dict(sys.modules, {
            "phase22_activation": self._make_phase22_activation(),
            "paper_trader": self._make_paper_trader(has_state=True),
            "eod_reconciliation": self._make_eod_reconciliation(unresolved=0),
            "src.portfolio.config": mock_cfg,
            "phase20_store": self._make_phase20_store(),
        }):
            result = _ps.get_portfolio_health()

        assert result["limits_from_config"] is False

    # ── 3. degraded_reasons contains the PortfolioConfig message -------------

    def test_degraded_reasons_contains_config_message(self):
        """degraded_reasons must include the PortfolioConfig import-failure entry."""
        import portfolio_snapshot as _ps

        mock_cfg = MagicMock()
        mock_cfg.PortfolioConfig.side_effect = ImportError("blocked")

        with patch.dict(sys.modules, {
            "phase22_activation": self._make_phase22_activation(),
            "paper_trader": self._make_paper_trader(has_state=True),
            "eod_reconciliation": self._make_eod_reconciliation(unresolved=0),
            "src.portfolio.config": mock_cfg,
            "phase20_store": self._make_phase20_store(),
        }):
            result = _ps.get_portfolio_health()

        reasons = result.get("degraded_reasons", [])
        assert len(reasons) >= 1, "degraded_reasons must have at least one entry"

        config_reason = next(
            (r for r in reasons if "PortfolioConfig" in r or "hardcoded defaults" in r),
            None,
        )
        assert config_reason is not None, (
            f"No PortfolioConfig-related reason found in degraded_reasons: {reasons!r}"
        )

    # ── 4. degraded flag is True ─────────────────────────────────────────────

    def test_degraded_flag_is_true_when_config_missing(self):
        """The boolean 'degraded' field must be True when config cannot be loaded."""
        import portfolio_snapshot as _ps

        mock_cfg = MagicMock()
        mock_cfg.PortfolioConfig.side_effect = ImportError("blocked")

        with patch.dict(sys.modules, {
            "phase22_activation": self._make_phase22_activation(),
            "paper_trader": self._make_paper_trader(has_state=True),
            "eod_reconciliation": self._make_eod_reconciliation(unresolved=0),
            "src.portfolio.config": mock_cfg,
            "phase20_store": self._make_phase20_store(),
        }):
            result = _ps.get_portfolio_health()

        assert result["degraded"] is True

    # ── 5. failure_reason is populated ──────────────────────────────────────

    def test_failure_reason_populated_when_config_missing(self):
        """failure_reason (first degraded reason) must not be None when config fails."""
        import portfolio_snapshot as _ps

        mock_cfg = MagicMock()
        mock_cfg.PortfolioConfig.side_effect = ImportError("blocked")

        with patch.dict(sys.modules, {
            "phase22_activation": self._make_phase22_activation(),
            "paper_trader": self._make_paper_trader(has_state=True),
            "eod_reconciliation": self._make_eod_reconciliation(unresolved=0),
            "src.portfolio.config": mock_cfg,
            "phase20_store": self._make_phase20_store(),
        }):
            result = _ps.get_portfolio_health()

        assert result.get("failure_reason") is not None, (
            "failure_reason must be set when health is DEGRADED"
        )

    # ── 6. Healthy path still works (sanity) ─────────────────────────────────

    def test_health_status_healthy_when_config_available(self):
        """Control: health is HEALTHY (not DEGRADED) when PortfolioConfig loads fine."""
        import portfolio_snapshot as _ps

        # Allow the real src.portfolio.config to be used — do NOT block it.
        with patch.dict(sys.modules, {
            "phase22_activation": self._make_phase22_activation(),
            "paper_trader": self._make_paper_trader(has_state=True),
            "eod_reconciliation": self._make_eod_reconciliation(unresolved=0),
            "phase20_store": self._make_phase20_store(),
        }):
            result = _ps.get_portfolio_health()

        # With real PortfolioConfig and no unresolved discrepancies:
        # status should be HEALTHY (initialized=True from the paper_trader mock).
        assert result["status"] == "HEALTHY"
        assert result["limits_from_config"] is True
        assert result.get("degraded_reasons", []) == []
