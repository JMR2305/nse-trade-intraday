"""Unit tests for PortfolioConfig (config.py).

Covers:
  - Default construction
  - paper_mode=False → ValueError
  - min_order_value >= max_order_value → ValueError
  - cash_reserve_pct + max_portfolio_exposure_pct > 1.0 → ValueError
  - Percentage out of (0,1] → ValueError
  - Convenience methods: reserve_amount, max_deployable, risk_amount
  - Env-var-driven bad values (e.g. PORTFOLIO_MAX_INSTRUMENT_PCT=20) → ValidationError
"""
from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.portfolio.config import PortfolioConfig, DEFAULT_CONFIG


class TestDefaultConstruction:
    def test_default_config_constructs(self):
        """Default PortfolioConfig should construct without errors."""
        cfg = PortfolioConfig()
        assert cfg.paper_mode is True

    def test_default_capital(self):
        """Default initial_capital is 100000."""
        cfg = PortfolioConfig()
        assert cfg.initial_capital == Decimal("100000")

    def test_default_currency(self):
        """Default base_currency is INR."""
        cfg = PortfolioConfig()
        assert cfg.base_currency == "INR"

    def test_default_singleton_importable(self):
        """DEFAULT_CONFIG is a valid PortfolioConfig."""
        assert isinstance(DEFAULT_CONFIG, PortfolioConfig)
        assert DEFAULT_CONFIG.paper_mode is True

    def test_frozen(self):
        """PortfolioConfig is frozen — mutation must raise."""
        cfg = PortfolioConfig()
        with pytest.raises((ValidationError, TypeError)):
            cfg.initial_capital = Decimal("999")


class TestPaperModeEnforcement:
    def test_paper_mode_false_raises(self):
        """paper_mode=False must raise ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioConfig(paper_mode=False)

    def test_paper_mode_true_succeeds(self):
        """paper_mode=True is the only valid value."""
        cfg = PortfolioConfig(paper_mode=True)
        assert cfg.paper_mode is True


class TestOrderValueConsistency:
    def test_min_equals_max_raises(self):
        """min_order_value == max_order_value → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioConfig(
                min_order_value=Decimal("5000"),
                max_order_value=Decimal("5000"),
            )

    def test_min_greater_than_max_raises(self):
        """min_order_value > max_order_value → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioConfig(
                min_order_value=Decimal("50000"),
                max_order_value=Decimal("10000"),
            )

    def test_valid_min_less_than_max(self):
        """min_order_value < max_order_value is valid."""
        cfg = PortfolioConfig(
            min_order_value=Decimal("1000"),
            max_order_value=Decimal("50000"),
        )
        assert cfg.min_order_value < cfg.max_order_value


class TestExposureReserveConsistency:
    def test_reserve_plus_exposure_over_one_raises(self):
        """cash_reserve_pct + max_portfolio_exposure_pct > 1.0 → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioConfig(
                cash_reserve_pct=Decimal("0.20"),
                max_portfolio_exposure_pct=Decimal("0.90"),
            )

    def test_reserve_plus_exposure_exactly_one_allowed(self):
        """cash_reserve_pct + max_portfolio_exposure_pct == 1.0 is allowed."""
        cfg = PortfolioConfig(
            cash_reserve_pct=Decimal("0.10"),
            max_portfolio_exposure_pct=Decimal("0.90"),
        )
        assert cfg.cash_reserve_pct + cfg.max_portfolio_exposure_pct == Decimal("1.0")


class TestPercentageValidation:
    def test_cash_reserve_zero_raises(self):
        """cash_reserve_pct = 0 is not in (0,1] → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioConfig(cash_reserve_pct=Decimal("0"))

    def test_cash_reserve_over_one_raises(self):
        """cash_reserve_pct > 1 → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioConfig(cash_reserve_pct=Decimal("1.1"))

    def test_max_daily_loss_zero_raises(self):
        """max_daily_loss_pct = 0 → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioConfig(max_daily_loss_pct=Decimal("0"))

    def test_max_drawdown_over_one_raises(self):
        """max_drawdown_pct > 1 → ValueError."""
        with pytest.raises((ValueError, ValidationError)):
            PortfolioConfig(max_drawdown_pct=Decimal("1.5"))


class TestConvenienceMethods:
    def test_reserve_amount(self):
        """reserve_amount(equity) = equity * cash_reserve_pct."""
        cfg = PortfolioConfig(cash_reserve_pct=Decimal("0.05"))
        equity = Decimal("100000")
        expected = (equity * Decimal("0.05")).quantize(Decimal("0.01"))
        assert cfg.reserve_amount(equity) == expected

    def test_max_deployable(self):
        """max_deployable(equity) = equity * max_portfolio_exposure_pct."""
        cfg = PortfolioConfig(max_portfolio_exposure_pct=Decimal("0.90"))
        equity = Decimal("100000")
        expected = (equity * Decimal("0.90")).quantize(Decimal("0.01"))
        assert cfg.max_deployable(equity) == expected

    def test_risk_amount(self):
        """risk_amount(equity) = equity * default_risk_per_trade_pct."""
        cfg = PortfolioConfig(default_risk_per_trade_pct=Decimal("0.01"))
        equity = Decimal("100000")
        expected = (equity * Decimal("0.01")).quantize(Decimal("0.01"))
        assert cfg.risk_amount(equity) == expected

    def test_max_instrument_value(self):
        """max_instrument_value uses max_instrument_exposure_pct."""
        cfg = PortfolioConfig(max_instrument_exposure_pct=Decimal("0.20"))
        assert cfg.max_instrument_value(Decimal("100000")) == Decimal("20000.00")

    def test_max_sector_value(self):
        """max_sector_value uses max_sector_exposure_pct."""
        cfg = PortfolioConfig(max_sector_exposure_pct=Decimal("0.35"))
        assert cfg.max_sector_value(Decimal("100000")) == Decimal("35000.00")

    def test_max_daily_loss_amount(self):
        """max_daily_loss_amount = equity * max_daily_loss_pct."""
        cfg = PortfolioConfig(max_daily_loss_pct=Decimal("0.03"))
        assert cfg.max_daily_loss_amount(Decimal("100000")) == Decimal("3000.00")

    def test_max_drawdown_amount(self):
        """max_drawdown_amount = peak_equity * max_drawdown_pct."""
        cfg = PortfolioConfig(max_drawdown_pct=Decimal("0.10"))
        assert cfg.max_drawdown_amount(Decimal("100000")) == Decimal("10000.00")


class TestEnvVarValidation:
    """Confirm that bad env var values are rejected at PortfolioConfig construction time.

    These tests guard against operators mistyping percentage fields as whole
    numbers (e.g. PORTFOLIO_MAX_INSTRUMENT_PCT=20 meaning 2000 % instead of
    0.20) or inverting order-value limits.  Each case must raise ValidationError
    immediately on construction so the misconfiguration is surfaced to the
    operator rather than silently applied.
    """

    # ── Percentage env vars: value > 1 must be rejected ─────────────────────

    def test_instrument_pct_env_var_greater_than_one_raises(self):
        """PORTFOLIO_MAX_INSTRUMENT_PCT=20 (2000%) must be rejected at construction."""
        with patch.dict(os.environ, {"PORTFOLIO_MAX_INSTRUMENT_PCT": "20"}):
            with pytest.raises(ValidationError, match="max_instrument_exposure_pct"):
                PortfolioConfig()

    def test_sector_pct_env_var_greater_than_one_raises(self):
        """PORTFOLIO_MAX_SECTOR_PCT=35 (3500%) must be rejected at construction."""
        with patch.dict(os.environ, {"PORTFOLIO_MAX_SECTOR_PCT": "35"}):
            with pytest.raises(ValidationError, match="max_sector_exposure_pct"):
                PortfolioConfig()

    def test_portfolio_exposure_pct_env_var_greater_than_one_raises(self):
        """PORTFOLIO_MAX_EXPOSURE_PCT=2 (200%) must be rejected at construction."""
        with patch.dict(os.environ, {"PORTFOLIO_MAX_EXPOSURE_PCT": "2"}):
            with pytest.raises(ValidationError, match="max_portfolio_exposure_pct"):
                PortfolioConfig()

    def test_strategy_pct_env_var_greater_than_one_raises(self):
        """PORTFOLIO_MAX_STRATEGY_PCT=1.5 (150%) must be rejected at construction."""
        with patch.dict(os.environ, {"PORTFOLIO_MAX_STRATEGY_PCT": "1.5"}):
            with pytest.raises(ValidationError, match="max_strategy_exposure_pct"):
                PortfolioConfig()

    def test_daily_loss_pct_env_var_greater_than_one_raises(self):
        """PORTFOLIO_MAX_DAILY_LOSS_PCT=3 (300%) must be rejected at construction."""
        with patch.dict(os.environ, {"PORTFOLIO_MAX_DAILY_LOSS_PCT": "3"}):
            with pytest.raises(ValidationError, match="max_daily_loss_pct"):
                PortfolioConfig()

    def test_drawdown_pct_env_var_greater_than_one_raises(self):
        """PORTFOLIO_MAX_DRAWDOWN_PCT=10 (1000%) must be rejected at construction."""
        with patch.dict(os.environ, {"PORTFOLIO_MAX_DRAWDOWN_PCT": "10"}):
            with pytest.raises(ValidationError, match="max_drawdown_pct"):
                PortfolioConfig()

    def test_cash_reserve_pct_env_var_greater_than_one_raises(self):
        """PORTFOLIO_CASH_RESERVE_PCT=5 (500%) must be rejected at construction."""
        with patch.dict(os.environ, {"PORTFOLIO_CASH_RESERVE_PCT": "5"}):
            with pytest.raises(ValidationError, match="cash_reserve_pct"):
                PortfolioConfig()

    def test_risk_per_trade_pct_env_var_greater_than_one_raises(self):
        """PORTFOLIO_RISK_PER_TRADE_PCT=2 (200%) must be rejected at construction."""
        with patch.dict(os.environ, {"PORTFOLIO_RISK_PER_TRADE_PCT": "2"}):
            with pytest.raises(ValidationError, match="default_risk_per_trade_pct"):
                PortfolioConfig()

    # ── Percentage env vars: value of zero must be rejected ──────────────────

    def test_instrument_pct_env_var_zero_raises(self):
        """PORTFOLIO_MAX_INSTRUMENT_PCT=0 must be rejected (must be > 0)."""
        with patch.dict(os.environ, {"PORTFOLIO_MAX_INSTRUMENT_PCT": "0"}):
            with pytest.raises(ValidationError, match="max_instrument_exposure_pct"):
                PortfolioConfig()

    def test_cash_reserve_pct_env_var_zero_raises(self):
        """PORTFOLIO_CASH_RESERVE_PCT=0 must be rejected (must be > 0)."""
        with patch.dict(os.environ, {"PORTFOLIO_CASH_RESERVE_PCT": "0"}):
            with pytest.raises(ValidationError, match="cash_reserve_pct"):
                PortfolioConfig()

    # ── Order-value consistency via env vars ──────────────────────────────────

    def test_min_order_value_env_var_exceeds_max_raises(self):
        """min_order_value > max_order_value via env vars must raise at construction."""
        with patch.dict(os.environ, {
            "PORTFOLIO_MIN_ORDER_VALUE": "50000",
            "PORTFOLIO_MAX_ORDER_VALUE": "5000",
        }):
            with pytest.raises(ValidationError):
                PortfolioConfig()

    def test_min_order_value_env_var_equals_max_raises(self):
        """min_order_value == max_order_value via env vars must raise at construction."""
        with patch.dict(os.environ, {
            "PORTFOLIO_MIN_ORDER_VALUE": "10000",
            "PORTFOLIO_MAX_ORDER_VALUE": "10000",
        }):
            with pytest.raises(ValidationError):
                PortfolioConfig()

    # ── Valid env-var overrides still construct successfully ──────────────────

    def test_valid_instrument_pct_env_var_succeeds(self):
        """PORTFOLIO_MAX_INSTRUMENT_PCT=0.15 (15%) is valid and must construct."""
        with patch.dict(os.environ, {"PORTFOLIO_MAX_INSTRUMENT_PCT": "0.15"}):
            cfg = PortfolioConfig()
        assert cfg.max_instrument_exposure_pct == Decimal("0.15")

    def test_valid_sector_pct_env_var_succeeds(self):
        """PORTFOLIO_MAX_SECTOR_PCT=0.25 (25%) is valid and must construct."""
        with patch.dict(os.environ, {"PORTFOLIO_MAX_SECTOR_PCT": "0.25"}):
            cfg = PortfolioConfig()
        assert cfg.max_sector_exposure_pct == Decimal("0.25")

    def test_valid_order_value_env_vars_succeed(self):
        """MIN < MAX via env vars is valid."""
        with patch.dict(os.environ, {
            "PORTFOLIO_MIN_ORDER_VALUE": "2000",
            "PORTFOLIO_MAX_ORDER_VALUE": "100000",
        }):
            cfg = PortfolioConfig()
        assert cfg.min_order_value < cfg.max_order_value
