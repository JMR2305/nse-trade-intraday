"""RC-10C1 Portfolio Core — immutable validated configuration.

PortfolioConfig is frozen on construction; live changes require a restart.
All percentage fields are validated to [0, 1].  Inconsistent limit
combinations (e.g. min_order_value >= max_order_value) are rejected.

No live-mode activation logic lives here.  paper_mode=True is enforced
by the model validator and cannot be overridden programmatically in this
RC batch.

Implementation note — validate_default=True on percentage fields
----------------------------------------------------------------
Pydantic v2 does NOT run field_validators on values that come from a
``default_factory`` unless the Field is marked ``validate_default=True``.
Because every percentage field reads its value from an env var via a
``default_factory`` lambda, omitting this flag would let a mis-typed env
var (e.g. PORTFOLIO_MAX_INSTRUMENT_PCT=20 meaning 2000 % instead of 0.20)
silently bypass the _pct_range validator.  All percentage and capital
fields therefore carry ``validate_default=True`` so the range check fires
whether the value comes from an env var, a default, or a direct kwarg.
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _env_decimal(key: str, default: str) -> Decimal:
    return Decimal(os.environ.get(key, default))


def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, str(default)))


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, "")
    if not v:
        return default
    return v.strip().lower() in {"1", "true", "yes"}


class PortfolioConfig(BaseModel):
    """Immutable validated portfolio configuration.

    Defaults are safe for paper-trading.  Override via environment
    variables (prefixed PORTFOLIO_) or direct construction kwargs.
    """
    model_config = ConfigDict(frozen=True)

    # ── Identity ──────────────────────────────────────────────────────
    portfolio_id: str = Field(
        default_factory=lambda: os.environ.get("PORTFOLIO_ID", "default"),
    )
    enabled: bool = Field(
        default_factory=lambda: _env_bool("PORTFOLIO_ENABLED", True),
    )
    base_currency: str = Field(
        default_factory=lambda: os.environ.get("PORTFOLIO_BASE_CURRENCY", "INR"),
    )

    # ── Capital ───────────────────────────────────────────────────────
    initial_capital: Decimal = Field(
        # Default aligned with the canonical paper-trading capital (₹100,000,
        # see portfolio_store.INITIAL_CAPITAL). Override via env if needed.
        default_factory=lambda: _env_decimal("PORTFOLIO_INITIAL_CAPITAL", "100000"),
        description="Starting capital in base_currency",
        validate_default=True,
    )
    cash_reserve_pct: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_CASH_RESERVE_PCT", "0.05"),
        description="Fraction of capital that must always remain free (0–1)",
        validate_default=True,
    )

    # ── Exposure limits ───────────────────────────────────────────────
    max_portfolio_exposure_pct: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_MAX_EXPOSURE_PCT", "0.90"),
        description="Max gross exposure as fraction of portfolio equity",
        validate_default=True,
    )
    max_instrument_exposure_pct: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_MAX_INSTRUMENT_PCT", "0.20"),
        description="Max single-instrument exposure as fraction of portfolio equity",
        validate_default=True,
    )
    max_sector_exposure_pct: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_MAX_SECTOR_PCT", "0.35"),
        description="Max sector exposure as fraction of portfolio equity",
        validate_default=True,
    )
    max_strategy_exposure_pct: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_MAX_STRATEGY_PCT", "0.40"),
        description="Max strategy exposure as fraction of portfolio equity",
        validate_default=True,
    )

    # ── Position / order counts ───────────────────────────────────────
    max_open_positions: int = Field(
        default_factory=lambda: _env_int("PORTFOLIO_MAX_OPEN_POSITIONS", 10),
        ge=1,
    )
    max_pending_orders: int = Field(
        default_factory=lambda: _env_int("PORTFOLIO_MAX_PENDING_ORDERS", 20),
        ge=1,
    )

    # ── Loss / drawdown caps ──────────────────────────────────────────
    max_daily_loss_pct: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_MAX_DAILY_LOSS_PCT", "0.03"),
        description="Max daily loss as fraction of capital; triggers allocation block",
        validate_default=True,
    )
    max_drawdown_pct: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_MAX_DRAWDOWN_PCT", "0.10"),
        description="Max drawdown from peak equity as fraction; triggers halt",
        validate_default=True,
    )
    max_capital_per_strategy_pct: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_MAX_CAPITAL_PER_STRATEGY_PCT", "0.40"),
        description="Max capital allocatable to a single strategy",
        validate_default=True,
    )

    # ── Position sizing ───────────────────────────────────────────────
    default_risk_per_trade_pct: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_RISK_PER_TRADE_PCT", "0.01"),
        description="Default risk per trade as fraction of capital",
        validate_default=True,
    )
    min_order_value: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_MIN_ORDER_VALUE", "5000"),
        description="Minimum acceptable order value in base_currency",
        validate_default=True,
    )
    max_order_value: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_MAX_ORDER_VALUE", "50000"),
        description="Maximum acceptable order value in base_currency",
        validate_default=True,
    )
    use_ai_confidence_sizing: bool = Field(
        default_factory=lambda: _env_bool("PORTFOLIO_USE_AI_CONFIDENCE", False),
        description="Advisory: if True, signal_confidence scales approved quantity",
    )
    ai_confidence_min: Decimal = Field(
        default_factory=lambda: _env_decimal("PORTFOLIO_AI_CONFIDENCE_MIN", "0.5"),
        description="Minimum confidence for AI sizing to have any effect",
        validate_default=True,
    )

    # ── Staleness thresholds ──────────────────────────────────────────
    stale_state_threshold_s: float = Field(
        default_factory=lambda: float(os.environ.get("PORTFOLIO_STALE_STATE_S", "60")),
        description="Portfolio state older than this (seconds) is stale",
    )
    stale_broker_threshold_s: float = Field(
        default_factory=lambda: float(os.environ.get("PORTFOLIO_STALE_BROKER_S", "120")),
        description="Broker snapshot older than this (seconds) is stale",
    )
    stale_price_threshold_s: float = Field(
        default_factory=lambda: float(os.environ.get("PORTFOLIO_STALE_PRICE_S", "30")),
        description="Market price older than this (seconds) is stale",
    )

    # ── Intervals ────────────────────────────────────────────────────
    reconciliation_interval_s: float = Field(
        default_factory=lambda: float(
            os.environ.get("PORTFOLIO_RECONCILIATION_INTERVAL_S", "300")
        ),
    )
    snapshot_interval_s: float = Field(
        default_factory=lambda: float(
            os.environ.get("PORTFOLIO_SNAPSHOT_INTERVAL_S", "60")
        ),
    )
    allocation_ttl_s: float = Field(
        default_factory=lambda: float(
            os.environ.get("PORTFOLIO_ALLOCATION_TTL_S", "30")
        ),
        description="AllocationDecision expires after this many seconds",
    )

    # ── Safety ───────────────────────────────────────────────────────
    paper_mode: bool = Field(
        default=True,
        description="Must remain True; live mode is structurally disabled in RC-10C",
    )

    # ── Validators ───────────────────────────────────────────────────

    @field_validator(
        "cash_reserve_pct",
        "max_portfolio_exposure_pct",
        "max_instrument_exposure_pct",
        "max_sector_exposure_pct",
        "max_strategy_exposure_pct",
        "max_daily_loss_pct",
        "max_drawdown_pct",
        "max_capital_per_strategy_pct",
        "default_risk_per_trade_pct",
        "max_capital_per_strategy_pct",
        "ai_confidence_min",
        mode="after",
    )
    @classmethod
    def _pct_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") < v <= Decimal("1")):
            raise ValueError(f"Percentage must be in (0, 1], got {v}")
        return v

    @field_validator("initial_capital", "min_order_value", "max_order_value", mode="after")
    @classmethod
    def _positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError(f"Value must be positive, got {v}")
        return v

    @model_validator(mode="after")
    def _validate_consistency(self) -> "PortfolioConfig":
        if not self.paper_mode:
            raise ValueError(
                "paper_mode must be True — live trading is structurally disabled in RC-10C1"
            )
        if self.min_order_value >= self.max_order_value:
            raise ValueError(
                f"min_order_value ({self.min_order_value}) must be < max_order_value ({self.max_order_value})"
            )
        if self.cash_reserve_pct + self.max_portfolio_exposure_pct > Decimal("1"):
            raise ValueError(
                "cash_reserve_pct + max_portfolio_exposure_pct must not exceed 1.0"
            )
        return self

    # ── Convenience ──────────────────────────────────────────────────

    def reserve_amount(self, equity: Decimal) -> Decimal:
        """Minimum cash that must remain free."""
        return (equity * self.cash_reserve_pct).quantize(Decimal("0.01"))

    def max_deployable(self, equity: Decimal) -> Decimal:
        """Maximum capital that may be deployed at once."""
        return (equity * self.max_portfolio_exposure_pct).quantize(Decimal("0.01"))

    def max_instrument_value(self, equity: Decimal) -> Decimal:
        return (equity * self.max_instrument_exposure_pct).quantize(Decimal("0.01"))

    def max_sector_value(self, equity: Decimal) -> Decimal:
        return (equity * self.max_sector_exposure_pct).quantize(Decimal("0.01"))

    def max_strategy_value(self, equity: Decimal) -> Decimal:
        return (equity * self.max_strategy_exposure_pct).quantize(Decimal("0.01"))

    def max_daily_loss_amount(self, equity: Decimal) -> Decimal:
        return (equity * self.max_daily_loss_pct).quantize(Decimal("0.01"))

    def max_drawdown_amount(self, peak_equity: Decimal) -> Decimal:
        return (peak_equity * self.max_drawdown_pct).quantize(Decimal("0.01"))

    def risk_amount(self, equity: Decimal) -> Decimal:
        return (equity * self.default_risk_per_trade_pct).quantize(Decimal("0.01"))


# Default singleton — modules may import this directly or construct their own.
DEFAULT_CONFIG = PortfolioConfig()
