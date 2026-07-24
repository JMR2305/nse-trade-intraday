"""Unit tests for PortfolioConfig (config.py).

Covers:
  - Default construction
  - paper_mode=False → ValueError
  - min_order_value >= max_order_value → ValueError
  - cash_reserve_pct + max_portfolio_exposure_pct > 1.0 → ValueError
  - Percentage out of (0,1] → ValueError
  - Convenience methods: reserve_amount, max_deployable, risk_amount
"""
from __future__ import annotations

from decimal import Decimal

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
