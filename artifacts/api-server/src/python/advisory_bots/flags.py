"""False-by-default feature flags for the disabled advisory integration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


ADVISORY_FLAG_NAMES = (
    "ADVISORY_BOTS_ENABLED",
    "ADVISORY_BOTS_API_ENABLED",
    "ADVISORY_BOTS_UI_ENABLED",
    "ADVISORY_BOTS_PERSIST_ENABLED",
    "ADVISORY_BOTS_SCHEDULER_ENABLED",
)


def _is_true(value: object) -> bool:
    return str(value or "").strip().lower() == "true"


@dataclass(frozen=True)
class AdvisoryFeatureFlags:
    bots_enabled: bool = False
    api_enabled: bool = False
    ui_enabled: bool = False
    persist_enabled: bool = False
    scheduler_enabled: bool = False
    environment: str = ""
    node_environment: str = ""
    declared_environment: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def persistence_environment_allowed(self) -> bool:
        node_environment = self.node_environment.strip().lower()
        declared_environment = self.declared_environment.strip().lower()
        if node_environment not in {"development", "test"}:
            return False
        return not declared_environment or declared_environment == node_environment

    def as_dict(self) -> dict[str, bool | str]:
        return {
            "ADVISORY_BOTS_ENABLED": self.bots_enabled,
            "ADVISORY_BOTS_API_ENABLED": self.api_enabled,
            "ADVISORY_BOTS_UI_ENABLED": self.ui_enabled,
            "ADVISORY_BOTS_PERSIST_ENABLED": self.persist_enabled,
            "ADVISORY_BOTS_SCHEDULER_ENABLED": self.scheduler_enabled,
            "environment": self.environment,
            "persistence_environment_allowed": self.persistence_environment_allowed,
        }


def get_advisory_flags(
    env: Mapping[str, object] | None = None,
) -> AdvisoryFeatureFlags:
    """Resolve advisory flags without ever treating an unset value as enabled."""
    source = os.environ if env is None else env
    return AdvisoryFeatureFlags(
        bots_enabled=_is_true(source.get("ADVISORY_BOTS_ENABLED")),
        api_enabled=_is_true(source.get("ADVISORY_BOTS_API_ENABLED")),
        ui_enabled=_is_true(source.get("ADVISORY_BOTS_UI_ENABLED")),
        persist_enabled=_is_true(source.get("ADVISORY_BOTS_PERSIST_ENABLED")),
        scheduler_enabled=_is_true(source.get("ADVISORY_BOTS_SCHEDULER_ENABLED")),
        environment=str(source.get("NODE_ENV") or source.get("ENVIRONMENT") or ""),
        node_environment=str(source.get("NODE_ENV") or ""),
        declared_environment=str(source.get("ENVIRONMENT") or ""),
    )