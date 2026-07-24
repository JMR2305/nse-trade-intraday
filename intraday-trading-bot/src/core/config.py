"""Central configuration using Pydantic Settings v2."""

from pathlib import Path
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingSettings(BaseSettings):
    """Trading mode and market hours."""
    mode: str = Field(default="PAPER", pattern=r"^(PAPER|REPLAY|SHADOW|SIMULATION|LIVE)$")
    timezone_display: str = "Asia/Kolkata"
    timezone_storage: str = "UTC"
    market_pre_open: str = "09:00"
    market_open: str = "09:15"
    market_close: str = "15:30"
    market_post_close: str = "15:40"

    # NOTE: The structural LIVE block (enforce_paper_mode) was removed in the
    # paper-to-live validation pass. LIVE mode is now gated entirely by the
    # runtime checks in ZerodhaBrokerConfig.is_live_order_allowed() (all 5
    # conditions must be satisfied simultaneously) and the kill switch in
    # ZerodhaOrderGateway.place_order(). Setting mode=LIVE without satisfying
    # those runtime gates routes every order to PaperBroker automatically.


class BrokerSettings(BaseSettings):
    """Broker configuration."""
    name: str = "zerodha"
    auth_flow: str = "official_oauth2"
    api_version: str = "v3"
    base_url: str = "https://api.kite.trade"
    login_url: str = "https://kite.zerodha.com/connect/login"
    cost_schedule_version: str = "2026-Q3"
    brokerage_per_order: float = 20.0
    use_bracket_orders: bool = False


class RiskSettings(BaseSettings):
    """Risk management settings."""
    max_leverage: float = Field(default=1.0, ge=1.0)
    risk_per_trade_pct: float = Field(default=1.0, gt=0.0, le=100.0)
    max_drawdown_inr: float = Field(default=50000.0, gt=0.0)
    daily_loss_limit_inr: float = Field(default=25000.0, gt=0.0)
    portfolio_heat_pct: float = Field(default=15.0, gt=0.0, le=100.0)
    sector_exposure_pct: float = Field(default=25.0, gt=0.0, le=100.0)
    correlation_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class ExecutionSettings(BaseSettings):
    """Execution engine settings."""
    slippage_model: str = Field(default="realistic", pattern=r"^(realistic|optimistic|pessimistic)$")
    partial_fill_handling: str = "immediate_retry"
    price_band_exit: bool = True
    square_off_state_machine: bool = True


class StrategySettings(BaseSettings):
    """Strategy configuration."""
    active_strategy: str = "vwap_rsi_v1"
    min_signal_quality: str = Field(default="MEDIUM", pattern=r"^(LOW|MEDIUM|HIGH)$")
    calibration_enabled: bool = False


class LoggingSettings(BaseSettings):
    """Logging configuration."""
    format: str = Field(default="structured_json", pattern=r"^(structured_json|text)$")
    level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    audit_all_sensitive: bool = True
    include_trace_id: bool = True
    include_span_id: bool = True


class IdempotencySettings(BaseSettings):
    """Idempotency configuration."""
    required: bool = True
    key_ttl_seconds: int = Field(default=86400, gt=0)


class APISettings(BaseSettings):
    """API configuration."""
    cors_allowed_origins: List[str] = Field(default_factory=lambda: ["*"])
    jwt_algorithm: str = Field(default="HS256", pattern=r"^(HS256|RS256)$")
    access_token_ttl_minutes: int = Field(default=30, gt=0)
    refresh_token_ttl_days: int = Field(default=7, gt=0)


class MarketIntelligenceSettings(BaseSettings):
    """Settings for the RC-10A Market Intelligence Layer."""

    model_config = SettingsConfigDict(env_prefix="MI_", extra="ignore")

    enabled: bool = True
    enabled_timeframes: List[str] = Field(
        default_factory=lambda: ["1m", "5m", "15m", "1h"]
    )
    max_indicator_buffer_bars: int = 150
    announcement_poll_interval_seconds: int = 60
    announcement_ttl_hours: int = 24
    announcement_blackout_window_minutes: int = 30
    bse_announcement_base_url: str = (
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    )
    nse_announcement_base_url: str = (
        "https://www.nseindia.com/api/corporate-announcements"
    )


class PaperSettings(BaseSettings):
    """Paper trading simulation settings."""
    initial_capital: float = Field(default=1_000_000.0, gt=0.0)
    slippage_model: str = Field(default="realistic", pattern=r"^(realistic|optimistic|pessimistic)$")


class AiForecastSettings(BaseSettings):
    """Settings for the RC-10B AI Forecast (Kronos) integration."""

    model_config = SettingsConfigDict(env_prefix="AI_", extra="ignore")

    enabled: bool = True
    kronos_base_url: str = "http://localhost:8090"
    kronos_timeout_ms: int = 2000
    kronos_max_retries: int = 1
    feature_schema_version: str = "1.0"
    default_forecast_horizon: str = "15m"
    benchmark_accuracy_alert_threshold: float = 0.52


class Settings(BaseSettings):
    """Root settings loaded from environment variables."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = "intraday-trading-bot"
    app_env: str = "development"
    debug: bool = False

    # Database
    # validation_alias reads from INTRADAY_DATABASE_URL / INTRADAY_DATABASE_URL_SYNC,
    # avoiding collision with the swing platform's DATABASE_URL env var.
    # Internal attribute names (settings.database_url, settings.database_url_sync)
    # are unchanged so all callers remain unmodified.
    database_url: str = Field(..., validation_alias="intraday_database_url", description="Async PostgreSQL URL")
    database_url_sync: str = Field(..., validation_alias="intraday_database_url_sync", description="Sync PostgreSQL URL for Alembic")

    # JWT (Operator Auth)
    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_access_token_ttl_minutes: int = 30
    jwt_refresh_token_ttl_days: int = 7

    # Zerodha (read-only skeleton)
    zerodha_api_key: Optional[str] = None
    zerodha_api_secret: Optional[str] = None

    # Nested settings
    trading: TradingSettings = Field(default_factory=TradingSettings)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    strategy: StrategySettings = Field(default_factory=StrategySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    idempotency: IdempotencySettings = Field(default_factory=IdempotencySettings)
    api: APISettings = Field(default_factory=APISettings)
    paper: PaperSettings = Field(default_factory=PaperSettings)
    market_intelligence: MarketIntelligenceSettings = Field(
        default_factory=MarketIntelligenceSettings
    )
    ai_forecast: AiForecastSettings = Field(default_factory=AiForecastSettings)

    @property
    def is_paper_mode(self) -> bool:
        """Check if running in paper mode."""
        return self.trading.mode == "PAPER"


# Singleton instance
settings = Settings()
