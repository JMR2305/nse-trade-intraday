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


# ── get_portfolio_config() ────────────────────────────────────────────────────


class TestGetPortfolioConfig:
    """Tests for get_portfolio_config() — the function backing GET /api/portfolio/config."""

    # ── 1. Happy path: loaded=True with default values ───────────────────────

    def test_loaded_true_when_portfolio_config_available(self):
        """get_portfolio_config() must return loaded=True when PortfolioConfig imports fine."""
        import portfolio_snapshot as _ps

        result = _ps.get_portfolio_config()

        assert result["loaded"] is True, (
            f"Expected loaded=True but got {result['loaded']!r}; error={result.get('error')}"
        )

    def test_limits_from_config_true_on_success(self):
        """limits_from_config mirrors loaded when PortfolioConfig is available."""
        import portfolio_snapshot as _ps

        result = _ps.get_portfolio_config()

        assert result["limits_from_config"] is True

    def test_config_contains_expected_keys(self):
        """The config dict must contain all limit/capital keys the panel needs."""
        import portfolio_snapshot as _ps

        result = _ps.get_portfolio_config()
        cfg = result["config"]

        required_keys = [
            "portfolio_id",
            "enabled",
            "initial_capital",
            "cash_reserve_pct",
            "max_portfolio_exposure_pct",
            "max_instrument_exposure_pct",
            "max_sector_exposure_pct",
            "max_strategy_exposure_pct",
            "max_open_positions",
            "max_pending_orders",
            "max_daily_loss_pct",
            "max_drawdown_pct",
            "min_order_value",
            "max_order_value",
            "default_risk_per_trade_pct",
        ]
        missing = [k for k in required_keys if k not in cfg]
        assert missing == [], f"config dict is missing keys: {missing}"

    def test_default_numeric_values_are_correct(self):
        """Default limit values must match PortfolioConfig spec without any env overrides."""
        import os
        import portfolio_snapshot as _ps

        # Strip any test-environment overrides for these specific keys so we get pure defaults.
        env_strip = {
            k: None
            for k in [
                "PORTFOLIO_MAX_INSTRUMENT_PCT",
                "PORTFOLIO_MAX_SECTOR_PCT",
                "PORTFOLIO_MAX_EXPOSURE_PCT",
                "PORTFOLIO_INITIAL_CAPITAL",
                "PORTFOLIO_CASH_RESERVE_PCT",
                "PORTFOLIO_MAX_DAILY_LOSS_PCT",
                "PORTFOLIO_MAX_DRAWDOWN_PCT",
                "PORTFOLIO_MIN_ORDER_VALUE",
                "PORTFOLIO_MAX_ORDER_VALUE",
            ]
        }
        # patch.dict with values=None removes the keys for the duration of the block
        with patch.dict(os.environ, {}, clear=False):
            for key in env_strip:
                os.environ.pop(key, None)
            result = _ps.get_portfolio_config()

        cfg = result["config"]
        assert result["loaded"] is True

        assert cfg["max_instrument_exposure_pct"] == pytest.approx(0.20), (
            "Default max_instrument_exposure_pct must be 0.20"
        )
        assert cfg["max_sector_exposure_pct"] == pytest.approx(0.35), (
            "Default max_sector_exposure_pct must be 0.35"
        )
        assert cfg["max_portfolio_exposure_pct"] == pytest.approx(0.90), (
            "Default max_portfolio_exposure_pct must be 0.90"
        )
        assert cfg["initial_capital"] == pytest.approx(100_000.0), (
            "Default initial_capital must be 100 000"
        )
        assert cfg["max_open_positions"] == 10, (
            "Default max_open_positions must be 10"
        )

    # ── 2. Env-var overrides are reflected in the returned values ────────────

    def test_env_var_overrides_instrument_limit(self):
        """PORTFOLIO_MAX_INSTRUMENT_PCT env var must override the returned value."""
        import os
        import importlib
        import portfolio_snapshot as _ps

        with patch.dict(os.environ, {"PORTFOLIO_MAX_INSTRUMENT_PCT": "0.15"}):
            # Reload the module so the default_factory lambdas pick up the new env
            importlib.reload(_ps)
            result = _ps.get_portfolio_config()

        # Reload back to clean state
        importlib.reload(_ps)

        cfg = result["config"]
        assert result["loaded"] is True
        assert cfg["max_instrument_exposure_pct"] == pytest.approx(0.15), (
            "PORTFOLIO_MAX_INSTRUMENT_PCT=0.15 must appear in config response"
        )

    def test_env_var_overrides_sector_limit(self):
        """PORTFOLIO_MAX_SECTOR_PCT env var must override the returned value."""
        import os
        import importlib
        import portfolio_snapshot as _ps

        with patch.dict(os.environ, {"PORTFOLIO_MAX_SECTOR_PCT": "0.25"}):
            importlib.reload(_ps)
            result = _ps.get_portfolio_config()

        importlib.reload(_ps)

        cfg = result["config"]
        assert result["loaded"] is True
        assert cfg["max_sector_exposure_pct"] == pytest.approx(0.25), (
            "PORTFOLIO_MAX_SECTOR_PCT=0.25 must appear in config response"
        )

    def test_env_var_overrides_initial_capital(self):
        """PORTFOLIO_INITIAL_CAPITAL env var must override the returned value."""
        import os
        import importlib
        import portfolio_snapshot as _ps

        with patch.dict(os.environ, {"PORTFOLIO_INITIAL_CAPITAL": "250000"}):
            importlib.reload(_ps)
            result = _ps.get_portfolio_config()

        importlib.reload(_ps)

        cfg = result["config"]
        assert result["loaded"] is True
        assert cfg["initial_capital"] == pytest.approx(250_000.0), (
            "PORTFOLIO_INITIAL_CAPITAL=250000 must appear in config response"
        )

    def test_env_var_overrides_max_open_positions(self):
        """PORTFOLIO_MAX_OPEN_POSITIONS env var must override the returned integer."""
        import os
        import importlib
        import portfolio_snapshot as _ps

        with patch.dict(os.environ, {"PORTFOLIO_MAX_OPEN_POSITIONS": "5"}):
            importlib.reload(_ps)
            result = _ps.get_portfolio_config()

        importlib.reload(_ps)

        cfg = result["config"]
        assert result["loaded"] is True
        assert cfg["max_open_positions"] == 5, (
            "PORTFOLIO_MAX_OPEN_POSITIONS=5 must appear in config response"
        )

    # ── 3. Fallback path: PortfolioConfig import fails ───────────────────────

    def test_loaded_false_when_import_fails(self):
        """get_portfolio_config() must return loaded=False when PortfolioConfig raises."""
        import portfolio_snapshot as _ps

        mock_cfg_module = MagicMock()
        mock_cfg_module.PortfolioConfig.side_effect = ImportError("blocked for test")

        with patch.dict(sys.modules, {"src.portfolio.config": mock_cfg_module}):
            result = _ps.get_portfolio_config()

        assert result["loaded"] is False, (
            f"Expected loaded=False on import failure, got {result['loaded']!r}"
        )

    def test_config_empty_dict_when_import_fails(self):
        """config must be an empty dict when PortfolioConfig raises."""
        import portfolio_snapshot as _ps

        mock_cfg_module = MagicMock()
        mock_cfg_module.PortfolioConfig.side_effect = ImportError("blocked for test")

        with patch.dict(sys.modules, {"src.portfolio.config": mock_cfg_module}):
            result = _ps.get_portfolio_config()

        assert result["config"] == {}, (
            f"Expected config={{}} on import failure, got {result['config']!r}"
        )

    def test_limits_from_config_false_when_import_fails(self):
        """limits_from_config must be False when PortfolioConfig raises."""
        import portfolio_snapshot as _ps

        mock_cfg_module = MagicMock()
        mock_cfg_module.PortfolioConfig.side_effect = ImportError("blocked for test")

        with patch.dict(sys.modules, {"src.portfolio.config": mock_cfg_module}):
            result = _ps.get_portfolio_config()

        assert result["limits_from_config"] is False

    def test_error_field_populated_when_import_fails(self):
        """error field must be a non-empty string when PortfolioConfig raises."""
        import portfolio_snapshot as _ps

        mock_cfg_module = MagicMock()
        mock_cfg_module.PortfolioConfig.side_effect = ImportError("test-sentinel-error")

        with patch.dict(sys.modules, {"src.portfolio.config": mock_cfg_module}):
            result = _ps.get_portfolio_config()

        assert result.get("error") is not None, "error must be set on import failure"
        assert isinstance(result["error"], str) and len(result["error"]) > 0

    # ── 4. Response structure is always present ───────────────────────────────

    def test_response_always_has_fetched_at(self):
        """fetched_at must always be present regardless of success or failure."""
        import portfolio_snapshot as _ps

        # Success path
        result_ok = _ps.get_portfolio_config()
        assert "fetched_at" in result_ok

        # Failure path
        mock_cfg_module = MagicMock()
        mock_cfg_module.PortfolioConfig.side_effect = ImportError("blocked")
        with patch.dict(sys.modules, {"src.portfolio.config": mock_cfg_module}):
            result_fail = _ps.get_portfolio_config()
        assert "fetched_at" in result_fail

    def test_error_is_none_on_success(self):
        """error field must be None when PortfolioConfig loads without exception."""
        import portfolio_snapshot as _ps

        result = _ps.get_portfolio_config()

        assert result["loaded"] is True
        assert result.get("error") is None, (
            f"error must be None on success, got {result.get('error')!r}"
        )


# ── Notification dedup tests ─────────────────────────────────────────────────


class TestConfigDefaultsNotificationDedup:
    """
    get_portfolio_health() must emit a config-defaults alert to the operator
    inbox exactly once per UTC day, no more, no less.

    All tests use a mocked phase20_store — no real DB is touched.
    """

    # ── Shared fixtures ──────────────────────────────────────────────────────

    @staticmethod
    def _base_sys_mocks(mock_cfg_module, mock_store) -> dict:
        """Return the sys.modules patch dict common to all dedup tests."""
        paper_trader = MagicMock()
        paper_trader._load_state.return_value = {
            "cash": 100_000.0,
            "initial_capital": 100_000.0,
            "positions": {},
            "last_updated": "2024-01-01T00:00:00+00:00",
        }
        return {
            "phase22_activation": MagicMock(
                get_activation_status=MagicMock(
                    return_value={"paper_automation_active": False}
                )
            ),
            "paper_trader": paper_trader,
            "eod_reconciliation": MagicMock(
                get_reconciliation_status=MagicMock(
                    return_value={"unresolved_count": 0}
                )
            ),
            "src.portfolio.config": mock_cfg_module,
            "phase20_store": mock_store,
        }

    @staticmethod
    def _make_broken_cfg() -> MagicMock:
        """A mock cfg module whose PortfolioConfig raises ImportError."""
        m = MagicMock()
        m.PortfolioConfig.side_effect = ImportError("simulated missing config")
        return m

    # ── 1. add_notification called exactly once on first miss ────────────────

    def test_add_notification_called_once_on_first_miss(self):
        """
        When PortfolioConfig is missing and no alert has been sent today,
        add_notification must be called exactly once.
        """
        import portfolio_snapshot as _ps

        store = MagicMock()
        store.kv_get.return_value = None          # never sent today
        store.kv_set.return_value = None
        store.add_notification.return_value = None

        mocks = self._base_sys_mocks(self._make_broken_cfg(), store)

        with patch.dict(sys.modules, mocks):
            _ps.get_portfolio_health()

        store.add_notification.assert_called_once()

    # ── 2. add_notification NOT called on second poll same day ───────────────

    def test_add_notification_not_called_when_already_sent_today(self):
        """
        When kv_get returns today's date string (alert already sent today),
        add_notification must NOT be called on a subsequent poll.
        """
        import portfolio_snapshot as _ps
        from datetime import datetime, timezone

        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        store = MagicMock()
        store.kv_get.return_value = today_utc     # already sent today
        store.kv_set.return_value = None
        store.add_notification.return_value = None

        mocks = self._base_sys_mocks(self._make_broken_cfg(), store)

        with patch.dict(sys.modules, mocks):
            _ps.get_portfolio_health()

        store.add_notification.assert_not_called()

    # ── 3. add_notification called when kv_get returns yesterday ────────────

    def test_add_notification_called_again_next_day(self):
        """
        When kv_get returns yesterday's date (alert was sent yesterday but not
        yet today), add_notification must fire again for the new UTC day.
        """
        import portfolio_snapshot as _ps
        from datetime import datetime, timezone, timedelta

        yesterday_utc = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%d")

        store = MagicMock()
        store.kv_get.return_value = yesterday_utc  # sent yesterday, not today
        store.kv_set.return_value = None
        store.add_notification.return_value = None

        mocks = self._base_sys_mocks(self._make_broken_cfg(), store)

        with patch.dict(sys.modules, mocks):
            _ps.get_portfolio_health()

        store.add_notification.assert_called_once()

    # ── 4. kv_set is called with today's date after emitting the alert ───────

    def test_kv_set_records_today_after_alert(self):
        """
        After firing the alert, kv_set must be called with the
        _ALERT_DEDUP_KEY and today's UTC date so the next poll is deduped.
        """
        import portfolio_snapshot as _ps
        from datetime import datetime, timezone

        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        store = MagicMock()
        store.kv_get.return_value = None          # first time today
        store.kv_set.return_value = None
        store.add_notification.return_value = None

        mocks = self._base_sys_mocks(self._make_broken_cfg(), store)

        with patch.dict(sys.modules, mocks):
            _ps.get_portfolio_health()

        # kv_set must have been called with the dedup key and today's date.
        store.kv_set.assert_called_once()
        _call_args = store.kv_set.call_args
        assert _call_args is not None
        positional = _call_args.args if hasattr(_call_args, "args") else _call_args[0]
        assert positional[1] == today_utc, (
            f"kv_set must record today's date {today_utc!r}; got {positional[1]!r}"
        )

    # ── 5. No notification when PortfolioConfig loads successfully ────────────

    def test_no_notification_when_config_loads_ok(self):
        """
        When PortfolioConfig imports and initialises without error,
        add_notification must NOT be called at all.
        """
        import portfolio_snapshot as _ps

        # Use the real src.portfolio.config (available in this env)
        store = MagicMock()
        store.kv_get.return_value = None
        store.kv_set.return_value = None
        store.add_notification.return_value = None

        paper_trader = MagicMock()
        paper_trader._load_state.return_value = {
            "cash": 100_000.0,
            "initial_capital": 100_000.0,
            "positions": {},
            "last_updated": "2024-01-01T00:00:00+00:00",
        }

        with patch.dict(sys.modules, {
            "phase22_activation": MagicMock(
                get_activation_status=MagicMock(
                    return_value={"paper_automation_active": False}
                )
            ),
            "paper_trader": paper_trader,
            "eod_reconciliation": MagicMock(
                get_reconciliation_status=MagicMock(
                    return_value={"unresolved_count": 0}
                )
            ),
            # Do NOT patch src.portfolio.config — let the real one load
            "phase20_store": store,
        }):
            _ps.get_portfolio_health()

        store.add_notification.assert_not_called()

    # ── 6. A broken notification store must not crash the health endpoint ─────

    def test_broken_store_does_not_raise(self):
        """
        If phase20_store raises on add_notification or kv_get, get_portfolio_health()
        must still return a valid response (best-effort notification).
        """
        import portfolio_snapshot as _ps

        store = MagicMock()
        store.kv_get.side_effect = RuntimeError("DB is down")
        store.kv_set.side_effect = RuntimeError("DB is down")
        store.add_notification.side_effect = RuntimeError("DB is down")

        mocks = self._base_sys_mocks(self._make_broken_cfg(), store)

        with patch.dict(sys.modules, mocks):
            result = _ps.get_portfolio_health()

        # Must return a valid dict with the expected keys
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "DEGRADED"

    # ── 7. Two calls within the same day emit only one notification ───────────

    def test_two_calls_same_day_emit_one_notification(self):
        """
        Simulate two consecutive health polls within the same UTC day.
        The first call should emit the alert; the second must be deduped.
        """
        import portfolio_snapshot as _ps
        from datetime import datetime, timezone

        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sent_value: list = [None]   # mutable cell for the stored kv value

        def kv_get_side_effect(key, default=None):
            return sent_value[0]

        def kv_set_side_effect(key, value):
            sent_value[0] = value

        store = MagicMock()
        store.kv_get.side_effect = kv_get_side_effect
        store.kv_set.side_effect = kv_set_side_effect
        store.add_notification.return_value = None

        mocks = self._base_sys_mocks(self._make_broken_cfg(), store)

        with patch.dict(sys.modules, mocks):
            _ps.get_portfolio_health()   # first call → should emit
            _ps.get_portfolio_health()   # second call → should be deduped

        assert store.add_notification.call_count == 1, (
            f"Expected add_notification to be called exactly once across two "
            f"same-day polls, but it was called {store.add_notification.call_count} time(s)"
        )
