"""Fail-closed controls for the disabled Phase 4A paper-entry framework.

This module intentionally has no dependency on trading, settings, broker, or
scheduler code.  The framework has no execution implementation; these flags
only describe whether a future operator review surface may be shown.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


CONTROLLED_PAPER_ENTRY_FLAG_NAMES = (
    "CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED",
    "CONTROLLED_PAPER_ENTRY_DRY_RUN_ONLY",
    "CONTROLLED_PAPER_ENTRY_REQUIRE_PHASE1H_PASS",
    "CONTROLLED_PAPER_ENTRY_REQUIRE_OPERATOR_APPROVAL",
    "CONTROLLED_PAPER_ENTRY_ALLOW_AUTO_ENABLE",
    "CONTROLLED_PAPER_ENTRY_ALLOW_BOOTSTRAP",
)


def _safe_bool(value: object, *, default: bool) -> bool:
    """Parse an explicit boolean, using the safer value for unknown input."""
    token = str(value or "").strip().lower()
    if token == "true":
        return True
    if token == "false":
        return False
    return default


@dataclass(frozen=True)
class ControlledPaperEntryFlags:
    framework_enabled: bool = False
    dry_run_only: bool = True
    require_phase1h_pass: bool = True
    require_operator_approval: bool = True
    allow_auto_enable: bool = False
    allow_bootstrap: bool = False

    @property
    def review_gate_safe(self) -> bool:
        """Whether the configuration is safe for a review-only status surface."""
        return (
            self.framework_enabled
            and self.dry_run_only
            and self.require_phase1h_pass
            and self.require_operator_approval
            and not self.allow_auto_enable
            and not self.allow_bootstrap
        )

    @property
    def execution_allowed(self) -> bool:
        """Always false: this framework contains no execution capability."""
        return False

    def as_dict(self) -> dict[str, bool]:
        return {
            "CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED": self.framework_enabled,
            "CONTROLLED_PAPER_ENTRY_DRY_RUN_ONLY": self.dry_run_only,
            "CONTROLLED_PAPER_ENTRY_REQUIRE_PHASE1H_PASS": self.require_phase1h_pass,
            "CONTROLLED_PAPER_ENTRY_REQUIRE_OPERATOR_APPROVAL": self.require_operator_approval,
            "CONTROLLED_PAPER_ENTRY_ALLOW_AUTO_ENABLE": self.allow_auto_enable,
            "CONTROLLED_PAPER_ENTRY_ALLOW_BOOTSTRAP": self.allow_bootstrap,
            "review_gate_safe": self.review_gate_safe,
            "execution_allowed": self.execution_allowed,
        }


def get_controlled_paper_entry_flags(
    env: Mapping[str, object] | None = None,
) -> ControlledPaperEntryFlags:
    """Resolve controls without allowing missing values to weaken safety."""
    source = os.environ if env is None else env
    return ControlledPaperEntryFlags(
        framework_enabled=_safe_bool(
            source.get("CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED"),
            default=False,
        ),
        dry_run_only=_safe_bool(
            source.get("CONTROLLED_PAPER_ENTRY_DRY_RUN_ONLY"),
            default=True,
        ),
        require_phase1h_pass=_safe_bool(
            source.get("CONTROLLED_PAPER_ENTRY_REQUIRE_PHASE1H_PASS"),
            default=True,
        ),
        require_operator_approval=_safe_bool(
            source.get("CONTROLLED_PAPER_ENTRY_REQUIRE_OPERATOR_APPROVAL"),
            default=True,
        ),
        allow_auto_enable=_safe_bool(
            source.get("CONTROLLED_PAPER_ENTRY_ALLOW_AUTO_ENABLE"),
            default=False,
        ),
        allow_bootstrap=_safe_bool(
            source.get("CONTROLLED_PAPER_ENTRY_ALLOW_BOOTSTRAP"),
            default=False,
        ),
    )