"""Application configuration using Pydantic Settings."""
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Web Intelligence Collector configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./web_intelligence.db",
        alias="DATABASE_URL",
    )

    # Snapshot storage
    snapshot_storage_dir: Path = Field(
        default=Path("./snapshots"),
        alias="SNAPSHOT_STORAGE_DIR",
    )

    # Service
    service_host: str = Field(default="0.0.0.0", alias="SERVICE_HOST")
    service_port: int = Field(default=8000, alias="SERVICE_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Fetching
    default_user_agent: str = Field(
        default="ApexQuant-WebIntelligence/0.1.0",
        alias="DEFAULT_USER_AGENT",
    )
    global_concurrency_limit: int = Field(default=5, alias="GLOBAL_CONCURRENCY_LIMIT")
    default_request_interval_seconds: float = Field(
        default=5.0, alias="DEFAULT_REQUEST_INTERVAL_SECONDS"
    )
    maximum_response_size_bytes: int = Field(
        default=10_485_760, alias="MAXIMUM_RESPONSE_SIZE_BYTES"
    )
    request_timeout_seconds: float = Field(default=30.0, alias="REQUEST_TIMEOUT_SECONDS")
    retry_count: int = Field(default=3, alias="RETRY_COUNT")
    max_redirects: int = Field(default=5, alias="MAX_REDIRECTS")

    # Content type validation
    allowed_content_types: list[str] = Field(
        default=["text/html", "application/xhtml+xml", "text/plain"],
        alias="ALLOWED_CONTENT_TYPES",
    )
    strict_content_type_validation: bool = Field(
        default=True, alias="STRICT_CONTENT_TYPE_VALIDATION"
    )

    # API
    api_default_page_size: int = Field(default=20, alias="API_DEFAULT_PAGE_SIZE")
    api_max_page_size: int = Field(default=100, alias="API_MAX_PAGE_SIZE")

    # Security
    allow_http_for_tests: bool = Field(default=False, alias="ALLOW_HTTP_FOR_TESTS")
    production_mode: bool = Field(default=True, alias="PRODUCTION_MODE")
    allowed_source_domains: list[str] = Field(
        default_factory=list, alias="ALLOWED_SOURCE_DOMAINS"
    )

    @field_validator("snapshot_storage_dir", mode="before")
    @classmethod
    def _resolve_path(cls, v: str | Path) -> Path:
        return Path(v) if isinstance(v, str) else v

    @field_validator("allowed_content_types", mode="before")
    @classmethod
    def _parse_content_types(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",")]
        return v

    @field_validator("allowed_source_domains", mode="before")
    @classmethod
    def _parse_domains(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [x.strip().lower() for x in v.split(",") if x.strip()]
        return [x.lower() for x in v] if v else []

    @property
    def is_async_sqlite(self) -> bool:
        return "aiosqlite" in self.database_url

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.database_url.lower()


settings = Settings()
