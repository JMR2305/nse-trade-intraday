"""RC-10C1: Portfolio configuration — immutable, validated, safe defaults."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _d(v: str) -> Decimal:
    return Decimal(v)


class PortfolioConfig(BaseModel):
    """Immutable portfolio configuration with safe defaults.

    paper_mode must always be True in this release — live trading is not enabled.
    """
    model_config = ConfigDict(frozen=True)

    # ── Identity ──────────────────────────────────────────────────────────
    portfolio_id: str = Field("default")
    enabled: bool = Field(True)
    paper_mode: bool = Field(True, description="Must always be True in RC-10C1")
    base_currency: str = Field("INR")

    # ── Capital ───────────────────────────────────────────────────────────
    initial_capital: Decimal = Field(_d("100000"), gt=Decimal("0"))
    cash_reserve_percentage: Decimal = Field(
        _d("0.05"), ge=Decimal("0"), le=Decimal("1"),
        description="Fraction of capital kept uninvested (0–1)",
    )

    # ── Exposure limits ───────────────────────────────────────────────────
    maximum_portfolio_exposure: Decimal = Field(
        _d("0.95"), gt=Decimal("0"), le=Decimal("1"),
        description="Max gross exposure as fraction of equity (0–1)",
    )
    maximum_instrument_exposure: Decimal = Field(
        _d("0.20"), gt=Decimal("0"), le=Decimal("1"),
    )
    maximum_sector_exposure: Decimal = Field(
        _d("0.40"), gt=Decimal("0"), le=Decimal("1"),
    )
    maximum_strategy_exposure: Decimal = Field(
        _d("0.50"), gt=Decimal("0"), le=Decimal("1"),
    )

    # ── Position / order counts ───────────────────────────────────────────
    maximum_open_positions: int = Field(10, gt=0)
    maximum_pending_orders: int = Field(20, gt=0)

    # ── Loss / drawdown ────────────────────────────────────────────────────
    maximum_daily_loss: Decimal = Field(
        _d("5000"), gt=Decimal("0"),
        description="Max daily loss in base currency before halting new allocations",
    )
    maximum_drawdown: Decimal = Field(
        _d("0.15"), gt=Decimal("0"), le=Decimal("1"),
        description="Max drawdown from peak equity as fraction (0–1)",
    )

    # ── Risk per trade ────────────────────────────────────────────────────
    default_risk_per_trade: Decimal = Field(
        _d("0.01"), gt=Decimal("0"), le=Decimal("0.10"),
        description="Default risk as fraction of capital per trade (0–0.10)",
    )

    # ── Order value bounds ────────────────────────────────────────────────
    minimum_order_value: Decimal = Field(_d("1000"), gt=Decimal("0"))
    maximum_order_value: Decimal = Field(_d("50000"), gt=Decimal("0"))

    # ── Staleness thresholds ──────────────────────────────────────────────
    stale_state_threshold_seconds: float = Field(60.0, gt=0)
    stale_market_price_threshold_seconds: float = Field(30.0, gt=0)
    stale_broker_snapshot_threshold_seconds: float = Field(120.0, gt=0)

    # ── Intervals ─────────────────────────────────────────────────────────
    reconciliation_interval_seconds: float = Field(300.0, gt=0)
    snapshot_interval_seconds: float = Field(600.0, gt=0)
    allocation_decision_ttl_seconds: float = Field(30.0, gt=0)

    # ── Strategy capital cap ──────────────────────────────────────────────
    maximum_capital_per_strategy: Decimal = Field(
        _d("0.50"), gt=Decimal("0"), le=Decimal("1"),
    )

    # ── AI advisory ───────────────────────────────────────────────────────
    ai_confidence_sizing_enabled: bool = Field(False)
    ai_confidence_sizing_max_adjustment: Decimal = Field(
        _d("0.20"), ge=Decimal("0"), le=Decimal("1"),
    )

    # ── Validators ────────────────────────────────────────────────────────

    @field_validator(
        "initial_capital", "cash_reserve_percentage",
        "maximum_portfolio_exposure", "maximum_instrument_exposure",
        "maximum_sector_exposure", "maximum_strategy_exposure",
        "maximum_daily_loss", "maximum_drawdown",
        "default_risk_per_trade", "minimum_order_value", "maximum_order_value",
        "maximum_capital_per_strategy", "ai_confidence_sizing_max_adjustment",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, v) -> Decimal:
        return Decimal(str(v)) if not isinstance(v, Decimal) else v

    @model_validator(mode="after")
    def _validate_consistency(self) -> "PortfolioConfig":
        if self.minimum_order_value >= self.maximum_order_value:
            raise ValueError(
                f"minimum_order_value ({self.minimum_order_value}) must be less than "
                f"maximum_order_value ({self.maximum_order_value})"
            )
        if self.cash_reserve_percentage >= self.maximum_portfolio_exposure:
            raise ValueError(
                "cash_reserve_percentage must be less than maximum_portfolio_exposure"
            )
        if self.paper_mode is False:
            raise ValueError(
                "paper_mode must be True in RC-10C1 — live trading is not enabled"
            )
        return self

    @property
    def reserve_amount(self) -> Decimal:
        return self.initial_capital * self.cash_reserve_percentage

    @property
    def allocatable_capital(self) -> Decimal:
        return self.initial_capital * (1 - self.cash_reserve_percentage)
